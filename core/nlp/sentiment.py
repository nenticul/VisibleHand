"""
Central-bank statement risk scorer (v2 — hybrid FinBERT + domain lexicon).

The score we want is NOT generic positive/negative sentiment. It is a
hawkishness-and-stress signal: how much does this statement's language imply
tightening pressure, inflation concern, or financial instability?

Two complementary signals are fused:

  1. FinBERT (`ProsusAI/finbert`) — via ONNX Runtime (fast) or HF pipeline
     (slow). Its `negative` probability mass maps to risk. Falls back to
     lexicon-only when neither backend is available.

  2. Domain lexicon (`core.nlp.lexicon`) — signed hawkish/dovish/stress phrase
     weights with negation handling. Interpretable and catches policy idioms
     ("higher for longer", "remain vigilant") that even FinBERT can miss.

The two are blended. When the transformer is unavailable the scorer degrades
gracefully to the lexicon alone — the API never hard-fails.

Output: 0 (very dovish / stable) ... 100 (very hawkish / high risk), plus a
SentimentResult carrying the breakdown for explainability.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from core.nlp.lexicon import lexicon_score, hawkish_dovish_label
from core.nlp import finbert as _finbert_mod

_W_TRANSFORMER = 0.55
_W_LEXICON = 0.45

_finbert_initialised = False


def _ensure_finbert():
    global _finbert_initialised
    if not _finbert_initialised:
        _finbert_mod.initialise()
        _finbert_initialised = True


@dataclass
class SentimentResult:
    score: float                       # 0-100, higher = hawkish / risk
    label: str
    confidence: float
    transformer_score: float | None = None
    lexicon_score: float | None = None
    drivers: list[str] = field(default_factory=list)
    hits: dict[str, int] = field(default_factory=dict)
    backend: str = "lexicon"


def _split_sentences(text: str, max_chunks: int = 8) -> list[str]:
    """Split into sentence-ish chunks (FinBERT works best on sentences)."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks = [s for s in sentences if len(s) > 15]
    return chunks[:max_chunks] if chunks else [text[:400]]


def _transformer_risk(text: str) -> float | None:
    """Run FinBERT and return 0-100 risk score, or None if unavailable."""
    _ensure_finbert()
    chunks = _split_sentences(text)
    risks: list[float] = []
    for chunk in chunks:
        probs = _finbert_mod.predict(chunk)
        if probs is None:
            continue
        risks.append(_finbert_mod.risk_score_from_probs(probs))
    if not risks:
        return None
    return round(sum(risks) / len(risks), 1)


def _lexicon_risk(text: str) -> tuple[float, dict[str, int]]:
    """Map the signed lexicon score into 0-100 via a logistic squash."""
    raw, hits = lexicon_score(text)
    risk01 = 1.0 / (1.0 + math.exp(-0.18 * raw))
    return round(risk01 * 100, 1), hits


def score_statement(text: str) -> float:
    """Back-compatible entry point: returns just the 0-100 float."""
    return analyse_statement(text).score


def analyse_statement(text: str) -> SentimentResult:
    """Full hybrid analysis with breakdown and drivers."""
    if not text or len(text) < 30:
        return SentimentResult(score=50.0, label="neutral", confidence=0.1, backend="lexicon")

    lex_score_val, hits = _lexicon_risk(text)
    raw_lex, _ = lexicon_score(text)
    trans_score = _transformer_risk(text)

    backend = _finbert_mod._backend if trans_score is not None else "lexicon"

    if trans_score is None:
        final = lex_score_val
        confidence = 0.5
    else:
        final = round(_W_TRANSFORMER * trans_score + _W_LEXICON * lex_score_val, 1)
        divergence = abs(trans_score - lex_score_val) / 100.0
        confidence = round(max(0.4, 0.95 - divergence), 2)

    drivers = [term for term, _ in sorted(hits.items(), key=lambda kv: -kv[1])[:4]]

    return SentimentResult(
        score=final,
        label=hawkish_dovish_label(raw_lex),
        confidence=confidence,
        transformer_score=trans_score,
        lexicon_score=lex_score_val,
        drivers=drivers,
        hits=hits,
        backend=backend,
    )
