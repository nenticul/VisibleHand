"""
Aspect-Based Sentiment Analysis (ABSA) for policy documents.

Generic positive/negative is too crude for country risk. This module assigns
per-aspect sentiment scores to central-bank statements and IMF documents,
letting the API surface not just "Brazil is risky" but "Brazil's banking-sector
language is stressed while monetary policy is neutral."

Five aspects tracked:

  | Aspect            | Signal                                  |
  |-------------------|-----------------------------------------|
  | monetary_policy   | Rate hike / accommodation language      |
  | fiscal_policy     | Consolidation / deficit / debt burden   |
  | financial_stability| NPL / systemic risk / banking stress   |
  | external_sector   | Reserves / current account / devaluation|
  | political_economy | Social tensions / reform resistance     |

Implementation: sentence-level keyword routing to the lexicon, then aggregate
FinBERT/lexicon sentiment per aspect. Works without GPU — lexicon-only path
gives deterministic, interpretable output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import mean

from core.nlp.lexicon import lexicon_score

# ── Aspect keyword routing ───────────────────────────────────────────────────

ASPECT_KEYWORDS: dict[str, list[str]] = {
    "monetary_policy": [
        "rate", "interest rate", "monetary policy", "tighten", "ease", "hawkish",
        "dovish", "restrictive", "accommodation", "stimulus", "hike", "cut",
        "inflation target", "policy rate", "federal funds", "key rate",
        "repo rate", "selic", "refinancing rate", "bank rate",
    ],
    "fiscal_policy": [
        "fiscal", "budget", "deficit", "debt", "consolidation", "spending",
        "revenue", "tax", "public debt", "sovereign", "austerity", "primary balance",
        "debt to gdp", "fiscal space", "fiscal capacity", "public finance",
        "expenditure", "borrowing", "bonds",
    ],
    "financial_stability": [
        "banking", "financial stability", "npl", "non-performing", "systemic risk",
        "capital adequacy", "credit risk", "liquidity", "bank", "financial sector",
        "stress test", "deposit", "loan", "leverage", "solvency", "credit growth",
        "financial system", "balance sheet",
    ],
    "external_sector": [
        "current account", "reserves", "exchange rate", "external", "trade",
        "imports", "exports", "balance of payments", "capital flows",
        "depreciation", "appreciation", "devaluation", "fx", "foreign exchange",
        "external debt", "remittances",
    ],
    "political_economy": [
        "reform", "structural", "institution", "governance", "political",
        "social", "inequality", "poverty", "protest", "stability", "election",
        "corruption", "rule of law", "property rights", "contract enforcement",
        "business environment", "investment climate",
    ],
}

# Pre-compiled patterns for efficiency
_ASPECT_PATTERNS: dict[str, re.Pattern] = {
    aspect: re.compile(r"\b(" + "|".join(re.escape(kw) for kw in sorted(kws, key=len, reverse=True)) + r")\b", re.I)
    for aspect, kws in ASPECT_KEYWORDS.items()
}


@dataclass
class AspectScores:
    monetary_policy: float | None = None
    fiscal_policy: float | None = None
    financial_stability: float | None = None
    external_sector: float | None = None
    political_economy: float | None = None
    overall: float = 50.0
    sentence_count: int = 0

    def to_dict(self) -> dict[str, float | None]:
        return {
            "monetary_policy": self.monetary_policy,
            "fiscal_policy": self.fiscal_policy,
            "financial_stability": self.financial_stability,
            "external_sector": self.external_sector,
            "political_economy": self.political_economy,
            "overall": self.overall,
        }


def _lexicon_to_risk(raw: float) -> float:
    """Convert signed lexicon raw score → 0-100 risk (hawkish/stressed = higher)."""
    import math
    risk01 = 1.0 / (1.0 + math.exp(-0.18 * raw))
    return round(risk01 * 100, 1)


def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+|\n", text.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def aspect_sentiment_score(text: str) -> AspectScores:
    """
    Compute per-aspect risk scores from a policy document / central-bank statement.
    Returns AspectScores with 0-100 values (higher = more stressed/risky).
    """
    if not text or len(text) < 40:
        return AspectScores()

    sentences = _split_sentences(text)
    if not sentences:
        return AspectScores()

    # Assign each sentence to one or more aspects
    aspect_signals: dict[str, list[float]] = {a: [] for a in ASPECT_KEYWORDS}

    for sentence in sentences:
        matched_aspects: list[str] = []
        for aspect, pattern in _ASPECT_PATTERNS.items():
            if pattern.search(sentence):
                matched_aspects.append(aspect)

        if not matched_aspects:
            continue

        raw_score, _ = lexicon_score(sentence)
        risk_score = _lexicon_to_risk(raw_score)

        for aspect in matched_aspects:
            aspect_signals[aspect].append(risk_score)

    # Aggregate per aspect
    aspect_results: dict[str, float | None] = {}
    for aspect, signals in aspect_signals.items():
        if signals:
            aspect_results[aspect] = round(mean(signals), 1)
        else:
            aspect_results[aspect] = None

    # Overall: average of all non-None aspects
    non_none = [v for v in aspect_results.values() if v is not None]
    overall = round(mean(non_none), 1) if non_none else 50.0

    return AspectScores(
        monetary_policy=aspect_results.get("monetary_policy"),
        fiscal_policy=aspect_results.get("fiscal_policy"),
        financial_stability=aspect_results.get("financial_stability"),
        external_sector=aspect_results.get("external_sector"),
        political_economy=aspect_results.get("political_economy"),
        overall=overall,
        sentence_count=len(sentences),
    )


def aggregate_aspect_scores(scores: list[AspectScores]) -> AspectScores:
    """
    Time-weight a list of AspectScores (most recent first) into a single score.
    Uses exponential weighting: most recent document has weight 1.0, older ones decay.
    """
    if not scores:
        return AspectScores()
    if len(scores) == 1:
        return scores[0]

    import math
    half_life = 3  # documents
    weights = [math.exp(-math.log(2) / half_life * i) for i in range(len(scores))]
    total_w = sum(weights)

    def _weighted_avg(vals: list[float | None], ws: list[float]) -> float | None:
        pairs = [(v, w) for v, w in zip(vals, ws) if v is not None]
        if not pairs:
            return None
        tw = sum(w for _, w in pairs)
        return round(sum(v * w for v, w in pairs) / tw, 1) if tw else None

    return AspectScores(
        monetary_policy=_weighted_avg([s.monetary_policy for s in scores], weights),
        fiscal_policy=_weighted_avg([s.fiscal_policy for s in scores], weights),
        financial_stability=_weighted_avg([s.financial_stability for s in scores], weights),
        external_sector=_weighted_avg([s.external_sector for s in scores], weights),
        political_economy=_weighted_avg([s.political_economy for s in scores], weights),
        overall=_weighted_avg([s.overall for s in scores], weights) or 50.0,  # type: ignore[arg-type]
    )
