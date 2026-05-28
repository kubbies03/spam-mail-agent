import pytest

import src.router as router_module
from src.router import HybridRouter
from src.router import should_send_alert
from src.schemas import ClassifierResult, EmailMessage, SenderReport, URLReport, Verdict
from src.schemas import ProcessingResult, SpamExplanation


def _classifier_result(
    verdict: Verdict,
    confidence: float,
    phishing_probability: float,
    spam_probability: float,
) -> ClassifierResult:
    return ClassifierResult(
        verdict=verdict,
        confidence=confidence,
        class_probabilities={
            "safe": max(0.0, 1.0 - max(phishing_probability, spam_probability)),
            "phishing": phishing_probability,
            "spam": spam_probability,
        },
        risk_score=max(phishing_probability, spam_probability),
        model_name="test",
        signals=[],
    )


@pytest.mark.asyncio
async def test_router_escalates_high_phishing_probability(monkeypatch: pytest.MonkeyPatch) -> None:
    router = HybridRouter()
    email = EmailMessage(message_id="route1", sender="user@example.com", subject="Verify account", body="check link")
    monkeypatch.setattr(router.classifier, "predict_email", lambda _: _classifier_result(Verdict.phishing, 0.94, 0.81, 0.12))
    monkeypatch.setattr(
        router_module,
        "analyze_urls",
        lambda _text: _awaitable([]),
    )
    monkeypatch.setattr(
        router_module,
        "lookup_sender",
        lambda _sender: _awaitable(SenderReport(sender_domain="example.com", trusted=False, unknown=False, signals=[])),
    )
    escalate, context = await router.should_escalate(email)
    assert escalate is True
    assert context["reasons"]["high_phishing_risk"] is True


@pytest.mark.asyncio
async def test_router_escalates_high_spam_probability(monkeypatch: pytest.MonkeyPatch) -> None:
    router = HybridRouter()
    email = EmailMessage(message_id="route2", sender="user@example.com", subject="Offer", body="check link")
    monkeypatch.setattr(router.classifier, "predict_email", lambda _: _classifier_result(Verdict.spam, 0.93, 0.10, 0.71))
    monkeypatch.setattr(router_module, "analyze_urls", lambda _text: _awaitable([]))
    monkeypatch.setattr(
        router_module,
        "lookup_sender",
        lambda _sender: _awaitable(SenderReport(sender_domain="example.com", trusted=False, unknown=False, signals=[])),
    )
    escalate, context = await router.should_escalate(email)
    assert escalate is True
    assert context["reasons"]["high_spam_risk"] is True


@pytest.mark.asyncio
async def test_router_escalates_low_confidence_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    router = HybridRouter()
    email = EmailMessage(message_id="route3", sender="user@example.com", subject="Hello", body="normal message")
    monkeypatch.setattr(router.classifier, "predict_email", lambda _: _classifier_result(Verdict.safe, 0.51, 0.12, 0.11))
    monkeypatch.setattr(router_module, "analyze_urls", lambda _text: _awaitable([]))
    monkeypatch.setattr(
        router_module,
        "lookup_sender",
        lambda _sender: _awaitable(SenderReport(sender_domain="gmail.com", trusted=True, unknown=False, signals=[])),
    )
    escalate, context = await router.should_escalate(email)
    assert escalate is True
    assert context["reasons"]["uncertain"] is True


@pytest.mark.asyncio
async def test_router_keeps_high_confidence_safe_on_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    router = HybridRouter()
    email = EmailMessage(message_id="route4", sender="user@gmail.com", subject="Team update", body="meeting tomorrow")
    monkeypatch.setattr(router.classifier, "predict_email", lambda _: _classifier_result(Verdict.safe, 0.97, 0.01, 0.02))
    monkeypatch.setattr(router_module, "analyze_urls", lambda _text: _awaitable([URLReport(url="https://example.com", domain="example.com", suspicious=False, score=0.0)]))
    monkeypatch.setattr(
        router_module,
        "lookup_sender",
        lambda _sender: _awaitable(SenderReport(sender_domain="gmail.com", trusted=True, unknown=False, signals=[])),
    )
    escalate, _context = await router.should_escalate(email)
    assert escalate is False


@pytest.mark.asyncio
async def test_router_known_notification_sender_stays_off_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    router = HybridRouter()
    email = EmailMessage(message_id="route5", sender="notify@facebookmail.com", subject="Facebook update", body="new activity")
    monkeypatch.setattr(router.classifier, "predict_email", lambda _: _classifier_result(Verdict.spam, 0.99, 0.01, 1.0))
    monkeypatch.setattr(router_module, "analyze_urls", lambda _text: _awaitable([]))
    monkeypatch.setattr(
        router_module,
        "lookup_sender",
        lambda _sender: _awaitable(
            SenderReport(
                sender_domain="facebookmail.com",
                trusted=True,
                unknown=False,
                signals=["known notification sender domain"],
            )
        ),
    )
    escalate, context = await router.should_escalate(email)
    assert escalate is False
    result = await router.fast_path(email, context)
    assert result.final_verdict != Verdict.spam


def test_should_send_alert_skips_known_notification_fast_path() -> None:
    result = ProcessingResult(
        email=EmailMessage(message_id="alert1", sender="notify@facebookmail.com", subject="Facebook", body="body"),
        route="fast",
        classifier=_classifier_result(Verdict.spam, 0.99, 0.01, 1.0),
        sender_report=SenderReport(
            sender_domain="facebookmail.com",
            trusted=True,
            unknown=False,
            signals=["known notification sender domain"],
        ),
        explanation=SpamExplanation(
            verdict=Verdict.suspicious,
            risk_score=0.6,
            summary="notification",
            spam_signals=["known notification sender domain"],
        ),
        final_verdict=Verdict.suspicious,
        risk_score=0.6,
    )
    assert should_send_alert(result) is False


def test_should_send_alert_allows_phishing_signal_on_fast_path() -> None:
    result = ProcessingResult(
        email=EmailMessage(message_id="alert2", sender="user@example.com", subject="Verify account", body="body"),
        route="fast",
        classifier=_classifier_result(Verdict.phishing, 0.95, 0.8, 0.1),
        sender_report=SenderReport(sender_domain="example.com", trusted=False, unknown=False, signals=[]),
        explanation=SpamExplanation(
            verdict=Verdict.phishing,
            risk_score=0.8,
            summary="phishing",
            spam_signals=["credential request"],
        ),
        final_verdict=Verdict.suspicious,
        risk_score=0.8,
    )
    assert should_send_alert(result) is True


async def _awaitable(value):
    return value
