from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a fine-tuned DistilBERT model to ONNX")
    parser.add_argument("--model-dir", type=Path, default=Path("models/distilbert_multilingual"))
    parser.add_argument("--output", type=Path, default=Path("models/distilbert_multilingual/model.onnx"))
    args = parser.parse_args()
    from transformers.onnx import FeaturesManager, export
    from transformers import AutoConfig, AutoModelForSequenceClassification, AutoTokenizer

    config = AutoConfig.from_pretrained(args.model_dir)
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_dir)
    model_kind, model_onnx_config = FeaturesManager.check_supported_model_or_raise(config, feature="sequence-classification")
    onnx_config = model_onnx_config(config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    export(preprocessor=tokenizer, model=model, config=onnx_config, opset=14, output=args.output)
    print(f"exported={args.output} model_kind={model_kind}")


if __name__ == "__main__":
    main()
