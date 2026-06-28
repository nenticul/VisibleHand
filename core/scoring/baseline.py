"""
Cross-sectional baseline scorer — VisibleHand's SECOND measurement mode.

VisibleHand can now score a country two complementary ways:

  • TEMPORAL (self-referential, the original engine in economic.py)
      Normalises each macro indicator against the country's OWN history with a
      robust median/MAD z-score. Answers: "Is this country worse than it
      usually is?" — excellent for detecting regime shifts and momentum, but a
      chronically-stressed economy can look "calm" simply because today matches
      its own grim baseline.

  • CROSS-SECTIONAL (this module)
      Normalises each indicator against an EXTERNAL baseline of other countries.
      Answers: "How risky is this country compared with the rest of the world,
      its peers, and a fixed gold standard?" — the view a sovereign-bond desk or
      an IMF Article IV mission actually uses.

Why this design (the part economists care about)
-------------------------------------------------
A naive cross-sectional score (rank everyone, 0–100) has two well-known flaws:
comparing Switzerland to Chad is meaningless, and a pure relative rank has no
absolute anchor (if every country deteriorates, ranks don't move). We fix both:

  1. PEER PERCENTILE — every indicator is ranked inside the country's peer group
     (income group ∩ region) using the empirical CDF with mid-rank tie handling.
     Peer groups degrade gracefully: income∩region → income → region → global,
     so a thin cell never produces a noisy rank.

  2. ANCHOR DISTANCE — a fixed basket of investment-grade benchmark economies
     defines what "low risk / 0" looks like. Each indicator's robust z-distance
     from the anchor median pins the scale to a real-world standard, so the score
     moves even when the whole peer group drifts together.

The published indicator score blends the two (60% peer rank, 40% anchor
distance). Both views, the peer composition, and every per-indicator percentile
are returned for full transparency.

Why this design (the part engineers care about)
------------------------------------------------
Pure standard library, no NumPy/pandas/sklearn. Fully deterministic — identical
inputs give byte-identical output. The reference distribution is a single
immutable value object that can be built once and reused across an entire
`/risk/compare` call, and introspected wholesale via the `/baseline` endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.scoring.economic import (
    WEIGHTS, _HIGHER_IS_WORSE, _LOWER_IS_WORSE, _RISK_PHRASE, _orient,
)
from core.scoring.stats import robust_z, convex_risk

# ── Peer-group taxonomy (self-contained: scoring must not depend on worldstate) ─

# World-Bank-style income groups for the 44-country universe.
INCOME_GROUP: dict[str, str] = {
    # High income
    "US": "H", "CA": "H", "DE": "H", "GB": "H", "FR": "H", "IT": "H", "ES": "H",
    "NL": "H", "CH": "H", "JP": "H", "KR": "H", "AU": "H", "CL": "H", "PL": "H",
    "HU": "H", "GR": "H", "SA": "H", "RU": "H",
    # Upper-middle income
    "AR": "UM", "BR": "UM", "CN": "UM", "CO": "UM", "MX": "UM", "MY": "UM",
    "PE": "UM", "TR": "UM", "ZA": "UM", "TH": "UM", "ID": "UM", "VE": "UM",
    # Lower-middle income
    "EG": "LM", "IN": "LM", "PH": "LM", "VN": "LM", "MA": "LM", "BD": "LM",
    "PK": "LM", "LK": "LM", "NG": "LM", "KE": "LM", "GH": "LM", "UA": "LM",
    "LB": "LM",
    # Low income
    "ET": "L",
}
INCOME_LABEL = {
    "H": "High income", "UM": "Upper-middle income",
    "LM": "Lower-middle income", "L": "Low income",
}

REGION: dict[str, str] = {
    "US": "N. America", "CA": "N. America", "MX": "N. America",
    "BR": "S. America", "AR": "S. America", "CO": "S. America",
    "CL": "S. America", "PE": "S. America", "VE": "S. America",
    "DE": "Europe", "GB": "Europe", "FR": "Europe", "IT": "Europe",
    "ES": "Europe", "GR": "Europe", "NL": "Europe", "HU": "Europe",
    "CH": "Europe", "PL": "Europe", "UA": "Europe", "RU": "Europe",
    "TR": "MENA", "SA": "MENA", "EG": "MENA", "MA": "MENA", "LB": "MENA",
    "ZA": "Sub-Saharan", "NG": "Sub-Saharan", "KE": "Sub-Saharan",
    "ET": "Sub-Saharan", "GH": "Sub-Saharan",
    "CN": "Asia-Pacific", "JP": "Asia-Pacific", "KR": "Asia-Pacific",
    "IN": "Asia-Pacific", "ID": "Asia-Pacific", "PK": "Asia-Pacific",
    "BD": "Asia-Pacific", "VN": "Asia-Pacific", "PH": "Asia-Pacific",
    "TH": "Asia-Pacific", "MY": "Asia-Pacific", "LK": "Asia-Pacific",
    "AU": "Asia-Pacific",
}

# Fixed anchor: diversified, investment-grade benchmark economies. Robust median
# over this basket defines "what good looks like" for every indicator.
ANCHOR_ECONOMIES = ["CH", "DE", "NL", "CA", "AU", "JP", "US", "GB", "FR"]

MIN_PEERS = 5          # below this, broaden the peer group one level
MIN_METRIC_OBS = 3     # below this, fall back to the global population for a metric
PEER_WEIGHT = 0.60     # blend: peer percentile vs ...
ANCHOR_WEIGHT = 0.40   # ... distance from the anchor basket


@dataclass(frozen=True)
class BaselineReference:
    """Immutable cross-country reference built from the latest value per country."""
    populations: dict[str, dict[str, float]]   # metric -> {country: latest value}
    anchor: dict[str, list[float]]             # metric -> sorted anchor values
    countries: list[str]

    def metric_population(self, metric: str) -> dict[str, float]:
        return self.populations.get(metric, {})


def build_baseline_reference(latest_by_country: dict[str, dict[str, float]]) -> BaselineReference:
    """
    Build the reference distribution.

    `latest_by_country` maps country code → {metric: latest value}.
    """
    populations: dict[str, dict[str, float]] = {}
    for cc, metrics in latest_by_country.items():
        for m, v in metrics.items():
            if v is None:
                continue
            populations.setdefault(m, {})[cc.upper()] = float(v)

    anchor: dict[str, list[float]] = {}
    for m, pop in populations.items():
        vals = sorted(pop[c] for c in ANCHOR_ECONOMIES if c in pop)
        anchor[m] = vals

    return BaselineReference(
        populations=populations,
        anchor=anchor,
        countries=sorted(cc.upper() for cc in latest_by_country),
    )


def resolve_peer_group(country: str, ref: BaselineReference) -> tuple[str, list[str]]:
    """
    Resolve the comparison peer group with graceful fallback:
    income ∩ region → income → region → global universe.
    """
    cc = country.upper()
    inc = INCOME_GROUP.get(cc)
    reg = REGION.get(cc)
    pool = set(ref.countries) | {cc}

    def members(pred) -> list[str]:
        return sorted(c for c in pool if pred(c))

    if inc and reg:
        grp = members(lambda c: INCOME_GROUP.get(c) == inc and REGION.get(c) == reg)
        if len(grp) >= MIN_PEERS:
            return f"{INCOME_LABEL.get(inc, inc)} · {reg}", grp
    if inc:
        grp = members(lambda c: INCOME_GROUP.get(c) == inc)
        if len(grp) >= MIN_PEERS:
            return INCOME_LABEL.get(inc, inc), grp
    if reg:
        grp = members(lambda c: REGION.get(c) == reg)
        if len(grp) >= MIN_PEERS:
            return reg, grp
    return "Global universe", sorted(pool)


def _percentile(value: float, population: list[float]) -> float:
    """Empirical percentile of `value` in `population` (0–1), mid-rank for ties."""
    if not population:
        return 0.5
    below = sum(1 for v in population if v < value)
    equal = sum(1 for v in population if v == value)
    return (below + 0.5 * equal) / len(population)


@dataclass
class CrossSectionalEconomicResult:
    score: float
    confidence: float
    drivers: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)
    percentiles: dict[str, float] = field(default_factory=dict)   # oriented peer percentile, 0–100
    peer_group: str = ""
    peer_n: int = 0


def cross_sectional_economic(
    country: str,
    latest_values: dict[str, float],
    ref: BaselineReference,
) -> CrossSectionalEconomicResult:
    """
    Score a country's economic risk against the external baseline.

    `latest_values` maps metric → the country's most recent value.
    """
    label, peers = resolve_peer_group(country, ref)
    peer_set = set(peers)

    risk_acc = 0.0
    weight_used = 0.0
    coverage = 0
    components: dict[str, float] = {}
    percentiles: dict[str, float] = {}
    drivers: list[tuple[float, str]] = []

    for metric, weight in WEIGHTS.items():
        if metric not in latest_values or latest_values[metric] is None:
            continue
        value = float(latest_values[metric])
        pop = ref.metric_population(metric)
        if not pop:
            continue

        peer_vals = [pop[c] for c in peer_set if c in pop]
        if len(peer_vals) < MIN_METRIC_OBS:
            peer_vals = list(pop.values())   # thin cell → global distribution
        if not peer_vals:
            continue

        coverage += 1

        # 1. Peer percentile, oriented so higher = more risk.
        pct = _percentile(value, peer_vals)
        risk_pct = (1.0 - pct) if metric in _LOWER_IS_WORSE else pct

        # 2. Distance from the anchor basket (absolute standard).
        anchor_vals = ref.anchor.get(metric, [])
        if len(anchor_vals) >= MIN_METRIC_OBS:
            anchor_z = _orient(metric, robust_z(value, anchor_vals))
            anchor_risk = convex_risk(anchor_z)
            indicator_score = 100.0 * (PEER_WEIGHT * risk_pct + ANCHOR_WEIGHT * anchor_risk)
        else:
            indicator_score = 100.0 * risk_pct

        components[metric] = round(indicator_score, 1)
        percentiles[metric] = round(risk_pct * 100.0, 1)
        risk_acc += indicator_score * weight
        weight_used += weight

        if risk_pct >= 0.70:
            label_phrase = _RISK_PHRASE.get(metric, metric)
            drivers.append((risk_pct, label_phrase))

    if weight_used == 0:
        return CrossSectionalEconomicResult(
            score=50.0, confidence=0.0, peer_group=label, peer_n=len(peers),
        )

    score = round(max(0.0, min(100.0, risk_acc / weight_used)), 1)

    coverage_ratio = coverage / max(len(WEIGHTS), 1)
    peer_adequacy = min(1.0, len(peers) / 8.0)
    confidence = round(0.6 * coverage_ratio + 0.4 * peer_adequacy, 2)

    top_drivers = [lab for _, lab in sorted(drivers, reverse=True)[:3]]
    return CrossSectionalEconomicResult(
        score=score,
        confidence=confidence,
        drivers=top_drivers,
        components=components,
        percentiles=percentiles,
        peer_group=label,
        peer_n=len(peers),
    )
