from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.classifier import export_svm_metadata, train_svm_tfidf


def load_csv(path: Path, text_col: str, label_col: str) -> tuple[list[str], list[int]]:
    texts: list[str] = []
    labels: list[int] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            text = row[text_col].strip()
            label_raw = row[label_col].strip().lower()
            label = 1 if label_raw in {"1", "spam", "true", "yes"} else 0
            if text:
                texts.append(text)
                labels.append(label)
    return texts, labels


def main() -> None:
    parser = argparse.ArgumentParser(description="Train fallback SVM + TF-IDF spam classifier")
    parser.add_argument("--csv", type=Path, default=Path("data/spam_dataset.csv"))
    parser.add_argument("--text-col", default="text")
    parser.add_argument("--label-col", default="label")
    parser.add_argument("--output", type=Path, default=Path("models/svm_tfidf.joblib"))
    args = parser.parse_args()
    texts, labels = load_csv(args.csv, args.text_col, args.label_col)
    metrics = train_svm_tfidf(texts, labels, args.output)
    export_svm_metadata(args.output)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
