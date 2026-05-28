from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Verdict(str, Enum):
    spam = "spam"
    safe = "safe"
    suspicious = "suspicious"
    phishing = "phishing"


class AttachmentMeta(BaseModel):
    filename: str
    content_type: str
    size_bytes: int = 0


class EmailMessage(BaseModel):
    message_id: str
    sender: str
    subject: str = ""
    body: str = ""
    source_mailbox: str | None = None
    source_uid: str | None = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    attachments: list[AttachmentMeta] = Field(default_factory=list)
    raw_headers: dict[str, str] = Field(default_factory=dict)


class ClassifierResult(BaseModel):
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    class_probabilities: dict[str, float] = Field(default_factory=dict)
    risk_score: float = Field(ge=0, le=1)
    model_name: str
    signals: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_probabilities(self) -> "ClassifierResult":
        normalized = {str(label).lower(): float(score) for label, score in self.class_probabilities.items()}
        for label in ("safe", "phishing", "spam"):
            normalized.setdefault(label, 0.0)
        self.class_probabilities = {
            label: min(max(score, 0.0), 1.0) for label, score in normalized.items()
        }
        self.risk_score = min(max(self.risk_score, 0.0), 1.0)
        return self

    @property
    def spam_probability(self) -> float:
        return float(self.class_probabilities.get("spam", 0.0))

    @property
    def phishing_probability(self) -> float:
        return float(self.class_probabilities.get("phishing", 0.0))


class URLReport(BaseModel):
    url: str
    domain: str
    suspicious: bool
    score: float = Field(ge=0, le=1)
    signals: list[str] = Field(default_factory=list)
    vt_malicious: int | None = None
    vt_suspicious: int | None = None


class SenderReport(BaseModel):
    sender_domain: str
    trusted: bool
    unknown: bool
    age_days: int | None = None
    signals: list[str] = Field(default_factory=list)


class SpamExplanation(BaseModel):
    verdict: Verdict
    risk_score: float = Field(ge=0, le=1)
    summary: str
    summary_vi: str | None = None
    spam_signals: list[str] = Field(default_factory=list)
    recommended_action: str = "review"
    raw: dict[str, Any] = Field(default_factory=dict)


class ProcessingResult(BaseModel):
    email: EmailMessage
    route: str
    classifier: ClassifierResult
    url_reports: list[URLReport] = Field(default_factory=list)
    sender_report: SenderReport | None = None
    explanation: SpamExplanation | None = None
    final_verdict: Verdict
    risk_score: float = Field(ge=0, le=1)
    latency_ms: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)
