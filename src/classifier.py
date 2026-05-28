from __future__ import annotations

import logging
import pickle
import re
from functools import lru_cache
from json import loads
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from .config import DEFAULT_DISTILBERT_MODEL_DIR, LEGACY_DISTILBERT_MODEL_DIR, get_settings
from .schemas import ClassifierResult, EmailMessage, Verdict

logger = logging.getLogger(__name__)


DEFAULT_SVM_MODEL_PATH = get_settings().model_dir / "svm_tfidf.joblib"
DEFAULT_RUNTIME_DISTILBERT_MODEL_DIR = get_settings().distilbert_model_dir
DEFAULT_MODEL_PATH = DEFAULT_SVM_MODEL_PATH
SUPPORTED_CLASSIFIER_LABELS = ("safe", "phishing", "spam")


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"https?://\S+", " URL ", text)
    text = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", " EMAIL ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def email_to_text(email: EmailMessage) -> str:
    attachment_text = " ".join(a.filename for a in email.attachments)
    return normalize_text(f"{email.sender} {email.subject} {email.body} {attachment_text}")


def build_svm_pipeline(cv: int = 3) -> Pipeline:
    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    preprocessor=normalize_text,
                    ngram_range=(1, 2),
                    min_df=1,
                    max_features=80000,
                    strip_accents="unicode",
                ),
            ),
            ("clf", CalibratedClassifierCV(LinearSVC(class_weight="balanced"), cv=cv)),
        ]
    )


def train_svm_tfidf(texts: list[str], labels: list[int], output_path: Path = DEFAULT_SVM_MODEL_PATH) -> dict[str, object]:
    if len(set(labels)) < 2:
        raise ValueError("Training requires both spam and ham labels.")
    x_train, x_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=42, stratify=labels
    )
    min_class_count = min(y_train.count(0), y_train.count(1))
    model = build_svm_pipeline(cv=max(2, min(3, min_class_count)))
    model.fit(x_train, y_train)
    preds = model.predict(x_test)
    metrics = {
        "precision": float(precision_score(y_test, preds, zero_division=0)),
        "recall": float(recall_score(y_test, preds, zero_division=0)),
        "f1": float(f1_score(y_test, preds, zero_division=0)),
        "confusion_matrix": confusion_matrix(y_test, preds).tolist(),
        "samples": len(texts),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output_path)
    logger.info("saved_svm_model path=%s metrics=%s", output_path, metrics)
    return metrics


class SpamClassifier:
    """Primary fast classifier.

    DistilBERT is preferred when a fine-tuned model exists. The SVM/TF-IDF
    model remains as a lightweight fallback for local development and tests.
    """

    def __init__(
        self,
        model_dir: Path = DEFAULT_RUNTIME_DISTILBERT_MODEL_DIR,
        fallback_model_path: Path = DEFAULT_SVM_MODEL_PATH,
    ) -> None:
        self.model_dir = model_dir
        self.fallback_model_path = fallback_model_path
        self.distilbert = DistilBertMultilingualClassifier(model_dir)
        self.model: Pipeline | None = None
        if fallback_model_path.exists():
            self.model = joblib.load(fallback_model_path)
        else:
            self.model = self._fallback_model()

    def _fallback_model(self) -> Pipeline:
        samples = [
            "win money now click urgent prize lottery",
            "verify your account password bank login",
            "limited offer claim gift card free",
            "meeting notes for tomorrow project update",
            "invoice attached for approved vendor payment",
            "family dinner plan this weekend",
        ]
        labels = [1, 1, 1, 0, 0, 0]
        model = build_svm_pipeline()
        model.fit(samples, labels)
        return model

    def predict_text(self, text: str) -> ClassifierResult:
        if self.distilbert.available():
            return self.distilbert.predict_text(text)
        if self.model is None:
            raise RuntimeError("Classifier model is not loaded.")
        probs = self.model.predict_proba([text])[0]
        safe_prob = float(probs[0])
        spam_prob = float(probs[1])
        class_probabilities = {"safe": safe_prob, "phishing": 0.0, "spam": spam_prob}
        verdict = Verdict.spam if spam_prob >= safe_prob else Verdict.safe
        confidence = float(max(class_probabilities.values()))
        signals = keyword_signals(text)
        return ClassifierResult(
            verdict=verdict,
            confidence=confidence,
            class_probabilities=class_probabilities,
            risk_score=spam_prob,
            model_name="svm_tfidf_fallback",
            signals=signals,
        )

    def predict_email(self, email: EmailMessage) -> ClassifierResult:
        return self.predict_text(email_to_text(email))


def keyword_signals(text: str) -> list[str]:
    normalized = normalize_text(text)
    rules = {
        "urgent language": r"\burgent|immediately|act now\b",
        "credential request": r"\bpassword|verify|login|account suspended\b",
        "financial lure": r"\bprize|lottery|gift card|refund|wire transfer\b",
        "url present": r"\burl\b|https?://",
        "attachment lure": r"\battached|invoice|receipt\b",
    }
    return [name for name, pattern in rules.items() if re.search(pattern, normalized)]


class DistilBertMultilingualClassifier:
    """Optional Hugging Face classifier wrapper used when a fine-tuned model exists."""

    def __init__(self, model_dir: Path | None = None) -> None:
        self.model_dir = self._resolve_model_dir(model_dir or get_settings().distilbert_model_dir)
        self.pipeline = None
        self.id2label = self._load_id2label()
        if self._has_local_model_artifacts():
            try:
                from transformers import pipeline

                self.pipeline = pipeline(
                    "text-classification",
                    model=str(self.model_dir.resolve()),
                    tokenizer=str(self.model_dir.resolve()),
                    truncation=True,
                    max_length=512,
                    top_k=None,
                    local_files_only=True,
                )
            except Exception as exc:  # pragma: no cover - optional dependency path
                logger.warning("distilbert_load_failed path=%s error=%s", self.model_dir, exc)

    def _resolve_model_dir(self, preferred_dir: Path) -> Path:
        candidates = [preferred_dir]
        for candidate in (DEFAULT_DISTILBERT_MODEL_DIR, LEGACY_DISTILBERT_MODEL_DIR):
            if candidate not in candidates:
                candidates.append(candidate)
        for candidate in candidates:
            resolved = candidate.resolve()
            if self._has_local_model_artifacts(resolved):
                return resolved
        return preferred_dir.resolve()

    def _has_local_model_artifacts(self, model_dir: Path | None = None) -> bool:
        target_dir = model_dir or self.model_dir
        if not target_dir.exists() or not target_dir.is_dir():
            return False
        required_files = ("config.json", "tokenizer.json", "model.safetensors")
        return all((target_dir / filename).exists() for filename in required_files)

    def _load_id2label(self) -> dict[str, str]:
        config_path = self.model_dir / "config.json"
        if not config_path.exists():
            return {str(index): label for index, label in enumerate(SUPPORTED_CLASSIFIER_LABELS)}
        try:
            data = loads(config_path.read_text(encoding="utf-8"))
            raw_mapping = data.get("id2label", {})
            mapping = {str(key): str(value).lower() for key, value in raw_mapping.items()}
            if mapping:
                return mapping
        except Exception as exc:  # pragma: no cover - config read is best-effort
            logger.warning("distilbert_config_read_failed path=%s error=%s", config_path, exc)
        return {str(index): label for index, label in enumerate(SUPPORTED_CLASSIFIER_LABELS)}

    def available(self) -> bool:
        return self.pipeline is not None

    def _normalize_label(self, label: str) -> str:
        normalized = str(label).lower()
        if normalized in SUPPORTED_CLASSIFIER_LABELS:
            return normalized
        if normalized.startswith("label_"):
            normalized = normalized.split("_", 1)[1]
        return self.id2label.get(normalized, normalized)

    def predict_text(self, text: str) -> ClassifierResult:
        if not self.pipeline:
            raise RuntimeError("DistilBERT model is unavailable. Train it with scripts/train_distilbert.py.")
        outputs = self.pipeline(text)
        scores = outputs[0] if outputs and isinstance(outputs[0], list) else outputs
        class_probabilities = {label: 0.0 for label in SUPPORTED_CLASSIFIER_LABELS}
        for item in scores:
            label = self._normalize_label(str(item["label"]))
            if label in class_probabilities:
                class_probabilities[label] = float(item["score"])
        predicted_label = max(class_probabilities, key=class_probabilities.get)
        confidence = float(class_probabilities[predicted_label])
        risk_score = float(max(class_probabilities["phishing"], class_probabilities["spam"]))
        return ClassifierResult(
            verdict=Verdict(predicted_label),
            confidence=confidence,
            class_probabilities=class_probabilities,
            risk_score=risk_score,
            model_name="distilbert_multilingual",
            signals=keyword_signals(text),
        )


def export_svm_metadata(model_path: Path = DEFAULT_MODEL_PATH) -> Path:
    metadata_path = model_path.with_suffix(".meta.pkl")
    payload = {"model_path": str(model_path), "onnx": "not exported; sklearn calibrated SVM uses pickle/joblib runtime"}
    with metadata_path.open("wb") as fh:
        pickle.dump(payload, fh)
    return metadata_path


@lru_cache(maxsize=1)
def get_default_classifier() -> SpamClassifier:
    return SpamClassifier()
