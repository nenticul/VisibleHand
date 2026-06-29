"""
Rigorous evaluation harness for the VisibleHand early-warning model.

`backtest.py` gives a single in-sample ROC/AUC. A *publishable* early-warning
study needs more, and this module adds it — all in pure Python/NumPy, no new
dependencies:

  1. **Bootstrap confidence intervals** on AUC and AUPRC, so "AUC = 0.84" comes
     with a band instead of a bare point estimate.
  2. **Baseline comparators** — a random/coin-flip floor, the base-rate (no-skill)
     classifier, and a single-indicator model — so the headline number means
     something relative to a floor a sceptic would accept.
  3. **Temporal (walk-forward / rolling-origin) calibration CV** — fit a logistic
     calibration on years strictly before the test year, predict the test year,
     pool the out-of-sample predictions. This is the look-ahead-free way to
     report calibration quality for an early-warning system.
  4. **Reliability curve + Murphy/Brier decomposition** — split the Brier score
     into reliability (calibration error), resolution (discrimination), and
     uncertainty (irreducible base-rate variance).
  5. **Paired-bootstrap model comparison** — a DeLong-free significance test for
     "is model A's AUC really better than model B's?"

Everything is deterministic given a seed so results are reproducible and the
calibration preprint can cite exact numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from core.calibration.crisis_dataset import ALL_EVENTS, CrisisEvent


# ── core metrics ─────────────────────────────────────────────────────────────
def auc_score(scores: list[float] | np.ndarray, labels: list[int] | np.ndarray) -> float:
    """
    ROC-AUC via the Mann-Whitney U statistic (exact, ties handled by mid-rank).
    Equivalent to the trapezoidal ROC area but cheaper and tie-safe.
    """
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    ranks[order] = np.arange(1, len(s) + 1)
    # mid-rank for ties
    _, inv, counts = np.unique(s, return_inverse=True, return_counts=True)
    cum = np.cumsum(counts)
    start = cum - counts
    mid = (start + cum + 1) / 2.0
    ranks = mid[inv]
    rank_sum_pos = ranks[y == 1].sum()
    return float((rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def average_precision(scores: list[float] | np.ndarray, labels: list[int] | np.ndarray) -> float:
    """Area under the precision-recall curve (average precision, step interpolation)."""
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    n_pos = int(y.sum())
    if n_pos == 0:
        return 0.0
    order = np.argsort(-s, kind="mergesort")
    y_sorted = y[order]
    tp = np.cumsum(y_sorted)
    fp = np.cumsum(1 - y_sorted)
    precision = tp / np.maximum(tp + fp, 1)
    recall = tp / n_pos
    # AP = Σ (R_k - R_{k-1}) · P_k
    ap = 0.0
    prev_r = 0.0
    for p, r in zip(precision, recall):
        ap += (r - prev_r) * p
        prev_r = r
    return float(ap)


def brier_score(probs: list[float] | np.ndarray, labels: list[int] | np.ndarray) -> float:
    """Mean squared error of probability forecasts (probs in [0, 1])."""
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels, dtype=float)
    if len(p) == 0:
        return 1.0
    return float(np.mean((p - y) ** 2))


# ── bootstrap CIs ────────────────────────────────────────────────────────────
def bootstrap_ci(
    scores: list[float] | np.ndarray,
    labels: list[int] | np.ndarray,
    metric_fn=auc_score,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> dict:
    """
    Stratified bootstrap CI for a ranking metric. Resamples positives and
    negatives separately so every replicate keeps both classes.
    """
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    point = metric_fn(s, y)
    if len(pos_idx) == 0 or len(neg_idx) == 0:
        return {"point": round(point, 4), "ci_low": None, "ci_high": None, "n_boot": 0}

    rng = np.random.default_rng(seed)
    reps = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        bp = rng.choice(pos_idx, size=len(pos_idx), replace=True)
        bn = rng.choice(neg_idx, size=len(neg_idx), replace=True)
        idx = np.concatenate([bp, bn])
        reps[i] = metric_fn(s[idx], y[idx])
    lo = float(np.quantile(reps, alpha / 2))
    hi = float(np.quantile(reps, 1 - alpha / 2))
    return {
        "point": round(point, 4),
        "ci_low": round(lo, 4),
        "ci_high": round(hi, 4),
        "se": round(float(reps.std(ddof=1)), 4),
        "n_boot": n_boot,
    }


# ── reliability / Brier decomposition ────────────────────────────────────────
def reliability_curve(
    probs: list[float] | np.ndarray,
    labels: list[int] | np.ndarray,
    n_bins: int = 10,
) -> list[dict]:
    """Binned reliability diagram points: mean predicted vs observed frequency."""
    p = np.clip(np.asarray(probs, dtype=float), 0.0, 1.0)
    y = np.asarray(labels, dtype=int)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out: list[dict] = []
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        mask = (p >= lo) & (p < hi if b < n_bins - 1 else p <= hi)
        n = int(mask.sum())
        if n == 0:
            continue
        out.append({
            "bin_lo": round(float(lo), 3),
            "bin_hi": round(float(hi), 3),
            "mean_predicted": round(float(p[mask].mean()), 4),
            "observed_frequency": round(float(y[mask].mean()), 4),
            "count": n,
        })
    return out


def brier_decomposition(
    probs: list[float] | np.ndarray,
    labels: list[int] | np.ndarray,
    n_bins: int = 10,
) -> dict:
    """
    Murphy (1973) three-component decomposition of the Brier score:
        BS = reliability − resolution + uncertainty
    Lower reliability is better (calibration error); higher resolution is better
    (the forecasts separate event from non-event base rates).
    """
    p = np.clip(np.asarray(probs, dtype=float), 0.0, 1.0)
    y = np.asarray(labels, dtype=float)
    n = len(p)
    if n == 0:
        return {"brier": None, "reliability": None, "resolution": None, "uncertainty": None}
    base = float(y.mean())
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    reliability = 0.0
    resolution = 0.0
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        mask = (p >= lo) & (p < hi if b < n_bins - 1 else p <= hi)
        nk = int(mask.sum())
        if nk == 0:
            continue
        fk = float(p[mask].mean())     # mean forecast in bin
        ok = float(y[mask].mean())     # observed freq in bin
        reliability += nk * (fk - ok) ** 2
        resolution += nk * (ok - base) ** 2
    reliability /= n
    resolution /= n
    uncertainty = base * (1 - base)
    return {
        "brier": round(brier_score(p, y), 4),
        "reliability": round(reliability, 4),
        "resolution": round(resolution, 4),
        "uncertainty": round(uncertainty, 4),
        "skill_score": round(1 - brier_score(p, y) / uncertainty, 4) if uncertainty > 0 else None,
        "base_rate": round(base, 4),
    }


# ── 1-D logistic calibration (for walk-forward) ──────────────────────────────
def _fit_logistic_1d(x: np.ndarray, y: np.ndarray, iters: int = 200, lr: float = 0.5) -> tuple[float, float]:
    """
    Fit P(y=1) = sigmoid(a + b·z) where z is standardised x, by gradient descent.
    Returns (a, b) on the standardised scale plus the (mean, std) used — but we
    bake standardisation into the returned closure via module-level use only.
    """
    mu, sd = float(x.mean()), float(x.std() or 1.0)
    z = (x - mu) / sd
    a, b = 0.0, 0.0
    n = len(x)
    for _ in range(iters):
        pred = 1.0 / (1.0 + np.exp(-(a + b * z)))
        ga = float(np.mean(pred - y))
        gb = float(np.mean((pred - y) * z))
        a -= lr * ga
        b -= lr * gb
    return (a, b, mu, sd)


def temporal_calibration_cv(
    events: list[CrisisEvent],
    score_of,
    min_train_years: int = 3,
    score_scale: float = 100.0,
) -> dict:
    """
    Walk-forward (rolling-origin) calibration. For each test year t (after the
    first `min_train_years` distinct years), fit a logistic calibration on all
    events strictly before t, predict events in year t, and pool the
    out-of-sample (prob, label) pairs. No look-ahead.

    `score_of(event) -> float` returns the model's raw 0..score_scale risk score.
    """
    rows = [(e, float(score_of(e))) for e in events]
    years = sorted({e.year for e, _ in rows})
    if len(years) <= min_train_years:
        return {"available": False, "reason": "insufficient distinct years"}

    oos_probs: list[float] = []
    oos_labels: list[int] = []
    fold_meta: list[dict] = []
    for t in years[min_train_years:]:
        train = [(e, s) for e, s in rows if e.year < t]
        test = [(e, s) for e, s in rows if e.year == t]
        if not test:
            continue
        ytr = np.array([e.label for e, _ in train], dtype=float)
        if len(set(ytr.tolist())) < 2:
            continue  # need both classes to fit
        xtr = np.array([s for _, s in train], dtype=float)
        a, b, mu, sd = _fit_logistic_1d(xtr, ytr)
        for e, s in test:
            z = (s - mu) / sd
            p = 1.0 / (1.0 + math.exp(-(a + b * z)))
            oos_probs.append(p)
            oos_labels.append(e.label)
        fold_meta.append({"test_year": t, "n_train": len(train), "n_test": len(test)})

    if len(oos_labels) < 5 or len(set(oos_labels)) < 2:
        return {"available": False, "reason": "insufficient out-of-sample folds"}

    return {
        "available": True,
        "n_oos": len(oos_labels),
        "n_folds": len(fold_meta),
        "oos_auc": bootstrap_ci(oos_probs, oos_labels, auc_score),
        "oos_ap": bootstrap_ci(oos_probs, oos_labels, average_precision),
        "oos_brier": brier_decomposition(oos_probs, oos_labels),
        "reliability_curve": reliability_curve(oos_probs, oos_labels),
        "folds": fold_meta,
    }


# ── baselines ────────────────────────────────────────────────────────────────
def _heuristic_scores(events: list[CrisisEvent]) -> np.ndarray:
    """Bridge to the existing heuristic so the harness runs without a live DB."""
    from core.calibration.backtest import _heuristic_score
    return np.array([_heuristic_score(e) for e in events], dtype=float)


def baseline_results(events: list[CrisisEvent], seed: int = 0) -> dict:
    """
    Floors a sceptic should accept. AUC of:
      - random            : coin-flip scores (expected 0.5)
      - base_rate         : everyone gets the population crisis rate (AUC 0.5, but
                            anchors the Brier 'no-skill' reference)
      - crisis_type_prior : score = historical positive-rate of the event's type
    """
    y = np.array([e.label for e in events], dtype=int)
    rng = np.random.default_rng(seed)

    rand = rng.random(len(events))

    base = float(y.mean())
    base_scores = np.full(len(events), base)

    # crisis-type prior: P(label=1 | crisis_type) computed in-sample
    type_rate: dict[str, float] = {}
    for ct in {e.crisis_type for e in events}:
        sub = [e.label for e in events if e.crisis_type == ct]
        type_rate[ct] = sum(sub) / len(sub)
    prior = np.array([type_rate[e.crisis_type] for e in events], dtype=float)

    return {
        "random": bootstrap_ci(rand, y, auc_score, seed=seed),
        "base_rate": {"point": 0.5, "note": "no-skill reference; Brier floor",
                      "brier": round(brier_score(base_scores, y), 4)},
        "crisis_type_prior": bootstrap_ci(prior, y, auc_score, seed=seed),
    }


# ── model comparison ─────────────────────────────────────────────────────────
def paired_bootstrap_compare(
    scores_a: list[float], scores_b: list[float], labels: list[int],
    metric_fn=auc_score, n_boot: int = 2000, seed: int = 0,
) -> dict:
    """
    Paired bootstrap test of metric(A) − metric(B) on the same labels.
    Returns the observed difference, its CI, and a two-sided bootstrap p-value.
    """
    a = np.asarray(scores_a, dtype=float)
    b = np.asarray(scores_b, dtype=float)
    y = np.asarray(labels, dtype=int)
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    obs = metric_fn(a, y) - metric_fn(b, y)
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        bp = rng.choice(pos_idx, size=len(pos_idx), replace=True)
        bn = rng.choice(neg_idx, size=len(neg_idx), replace=True)
        idx = np.concatenate([bp, bn])
        diffs[i] = metric_fn(a[idx], y[idx]) - metric_fn(b[idx], y[idx])
    p_two = 2.0 * min((diffs <= 0).mean(), (diffs >= 0).mean())
    return {
        "delta": round(float(obs), 4),
        "ci_low": round(float(np.quantile(diffs, 0.025)), 4),
        "ci_high": round(float(np.quantile(diffs, 0.975)), 4),
        "p_value": round(float(min(p_two, 1.0)), 4),
        "favours": "A" if obs > 0 else "B" if obs < 0 else "tie",
    }


# ── top-level orchestration ──────────────────────────────────────────────────
@dataclass
class EvaluationReport:
    n_events: int
    n_crises: int
    base_rate: float
    auc: dict
    average_precision: dict
    brier_decomposition: dict
    reliability_curve: list[dict]
    temporal_cv: dict
    baselines: dict
    by_crisis_type: dict
    note: str = ""
    score_source: str = "heuristic"
    extras: dict = field(default_factory=dict)


def run_evaluation(
    db_scores: dict[tuple[str, int], float] | None = None,
    n_boot: int = 2000,
    seed: int = 0,
) -> EvaluationReport:
    """
    Full evaluation pass over the crisis dataset. Uses live DB composite scores
    where available (keyed by (country, year)), otherwise the documented
    heuristic bridge. The reported metrics are honest about which path was used.
    """
    events = ALL_EVENTS
    if db_scores:
        scores = np.array([
            db_scores.get((e.country, e.year), _heuristic_score_single(e)) for e in events
        ], dtype=float)
        n_live = sum(1 for e in events if (e.country, e.year) in db_scores)
        source = f"live_db ({n_live}/{len(events)} from DB, remainder heuristic)"
    else:
        scores = _heuristic_scores(events)
        source = "heuristic (no live DB scores supplied)"

    labels = [e.label for e in events]
    probs = (scores / 100.0).tolist()

    def score_of(ev: CrisisEvent) -> float:
        if db_scores and (ev.country, ev.year) in db_scores:
            return db_scores[(ev.country, ev.year)]
        return _heuristic_score_single(ev)

    by_type: dict[str, dict] = {}
    for ct in sorted({e.crisis_type for e in events if e.crisis_type != "none"}):
        # one-vs-rest AUC: does the score separate this crisis type from negatives?
        idx = [i for i, e in enumerate(events) if e.crisis_type == ct or e.label == 0]
        sub_scores = scores[idx]
        sub_labels = [labels[i] for i in idx]
        if len(set(sub_labels)) < 2:
            continue
        by_type[ct] = {"auc": round(auc_score(sub_scores, sub_labels), 3),
                       "n": int(sum(1 for i in idx if events[i].crisis_type == ct))}

    return EvaluationReport(
        n_events=len(events),
        n_crises=sum(labels),
        base_rate=round(sum(labels) / len(labels), 4),
        auc=bootstrap_ci(scores, labels, auc_score, n_boot=n_boot, seed=seed),
        average_precision=bootstrap_ci(scores, labels, average_precision, n_boot=n_boot, seed=seed),
        brier_decomposition=brier_decomposition(probs, labels),
        reliability_curve=reliability_curve(probs, labels),
        temporal_cv=temporal_calibration_cv(events, score_of),
        baselines=baseline_results(events, seed=seed),
        by_crisis_type=by_type,
        score_source=source,
        note=(
            "AUC/AP carry stratified-bootstrap 95% CIs. temporal_cv reports "
            "look-ahead-free out-of-sample calibration (logistic fit on prior "
            "years only). Brier is decomposed into reliability/resolution/"
            "uncertainty (Murphy 1973). Baselines give the no-skill floor."
        ),
    )


def _heuristic_score_single(e: CrisisEvent) -> float:
    from core.calibration.backtest import _heuristic_score
    return _heuristic_score(e)
