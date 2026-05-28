from __future__ import annotations

import logging

from .classifier import get_default_classifier
from .config import get_settings
from .explainer import get_default_explainer
from .schemas import EmailMessage, ProcessingResult, Verdict
from .security import analyze_urls, lookup_sender

logger = logging.getLogger(__name__)


def should_send_alert(result: ProcessingResult) -> bool:
    sender_signals = result.sender_report.signals if result.sender_report else []
    known_notification_sender = "known notification sender domain" in sender_signals
    phishing_signal_present = any(
        signal in {"credential request", "brand impersonation pattern", "virustotal malicious=1"}
        or signal.startswith("virustotal malicious=")
        for signal in (result.explanation.spam_signals if result.explanation else result.classifier.signals)
    )
    suspicious_url_present = any(report.suspicious and report.score >= 0.45 for report in result.url_reports)
    if known_notification_sender and result.route != "agent" and not phishing_signal_present and not suspicious_url_present:
        return False
    if result.route == "agent":
        return result.final_verdict in {Verdict.spam, Verdict.suspicious, Verdict.phishing}
    return result.final_verdict == Verdict.phishing or phishing_signal_present or suspicious_url_present


class HybridRouter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.classifier = get_default_classifier()
        self.explainer = get_default_explainer()

    async def should_escalate(self, email: EmailMessage) -> tuple[bool, dict[str, object]]:
        classifier = self.classifier.predict_email(email)
        urls = await analyze_urls(f"{email.subject}\n{email.body}")
        sender = await lookup_sender(email.sender)
        suspicious_urls = any(report.suspicious for report in urls)
        uncertain = classifier.confidence < self.settings.classifier_threshold
        unknown_domain = sender.unknown and sender.sender_domain not in self.settings.trusted_domains
        risk_keyword_count = len(classifier.signals)
        phishing_prob = classifier.phishing_probability
        spam_prob = classifier.spam_probability
        known_notification_sender = "known notification sender domain" in sender.signals
        high_phishing_risk = phishing_prob >= self.settings.phishing_escalation_threshold
        high_spam_risk = spam_prob >= self.settings.spam_escalation_threshold
        escalate = (
            uncertain
            or suspicious_urls
            or unknown_domain
            or (high_phishing_risk and not known_notification_sender)
            or (high_spam_risk and not known_notification_sender)
            or risk_keyword_count >= 3
        )
        context = {
            "classifier": classifier,
            "url_reports": urls,
            "sender_report": sender,
            "reasons": {
                "uncertain": uncertain,
                "suspicious_urls": suspicious_urls,
                "unknown_domain": unknown_domain,
                "predicted_label": classifier.verdict.value,
                "phishing_probability": phishing_prob,
                "spam_probability": spam_prob,
                "risk_score": classifier.risk_score,
                "high_phishing_risk": high_phishing_risk,
                "high_spam_risk": high_spam_risk,
                "known_notification_sender": known_notification_sender,
                "risk_keyword_count": risk_keyword_count,
            },
        }
        logger.info("route_decision escalate=%s reasons=%s", escalate, context["reasons"])
        return escalate, context

    async def fast_path(self, email: EmailMessage, context: dict[str, object], latency_ms: int = 0) -> ProcessingResult:
        classifier = context["classifier"]
        urls = context["url_reports"]
        sender = context["sender_report"]
        reasons = context["reasons"]
        explanation = await self.explainer.explain(email, classifier, urls, sender)  # type: ignore[arg-type]
        risk = max(classifier.risk_score, explanation.risk_score, *(r.score for r in urls), 0.0)  # type: ignore[attr-defined]
        known_notification_sender = bool(reasons.get("known_notification_sender"))
        phishing_signal_present = (
            classifier.phishing_probability >= self.settings.phishing_escalation_threshold  # type: ignore[attr-defined]
            or any(report.suspicious and report.score >= 0.45 for report in urls)  # type: ignore[arg-type]
        )
        if classifier.verdict == Verdict.phishing and risk >= 0.6:  # type: ignore[attr-defined]
            verdict = Verdict.spam
        elif known_notification_sender and not phishing_signal_present:
            verdict = Verdict.safe if risk < 0.85 else Verdict.suspicious
        else:
            verdict = Verdict.spam if risk >= 0.75 else Verdict.suspicious if risk >= 0.45 else Verdict.safe
        return ProcessingResult(
            email=email,
            route="fast",
            classifier=classifier,  # type: ignore[arg-type]
            url_reports=urls,  # type: ignore[arg-type]
            sender_report=sender,  # type: ignore[arg-type]
            explanation=explanation,
            final_verdict=verdict,
            risk_score=min(risk, 1.0),
            latency_ms=latency_ms,
            metadata={"routing_reasons": context["reasons"], "classifier_label": classifier.verdict.value},  # type: ignore[attr-defined]
        )
