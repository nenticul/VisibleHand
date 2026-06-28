"""
Export ProsusAI/finbert to ONNX for fast CPU inference.

Run once before deploying:
  python scripts/export_finbert_onnx.py

Requires: transformers torch onnx (pip install transformers torch onnx)
Output: models/finbert-onnx/model.onnx + tokenizer files (~120 MB)
"""

from __future__ import annotations

import sys
from pathlib import Path

OUTPUT_DIR = Path("models/finbert-onnx")
MODEL_NAME = "ProsusAI/finbert"


def main() -> None:
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
    except ImportError:
        print("ERROR: torch and transformers are required. Run:")
        print("  pip install torch transformers")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {MODEL_NAME} from Hugging Face...")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
    model.eval()

    print("Exporting to ONNX...")
    dummy = tokenizer(
        "The committee raised interest rates by 25 basis points.",
        return_tensors="pt",
        max_length=512,
        truncation=True,
        padding="max_length",
    )

    onnx_path = OUTPUT_DIR / "model.onnx"
    torch.onnx.export(
        model,
        (dummy["input_ids"], dummy["attention_mask"], dummy["token_type_ids"]),
        str(onnx_path),
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch"},
            "attention_mask": {0: "batch"},
            "token_type_ids": {0: "batch"},
            "logits": {0: "batch"},
        },
        opset_version=14,
    )
    print(f"ONNX model saved to {onnx_path} ({onnx_path.stat().st_size / 1e6:.1f} MB)")

    # Save tokenizer alongside model
    tokenizer.save_pretrained(str(OUTPUT_DIR))
    print(f"Tokenizer saved to {OUTPUT_DIR}")

    # Quick sanity-check via onnxruntime
    try:
        import onnxruntime as ort
        import numpy as np

        sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        inputs_np = {k: v.numpy().astype(np.int64) for k, v in dummy.items()}
        logits = sess.run(None, inputs_np)[0]
        labels = ["positive", "negative", "neutral"]
        from scipy.special import softmax  # noqa: PLC0415
        probs = softmax(logits[0])
        print("Sanity-check inference:")
        for label, p in zip(labels, probs):
            print(f"  {label}: {p:.3f}")
        print("Export successful.")
    except ImportError:
        print("onnxruntime not installed — skipping sanity check. Install with: pip install onnxruntime")


if __name__ == "__main__":
    main()
