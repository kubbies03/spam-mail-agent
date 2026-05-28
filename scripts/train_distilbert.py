from __future__ import annotations

import argparse
import csv
import inspect
import json
import sys
from pathlib import Path

import numpy as np
from datasets import Dataset
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import train_test_split
import torch
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)

sys.path.append(str(Path(__file__).resolve().parents[1]))

LABEL2ID = {"safe": 0, "phishing": 1, "spam": 2}
ID2LABEL = {idx: label for label, idx in LABEL2ID.items()}
LABEL_ALIASES = {
    "0": "safe",
    "ham": "safe",
    "safe": "safe",
    "legitimate": "safe",
    "not spam": "safe",
    "non-spam": "safe",
    "1": "phishing",
    "phish": "phishing",
    "phishing": "phishing",
    "scam": "phishing",
    "fraud": "phishing",
    "2": "spam",
    "spam": "spam",
    "true": "spam",
}


def normalize_label(value: str) -> int:
    label = LABEL_ALIASES.get(value.strip().lower())
    if label is None:
        raise ValueError(f"Unsupported label: {value!r}")
    return LABEL2ID[label]


def load_rows(path: Path, text_col: str, label_col: str) -> tuple[list[str], list[int]]:
    texts: list[str] = []
    labels: list[int] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            text = str(row[text_col]).strip()
            if not text:
                continue
            texts.append(text)
            labels.append(normalize_label(row[label_col]))
    if len(set(labels)) < 2:
        raise ValueError(f"{path} must contain at least two labels.")
    return texts, labels


def to_dataset(texts: list[str], labels: list[int]) -> Dataset:
    return Dataset.from_dict({"text": texts, "label": labels})


def compute_metrics(eval_pred) -> dict[str, object]:
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels,
        preds,
        labels=[0, 1, 2],
        average=None,
        zero_division=0,
    )
    macro_precision, macro_recall, macro_f1, _ = precision_recall_fscore_support(
        labels,
        preds,
        labels=[0, 1, 2],
        average="macro",
        zero_division=0,
    )
    weighted_precision, weighted_recall, weighted_f1, _ = precision_recall_fscore_support(
        labels,
        preds,
        labels=[0, 1, 2],
        average="weighted",
        zero_division=0,
    )
    metrics: dict[str, object] = {
        "macro_precision": float(macro_precision),
        "macro_recall": float(macro_recall),
        "macro_f1": float(macro_f1),
        "weighted_precision": float(weighted_precision),
        "weighted_recall": float(weighted_recall),
        "weighted_f1": float(weighted_f1),
        "confusion_matrix": confusion_matrix(labels, preds, labels=[0, 1, 2]).tolist(),
    }
    for idx, label in ID2LABEL.items():
        metrics[f"{label}_precision"] = float(precision[idx])
        metrics[f"{label}_recall"] = float(recall[idx])
        metrics[f"{label}_f1"] = float(f1[idx])
    return metrics


def compute_class_weights(labels: list[int]) -> list[float]:
    counts = np.bincount(labels, minlength=len(LABEL2ID))
    total = counts.sum()
    return [float(total / (len(LABEL2ID) * count)) if count else 0.0 for count in counts]


def training_args_with_eval_strategy(**kwargs) -> TrainingArguments:
    params = inspect.signature(TrainingArguments.__init__).parameters
    if "evaluation_strategy" in params:
        kwargs["evaluation_strategy"] = "epoch"
    else:
        kwargs["eval_strategy"] = "epoch"
    return TrainingArguments(**kwargs)


class WeightedTrainer(Trainer):
    def __init__(self, class_weights: list[float] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.class_weights = class_weights

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.get("labels")
        outputs = model(**inputs)
        logits = outputs.get("logits")
        if self.class_weights is None:
            loss = outputs.get("loss")
        else:
            weights = torch.tensor(self.class_weights, dtype=logits.dtype, device=logits.device)
            loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
            loss = loss_fn(logits.view(-1, model.config.num_labels), labels.view(-1))
        return (loss, outputs) if return_outputs else loss


def build_datasets(
    train_path: Path,
    validation_path: Path | None,
    test_path: Path | None,
    text_col: str,
    label_col: str,
) -> tuple[dict[str, Dataset], list[int]]:
    train_texts, train_labels = load_rows(train_path, text_col, label_col)

    if validation_path:
        valid_texts, valid_labels = load_rows(validation_path, text_col, label_col)
    else:
        train_texts, valid_texts, train_labels, valid_labels = train_test_split(
            train_texts,
            train_labels,
            test_size=0.1,
            stratify=train_labels,
            random_state=42,
        )

    if test_path:
        test_texts, test_labels = load_rows(test_path, text_col, label_col)
    else:
        valid_texts, test_texts, valid_labels, test_labels = train_test_split(
            valid_texts,
            valid_labels,
            test_size=0.5,
            stratify=valid_labels,
            random_state=42,
        )

    return {
        "train": to_dataset(train_texts, train_labels),
        "validation": to_dataset(valid_texts, valid_labels),
        "test": to_dataset(test_texts, test_labels),
    }, train_labels


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune DistilBERT for safe/phishing/spam email detection")
    parser.add_argument("--csv", type=Path, default=Path("data/spam_dataset.csv"))
    parser.add_argument("--validation-csv", type=Path, default=None)
    parser.add_argument("--test-csv", type=Path, default=None)
    parser.add_argument("--text-col", default="text")
    parser.add_argument("--label-col", default="label")
    parser.add_argument("--base-model", default="distilbert-base-uncased")
    parser.add_argument("--output", type=Path, default=Path("models/distilbert_multilingual"))
    parser.add_argument("--epochs", type=float, default=2)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--class-weights", choices=["none", "auto"], default="auto")
    args = parser.parse_args()

    dataset, train_labels = build_datasets(
        args.csv,
        args.validation_csv,
        args.test_csv,
        args.text_col,
        args.label_col,
    )
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=512)

    tokenized = {name: split.map(tokenize, batched=True) for name, split in dataset.items()}
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model,
        num_labels=len(LABEL2ID),
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )
    class_weights = compute_class_weights(train_labels) if args.class_weights == "auto" else None
    training_args = training_args_with_eval_strategy(
        output_dir=str(args.output),
        learning_rate=2e-5,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        num_train_epochs=args.epochs,
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        fp16=torch.cuda.is_available(),
        dataloader_pin_memory=torch.cuda.is_available(),
        logging_steps=20,
    )
    trainer = WeightedTrainer(
        class_weights=class_weights,
        model=model,
        args=training_args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["validation"],
        tokenizer=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
        compute_metrics=compute_metrics,
    )
    trainer.train()
    metrics = trainer.evaluate()
    test_metrics = trainer.evaluate(eval_dataset=tokenized["test"], metric_key_prefix="test")
    trainer.save_model(str(args.output))
    tokenizer.save_pretrained(str(args.output))
    payload = {
        "labels": LABEL2ID,
        "class_weights": class_weights,
        "validation": metrics,
        "test": test_metrics,
    }
    (args.output / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
