"""
Crisis-type hazard models.

v0.1 ships a pure-numpy, L2-regularised, class-weighted logistic baseline plus a
transparent heuristic fallback (so every country always gets a hazard estimate,
even where labels are too sparse to train). Gradient-boosting / TabPFN / survival
models are optional, benchmark-gated experiments (build guide §7.3) and are not a
hard dependency.

All probabilities are experimental until calibration is validated — surfaced via
``calibration_status``.
"""

from __future__ import annotations

import json
import math
import os
from typing import Optional, Protocol

import numpy as np

from core.worldstate import registry as R

# Feature columns fed to hazard models (broadly available across the panel).
HAZARD_FEATURE_COLUMNS = list(R.EMBEDDING_FEATURE_COLUMNS)

# target → crisis_dataset crisis_type(s) that count as a positive label
TARGET_TO_CRISIS_TYPES = {
    "sovereign_default": {"default"},
    "currency_crisis": {"currency"},
    "imf_programme": {"imf_programme"},
    "banking_crisis": {"banking"},
    "civil_conflict": {"civil_war"},
    "coup": {"coup"},
    "political_instability": {"coup", "civil_war"},
    # sanctions_shock has no direct label in the crisis dataset → heuristic only
}


# ── metrics (pure numpy) ─────────────────────────────────────────────────────
def roc_auc(y: np.ndarray, p: np.ndarray) -> Optional[float]:
    y = np.asarray(y); p = np.asarray(p, dtype=float)
    pos, neg = p[y == 1], p[y == 0]
    if pos.size == 0 or neg.size == 0:
        return None
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    # average ranks for ties
    _, inv, counts = np.unique(p, return_inverse=True, return_counts=True)
    sums = np.zeros(counts.size); np.add.at(sums, inv, ranks)
    avg = sums / counts
    ranks = avg[inv]
    auc = (ranks[y == 1].sum() - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size)
    return float(auc)


def average_precision(y: np.ndarray, p: np.ndarray) -> Optional[float]:
    y = np.asarray(y); p = np.asarray(p, dtype=float)
    if y.sum() == 0:
        return None
    order = np.argsort(-p, kind="mergesort")
    y_sorted = y[order]
    tp = np.cumsum(y_sorted)
    precision = tp / np.arange(1, len(y) + 1)
    recall = tp / y.sum()
    ap, prev_r = 0.0, 0.0
    for prec, rec in zip(precision, recall):
        ap += prec * (rec - prev_r)
        prev_r = rec
    return float(ap)


def brier_score(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(np.asarray(p, float), 1e-7, 1 - 1e-7)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def expected_calibration_error(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    y = np.asarray(y, float); p = np.asarray(p, float)
    edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p < hi if i < n_bins - 1 else p <= hi)
        if mask.sum() == 0:
            continue
        ece += (mask.sum() / len(p)) * abs(p[mask].mean() - y[mask].mean())
    return float(ece)


def all_metrics(y, p) -> dict:
    return {
        "auc": roc_auc(y, p),
        "pr_auc": average_precision(y, p),
        "brier_score": brier_score(y, p),
        "log_loss": log_loss(y, p),
        "calibration_error": expected_calibration_error(y, p),
    }


# ── model interface ──────────────────────────────────────────────────────────
class BaseHazardModel(Protocol):
    name: str
    version: str

    def fit(self, X: np.ndarray, y: np.ndarray) -> None: ...
    def predict_proba(self, X: np.ndarray) -> np.ndarray: ...
    def save(self, path: str) -> None: ...


class LogisticHazardModel:
    """L2-regularised, class-weighted logistic regression (numpy)."""

    name = R.HAZARD_MODEL_NAME
    version = R.HAZARD_MODEL_VERSION

    def __init__(self, l2: float = 1.0, lr: float = 0.1, iters: int = 2000,
                 class_weight: str = "balanced", columns: Optional[list] = None):
        self.l2 = l2; self.lr = lr; self.iters = iters
        self.class_weight = class_weight
        self.columns = columns or HAZARD_FEATURE_COLUMNS
        self.mean_ = self.std_ = self.w_ = None
        self.b_ = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        X = np.asarray(X, float); y = np.asarray(y, float)
        X = self._impute_fit(X)
        self.mean_ = X.mean(axis=0); self.std_ = X.std(axis=0)
        self.std_[self.std_ < 1e-9] = 1.0
        Xs = (X - self.mean_) / self.std_
        n, d = Xs.shape
        self.w_ = np.zeros(d); self.b_ = 0.0

        if self.class_weight == "balanced" and y.sum() not in (0, n):
            w_pos = n / (2 * y.sum()); w_neg = n / (2 * (n - y.sum()))
        else:
            w_pos = w_neg = 1.0
        sw = np.where(y == 1, w_pos, w_neg)

        for _ in range(self.iters):
            z = Xs @ self.w_ + self.b_
            p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
            grad = (sw * (p - y))
            gw = Xs.T @ grad / n + self.l2 * self.w_ / n
            gb = grad.sum() / n
            self.w_ -= self.lr * gw
            self.b_ -= self.lr * gb

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = self._impute_transform(np.asarray(X, float))
        Xs = (X - self.mean_) / self.std_
        z = Xs @ self.w_ + self.b_
        return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))

    def _impute_fit(self, X):
        self.impute_ = np.nanmean(np.where(np.all(np.isnan(X), 0), 0.0, X), axis=0)
        self.impute_ = np.nan_to_num(self.impute_)
        return self._impute_transform(X)

    def _impute_transform(self, X):
        X = X.copy()
        idx = np.where(np.isnan(X))
        if idx[0].size:
            X[idx] = np.take(self.impute_, idx[1])
        return X

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez(path, w=self.w_, b=self.b_, mean=self.mean_, std=self.std_,
                 impute=self.impute_)
        with open(path + ".json", "w") as f:
            json.dump({"name": self.name, "version": self.version,
                       "columns": self.columns}, f)

    @classmethod
    def load(cls, path: str) -> "LogisticHazardModel":
        d = np.load(path + ".npz" if not path.endswith(".npz") else path)
        obj = cls()
        obj.w_ = d["w"]; obj.b_ = float(d["b"]); obj.mean_ = d["mean"]
        obj.std_ = d["std"]; obj.impute_ = d["impute"]
        return obj


# ── heuristic fallback (always available) ────────────────────────────────────
def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def heuristic_hazards(row: dict, code: str = "") -> dict[str, float]:
    """Transparent feature-driven priors per target (no training)."""
    g = lambda k: row.get(k) if row.get(k) is not None else 0.0
    infl = g("inflation_z"); debt = g("debt_to_gdp_z"); fx = g("fx_reserves_z")
    ca = g("current_account_z"); npl = g("bank_npl_z"); credit = g("credit_gap_z")
    gov = (g("governance_structural_score") - 50.0) / 25.0
    ev = math.log1p(g("event_count_90d"))
    base = (g("visiblehand_score") - 50.0) / 25.0
    sanc = R.SANCTIONED.get(code.upper(), 0.0)
    conflict = 1.0 if code.upper() in R.CONFLICT_COUNTRIES else 0.0

    return {
        "sovereign_default": round(_sig(-2.4 + 0.6 * debt - 0.5 * fx + 0.4 * base), 4),
        "currency_crisis": round(_sig(-2.0 + 0.7 * infl - 0.6 * fx + 0.3 * base), 4),
        "imf_programme": round(_sig(-2.2 + 0.5 * debt - 0.5 * fx - 0.4 * ca), 4),
        "banking_crisis": round(_sig(-2.6 + 0.7 * npl + 0.4 * credit), 4),
        "civil_conflict": round(_sig(-2.8 + 0.8 * gov + 0.5 * ev + 1.0 * conflict), 4),
        "coup": round(_sig(-3.2 + 0.7 * gov + 0.4 * ev), 4),
        "sanctions_shock": round(_sig(-2.5 + 2.0 * sanc + 0.4 * gov + 0.3 * conflict), 4),
        "political_instability": round(_sig(-2.0 + 0.6 * gov + 0.5 * ev + 0.3 * base), 4),
    }


def hazard_vector(row: dict, columns: list = HAZARD_FEATURE_COLUMNS) -> np.ndarray:
    return np.asarray([[row.get(c) if row.get(c) is not None else np.nan
                        for c in columns]], dtype=float)


def build_label(outcome_index: dict, code: str, year: int, target: str,
                horizon_months: int) -> Optional[int]:
    """1 if a crisis matching ``target`` occurs within the horizon, else 0.

    Annual resolution: horizon 6/12 → next year; 18 → next two years.
    Returns None for targets with no label coverage (e.g. sanctions_shock)."""
    crisis_types = TARGET_TO_CRISIS_TYPES.get(target)
    if not crisis_types:
        return None
    alias = R.aliased_for_crisis_dataset(code)
    years_ahead = [1, 2] if horizon_months >= 18 else [1]
    target_years = {year + a for a in years_ahead}
    for (ey, etype) in outcome_index.get(alias, []):
        if etype in crisis_types and ey in target_years:
            return 1
    return 0
