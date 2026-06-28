"""
FinBERT inference — ONNX runtime path with Hugging Face fallback.

Load order:
  1. ONNX Runtime (fast, CPU, ~50ms/inference) from `models/finbert-onnx/`
  2. Hugging Face `transformers` pipeline (slower, loads full PyTorch model)
  3. Pure lexicon fallback (no ML, always available)

Export the ONNX model once with: `python scripts/export_finbert_onnx.py`

Output: probability distribution over {negative, neutral, positive}.
We map negative -> risk, positive -> stability.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Label order used by ProsusAI/finbert tokenizer
_FINBERT_LABELS = ["positive", "negative", "neutral"]

_ort_session = None
_tokenizer = None
_hf_pipeline = None
_backend: str = "none"   # "onnx" | "hf" | "none"


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


def _try_load_onnx(model_dir: str) -> bool:
    global _ort_session, _tokenizer, _backend
    model_path = Path(model_dir) / "model.onnx"
    vocab_path = Path(model_dir)
    if not model_path.exists():
        return False
    try:
        import onnxruntime as ort
        from transformers import AutoTokenizer

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.log_severity_level = 3  # suppress INFO spam
        _ort_session = ort.InferenceSession(
            str(model_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        _tokenizer = AutoTokenizer.from_pretrained(str(vocab_path))
        _backend = "onnx"
        log.info("FinBERT ONNX loaded from %s", model_dir)
        return True
    except Exception as exc:
        log.debug("ONNX load failed (%s): %s", model_dir, exc)
        return False


def _try_load_hf(model_name: str) -> bool:
    global _hf_pipeline, _backend
    try:
        from transformers import pipeline as hf_pipeline

        _hf_pipeline = hf_pipeline(
            "text-classification",
            model=model_name,
            top_k=None,
            truncation=True,
        )
        _backend = "hf"
        log.info("FinBERT HF pipeline loaded (%s)", model_name)
        return True
    except Exception as exc:
        log.debug("HF pipeline load failed: %s", exc)
        return False


def initialise(model_dir: str | None = None, model_name: str = "ProsusAI/finbert") -> str:
    """
    Initialise the NLP backend. Call once at startup.
    Returns the backend name: "onnx" | "hf" | "none".
    """
    global _backend
    if _backend != "none":
        return _backend

    # Try ONNX first
    resolved_dir = model_dir or os.environ.get("NLP_MODEL_DIR", "models/finbert-onnx")
    if _try_load_onnx(resolved_dir):
        return _backend

    # Fall back to HF pipeline
    if _try_load_hf(model_name):
        return _backend

    log.warning(
        "No FinBERT backend available — using lexicon only. "
        "Run `python scripts/export_finbert_onnx.py` to enable ONNX inference."
    )
    return "none"


def predict(text: str) -> dict[str, float] | None:
    """
    Run inference on `text`. Returns {label: probability} or None on failure.
    Labels: 'positive', 'negative', 'neutral'.
    """
    if _backend == "onnx":
        return _predict_onnx(text)
    if _backend == "hf":
        return _predict_hf(text)
    return None


def _predict_onnx(text: str) -> dict[str, float] | None:
    if _ort_session is None or _tokenizer is None:
        return None
    try:
        inputs = _tokenizer(
            text,
            return_tensors="np",
            max_length=512,
            truncation=True,
            padding="max_length",
        )
        ort_inputs = {
            k: v.astype(np.int64)
            for k, v in inputs.items()
            if k in {inp.name for inp in _ort_session.get_inputs()}
        }
        logits = _ort_session.run(None, ort_inputs)[0][0]
        probs = _softmax(logits)
        return dict(zip(_FINBERT_LABELS, probs.tolist()))
    except Exception as exc:
        log.debug("ONNX inference error: %s", exc)
        return None


def _predict_hf(text: str) -> dict[str, float] | None:
    if _hf_pipeline is None:
        return None
    try:
        preds = _hf_pipeline(text[:512])
        scores = preds[0] if isinstance(preds[0], list) else preds
        return {p["label"].lower(): p["score"] for p in scores}
    except Exception as exc:
        log.debug("HF inference error: %s", exc)
        return None


def risk_score_from_probs(probs: dict[str, float]) -> float:
    """
    Map FinBERT label probabilities to a 0-100 risk score.
    negative → risk, positive → stability, neutral → midpoint.
    """
    neg = probs.get("negative", 0.0)
    pos = probs.get("positive", 0.0)
    neu = probs.get("neutral", 0.0)
    return round((neg * 1.0 + neu * 0.5 + pos * 0.0) * 100, 1)
