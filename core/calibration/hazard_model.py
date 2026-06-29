"""
Discrete-time hazard model for crisis early-warning (Shumway 2001 style).

A discrete-time hazard model is a pooled logistic regression over (subject, time)
observations: P(crisis within the horizon | features now). Here each observation
is a (country, year) point from the C7 panel, the features are the four
point-in-time sub-scores, and the label is the crisis flag 12 months out.

Two design choices keep it honest and robust on a small, imbalanced panel:

  1. **Monotonic (non-negativity) constraints.** Every sub-score is risk-oriented
     (higher = worse), so every coefficient is constrained ≥ 0 via projected
     gradient descent. The model can never learn "more governance risk lowers
     crisis probability" — a sign error that wrecks credibility — and it stays
     sensible when data is thin.
  2. **L2 regularisation.** Shrinks coefficients so 30-40 events don't overfit
     four features.

This is glass-box: the fitted coefficients are reported directly (no SHAP). It is
trained on whatever the panel covers and is explicit about `n_train` and class
balance. It does NOT replace the linear composite — it's an additional,
opt-in early-warning probability so the published calibration is preserved.
"""

from __future__ import annotations

import numpy as np

from core.calibration.panel import materialize_crisis_panel
from core.calibration.evaluation import auc_score, brier_decomposition, bootstrap_ci

FEATURES = ["economic", "political", "nlp", "governance"]
_NEUTRAL = 50.0  # impute a missing sub-score as neutral risk


class DiscreteTimeHazard:
    def __init__(self, l2: float = 1.0, monotone: bool = True,
                 iters: int = 800, lr: float = 0.2):
        self.l2 = l2
        self.monotone = monotone
        self.iters = iters
        self.lr = lr
        self.mu = None
        self.sd = None
        self.w = None
        self.b = 0.0
        self.features: list[str] = []

    def fit(self, X, y, features: list[str] | None = None) -> "DiscreteTimeHazard":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.features = features or [f"x{i}" for i in range(X.shape[1])]
        self.mu = X.mean(axis=0)
        self.sd = X.std(axis=0)
        self.sd[self.sd == 0] = 1.0
        Z = (X - self.mu) / self.sd
        n, d = Z.shape
        w = np.zeros(d)
        b = 0.0
        for _ in range(self.iters):
            p = 1.0 / (1.0 + np.exp(-(Z @ w + b)))
            gw = Z.T @ (p - y) / n + self.l2 * w / n
            gb = float(np.mean(p - y))
            w -= self.lr * gw
            b -= self.lr * gb
            if self.monotone:
                w = np.maximum(w, 0.0)   # projected gradient: coefficients ≥ 0
        self.w = w
        self.b = b
        return self

    def predict_proba(self, X) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        Z = (X - self.mu) / self.sd
        return 1.0 / (1.0 + np.exp(-(Z @ self.w + self.b)))

    def coefficients(self) -> dict:
        """Standardised coefficients (per-1-SD effect on the log-odds)."""
        return {f: round(float(c), 4) for f, c in zip(self.features, self.w)}

    def summary(self) -> dict:
        return {
            "intercept": round(float(self.b), 4),
            "coefficients_std": self.coefficients(),
            "l2": self.l2,
            "monotone": self.monotone,
        }


def _matrix_from_events(events: list[dict]):
    """Build (X, y) from panel live-events, imputing missing sub-scores as neutral."""
    X, y = [], []
    for e in events:
        if e.get("label") is None:
            continue
        row = [float(e[f]) if e.get(f) is not None else _NEUTRAL for f in FEATURES]
        X.append(row)
        y.append(int(e["label"]))
    return np.array(X, dtype=float), np.array(y, dtype=int)


def train_from_panel(db, l2: float = 1.0, monotone: bool = True,
                     n_boot: int = 1000) -> dict:
    """
    Train the discrete-time hazard model on the C7 point-in-time panel.

    Returns a JSON-friendly dict with the fitted (glass-box) coefficients, the
    in-sample discrimination/calibration, training coverage, and an honest note
    about sample size. Status is 'insufficient' when the panel cannot supply
    enough labelled, two-class observations to fit responsibly.
    """
    panel = materialize_crisis_panel(db)
    events = panel["coverage"]["live_events"]
    X, y = _matrix_from_events(events)

    n = len(y)
    n_pos = int(y.sum()) if n else 0
    if n < 12 or n_pos == 0 or n_pos == n:
        return {
            "status": "insufficient",
            "n_train": n,
            "n_positive": n_pos,
            "coverage": {k: panel["coverage"][k] for k in
                         ("n_events", "live", "insufficient", "coverage_rate")},
            "note": ("Not enough live-scored, two-class panel observations to fit a "
                     "hazard model yet — backfill historical indicator depth for the "
                     "panel countries (see /calibration/panel)."),
        }

    model = DiscreteTimeHazard(l2=l2, monotone=monotone).fit(X, y, features=FEATURES)
    proba = model.predict_proba(X)

    auc_ci = bootstrap_ci(proba.tolist(), y.tolist(), auc_score, n_boot=n_boot)
    brier = brier_decomposition(proba.tolist(), y.tolist())

    # rank features by standardised effect
    coefs = model.coefficients()
    ranked = sorted(coefs.items(), key=lambda kv: -kv[1])

    return {
        "status": "available",
        "model": "discrete-time-logistic-hazard",
        "horizon_months": 12,
        "n_train": n,
        "n_positive": n_pos,
        "class_balance": round(n_pos / n, 3),
        "summary": model.summary(),
        "feature_ranking": [{"feature": f, "coef_std": c} for f, c in ranked],
        "in_sample_auc": auc_ci,
        "in_sample_brier": brier,
        "coverage": {k: panel["coverage"][k] for k in
                     ("n_events", "live", "insufficient", "coverage_rate")},
        "note": ("Monotone (coefficients ≥ 0) L2-regularised discrete-time hazard at "
                 "the dataset's native 12-month horizon. In-sample metrics shown; "
                 "with a small panel they overstate out-of-sample skill — see the "
                 "walk-forward CV on /calibration/evaluation. Default composite is "
                 "unchanged; this is an opt-in early-warning probability."),
    }
