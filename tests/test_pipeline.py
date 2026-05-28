from __future__ import annotations

import pytest

import src.pipeline as pipeline_module
from src.pipeline import SpamEmailPipeline
from src.schemas import ClassifierResult, EmailMessage, ProcessingResult, SenderReport, SpamExplanation, Verdict


def _make_result(message_id: str, verdict: Verdict = Verdict.spam) -> ProcessingResult:
    email = EmailMessage(message_id=message_id, sender="user@example.com", subject="Test", body="body")
    classifier = ClassifierResult(
        verdict=verdict,
        confidence=0.95,
        class_probabilities={"safe": 0.05, "phishing": 0.0, "spam": 0.95},
        risk_score=0.95,
        model_name="test",
    )
    return ProcessingResult(
        email=email,
        route="fast",
        classifier=classifier,
        final_verdict=verdict,
        risk_score=0.95,
    )


# --- duplicate guard ---

@pytest.mark.asyncio
async def test_process_email_skips_duplicate_in_db(monkeypatch: pytest.MonkeyPatch):
    pipeline = SpamEmailPipeline()
    email = EmailMessage(message_id="dup1", sender="a@b.com", subject="s", body="b")

    monkeypatch.setattr(pipeline_module, "is_processed", lambda _mid: True)
    monkeypatch.setattr(pipeline_module, "save_result", lambda _r: None)

    marked = []
    monkeypatch.setattr(pipeline.fetcher, "mark_seen", lambda e: marked.append(e.message_id))

    result = await pipeline.process_email(email)
    assert result is None
    assert "dup1" in marked


@pytest.mark.asyncio
async def test_process_email_skips_inflight(monkeypatch: pytest.MonkeyPatch):
    pipeline = SpamEmailPipeline()
    email = EmailMessage(message_id="dup2", sender="a@b.com", subject="s", body="b")
    pipeline.inflight.add("dup2")

    monkeypatch.setattr(pipeline_module, "is_processed", lambda _mid: False)
    monkeypatch.setattr(pipeline_module, "save_result", lambda _r: None)

    marked = []
    monkeypatch.setattr(pipeline.fetcher, "mark_seen", lambda e: marked.append(e.message_id))

    result = await pipeline.process_email(email)
    assert result is None
    assert "dup2" in marked


# --- fast path routing ---

@pytest.mark.asyncio
async def test_process_email_uses_fast_path_when_not_escalated(monkeypatch: pytest.MonkeyPatch):
    pipeline = SpamEmailPipeline()
    email = EmailMessage(message_id="fast1", sender="a@gmail.com", subject="Hello", body="normal")
    expected = _make_result("fast1", Verdict.safe)

    monkeypatch.setattr(pipeline_module, "is_processed", lambda _mid: False)
    monkeypatch.setattr(pipeline_module, "save_result", lambda _r: None)
    monkeypatch.setattr(pipeline_module, "send_alert", lambda _r: _awaitable(None))
    monkeypatch.setattr(pipeline.fetcher, "mark_seen", lambda _e: None)
    monkeypatch.setattr(pipeline.router, "should_escalate", lambda _e: _awaitable((False, {})))
    monkeypatch.setattr(pipeline.router, "fast_path", lambda _e, _ctx, latency_ms=0: _awaitable(expected))

    result = await pipeline.process_email(email)
    assert result is not None
    assert result.route == "fast"
    assert result.final_verdict == Verdict.safe


# --- agent path routing ---

@pytest.mark.asyncio
async def test_process_email_uses_agent_path_when_escalated(monkeypatch: pytest.MonkeyPatch):
    pipeline = SpamEmailPipeline()
    email = EmailMessage(message_id="agent1", sender="x@evil.xyz", subject="Phish", body="click")

    def _make_agent_result(message_id: str) -> ProcessingResult:
        e = EmailMessage(message_id=message_id, sender="user@example.com", subject="Test", body="body")
        classifier = ClassifierResult(
            verdict=Verdict.phishing,
            confidence=0.95,
            class_probabilities={"safe": 0.05, "phishing": 0.90, "spam": 0.05},
            risk_score=0.90,
            model_name="test",
        )
        return ProcessingResult(
            email=e,
            route="agent",
            classifier=classifier,
            final_verdict=Verdict.phishing,
            risk_score=0.90,
        )

    expected = _make_agent_result("agent1")

    monkeypatch.setattr(pipeline_module, "is_processed", lambda _mid: False)
    monkeypatch.setattr(pipeline_module, "save_result", lambda _r: None)
    monkeypatch.setattr(pipeline_module, "send_alert", lambda _r: _awaitable(None))
    monkeypatch.setattr(pipeline.fetcher, "mark_seen", lambda _e: None)
    monkeypatch.setattr(pipeline.router, "should_escalate", lambda _e: _awaitable((True, {})))
    monkeypatch.setattr(pipeline.agent, "run", lambda _e, latency_ms=0: _awaitable(expected))

    result = await pipeline.process_email(email)
    assert result is not None
    assert result.route == "agent"
    assert result.final_verdict == Verdict.phishing


# --- error handling ---

@pytest.mark.asyncio
async def test_process_email_returns_none_on_exception(monkeypatch: pytest.MonkeyPatch):
    pipeline = SpamEmailPipeline()
    email = EmailMessage(message_id="err1", sender="a@b.com", subject="s", body="b")

    monkeypatch.setattr(pipeline_module, "is_processed", lambda _mid: False)
    monkeypatch.setattr(pipeline_module, "save_result", lambda _r: None)
    monkeypatch.setattr(pipeline.fetcher, "mark_seen", lambda _e: None)
    monkeypatch.setattr(pipeline.router, "should_escalate", lambda _e: _raise(RuntimeError("boom")))

    result = await pipeline.process_email(email)
    assert result is None


# --- poll_once ---

@pytest.mark.asyncio
async def test_poll_once_returns_empty_on_fetch_failure(monkeypatch: pytest.MonkeyPatch):
    pipeline = SpamEmailPipeline()

    def bad_fetch(_limit):
        raise ConnectionError("imap down")

    monkeypatch.setattr(pipeline.fetcher, "fetch_unseen", bad_fetch)
    results = await pipeline.poll_once()
    assert results == []


@pytest.mark.asyncio
async def test_poll_once_processes_fetched_emails(monkeypatch: pytest.MonkeyPatch):
    pipeline = SpamEmailPipeline()
    email = EmailMessage(message_id="poll1", sender="a@b.com", subject="s", body="b")
    expected = _make_result("poll1", Verdict.spam)

    monkeypatch.setattr(pipeline.fetcher, "fetch_unseen", lambda _limit: [email])
    monkeypatch.setattr(pipeline, "process_email", lambda _e: _awaitable(expected))

    results = await pipeline.poll_once()
    assert len(results) == 1
    assert results[0].final_verdict == Verdict.spam


async def _awaitable(value):
    return value


async def _raise(exc: Exception):
    raise exc
