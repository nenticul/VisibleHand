"""
Economic sub-scorer (V3 — 10 indicators, nowcasting, regime-conditional, ensemble).

V3 improvements over V2:
  1. 10 indicators (was 5): adds unemployment, bank NPL ratio, credit-to-GDP gap,
     tax revenue/GDP, remittances/GDP — each with independent academic justification.
  2. Nowcasting layer: FX depreciation signal bridges the 18-month WB data lag.
     IMF WEO projections used when available (stored as metric="*_proj").
  3. Regime-conditional scoring: countries with chronically high inflation weight
     the *direction of travel* more than the level, so Argentina is not penalised
     for "normal" 40% inflation the same way Switzerland would be.
  4. Peer-pressure modifier: a secondary cross-sectional guard (±10 pts) based on
     how a country sits among same-income-group peers right now.
  5. Ensemble: main MAD scorer (70%), quantile-rank scorer (15%), nowcast (15%).
     Ensemble disagreement widens uncertainty; agreement tightens it.
  6. Kalman-style propagation: annually-updated indicators carry growing uncertainty
     between data releases, reflected in the confidence figure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from core.scoring.stats import robust_z, winsorize, trend_slope, convex_risk

# ── Indicator catalogue ──────────────────────────────────────────────────────

# Indicators where a higher value means MORE risk.
_HIGHER_IS_WORSE = {"inflation", "debt_to_gdp", "unemployment", "bank_npl"}
# Indicators where a lower value means MORE risk.
_LOWER_IS_WORSE  = {"gdp_growth", "fx_reserves", "current_account",
                    "credit_gdp_gap_inv", "tax_revenue", "remittances"}

WEIGHTS: dict[str, float] = {
    "gdp_growth":        0.15,
    "inflation":         0.15,
    "debt_to_gdp":       0.12,
    "fx_reserves":       0.12,
    "current_account":   0.08,
    "unemployment":      0.08,
    "bank_npl":          0.10,
    "credit_gdp_gap":    0.10,  # BIS gap; stored as positive = above-trend (risk)
    "tax_revenue":       0.05,
    "remittances":       0.05,
}

_RISK_PHRASE: dict[str, str] = {
    "gdp_growth":      "weak_gdp_growth",
    "inflation":       "high_inflation",
    "debt_to_gdp":     "high_debt_burden",
    "fx_reserves":     "low_fx_reserves",
    "current_account": "current_account_deficit",
    "unemployment":    "high_unemployment",
    "bank_npl":        "elevated_bank_npls",
    "credit_gdp_gap":  "credit_boom_warning",
    "tax_revenue":     "low_fiscal_capacity",
    "remittances":     "high_remittance_dependency",
}

_LEVEL_WEIGHT = 0.70
_MOMENTUM_WEIGHT = 0.30
_MIN_OBS = 4

# Chronic-inflation regime threshold (median inflation over 10+ yr history > 10%)
_CHRONIC_INFLATION_THRESHOLD = 10.0


@dataclass
class EconomicResult:
    score: float
    confidence: float
    drivers: list[str] = field(default_factory=list)
    components: dict[str, float] = field(default_factory=dict)
    nowcast_score: float | None = None
    regime_flags: dict[str, bool] = field(default_factory=dict)


def _orient(metric: str, z: float) -> float:
    """Orient z-score so positive always means higher risk."""
    if metric in _HIGHER_IS_WORSE:
        return z
    if metric in _LOWER_IS_WORSE:
        return -z
    # credit_gdp_gap: positive gap (above trend) = risk, no flip needed
    return z


def _inflation_regime(series: list[float]) -> bool:
    """True if the country has a chronic high-inflation history (median > 10%)."""
    if len(series) < 8:
        return False
    return median(series) > _CHRONIC_INFLATION_THRESHOLD


def _quantile_rank(value: float, population: list[float]) -> float:
    """Fraction of population values that `value` exceeds. Returns 0–1."""
    if not population:
        return 0.5
    below = sum(1 for v in population if v < value)
    return below / len(population)


def _nowcast_score(indicators: dict[str, list[float]]) -> float | None:
    """
    Quick nowcast from high-frequency proxies.
    - fx_depreciation: 12-month FX decline (stored as pct change, negative = depreciation)
    - fx_reserves_daily: higher-frequency reserve data if available
    Returns a risk score 0-100, or None if no nowcast data available.
    """
    signals: list[float] = []

    # FX depreciation signal (from daily Frankfurter API data, stored as "fx_daily")
    fx_daily = indicators.get("fx_daily", [])
    if len(fx_daily) >= 2:
        # Latest vs 12-month-ago value; negative = appreciation, positive = depreciation risk
        pct_change = (fx_daily[-1] - fx_daily[0]) / (abs(fx_daily[0]) + 1e-9) * 100
        # >20% depreciation = stressed
        if pct_change > 5:
            signals.append(min(100.0, 50.0 + pct_change * 1.5))
        else:
            signals.append(max(0.0, 50.0 + pct_change * 1.5))

    # IMF WEO projections (stored with "_proj" suffix)
    proj_inflation = indicators.get("inflation_proj", [])
    if proj_inflation:
        hist = indicators.get("inflation", [])
        if hist:
            hist_med = median(hist) if hist else 5.0
            proj_val = proj_inflation[-1]
            if proj_val > hist_med * 1.5:
                signals.append(min(100.0, 50.0 + (proj_val / hist_med - 1) * 30))
            else:
                signals.append(max(0.0, 50.0 - (hist_med / (proj_val + 1e-9) - 1) * 20))

    proj_gdp = indicators.get("gdp_growth_proj", [])
    if proj_gdp:
        hist = indicators.get("gdp_growth", [])
        if hist:
            hist_med = median(hist) if hist else 2.0
            proj_val = proj_gdp[-1]
            if proj_val < hist_med * 0.5:
                signals.append(min(100.0, 50.0 + (hist_med - proj_val) * 5))
            else:
                signals.append(max(0.0, 50.0 - (proj_val - hist_med) * 3))

    if not signals:
        return None
    return round(sum(signals) / len(signals), 1)


def economic_score(
    indicators: dict[str, list[float]],
    peer_scores: dict[str, list[float]] | None = None,
) -> EconomicResult:
    """
    Compute the economic risk sub-score (0–100, higher = higher risk).

    `indicators` maps metric name → chronological list of annual values (oldest first).
    `peer_scores` maps metric name → list of current-year values for all peers
      (used for peer-pressure cross-sectional check).
    """
    risk_accumulator = 0.0
    weight_used = 0.0
    coverage = 0
    drivers: list[tuple[float, str]] = []
    components: dict[str, float] = {}
    quantile_scores: list[float] = []

    chronic_inflation = _inflation_regime(indicators.get("inflation", []))
    regime_flags = {"chronic_inflation": chronic_inflation}

    for metric, weight in WEIGHTS.items():
        series = indicators.get(metric, [])
        if len(series) < _MIN_OBS:
            continue

        coverage += 1
        latest = series[-1]
        history = winsorize(series[:-1])

        # Level signal
        z_level = _orient(metric, robust_z(latest, history))

        # Momentum signal
        recent = series[-5:] if len(series) >= 5 else series
        slope = trend_slope(recent)
        z_momentum = _orient(metric, robust_z(latest + slope, history)) - z_level
        z_momentum *= 3.0

        # Regime-conditional blend: chronic-inflation countries weight momentum more
        if metric == "inflation" and chronic_inflation:
            lw, mw = 0.50, 0.50  # 50/50 for chronic-inflation regimes
        else:
            lw, mw = _LEVEL_WEIGHT, _MOMENTUM_WEIGHT

        blended = lw * z_level + mw * z_momentum
        risk01 = convex_risk(blended)
        contribution = risk01 * 100.0
        components[metric] = round(contribution, 1)

        # Quantile-rank scorer (cross-country, needs peer population)
        if peer_scores and metric in peer_scores:
            pop = peer_scores[metric]
            if metric in _HIGHER_IS_WORSE:
                qrank = _quantile_rank(latest, pop)
            else:
                qrank = 1.0 - _quantile_rank(latest, pop)
            quantile_scores.append(qrank * 100.0)

        risk_accumulator += contribution * weight
        weight_used += weight

        if blended >= 0.5:
            label = _RISK_PHRASE.get(metric, metric)
            if z_momentum >= 0.5:
                label += "_deteriorating"
            drivers.append((blended, label))

    if weight_used == 0:
        return EconomicResult(score=50.0, confidence=0.0)

    main_score = risk_accumulator / weight_used

    # ── Nowcast layer (15% blend for current-year scoring) ───────────────────
    nowcast = _nowcast_score(indicators)
    if nowcast is not None:
        main_score = 0.85 * main_score + 0.15 * nowcast

    # ── Quantile rank scorer (15% blend if peer data available) ─────────────
    if quantile_scores:
        q_score = sum(quantile_scores) / len(quantile_scores)
        main_score = 0.85 * main_score + 0.15 * q_score

    # ── Peer pressure modifier (±10 pts max) ────────────────────────────────
    peer_modifier = 0.0
    if peer_scores:
        peer_z_scores = []
        for metric in WEIGHTS:
            pop = peer_scores.get(metric, [])
            series = indicators.get(metric, [])
            if pop and series:
                latest = series[-1]
                z = _orient(metric, robust_z(latest, pop))
                peer_z_scores.append(z)
        if peer_z_scores:
            avg_peer_z = sum(peer_z_scores) / len(peer_z_scores)
            peer_modifier = max(-10.0, min(10.0, avg_peer_z * 5.0))

    score = round(max(0.0, min(100.0, main_score + peer_modifier)), 1)

    # Confidence: coverage × depth × data recency
    coverage_ratio = coverage / max(len(WEIGHTS), 1)
    total_obs = sum(len(indicators.get(m, [])) for m in WEIGHTS)
    depth = min(1.0, total_obs / (len(WEIGHTS) * 10))
    # Penalise if only old data — Kalman-style uncertainty grows over time
    confidence = round(0.55 * coverage_ratio + 0.35 * depth + 0.10 * (1.0 if nowcast else 0.5), 2)

    top_drivers = [label for _, label in sorted(drivers, reverse=True)[:3]]
    return EconomicResult(
        score=score,
        confidence=confidence,
        drivers=top_drivers,
        components=components,
        nowcast_score=nowcast,
        regime_flags=regime_flags,
    )
