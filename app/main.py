"""FastAPI HTTP interface wrapping the spam-mail-agent pipeline.

Endpoints:
  POST /classify          — classify a raw email (JSON body)
  GET  /health            — liveness + readiness probe
  GET  /metrics           — Prometheus text exposition
  GET  /analytics         — DB-backed aggregate statistics
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from src.agent import SpamAgent
from src.classifier import get_default_classifier
from src.db import analytics, init_db, save_result
from src.logging_config import configure_logging
from src.monitoring import latency_timer, metrics
from src.router import HybridRouter
from src.schemas import AttachmentMeta, EmailMessage, Verdict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics (prometheus_client is optional — degrade gracefully)
# ---------------------------------------------------------------------------
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _PROM_AVAILABLE = True
    _requests_total = Counter(
        "spam_requests_total",
        "Total classify requests",
        ["verdict", "route"],
    )
    _latency = Histogram(
        "spam_latency_seconds",
        "Classify latency in seconds",
        buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    )
    _errors_total = Counter("spam_errors_total", "Total processing errors")
    _active = Gauge("spam_active_connections", "Active classify requests in flight")
except ImportError:  # pragma: no cover
    _PROM_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

_router: HybridRouter | None = None
_agent: SpamAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _router, _agent
    configure_logging("INFO")
    init_db()
    _router = HybridRouter()
    _agent = SpamAgent()
    # Warm up the classifier so first request is fast
    get_default_classifier()
    logger.info("spam_agent_api_started")
    yield
    logger.info("spam_agent_api_stopped")


app = FastAPI(
    title="Spam Mail Agent API",
    version="1.0.0",
    description="Hybrid ML + LangGraph email spam/phishing classifier",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class ClassifyRequest(BaseModel):
    sender: str
    subject: str = ""
    body: str = ""
    message_id: str | None = Field(default=None, description="Unique email ID; auto-generated if omitted")
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    raw_headers: dict[str, str] = Field(default_factory=dict)


class ClassifyResponse(BaseModel):
    message_id: str
    verdict: str
    risk_score: float
    route: str
    confidence: float
    signals: list[str]
    summary: str | None
    recommended_action: str
    latency_ms: int
    agent_backend: str | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health():
    """Kubernetes liveness + readiness probe."""
    return {"status": "ok", "classifier": "ready"}


@app.get("/metrics", response_class=PlainTextResponse, tags=["ops"])
async def prometheus_metrics():
    """Prometheus text exposition (compatible with prometheus_client)."""
    if _PROM_AVAILABLE:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    # Fallback: expose in-memory metrics as simple key=value text
    snap = metrics.snapshot()
    lines = [f"# spam_agent in-memory metrics (prometheus_client not installed)"]
    for key, value in snap.items():
        if isinstance(value, (int, float)):
            lines.append(f"spam_{key} {value}")
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")


@app.get("/analytics", tags=["ops"])
async def get_analytics():
    """Aggregate statistics from the database."""
    return analytics()


@app.post("/classify", response_model=ClassifyResponse, tags=["classify"])
async def classify(req: ClassifyRequest, request: Request):
    """Classify an email and return verdict with risk score."""
    if _router is None or _agent is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready")

    if _PROM_AVAILABLE:
        _active.inc()

    start = time.perf_counter()
    try:
        attachments = [AttachmentMeta(**a) for a in req.attachments] if req.attachments else []
        email = EmailMessage(
            message_id=req.message_id or f"api-{uuid.uuid4().hex}",
            sender=req.sender,
            subject=req.subject,
            body=req.body,
            attachments=attachments,
            raw_headers=req.raw_headers,
        )

        with latency_timer() as elapsed:
            escalate, context = await _router.should_escalate(email)
            if escalate:
                result = await _agent.run(email, latency_ms=elapsed())
            else:
                result = await _router.fast_path(email, context, latency_ms=elapsed())
            result.latency_ms = elapsed()

        save_result(result)
        metrics.record(result.route, result.final_verdict.value, result.classifier.confidence, result.latency_ms)

        duration = time.perf_counter() - start
        if _PROM_AVAILABLE:
            _requests_total.labels(verdict=result.final_verdict.value, route=result.route).inc()
            _latency.observe(duration)

        explanation = result.explanation
        return ClassifyResponse(
            message_id=email.message_id,
            verdict=result.final_verdict.value,
            risk_score=round(result.risk_score, 4),
            route=result.route,
            confidence=round(result.classifier.confidence, 4),
            signals=result.classifier.signals,
            summary=explanation.summary if explanation else None,
            recommended_action=explanation.recommended_action if explanation else "review",
            latency_ms=result.latency_ms,
            agent_backend=result.metadata.get("agent_backend"),
        )

    except Exception as exc:
        if _PROM_AVAILABLE:
            _errors_total.inc()
        logger.exception("classify_failed error=%s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    finally:
        if _PROM_AVAILABLE:
            _active.dec()
