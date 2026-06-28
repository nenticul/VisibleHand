"""
Robust statistical primitives for the scoring engine.

The original scorer used plain mean/std z-scores, which are badly distorted by
crisis years (COVID-2020, hyperinflation episodes). These break exactly when
risk matters most. This module provides outlier-resistant alternatives:

  - robust_z       : median/MAD-based z-score (resistant to fat tails)
  - winsorize      : clamp extreme observations before computing statistics
  - trend_slope    : Theil–Sen robust slope to capture momentum / direction
  - ewma           : exponentially weighted moving average (recency emphasis)
  - logistic       : smooth bounded squashing to [0, 1]
"""

from __future__ import annotations

import math
from statistics import median


def winsorize(series: list[float], limit: float = 0.10) -> list[float]:
    """Clamp the top/bottom `limit` fraction of observations to the quantile edge."""
    if len(series) < 5:
        return list(series)
    ordered = sorted(series)
    n = len(ordered)
    k = max(1, int(n * limit))
    lo, hi = ordered[k], ordered[n - 1 - k]
    return [min(max(x, lo), hi) for x in series]


def _mad(series: list[float], med: float) -> float:
    """Median absolute deviation, scaled to be a consistent estimator of sigma."""
    deviations = [abs(x - med) for x in series]
    return median(deviations) * 1.4826 if deviations else 0.0


def robust_z(value: float, series: list[float], clip: float = 3.0) -> float:
    """
    Median/MAD-based z-score of `value` against `series`, clipped to [-clip, clip].

    Falls back to mean/std if MAD is degenerate (e.g. many identical values),
    and returns 0.0 if no spread can be estimated at all.
    """
    if not series:
        return 0.0
    med = median(series)
    scale = _mad(series, med)
    if scale == 0:
        # Degenerate MAD — fall back to classic std.
        mu = sum(series) / len(series)
        var = sum((x - mu) ** 2 for x in series) / len(series)
        scale = math.sqrt(var)
        med = mu
    if scale == 0:
        # Zero-variance history (a perfectly flat baseline). There is no
        # statistical spread to normalise by, so fall back to a *relative*
        # deviation: how large is the move compared with the baseline level?
        # tanh keeps it bounded and preserves magnitude ordering (a 5% move
        # reads mild, an 800% move reads extreme) instead of saturating both.
        if value == med:
            return 0.0
        denom = abs(med) * 0.5 + 1e-9
        return clip * math.tanh((value - med) / denom)
    z = (value - med) / scale
    return max(-clip, min(clip, z))


def trend_slope(series: list[float]) -> float:
    """
    Theil–Sen robust slope: the median of all pairwise slopes.

    Positive = the indicator is rising over time, negative = falling.
    Robust to a single anomalous year that would wreck an OLS fit.
    """
    n = len(series)
    if n < 3:
        return 0.0
    slopes = [
        (series[j] - series[i]) / (j - i)
        for i in range(n)
        for j in range(i + 1, n)
    ]
    return median(slopes) if slopes else 0.0


def ewma(series: list[float], half_life: float = 3.0) -> float:
    """Exponentially weighted moving average, most recent observation last."""
    if not series:
        return 0.0
    decay = math.log(2) / half_life
    weights = [math.exp(-decay * (len(series) - 1 - i)) for i in range(len(series))]
    total_w = sum(weights)
    return sum(v * w for v, w in zip(series, weights)) / total_w if total_w else 0.0


def logistic(x: float, steepness: float = 1.0) -> float:
    """Smooth squash of any real number into (0, 1). logistic(0) = 0.5."""
    return 1.0 / (1.0 + math.exp(-steepness * x))


def convex_risk(z: float) -> float:
    """
    Map a (directional) z-score to a risk contribution in [0, 1] with a convex
    tail: being 3 SD into the danger zone is disproportionately worse than 1 SD.

    z is expected to be oriented so that higher = more risk.
    """
    # Logistic centred at 0, but with extra weight on the upper tail.
    base = logistic(z, steepness=0.9)
    # Convex emphasis: square-ish boost above the midpoint.
    if base > 0.5:
        base = 0.5 + (base - 0.5) ** 0.85 * 0.5 / (0.5 ** 0.85)
    return max(0.0, min(1.0, base))
