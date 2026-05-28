from __future__ import annotations

import logging
from typing import Any, TypedDict

from .classifier import get_default_classifier
from .explainer import fallback_explanation, get_default_explainer
from .schemas import ClassifierResult, EmailMessage, ProcessingResult, SenderReport, URLReport, Verdict
from .security import analyze_urls, lookup_sender

logger = logging.getLogger(__name__)

classifier_singleton = get_default_classifier()


class AgentState(TypedDict):
    email: dict[str, Any]
    classifier: dict[str, Any] | None
    url_reports: list[dict[str, Any]]
    sender_report: dict[str, Any] | None
    risk_score: float
    final_verdict: str


# --- node functions ---

async def _node_classify(state: AgentState) -> AgentState:
    email = EmailMessage.model_validate(state["email"])
    result = classifier_singleton.predict_email(email)
    logger.info("agent_classify verdict=%s confidence=%.2f", result.verdict.value, result.confidence)
    return {**state, "classifier": result.model_dump(mode="json")}


async def _node_check_security(state: AgentState) -> AgentState:
    email = EmailMessage.model_validate(state["email"])
    urls = await analyze_urls(f"{email.subject}\n{email.body}")
    sender = await lookup_sender(email.sender)
    logger.info(
        "agent_security suspicious_urls=%s sender_unknown=%s",
        any(r.suspicious for r in urls),
        sender.unknown,
    )
    return {
        **state,
        "url_reports": [r.model_dump(mode="json") for r in urls],
        "sender_report": sender.model_dump(mode="json"),
    }


async def _node_finalize(state: AgentState) -> AgentState:
    classifier = ClassifierResult.model_validate(state["classifier"])
    urls = [URLReport.model_validate(r) for r in state["url_reports"]]
    sender = SenderReport.model_validate(state["sender_report"])
    email = EmailMessage.model_validate(state["email"])

    explanation = fallback_explanation(email, classifier, urls, sender)
    risk = max(
        classifier.risk_score,
        explanation.risk_score,
        *(r.score for r in urls),
        0.0,
    )
    if sender.unknown:
        risk = min(1.0, risk + 0.05)
    if classifier.verdict == Verdict.phishing:
        risk = min(1.0, max(risk, classifier.risk_score + 0.1))

    verdict = Verdict.spam if risk >= 0.75 else Verdict.suspicious if risk >= 0.45 else Verdict.safe
    if classifier.verdict == Verdict.phishing and verdict == Verdict.safe:
        verdict = Verdict.suspicious

    logger.info("agent_finalize verdict=%s risk=%.2f", verdict.value, risk)
    return {**state, "risk_score": risk, "final_verdict": verdict.value}


def _build_graph():
    try:
        from langgraph.graph import END, StateGraph

        graph = StateGraph(AgentState)
        graph.add_node("classify", _node_classify)
        graph.add_node("check_security", _node_check_security)
        graph.add_node("finalize", _node_finalize)
        graph.set_entry_point("classify")
        graph.add_edge("classify", "check_security")
        graph.add_edge("check_security", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()
    except Exception as exc:  # pragma: no cover - langgraph unavailable
        logger.warning("langgraph_unavailable falling back to sequential error=%s", exc)
        return None


_GRAPH = _build_graph()


class _FallbackGraph:
    """Sequential fallback when LangGraph is not importable."""

    async def ainvoke(self, state: AgentState) -> AgentState:
        state = await _node_classify(state)
        state = await _node_check_security(state)
        state = await _node_finalize(state)
        return state


class SpamAgent:
    def __init__(self) -> None:
        self.graph = _GRAPH if _GRAPH is not None else _FallbackGraph()
        self.explainer = get_default_explainer()

    def metadata_backend_name(self) -> str:
        return "langgraph" if not isinstance(self.graph, _FallbackGraph) else "fallback"

    async def run(self, email: EmailMessage, latency_ms: int = 0) -> ProcessingResult:
        initial: AgentState = {
            "email": email.model_dump(mode="json"),
            "classifier": None,
            "url_reports": [],
            "sender_report": None,
            "risk_score": 0.0,
            "final_verdict": Verdict.safe.value,
        }
        state = await self.graph.ainvoke(initial)

        classifier = (
            ClassifierResult.model_validate(state["classifier"])
            if state.get("classifier")
            else classifier_singleton.predict_email(email)
        )
        urls = [URLReport.model_validate(r) for r in state.get("url_reports") or []]
        sender = (
            SenderReport.model_validate(state["sender_report"])
            if state.get("sender_report")
            else await lookup_sender(email.sender)
        )
        explanation = await self.explainer.explain(email, classifier, urls, sender)

        risk = max(float(state.get("risk_score", 0.0)), explanation.risk_score)
        final = Verdict(state.get("final_verdict", explanation.verdict.value))

        if classifier.verdict == Verdict.phishing:
            risk = min(1.0, max(risk, classifier.risk_score + 0.1))
            if final == Verdict.safe:
                final = Verdict.suspicious
        if explanation.verdict == Verdict.spam and risk >= 0.7:
            final = Verdict.spam
        if classifier.verdict == Verdict.phishing and risk >= 0.75:
            final = Verdict.spam

        return ProcessingResult(
            email=email,
            route="agent",
            classifier=classifier,
            url_reports=urls,
            sender_report=sender,
            explanation=explanation,
            final_verdict=final,
            risk_score=min(risk, 1.0),
            latency_ms=latency_ms,
            metadata={
                "agent_verdict": state.get("final_verdict"),
                "classifier_label": classifier.verdict.value,
                "class_probabilities": classifier.class_probabilities,
                "agent_backend": "langgraph" if _GRAPH is not None else "fallback",
            },
        )
