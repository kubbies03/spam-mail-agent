from pathlib import Path

from src.classifier import DistilBertMultilingualClassifier, SpamClassifier
from src.schemas import EmailMessage, Verdict


def test_distilbert_reads_multiclass_labels_from_artifact() -> None:
    classifier = DistilBertMultilingualClassifier(Path("docs/22590"))
    assert classifier.id2label == {"0": "safe", "1": "phishing", "2": "spam"}


def test_classifier_risk_score_uses_highest_risky_class() -> None:
    classifier = SpamClassifier(model_dir=Path("does-not-exist"))
    email = EmailMessage(
        message_id="t1",
        sender="promo@example.com",
        subject="Urgent prize",
        body="Win a gift card now and verify your account password.",
    )
    result = classifier.predict_email(email)
    assert result.verdict in {Verdict.spam, Verdict.safe}
    assert 0 <= result.confidence <= 1
    assert result.risk_score == max(result.class_probabilities["phishing"], result.class_probabilities["spam"])
    assert "credential request" in result.signals


def test_binary_fallback_still_returns_valid_classifier_result() -> None:
    classifier = SpamClassifier(model_dir=Path("does-not-exist"))
    result = classifier.predict_text("invoice update for approved vendor payment")
    assert set(result.class_probabilities) == {"safe", "phishing", "spam"}
    # When the SVM binary fallback is used, phishing probability is 0.0.
    # When DistilBERT is available, it may return a tiny non-zero phishing score.
    assert result.class_probabilities["phishing"] < 0.01
    assert result.risk_score == result.spam_probability
