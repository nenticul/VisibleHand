"""
Conformal uncertainty + abstention.

Split conformal prediction over a held-out calibration set gives a distribution-
free half-width with marginal coverage. Time series violate exchangeability, so
the evaluate script fits the calibrator on a *past* validation window and the
coverage report is always published alongside (build guide §11).
"""

from __future__ import annotations

import json
import os
from typing import Optional

import numpy as np


class ConformalCalibrator:
    def __init__(self):
        self.residuals_: Optional[np.ndarray] = None

    def fit(self, y_true: np.ndarray, y_pred: np.ndarray,
            dates: Optional[np.ndarray] = None) -> "ConformalCalibrator":
        y_true = np.asarray(y_true, float); y_pred = np.asarray(y_pred, float)
        self.residuals_ = np.sort(np.abs(y_true - y_pred))
        return self

    def half_width(self, alpha: float = 0.1) -> float:
        if self.residuals_ is None or self.residuals_.size == 0:
            return float("nan")
        n = self.residuals_.size
        # finite-sample conformal quantile level
        q_level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
        return float(np.quantile(self.residuals_, q_level, method="higher"))

    def interval(self, y_pred: float, alpha: float = 0.1,
                 lo: float = 0.0, hi: float = 100.0) -> tuple[float, float]:
        hw = self.half_width(alpha)
        if not np.isfinite(hw):
            hw = 9.0  # fallback half-width if uncalibrated
        return (round(max(lo, y_pred - hw), 2), round(min(hi, y_pred + hw), 2))

    def coverage_report(self, alpha: float = 0.1) -> dict:
        if self.residuals_ is None or self.residuals_.size == 0:
            return {"coverage_target": 1 - alpha, "empirical_coverage": None, "n": 0}
        hw = self.half_width(alpha)
        covered = float(np.mean(self.residuals_ <= hw))
        return {
            "coverage_target": round(1 - alpha, 4),
            "empirical_coverage": round(covered, 4),
            "half_width": round(hw, 4),
            "n": int(self.residuals_.size),
        }

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        res = self.residuals_ if self.residuals_ is not None else np.array([])
        with open(path, "w") as f:
            json.dump({"residuals": [round(float(x), 4) for x in res]}, f)

    @classmethod
    def load(cls, path: str) -> "ConformalCalibrator":
        obj = cls()
        with open(path) as f:
            data = json.load(f)
        obj.residuals_ = np.sort(np.asarray(data.get("residuals", []), dtype=float))
        return obj


def abstain_decision(
    feature_row: dict,
    interval: tuple[float, float],
    hazard_calibration_status: str = "experimental",
    min_quality: float = 0.5,
    max_missing: int = 4,
    max_width: float = 40.0,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    dq = feature_row.get("data_quality_score")
    if dq is not None and dq < min_quality:
        reasons.append(f"data_quality_score {dq:.2f} < {min_quality}")
    mc = feature_row.get("missing_feature_count")
    if mc is not None and mc > max_missing:
        reasons.append(f"missing_feature_count {mc} > {max_missing}")
    width = interval[1] - interval[0]
    if width > max_width:
        reasons.append(f"interval_width {width:.1f} > {max_width}")
    if hazard_calibration_status == "invalid":
        reasons.append("hazard model calibration invalid")
    return (len(reasons) > 0, reasons)
