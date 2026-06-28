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
