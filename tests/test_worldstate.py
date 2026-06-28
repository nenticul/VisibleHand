"""Unit tests for the VH-WSM world-state layer.

These run under the SQLite-stubbed test environment (see conftest) because they
exercise the pure-numpy logic directly, without touching the database.
"""

import numpy as np
import pytest

from core.worldstate import registry as R
from core.worldstate import hazards as H
from core.worldstate import graph
from core.worldstate.embeddings import StandardizedPCAEmbedder, _l2_normalize
from core.worldstate.uncertainty import ConformalCalibrator, abstain_decision
from core.worldstate.analogues import AnalogueSearchService
from core.worldstate.features import _robust_z, _z_to_risk


# ── metrics ──────────────────────────────────────────────────────────────────
def test_roc_auc_perfect_separation():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.8, 0.9])
    assert H.roc_auc(y, p) == pytest.approx(1.0)


def test_roc_auc_single_class_returns_none():
    assert H.roc_auc(np.array([1, 1, 1]), np.array([0.2, 0.5, 0.9])) is None


def test_brier_and_logloss_finite():
    y = np.array([0, 1, 0, 1]); p = np.array([0.2, 0.7, 0.3, 0.6])
    assert 0 <= H.brier_score(y, p) <= 1
    assert H.log_loss(y, p) > 0


def test_expected_calibration_error_perfect():
    # predictions equal observed frequencies in each bin -> low ECE
    y = np.array([0, 0, 1, 1, 1]); p = np.array([0.0, 0.0, 1.0, 1.0, 1.0])
    assert H.expected_calibration_error(y, p) == pytest.approx(0.0, abs=1e-9)


# ── logistic hazard model ────────────────────────────────────────────────────
def test_logistic_probabilities_in_range_and_ordered():
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal(-1, 0.5, (40, 3)), rng.normal(1, 0.5, (40, 3))])
    y = np.array([0] * 40 + [1] * 40)
    m = H.LogisticHazardModel(iters=500)
    m.fit(X, y)
    p = m.predict_proba(X)
    assert p.min() >= 0.0 and p.max() <= 1.0
    assert p[y == 1].mean() > p[y == 0].mean()


def test_heuristic_hazards_all_targets_in_unit_interval():
    row = {"inflation_z": 2.0, "debt_to_gdp_z": 1.5, "fx_reserves_z": -1.0,
           "bank_npl_z": 1.0, "governance_structural_score": 70.0,
           "event_count_90d": 5, "visiblehand_score": 72.0}
    hz = H.heuristic_hazards(row, code="AR")
    assert set(hz) == set(R.HAZARD_TARGETS)
    assert all(0.0 <= v <= 1.0 for v in hz.values())


def test_build_label_horizon_and_none_for_uncovered_target():
    idx = {"AR": [(2018, "currency")]}
    assert H.build_label(idx, "AR", 2017, "currency_crisis", 12) == 1
    assert H.build_label(idx, "AR", 2016, "currency_crisis", 12) == 0
    assert H.build_label(idx, "AR", 2016, "currency_crisis", 18) == 1   # +2 years
    assert H.build_label(idx, "AR", 2017, "sanctions_shock", 12) is None


# ── embeddings ───────────────────────────────────────────────────────────────
def test_pca_deterministic_and_l2_normalised():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(50, 6))
    e1 = StandardizedPCAEmbedder(n_components=4); v1 = e1.fit_transform(X)
    e2 = StandardizedPCAEmbedder(n_components=4); v2 = e2.fit_transform(X)
    assert np.allclose(v1, v2)                       # deterministic
    norms = np.linalg.norm(v1, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-6)        # unit vectors


def test_pca_handles_missing_values():
    X = np.array([[1.0, np.nan, 3.0], [2.0, 2.0, np.nan], [3.0, 4.0, 5.0], [4.0, 5.0, 6.0]])
    e = StandardizedPCAEmbedder(n_components=2)
    v = e.fit_transform(X)
    assert np.isfinite(v).all()


# ── analogue leakage rules ───────────────────────────────────────────────────
def _v(x, y):
    return _l2_normalize(np.array([[x, y]], dtype=float))[0]


def test_analogue_search_excludes_future_and_recent_same_country():
    svc = AnalogueSearchService.__new__(AnalogueSearchService)
    svc.db = None
    svc.embedding_version = R.EMBEDDING_VERSION
    svc._outcomes = {}
    svc._cache = [
        ("AR", "2020-12-31", _v(1.0, 0.1)),    # the query state
        ("AR", "2021-12-31", _v(1.0, 0.1)),    # FUTURE -> must be excluded
        ("AR", "2020-10-01", _v(1.0, 0.1)),    # same country, 91d gap -> excluded
        ("US", "2019-06-01", _v(0.9, 0.2)),    # valid historical analogue
        ("BR", "2018-06-01", _v(0.2, 1.0)),    # valid but dissimilar
    ]
    res = svc.find_analogues("AR", "2020-12-31", k=10, min_date_gap_days=180)
    dates = {(a["country"], a["date"]) for a in res}
    assert ("AR", "2021-12-31") not in dates          # no future
    assert ("AR", "2020-10-01") not in dates          # no recent same-country
    assert ("US", "2019-06-01") in dates
    # similarity ordering
    sims = [a["similarity"] for a in res]
    assert sims == sorted(sims, reverse=True)


def test_analogue_search_empty_when_query_missing():
    svc = AnalogueSearchService.__new__(AnalogueSearchService)
    svc.db = None; svc.embedding_version = R.EMBEDDING_VERSION
    svc._outcomes = {}; svc._cache = [("US", "2019-06-01", _v(1.0, 0.0))]
    assert svc.find_analogues("AR", "2020-12-31") == []


# ── spillover ────────────────────────────────────────────────────────────────
def test_spillover_features_shape_and_values():
    score_map = {"US": 40.0, "CA": 30.0, "MX": 55.0, "CN": 60.0}
    sp = graph.spillover_features(score_map, "MX")
    # MX region is N. America -> peers US, CA
    assert sp["regional_mean_score"] == pytest.approx(35.0)
    assert sp["regional_max_score"] == pytest.approx(40.0)
    assert sp["neighbour_mean_score"] == pytest.approx(40.0)   # only US present
    assert sp["trade_weighted_partner_score"] is not None
    assert isinstance(sp["conflict_neighbour_flag"], bool)


# ── conformal uncertainty ────────────────────────────────────────────────────
def test_conformal_monotonic_and_covers():
    rng = np.random.default_rng(2)
    resid = rng.normal(50, 8, 500)
    truth = resid; pred = np.full_like(resid, 50.0)
    cal = ConformalCalibrator().fit(truth, pred)
    hw_tight = cal.half_width(alpha=0.2)
    hw_wide = cal.half_width(alpha=0.05)
    assert hw_wide >= hw_tight                       # smaller alpha -> wider
    rep = cal.coverage_report(alpha=0.1)
    assert rep["empirical_coverage"] >= 0.88         # ~90% coverage


def test_conformal_interval_clipped_and_centered():
    cal = ConformalCalibrator().fit(np.array([0, 1, 2, 3, 4.0]), np.zeros(5))
    lo, hi = cal.interval(98.0, alpha=0.1, lo=0.0, hi=100.0)
    assert hi <= 100.0 and lo >= 0.0


def test_abstain_on_low_quality():
    abstain, reasons = abstain_decision(
        {"data_quality_score": 0.3, "missing_feature_count": 6}, (40.0, 90.0))
    assert abstain and len(reasons) >= 1


def test_no_abstain_on_good_row():
    abstain, reasons = abstain_decision(
        {"data_quality_score": 0.9, "missing_feature_count": 0}, (62.0, 80.0))
    assert not abstain and reasons == []


# ── feature helpers ──────────────────────────────────────────────────────────
def test_robust_z_detects_outlier():
    z = _robust_z([1.0, 1.1, 0.9, 1.0, 5.0], 5.0)
    assert z is not None and z > 2.0


def test_robust_z_insufficient_history():
    assert _robust_z([1.0, 2.0], 2.0) is None


def test_z_to_risk_direction():
    assert _z_to_risk(2.0, +1) > 50.0       # high value, +risk -> elevated
    assert _z_to_risk(2.0, -1) < 50.0       # high value, -risk -> reduced
    assert _z_to_risk(None, +1) is None
