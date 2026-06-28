"""
Governance sub-scorer (Phase 5 — V-Dem, WJP, TI CPI, Freedom House).

Governance is slow-moving structural risk: rule of law, corruption, civil
liberties, judicial independence. It explains why some countries survive high
debt or conflict while others don't. Commercial products (ICRG) charge
specifically for these qualitative scores. VisibleHand produces them from
free public data.

Scoring approach:
  - Normalise cross-sectionally (vs global distribution), not own-history —
    governance is inherently comparative: Sweden and Somalia should not both
    be "average" relative to themselves.
  - 3-year exponential smoothing to reduce year-to-year noise from small survey
    samples.
  - Equal-weight five composite inputs.
  - Update annually when V-Dem/WJP/TI release new data.

Output: GovernanceResult with score 0-100 (higher = more risk/worse governance).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from core.scoring.stats import robust_z, convex_risk

# ── Indicator catalogue ──────────────────────────────────────────────────────

# V-Dem indicator keys (as stored in DB) — higher raw score = better governance
# so we invert: higher governance quality → lower risk
VDEM_INDICATORS: dict[str, str] = {
    "v2x_corr":         "political_corruption",
    "v2x_rule":         "rule_of_law",
    "v2xcs_ccsi":       "civil_society",
    "v2x_jucon":        "judicial_independence",
    "v2x_freexp_altinf": "press_freedom",
}

# Other governance indicators
OTHER_INDICATORS: dict[str, str] = {
    "wjp_rule_of_law":  "wjp_rule_of_law",   # 0–1, higher = better
    "ti_cpi":           "ti_cpi",             # 0–100, higher = less corrupt
    "fh_political":     "fh_political_rights",# 1–7, higher = worse
    "fh_civil":         "fh_civil_liberties", # 1–7, higher = worse
    "rsf_press":        "rsf_press_freedom",  # 0–100, higher = better
}

# Which indicators are "higher = better governance" (need inversion to risk)
_HIGHER_IS_BETTER = {
    "v2x_corr", "v2x_rule", "v2xcs_ccsi", "v2x_jucon", "v2x_freexp_altinf",
    "wjp_rule_of_law", "ti_cpi", "rsf_press",
}
# Which are "higher = worse governance" (direct risk signal)
_HIGHER_IS_WORSE = {"fh_political", "fh_civil"}

_SMOOTHING_HALFLIFE = 3.0  # years — 3-year exponential smoothing
_MIN_OBS = 2


@dataclass
class GovernanceResult:
    score: float
    confidence: float
    drivers: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)
    press_freedom_confidence_modifier: float = 1.0


def _ewma_latest(series: list[float], half_life: float = _SMOOTHING_HALFLIFE) -> float:
    """Exponentially weighted latest value (smoothed)."""
    if not series:
        return 0.0
    decay = math.log(2) / half_life
    weights = [math.exp(-decay * (len(series) - 1 - i)) for i in range(len(series))]
    total_w = sum(weights)
    return sum(v * w for v, w in zip(series, weights)) / total_w if total_w else series[-1]


def governance_score(
    indicators: dict[str, list[float]],
    global_population: dict[str, list[float]] | None = None,
) -> GovernanceResult:
    """
    Compute governance risk sub-score (0–100, higher = more risk).

    `indicators` maps metric key → list of annual values (oldest first).
    `global_population` maps metric key → list of all countries' latest values,
      used for cross-sectional normalisation. Falls back to own-history if absent.
    """
    risk_scores: list[float] = []
    components: dict[str, float] = {}
    drivers: list[tuple[float, str]] = []
    coverage = 0
    press_freedom_modifier = 1.0

    all_metrics = {**VDEM_INDICATORS, **OTHER_INDICATORS}

    for metric, label in all_metrics.items():
        series = indicators.get(metric, [])
        if len(series) < _MIN_OBS:
            continue

        coverage += 1
        smoothed = _ewma_latest(series)

        if global_population and metric in global_population:
            pop = global_population[metric]
            if metric in _HIGHER_IS_BETTER:
                # Low rank in a "better = higher" metric → high risk
                below = sum(1 for v in pop if v < smoothed)
                percentile = below / len(pop) if pop else 0.5
                risk01 = 1.0 - percentile
            else:
                # "Higher = worse": high rank → high risk
                below = sum(1 for v in pop if v < smoothed)
                percentile = below / len(pop) if pop else 0.5
                risk01 = percentile
        else:
            # Fallback: own-history z-score
            history = series[:-1]
            if not history:
                history = series
            z = robust_z(smoothed, history)
            if metric in _HIGHER_IS_BETTER:
                z = -z  # inverted
            risk01 = convex_risk(z)

        contribution = round(risk01 * 100.0, 1)
        components[label] = contribution
        risk_scores.append(contribution)

        if contribution > 60:
            drivers.append((contribution, f"weak_{label}"))

        # Press freedom is a confidence modifier for NLP scorer
        if metric in ("v2x_freexp_altinf", "rsf_press") and metric in _HIGHER_IS_BETTER:
            # Low press freedom → lower NLP confidence for that country
            press_freedom_modifier = min(
                press_freedom_modifier,
                0.5 + risk01 * 0.5  # ranges from 0.5 (worst) to 1.0 (best)
            )

    if not risk_scores:
        return GovernanceResult(score=50.0, confidence=0.0)

    score = round(sum(risk_scores) / len(risk_scores), 1)
    score = max(0.0, min(100.0, score))

    coverage_ratio = coverage / max(len(all_metrics), 1)
    confidence = round(0.7 * coverage_ratio + 0.3 * min(1.0, coverage / 5), 2)

    top_drivers = [label for _, label in sorted(drivers, reverse=True)[:3]]

    return GovernanceResult(
        score=score,
        confidence=confidence,
        drivers=top_drivers,
        components=components,
        press_freedom_confidence_modifier=round(press_freedom_modifier, 2),
    )
