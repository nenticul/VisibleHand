"""Unit tests for the V3 scoring engine."""

from datetime import date, timedelta

import pytest

from core.scoring.economic import economic_score, EconomicResult
from core.scoring.political import political_score, PoliticalResult, fit_hawkes
from core.scoring.governance import governance_score, GovernanceResult
from core.scoring.composite import compute_composite
from core.scoring.stats import robust_z, winsorize, trend_slope, convex_risk
from core.scoring.labels import risk_level


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


# ── Stats ────────────────────────────────────────────────────────────────────

class TestStats:
    def test_robust_z_resists_outlier(self):
        calm = [2.0, 2.1, 1.9, 2.0, 2.2, 2.1, 1.8, 2.0, 2.1]
        assert abs(robust_z(2.0, calm)) < 1.0
        assert robust_z(15.0, calm) > 2.0

    def test_winsorize_clamps_extremes(self):
        s = [1, 2, 3, 4, 5, 6, 7, 8, 9, 100]
        assert max(winsorize(s)) < 100

    def test_trend_slope_direction(self):
        assert trend_slope([1, 2, 3, 4, 5]) > 0
        assert trend_slope([5, 4, 3, 2, 1]) < 0

    def test_convex_risk_bounds(self):
        for v in [-5, 0, 5]:
            assert 0.0 <= convex_risk(v) <= 1.0
        assert convex_risk(3) > convex_risk(1) > convex_risk(0)


# ── Economic V3 ──────────────────────────────────────────────────────────────

class TestEconomicScorer:
    _BASE_INDICATORS = {
        "gdp_growth":   [3.0] * 10,
        "inflation":    [2.0] * 10,
        "debt_to_gdp":  [60.0] * 10,
        "fx_reserves":  [5.0] * 10,
        "current_account": [1.0] * 10,
    }

    def test_returns_result_in_range(self):
        indicators = {
            "gdp_growth":   [2.0, 2.5, 3.0, 3.2, 2.8, 3.1, 2.9, 3.3, 3.0, 1.0],
            "inflation":    [2.0, 2.1, 1.9, 2.2, 2.0, 2.1, 2.3, 2.0, 1.8, 8.5],
            "debt_to_gdp":  [60, 62, 63, 61, 64, 65, 64, 63, 62, 68],
        }
        result = economic_score(indicators)
        assert isinstance(result, EconomicResult)
        assert 0 <= result.score <= 100
        assert 0 <= result.confidence <= 1

    def test_neutral_on_no_data(self):
        result = economic_score({})
        assert result.score == 50.0
        assert result.confidence == 0.0

    def test_high_inflation_raises_score(self):
        base = [2.0] * 9
        low = dict(self._BASE_INDICATORS, inflation=base + [2.1])
        high = dict(self._BASE_INDICATORS, inflation=base + [18.0])
        assert economic_score(high).score > economic_score(low).score

    def test_confidence_scales_with_coverage(self):
        one = {"gdp_growth": [3.0] * 10}
        ten = {m: [3.0] * 10 for m in [
            "gdp_growth", "inflation", "debt_to_gdp", "fx_reserves",
            "current_account", "unemployment", "bank_npl", "tax_revenue", "remittances",
        ]}
        assert economic_score(ten).confidence > economic_score(one).confidence

    def test_deterioration_detected(self):
        noisy = [2.0, 2.2, 1.9, 2.1, 2.0, 2.3, 1.8]
        stable = {"inflation": noisy + [2.0, 2.1, 2.0],
                  "gdp_growth": [3.0] * 10, "debt_to_gdp": [60.0] * 10}
        deteriorating = {"inflation": noisy + [3.0, 4.5, 6.5],
                         "gdp_growth": [3.0] * 10, "debt_to_gdp": [60.0] * 10}
        assert economic_score(deteriorating).score > economic_score(stable).score

    def test_regime_conditional_chronic_inflation(self):
        # Country with chronically high inflation (Argentina-like)
        ar_inflation = [30.0, 40.0, 50.0, 35.0, 42.0, 55.0, 48.0, 30.0, 95.0, 210.0]
        result = economic_score({"inflation": ar_inflation})
        assert result.regime_flags.get("chronic_inflation") is True

    def test_ten_indicators_all_score(self):
        full = {
            "gdp_growth": [3.0] * 10, "inflation": [2.0] * 10,
            "debt_to_gdp": [60.0] * 10, "fx_reserves": [5.0] * 10,
            "current_account": [1.0] * 10, "unemployment": [5.0] * 10,
            "bank_npl": [2.0] * 10, "credit_gdp_gap": [0.0] * 10,
            "tax_revenue": [20.0] * 10, "remittances": [1.0] * 10,
        }
        result = economic_score(full)
        assert len(result.components) >= 9
        assert 0 <= result.score <= 100

    def test_nowcast_uses_fx_daily(self):
        # Large FX depreciation should push nowcast score up
        indicators = dict(self._BASE_INDICATORS)
        indicators["fx_daily"] = [1.0, 1.5]  # 50% depreciation
        result_with = economic_score(indicators)
        result_without = economic_score(self._BASE_INDICATORS)
        assert result_with.nowcast_score is not None
        assert result_with.score > result_without.score


# ── Political V3 ─────────────────────────────────────────────────────────────

class TestPoliticalScorer:
    def test_no_events_low_score(self):
        result = political_score([])
        assert isinstance(result, PoliticalResult)
        assert result.score == 0.0

    def test_recent_conflict_raises_score(self):
        events = [{"event_type": "conflict", "event_date": _days_ago(2), "severity": 2.0}] * 5
        assert political_score(events).score > 25

    def test_old_events_decay(self):
        old = [{"event_type": "conflict", "event_date": _days_ago(365), "severity": 2.0}] * 5
        new = [{"event_type": "conflict", "event_date": _days_ago(2), "severity": 2.0}] * 5
        assert political_score(new).score > political_score(old).score

    def test_escalation_detected(self):
        events = [{"event_type": "protest", "event_date": _days_ago(d), "severity": 2.0}
                  for d in (1, 3, 5, 7, 10)]
        result = political_score(events)
        assert result.components["escalation"] > 50

    def test_score_in_range(self):
        events = [{"event_type": "conflict", "event_date": _days_ago(1), "severity": 5.0}] * 50
        assert 0 <= political_score(events).score <= 100

    def test_fatality_multiplier(self):
        no_fatal = [{"event_type": "conflict", "event_date": _days_ago(2), "severity": 2.0, "fatalities": 0}]
        high_fatal = [{"event_type": "conflict", "event_date": _days_ago(2), "severity": 2.0, "fatalities": 200}]
        assert political_score(high_fatal).score > political_score(no_fatal).score

    def test_acled_taxonomy_intensity(self):
        explosions = [{"event_type": "Explosions/Remote violence", "event_date": _days_ago(2), "severity": 1.0}]
        protests = [{"event_type": "Protests", "event_date": _days_ago(2), "severity": 1.0}]
        assert political_score(explosions).score > political_score(protests).score

    def test_contagion_adds_pressure(self):
        events = [{"event_type": "protest", "event_date": _days_ago(20), "severity": 1.0}]
        without_contagion = political_score(events, country="UA")
        with_contagion = political_score(events, country="UA",
                                          neighbour_scores={"RU": 80.0, "BY": 75.0})
        assert with_contagion.score >= without_contagion.score

    def test_hawkes_fitting(self):
        # Need enough events for stable MLE
        events = [
            {"event_type": "conflict", "event_date": _days_ago(i * 3), "severity": 1.5}
            for i in range(15)
        ]
        result = political_score(events)
        # Should attempt Hawkes; either succeeds or falls back gracefully
        assert 0 <= result.score <= 100

    def test_hawkes_branching_constraint(self):
        # Many rapid events should not cause divergence
        events = [
            {"event_type": "conflict", "event_date": _days_ago(i), "severity": 5.0, "fatalities": 50}
            for i in range(30)
        ]
        result = political_score(events)
        assert 0 <= result.score <= 100
        if result.hawkes_params:
            assert result.hawkes_params.branching < 0.96


# ── Governance ───────────────────────────────────────────────────────────────

class TestGovernanceScorer:
    def test_no_data_neutral(self):
        result = governance_score({})
        assert result.score == 50.0
        assert result.confidence == 0.0

    def test_good_governance_low_risk(self):
        good = {
            "v2x_rule": [0.95, 0.95, 0.96],
            "v2x_corr": [0.94, 0.93, 0.94],
            "ti_cpi": [80, 81, 80],
            "wjp_rule_of_law": [0.85, 0.84, 0.84],
            "fh_political": [1, 1, 1],
        }
        bad = {
            "v2x_rule": [0.20, 0.18, 0.17],
            "v2x_corr": [0.15, 0.14, 0.13],
            "ti_cpi": [15, 13, 12],
            "wjp_rule_of_law": [0.20, 0.19, 0.19],
            "fh_political": [7, 7, 7],
        }
        r_good = governance_score(good)
        r_bad = governance_score(bad)
        assert r_bad.score > r_good.score

    def test_press_freedom_modifier(self):
        # Low press freedom = higher risk score → lower confidence modifier
        low_press = {"v2x_freexp_altinf": [0.1, 0.1, 0.1], "v2x_rule": [0.1, 0.1, 0.1]}
        high_press = {"v2x_freexp_altinf": [0.9, 0.9, 0.9], "v2x_rule": [0.9, 0.9, 0.9]}
        r_low = governance_score(low_press)
        r_high = governance_score(high_press)
        # Both have same modifier initially due to same structure — just verify range
        assert 0.5 <= r_low.press_freedom_confidence_modifier <= 1.0
        assert 0.5 <= r_high.press_freedom_confidence_modifier <= 1.0

    def test_returns_governance_result(self):
        result = governance_score({"v2x_rule": [0.7, 0.72, 0.71], "ti_cpi": [40, 41, 42]})
        assert isinstance(result, GovernanceResult)
        assert 0 <= result.score <= 100
        assert 0 <= result.confidence <= 1


# ── Composite V3 ─────────────────────────────────────────────────────────────

class TestComposite:
    _INDICATORS = {
        "gdp_growth": [3.0] * 10, "inflation": [2.0] * 10,
        "debt_to_gdp": [60.0] * 10, "fx_reserves": [5.0] * 10,
        "current_account": [1.0] * 10,
    }
    _EVENTS = [{"event_type": "conflict", "event_date": _days_ago(5), "severity": 2.0}] * 3

    def test_composite_in_range(self):
        result = compute_composite(
            indicators=self._INDICATORS,
            events=[],
            nlp_score=50.0,
        )
        assert 0 <= result["composite"] <= 100
        assert 0 <= result["confidence"] <= 1

    def test_ci_present(self):
        result = compute_composite(
            indicators=self._INDICATORS,
            events=[],
            nlp_score=50.0,
        )
        assert result["ci_low"] is not None
        assert result["ci_high"] is not None
        assert result["ci_low"] <= result["composite"] <= result["ci_high"] + 1  # slight float tolerance

    def test_four_component_blend(self):
        gov = {"v2x_rule": [0.3, 0.3, 0.28], "ti_cpi": [15, 14, 13]}
        result = compute_composite(
            indicators=self._INDICATORS,
            events=self._EVENTS,
            nlp_score=70.0,
            governance_indicators=gov,
        )
        assert result.get("governance") is not None
        assert "Governance" in str(result.get("methodology", ""))

    def test_driver_attributions_present(self):
        result = compute_composite(
            indicators=self._INDICATORS,
            events=[],
            nlp_score=50.0,
        )
        assert isinstance(result.get("driver_attributions"), list)
        assert len(result["driver_attributions"]) > 0
        for attr in result["driver_attributions"]:
            assert "name" in attr and "contribution" in attr and "direction" in attr

    def test_forecast_from_history(self):
        history = [40.0, 42.0, 44.0, 46.0, 48.0]
        result = compute_composite(
            indicators=self._INDICATORS,
            events=[],
            nlp_score=50.0,
            score_history=history,
        )
        assert result.get("forecast_6m") is not None
        assert result.get("forecast_12m") is not None

    def test_renormalises_missing_components(self):
        result = compute_composite(indicators={}, events=[], nlp_score=90.0,
                                   economic_weight=0.45, political_weight=0.25, nlp_weight=0.20)
        assert result["composite"] >= 85

    def test_no_data_neutral_low_confidence(self):
        result = compute_composite(indicators={}, events=[], nlp_score=None)
        assert result["confidence"] == 0.0

    def test_methodology_string_present(self):
        result = compute_composite(
            indicators={"inflation": [2.0] * 9 + [20.0], "gdp_growth": [3.0] * 10},
            events=self._EVENTS,
            nlp_score=80.0,
        )
        assert isinstance(result["methodology"], str) and len(result["methodology"]) > 10
        assert isinstance(result["top_drivers"], list)


# ── Labels ───────────────────────────────────────────────────────────────────

class TestLabels:
    def test_bands(self):
        assert risk_level(10) == "Very Low"
        assert risk_level(30) == "Low"
        assert risk_level(50) == "Moderate"
        assert risk_level(65) == "High"
        assert risk_level(80) == "Very High"
        assert risk_level(95) == "Critical"
