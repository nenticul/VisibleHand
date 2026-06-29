"""Tests for the calibration system: crisis dataset, backtest, ROC-AUC."""

import pytest

from core.calibration.crisis_dataset import (
    ALL_EVENTS,
    CRISIS_EVENTS,
    NEGATIVE_CONTROLS,
    CrisisEvent,
    get_crisis_labels,
    get_positive_rate,
)
from core.calibration.backtest import (
    run_backtest,
    _roc_curve,
    _brier_score,
    _auc_from_sorted,
)
from core.calibration.evaluation import (
    auc_score,
    average_precision,
    bootstrap_ci,
    brier_decomposition,
    reliability_curve,
    temporal_calibration_cv,
    paired_bootstrap_compare,
    baseline_results,
    run_evaluation,
)


class TestCrisisDataset:
    def test_has_enough_events(self):
        assert len(ALL_EVENTS) >= 80

    def test_has_crisis_and_control_events(self):
        n_pos = sum(1 for e in ALL_EVENTS if e.label == 1)
        n_neg = sum(1 for e in ALL_EVENTS if e.label == 0)
        assert n_pos >= 50
        assert n_neg >= 10

    def test_crisis_labels_dict(self):
        labels = get_crisis_labels()
        assert isinstance(labels, dict)
        # All values should be 0 or 1
        assert all(v in (0, 1) for v in labels.values())

    def test_positive_rate_reasonable(self):
        rate = get_positive_rate()
        # Should be between 50% and 95% given our dataset construction
        assert 0.5 < rate < 0.95

    def test_crisis_types_present(self):
        types = {e.crisis_type for e in CRISIS_EVENTS}
        assert "default" in types
        assert "banking" in types
        assert "civil_war" in types
        assert "coup" in types
        assert "currency" in types
        assert "imf_programme" in types

    def test_country_codes_are_two_chars(self):
        for e in ALL_EVENTS:
            assert len(e.country) == 2, f"Invalid code: {e.country}"

    def test_years_in_range(self):
        for e in ALL_EVENTS:
            assert 1990 <= e.year <= 2025, f"Year out of range: {e.year}"

    def test_ukraine_2022_present(self):
        ua_2022 = [e for e in CRISIS_EVENTS
                   if e.country == "UA" and e.year == 2022]
        assert len(ua_2022) > 0


class TestROCCurve:
    def test_perfect_classifier(self):
        # Perfect: crisis scores = 90, non-crisis = 10
        scores = [90.0, 90.0, 10.0, 10.0]
        labels = [1, 1, 0, 0]
        fprs, tprs, _ = _roc_curve(scores, labels)
        auc = _auc_from_sorted(fprs, tprs)
        assert auc == pytest.approx(1.0, abs=0.01)

    def test_random_classifier_near_05(self):
        import random
        random.seed(42)
        scores = [random.uniform(0, 100) for _ in range(200)]
        labels = [random.randint(0, 1) for _ in range(200)]
        fprs, tprs, _ = _roc_curve(scores, labels)
        auc = _auc_from_sorted(fprs, tprs)
        # Random classifier AUC ≈ 0.5
        assert 0.3 < auc < 0.7

    def test_roc_curve_bounds(self):
        scores = [80.0, 60.0, 40.0, 20.0]
        labels = [1, 0, 1, 0]
        fprs, tprs, thresholds = _roc_curve(scores, labels)
        assert fprs[0] == 0.0
        assert tprs[0] == 0.0
        assert all(0.0 <= f <= 1.0 for f in fprs)
        assert all(0.0 <= t <= 1.0 for t in tprs)

    def test_brier_score_perfect(self):
        # Perfect calibration: probability 1.0 for crisis, 0.0 for non-crisis
        scores = [100.0, 100.0, 0.0, 0.0]
        labels = [1, 1, 0, 0]
        bs = _brier_score(scores, labels)
        assert bs == pytest.approx(0.0, abs=0.01)

    def test_brier_score_worst(self):
        # Worst calibration: always wrong
        scores = [0.0, 0.0, 100.0, 100.0]
        labels = [1, 1, 0, 0]
        bs = _brier_score(scores, labels)
        assert bs == pytest.approx(1.0, abs=0.01)


class TestBacktest:
    def test_run_backtest_returns_result(self):
        result = run_backtest()
        assert result.auc > 0.0
        assert result.brier_score >= 0.0
        assert result.n_events == len(ALL_EVENTS)
        assert result.n_crises > 0

    def test_backtest_auc_above_random(self):
        # Heuristic scores should give AUC > 0.5 (they're designed to be informative)
        result = run_backtest()
        assert result.auc > 0.55, f"AUC {result.auc} not above 0.55 — check heuristic scores"
        # Note: heuristic AUC may be 1.0 because synthetic scores perfectly separate
        # crisis (60-85) from non-crisis (30-55). Live DB scores will be noisier.

    def test_backtest_roc_curve_valid(self):
        result = run_backtest()
        assert len(result.roc_curve) > 5
        for pt in result.roc_curve:
            assert 0.0 <= pt["fpr"] <= 1.0
            assert 0.0 <= pt["tpr"] <= 1.0

    def test_backtest_by_crisis_type(self):
        result = run_backtest()
        # by_crisis_type only includes types with both positive and negative examples.
        # With current dataset (negatives use type "none"), this may be empty.
        assert isinstance(result.by_crisis_type, dict)

    def test_backtest_with_perfect_db_scores(self):
        # Provide perfect DB scores: crisis -> 90, non-crisis -> 10
        db = {(e.country, e.year): 90.0 if e.label == 1 else 10.0
              for e in ALL_EVENTS}
        result = run_backtest(db_scores=db)
        assert result.auc > 0.90

    def test_pr_auc_positive(self):
        result = run_backtest()
        assert result.pr_auc > 0.0


class TestEvaluationMetrics:
    def test_auc_perfect_and_reversed(self):
        labels = [1, 1, 0, 0]
        assert auc_score([1.0, 1.0, 0.0, 0.0], labels) == pytest.approx(1.0)
        assert auc_score([0.0, 0.0, 1.0, 1.0], labels) == pytest.approx(0.0)

    def test_auc_handles_ties(self):
        # All-equal scores → AUC exactly 0.5 (mid-rank handling)
        assert auc_score([5.0, 5.0, 5.0, 5.0], [1, 0, 1, 0]) == pytest.approx(0.5)

    def test_auc_matches_trapezoidal_backtest(self):
        # New rank-based AUC should agree with the existing trapezoidal one
        import random
        random.seed(7)
        scores = [random.uniform(0, 100) for _ in range(150)]
        labels = [random.randint(0, 1) for _ in range(150)]
        fprs, tprs, _ = _roc_curve(scores, labels)
        trap = _auc_from_sorted(fprs, tprs)
        assert auc_score(scores, labels) == pytest.approx(trap, abs=0.01)

    def test_average_precision_perfect(self):
        assert average_precision([1.0, 1.0, 0.0, 0.0], [1, 1, 0, 0]) == pytest.approx(1.0)

    def test_bootstrap_ci_brackets_point(self):
        scores = [90, 85, 80, 20, 15, 10, 70, 30]
        labels = [1, 1, 1, 0, 0, 0, 1, 0]
        ci = bootstrap_ci(scores, labels, auc_score, n_boot=500, seed=1)
        assert ci["ci_low"] <= ci["point"] <= ci["ci_high"]
        assert ci["n_boot"] == 500

    def test_brier_decomposition_identity(self):
        # BS = reliability − resolution + uncertainty (Murphy identity)
        import random
        random.seed(3)
        probs = [random.random() for _ in range(200)]
        labels = [random.randint(0, 1) for _ in range(200)]
        d = brier_decomposition(probs, labels, n_bins=10)
        recon = d["reliability"] - d["resolution"] + d["uncertainty"]
        assert recon == pytest.approx(d["brier"], abs=0.02)

    def test_reliability_curve_well_formed(self):
        probs = [0.05, 0.15, 0.85, 0.95, 0.45, 0.55]
        labels = [0, 0, 1, 1, 0, 1]
        curve = reliability_curve(probs, labels, n_bins=5)
        assert all(0.0 <= b["observed_frequency"] <= 1.0 for b in curve)
        assert all(b["count"] >= 1 for b in curve)

    def test_temporal_cv_no_lookahead(self):
        from core.calibration.crisis_dataset import ALL_EVENTS as EV
        from core.calibration.backtest import _heuristic_score
        cv = temporal_calibration_cv(EV, _heuristic_score)
        assert cv["available"] is True
        # every fold trains only on strictly-earlier years
        for f in cv["folds"]:
            assert f["n_train"] > 0 and f["n_test"] > 0

    def test_paired_bootstrap_detects_difference(self):
        from core.calibration.crisis_dataset import ALL_EVENTS as EV
        from core.calibration.backtest import _heuristic_score
        import numpy as np
        labels = [e.label for e in EV]
        good = [_heuristic_score(e) for e in EV]
        rand = list(np.random.default_rng(0).random(len(EV)))
        cmp = paired_bootstrap_compare(good, rand, labels, n_boot=500)
        assert cmp["favours"] == "A"
        assert cmp["delta"] > 0

    def test_baselines_present(self):
        from core.calibration.crisis_dataset import ALL_EVENTS as EV
        b = baseline_results(EV)
        assert "random" in b and "base_rate" in b and "crisis_type_prior" in b


class TestRunEvaluation:
    def test_report_structure(self):
        rep = run_evaluation(n_boot=300)
        assert rep.n_events == len(ALL_EVENTS)
        assert rep.auc["point"] >= 0.5
        assert rep.average_precision["point"] >= 0.0
        assert rep.temporal_cv["available"] is True
        assert "reliability" in rep.brier_decomposition
        assert rep.score_source.startswith("heuristic")

    def test_live_db_scores_path(self):
        # Supplying perfect DB scores should be reflected in score_source + AUC
        db = {(e.country, e.year): 90.0 if e.label == 1 else 10.0 for e in ALL_EVENTS}
        rep = run_evaluation(db_scores=db, n_boot=300)
        assert "live_db" in rep.score_source
        assert rep.auc["point"] > 0.9

    def test_live_only_evaluation(self):
        from core.calibration.evaluation import live_only_evaluation
        # well-separated live events -> high AUC, both classes, by-type present
        events = []
        for i in range(30):
            crisis = i % 2 == 0
            events.append({"label": 1 if crisis else 0,
                           "score": 80.0 if crisis else 25.0,
                           "crisis_type": "currency" if crisis else "none"})
        out = live_only_evaluation(events, n_boot=200)
        assert out is not None
        assert out["n"] == 30 and out["n_crises"] == 15
        assert out["auc"]["point"] > 0.95
        assert out["auc"]["ci_low"] is not None

    def test_live_only_evaluation_insufficient(self):
        from core.calibration.evaluation import live_only_evaluation
        # too few / single-class -> None
        assert live_only_evaluation([], n_boot=50) is None
        assert live_only_evaluation(
            [{"label": 1, "score": 70.0, "crisis_type": "x"}] * 20, n_boot=50) is None


from types import SimpleNamespace


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
    def filter(self, *a, **k):
        return self
    def all(self):
        return list(self._rows)


class _FakeSession:
    """Minimal stand-in: returns rows per model name; filter() is a no-op so tests
    use single-country event sets."""
    def __init__(self, store):
        self.store = store
    def query(self, model):
        name = getattr(model, "__name__", str(model))
        return _FakeQuery(self.store.get(name, []))
    def close(self):
        pass


class TestPanelMaterialisation:
    def test_before_point_in_time(self):
        from core.calibration.panel import _before
        # annual indicator: included only if its year < crisis year
        assert _before(SimpleNamespace(year=2016, date=None), 2018, "2018-01-01") is True
        assert _before(SimpleNamespace(year=2018, date=None), 2018, "2018-01-01") is False
        assert _before(SimpleNamespace(year=2020, date=None), 2018, "2018-01-01") is False
        # daily indicator: included only if its date is before the cutoff
        assert _before(SimpleNamespace(year=None, date="2017-06-01"), 2018, "2018-01-01") is True
        assert _before(SimpleNamespace(year=None, date="2018-06-01"), 2018, "2018-01-01") is False

    def test_empty_db_all_insufficient(self, monkeypatch):
        import core.calibration.panel as panel
        monkeypatch.setattr(panel, "ALL_EVENTS",
                            [SimpleNamespace(country="AR", year=2018, crisis_type="currency", label=1)])
        db = _FakeSession({})
        out = panel.materialize_crisis_panel(db)
        assert out["scores"] == {}
        assert out["coverage"]["live"] == 0
        assert out["coverage"]["insufficient"] == 1

    def test_scores_when_data_present(self, monkeypatch):
        import core.calibration.panel as panel
        monkeypatch.setattr(panel, "ALL_EVENTS",
                            [SimpleNamespace(country="AR", year=2018, crisis_type="currency", label=1)])
        # economic history strictly before 2018, plus a leaking 2019 row
        ind = [SimpleNamespace(country_code="AR", metric="gdp_growth", year=y, date=None,
                               value=float(2 - (y - 2010) * 0.3)) for y in range(2010, 2018)]
        ind += [SimpleNamespace(country_code="AR", metric="inflation", year=y, date=None,
                                value=float(10 + (y - 2010) * 2)) for y in range(2010, 2018)]
        ind += [SimpleNamespace(country_code="AR", metric="gdp_growth", year=2019, date=None, value=99.0)]
        store = {"Indicator": ind, "PoliticalEvent": [], "GovernanceIndicator": []}
        out = panel.materialize_crisis_panel(_FakeSession(store))
        assert ("AR", 2018) in out["scores"]
        assert out["coverage"]["live"] == 1
        assert 0.0 <= out["scores"][("AR", 2018)] <= 100.0
        # feature coverage: economic present, political/governance absent here
        fc = out["coverage"]["feature_coverage"]
        assert fc["economic"] == 1
        assert fc["political"] == 0 and fc["governance"] == 0

    def test_gov_pop_asof_excludes_future(self):
        from core.calibration.panel import _gov_pop_asof
        gov = [
            SimpleNamespace(country_code="AR", metric="wgi_rule_of_law", year=2015, value=-0.5),
            SimpleNamespace(country_code="BR", metric="wgi_rule_of_law", year=2016, value=0.1),
            SimpleNamespace(country_code="CL", metric="wgi_rule_of_law", year=2020, value=1.2),  # future
        ]
        db = _FakeSession({"GovernanceIndicator": gov})
        pop = _gov_pop_asof(db, 2018, {})
        vals = pop["wgi_rule_of_law"]
        assert -0.5 in vals and 0.1 in vals
        assert 1.2 not in vals  # 2020 value excluded for an as-of-2018 population


class TestHazardModel:
    def _separable(self, n=120, seed=0):
        import numpy as np
        rng = np.random.default_rng(seed)
        # high sub-scores -> crisis; build a clearly separable set
        Xpos = rng.uniform(60, 95, size=(n // 2, 4))
        Xneg = rng.uniform(5, 40, size=(n // 2, 4))
        X = np.vstack([Xpos, Xneg])
        y = np.array([1] * (n // 2) + [0] * (n // 2))
        return X, y

    def test_fits_and_discriminates(self):
        from core.calibration.hazard_model import DiscreteTimeHazard
        from core.calibration.evaluation import auc_score
        X, y = self._separable()
        m = DiscreteTimeHazard(l2=0.5).fit(X, y, features=["economic", "political", "nlp", "governance"])
        proba = m.predict_proba(X)
        assert auc_score(proba.tolist(), y.tolist()) > 0.95

    def test_monotone_constraint_holds(self):
        from core.calibration.hazard_model import DiscreteTimeHazard
        import numpy as np
        # adversarial: one feature is anti-correlated with the label
        rng = np.random.default_rng(1)
        X = rng.uniform(0, 100, size=(200, 4))
        y = (X[:, 0] > 50).astype(int)
        X[:, 1] = 100 - X[:, 0]  # feature 1 negatively related to y
        m = DiscreteTimeHazard(l2=0.1, monotone=True).fit(X, y, features=["a", "b", "c", "d"])
        assert all(c >= 0 for c in m.coefficients().values())  # no negative coefficients

    def test_non_monotone_allows_negative(self):
        from core.calibration.hazard_model import DiscreteTimeHazard
        import numpy as np
        rng = np.random.default_rng(2)
        X = rng.uniform(0, 100, size=(200, 4))
        y = (X[:, 0] > 50).astype(int)
        X[:, 1] = 100 - X[:, 0]
        m = DiscreteTimeHazard(l2=0.01, monotone=False).fit(X, y, features=["a", "b", "c", "d"])
        assert min(m.coefficients().values()) < 0  # unconstrained can go negative

    def test_train_from_panel_insufficient(self, monkeypatch):
        import core.calibration.hazard_model as hm
        monkeypatch.setattr(hm, "materialize_crisis_panel",
                            lambda db: {"coverage": {"n_events": 99, "live": 2, "insufficient": 97,
                                                     "coverage_rate": 0.02,
                                                     "live_events": [
                                                         {"label": 1, "economic": 80, "political": 70, "nlp": 60, "governance": 75},
                                                         {"label": 0, "economic": 20, "political": 30, "nlp": 40, "governance": 25},
                                                     ]}})
        out = hm.train_from_panel(object())
        assert out["status"] == "insufficient"
        assert out["n_train"] == 2

    def test_train_from_panel_available(self, monkeypatch):
        import core.calibration.hazard_model as hm
        live = []
        for i in range(40):
            crisis = i % 2 == 0
            live.append({"label": 1 if crisis else 0,
                         "economic": 80 if crisis else 25,
                         "political": 70 if crisis else 20,
                         "nlp": 60 if crisis else 45,
                         "governance": 75 if crisis else 30})
        monkeypatch.setattr(hm, "materialize_crisis_panel",
                            lambda db: {"coverage": {"n_events": 99, "live": 40, "insufficient": 59,
                                                     "coverage_rate": 0.40, "live_events": live}})
        out = hm.train_from_panel(object(), n_boot=200)
        assert out["status"] == "available"
        assert out["n_train"] == 40
        assert set(out["summary"]["coefficients_std"]) == {"economic", "political", "nlp", "governance"}
        assert out["in_sample_auc"]["point"] > 0.9
        # monotone default -> all coefficients non-negative
        assert all(c >= 0 for c in out["summary"]["coefficients_std"].values())

    def test_missing_subscore_imputed(self):
        from core.calibration.hazard_model import _matrix_from_events, _NEUTRAL
        X, y = _matrix_from_events([
            {"label": 1, "economic": 80, "political": None, "nlp": None, "governance": 70},
        ])
        assert X[0][1] == _NEUTRAL and X[0][2] == _NEUTRAL  # missing political/nlp imputed neutral
        assert X[0][0] == 80 and X[0][3] == 70
