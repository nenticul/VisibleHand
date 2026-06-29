"""Tests for the monetary-regime classifier (pure-function, no DB/network)."""

from core.scoring.regime import classify_nlp_regime


def test_crisis_hawkish_high_inflation_thin_reserves():
    # Hawkish tone + high inflation risk + thin-reserve risk → crisis defence.
    r = classify_nlp_regime(82.0, {"inflation": 90.0, "fx_reserves": 85.0, "gdp_growth": 60.0})
    assert r["regime"] == "crisis_hawkish"
    assert r["suggested_multiplier"] > 1.0


def test_proactive_hawkish_strength():
    # Hawkish tone + strong growth (low gdp risk) + contained inflation → pre-emptive.
    r = classify_nlp_regime(70.0, {"inflation": 30.0, "fx_reserves": 20.0, "gdp_growth": 25.0})
    assert r["regime"] == "proactive_hawkish"
    assert r["suggested_multiplier"] < 1.0


def test_ambiguous_hawkish_mixed():
    r = classify_nlp_regime(70.0, {"inflation": 60.0, "fx_reserves": 40.0, "gdp_growth": 55.0})
    assert r["regime"] == "ambiguous_hawkish"
    assert r["suggested_multiplier"] == 1.0


def test_dovish_and_neutral_bands():
    assert classify_nlp_regime(20.0, {})["regime"] == "dovish"
    assert classify_nlp_regime(50.0, {})["regime"] == "neutral"


def test_unknown_without_nlp():
    r = classify_nlp_regime(None, {"inflation": 90.0})
    assert r["regime"] == "unknown"
    assert r["suggested_multiplier"] == 1.0


def test_multiplier_never_mutates_published_score():
    # The classifier only *reports* a multiplier; it must always return 1.0 for
    # non-hawkish regimes so nothing downstream is tempted to silently apply it.
    for score in (10, 40, 50, 64):
        assert classify_nlp_regime(float(score), {})["suggested_multiplier"] == 1.0
