"""
Central-bank hawkish/dovish lexicon.

WHY THIS EXISTS
---------------
The original scorer used `distilbert-base-uncased-finetuned-sst-2-english`, a
movie-review sentiment model. On central-bank text it is actively misleading:
"we remain vigilant" or "prepared to act decisively" read as *positive* to a
movie-review model, yet they are unambiguously *hawkish* (tightening, higher
risk). Generic sentiment is the wrong axis entirely.

The correct axis for monetary-policy text is HAWKISH ↔ DOVISH. This module
encodes a domain lexicon of policy phrases with signed weights, plus negation
and intensifier handling. It is combined with FinBERT (a finance-trained
transformer) in `sentiment.py` for a hybrid score that is both interpretable
and robust.

Score convention: positive contribution = hawkish = higher risk.
"""

from __future__ import annotations

import re

# Multi-word phrases are matched before single tokens. Weights are on a roughly
# [-3, 3] scale per hit; the aggregate is squashed downstream.
HAWKISH_TERMS: dict[str, float] = {
    # tightening / restrictive stance
    "raise rates": 2.5, "rate hike": 2.5, "tighten": 2.0, "tightening": 2.0,
    "restrictive": 2.0, "sufficiently restrictive": 2.5, "higher for longer": 2.5,
    "withdraw accommodation": 2.2, "remove accommodation": 2.2,
    "prepared to act": 1.8, "act decisively": 2.0, "forceful": 2.0,
    "vigilant": 1.5, "remain vigilant": 1.6, "closely monitor": 1.0,
    "upside risks to inflation": 2.4, "inflationary pressures": 2.0,
    "elevated inflation": 2.0, "persistent inflation": 2.4, "sticky inflation": 2.2,
    "above target": 1.8, "de-anchor": 2.5, "second-round effects": 2.0,
    "wage pressures": 1.6, "overheating": 2.2, "combat inflation": 2.2,
    "price stability": 1.0, "firmly committed": 1.5, "additional tightening": 2.6,
    "further increases": 2.0, "more restrictive": 2.4,
}

DOVISH_TERMS: dict[str, float] = {
    # easing / accommodative stance
    "cut rates": -2.5, "rate cut": -2.5, "lower rates": -2.3, "ease": -2.0,
    "easing": -2.0, "accommodative": -2.2, "accommodation": -1.8,
    "support growth": -1.8, "supportive": -1.6, "stimulus": -2.0,
    "moderate the degree": -2.0, "moderate restriction": -2.0,
    "inflation is declining": -2.0, "disinflation": -1.8, "easing inflation": -2.0,
    "downside risks to growth": -2.0, "weakening demand": -1.8,
    "soft landing": -1.2, "patient": -1.0, "data-dependent": -0.6,
    "gradual": -0.8, "return to target": -1.2, "well-anchored": -1.5,
    "cooling": -1.4, "slack": -1.4, "subdued": -1.4, "below target": -1.8,
    "pause": -1.2, "hold rates": -0.8, "no further": -1.5,
}

# Stress / instability vocabulary — independent of stance, raises risk directly.
STRESS_TERMS: dict[str, float] = {
    "crisis": 2.5, "emergency": 2.5, "turmoil": 2.2, "instability": 2.0,
    "volatility": 1.5, "uncertainty": 1.2, "elevated uncertainty": 1.6,
    "recession": 2.0, "contraction": 1.6, "currency pressure": 2.2,
    "capital outflows": 2.4, "depreciation": 1.8, "reserves declined": 2.2,
    "default": 3.0, "restructuring": 2.2, "intervention": 1.6,
    "exceptional": 1.4, "extraordinary": 1.6, "martial law": 3.0, "wartime": 2.6,
}

_NEGATORS = {"no", "not", "never", "without", "neither", "nor", "little", "limited"}
_INTENSIFIERS = {"very": 1.4, "highly": 1.4, "significantly": 1.5, "substantially": 1.5,
                 "strongly": 1.4, "considerably": 1.4, "materially": 1.3}
_DIMINISHERS = {"somewhat": 0.6, "slightly": 0.5, "marginally": 0.5, "modestly": 0.6}

_ALL_TERMS = {**HAWKISH_TERMS, **DOVISH_TERMS, **STRESS_TERMS}
# Longest phrases first so "raise rates" wins over "rates".
_SORTED_TERMS = sorted(_ALL_TERMS.items(), key=lambda kv: -len(kv[0]))


def _context_multiplier(text: str, start: int) -> float:
    """Inspect the ~3 words before a match for negation / intensifiers."""
    prefix = text[max(0, start - 40):start].lower()
    words = re.findall(r"[a-z'-]+", prefix)[-3:]
    mult = 1.0
    for w in words:
        if w in _NEGATORS:
            mult *= -0.8                 # negation flips and slightly damps
        elif w in _INTENSIFIERS:
            mult *= _INTENSIFIERS[w]
        elif w in _DIMINISHERS:
            mult *= _DIMINISHERS[w]
    return mult


def lexicon_score(text: str) -> tuple[float, dict[str, int]]:
    """
    Return (raw_signed_score, hit_counts).

    raw_signed_score aggregates hawkish(+) / dovish(-) / stress(+) hits with
    negation and intensifier handling. hit_counts is for explainability.
    """
    if not text:
        return 0.0, {}
    lowered = text.lower()
    total = 0.0
    hits: dict[str, int] = {}
    consumed: list[tuple[int, int]] = []  # spans already matched (avoid overlap)

    for term, weight in _SORTED_TERMS:
        for m in re.finditer(re.escape(term), lowered):
            s, e = m.start(), m.end()
            if any(s < ce and e > cs for cs, ce in consumed):
                continue
            consumed.append((s, e))
            total += weight * _context_multiplier(lowered, s)
            hits[term] = hits.get(term, 0) + 1

    return total, hits


def hawkish_dovish_label(raw: float) -> str:
    if raw >= 4:
        return "strongly hawkish"
    if raw >= 1.5:
        return "hawkish"
    if raw > -1.5:
        return "neutral"
    if raw > -4:
        return "dovish"
    return "strongly dovish"
