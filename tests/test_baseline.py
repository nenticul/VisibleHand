"""
Tests for the cross-sectional baseline scorer and the two-mode composite.
Pure-function tests — no DB, no network.
"""

from core.scoring.baseline import (
    build_baseline_reference, resolve_peer_group, cross_sectional_economic,
    INCOME_GROUP, REGION, ANCHOR_ECONOMIES, _percentile,
)
from core.scoring.composite import compute_composite


# A High-income · Europe peer cell (all real codes in that cell).
_HI_EU = ["DE", "FR", "IT", "ES", "NL", "CH", "GB", "GR", "HU", "PL"]


def _synthetic_reference():
    """Build a reference where GR is the worst and CH the best on every metric."""
    latest = {}
    # inflation (higher = worse): GR worst
    inflation = {"GR": 14.0, "HU": 6.0, "PL": 5.0, "GB": 4.0, "IT": 3.5,
                 "ES": 3.0, "FR": 2.5, "DE": 2.0, "NL": 1.8, "CH": 1.0}
    # fx_reserves (lower = worse): GR lowest
    reserves = {"GR": 1.0, "HU": 3.0, "PL": 4.0, "GB": 5.0, "IT": 6.0,
                "ES": 6.5, "FR": 7.0, "DE": 8.0, "NL": 8.5, "CH": 12.0}
    # debt_to_gdp (higher = worse): GR worst
    debt = {"GR": 180.0, "IT": 140.0, "FR": 110.0, "ES": 105.0, "GB": 100.0,
            "HU": 75.0, "DE": 65.0, "NL": 55.0, "PL": 50.0, "CH": 40.0}
    for c in _HI_EU:
        latest[c] = {"inflation": inflation[c], "fx_reserves": reserves[c],
                     "debt_to_gdp": debt[c]}
    return build_baseline_reference(latest)


def test_percentile_midrank():
    assert _percentile(5, [1, 2, 3, 4, 5]) == 0.9  # 4 below + 0.5 tie of 5/5
    assert _percentile(0, [1, 2, 3]) == 0.0
    assert _percentile(10, [1, 2, 3]) == 1.0


def test_peer_group_income_region():
    ref = _synthetic_reference()
    label, peers = resolve_peer_group("DE", ref)
    assert "High income" in label and "Europe" in label
    assert set(peers) == set(_HI_EU)


def test_peer_group_fallback_for_thin_cell():
    # Ethiopia is the only Low-income country → must fall back past income to region.
    latest = {c: {"inflation": 5.0} for c in
              ["ET", "NG", "KE", "GH", "ZA"]}  # all Sub-Saharan
    ref = build_baseline_reference(latest)
    label, peers = resolve_peer_group("ET", ref)
    assert label == "Sub-Saharan"
    assert "ET" in peers and "NG" in peers


def test_cross_sectional_orientation_worst_country():
    ref = _synthetic_reference()
    res = cross_sectional_economic(
        "GR", {"inflation": 14.0, "fx_reserves": 1.0, "debt_to_gdp": 180.0}, ref
    )
    # GR is worst on every metric → near-maximal oriented percentiles & high score.
    assert res.percentiles["inflation"] >= 90
    assert res.percentiles["fx_reserves"] >= 90      # lowest reserves → highest risk
    assert res.percentiles["debt_to_gdp"] >= 90
    assert res.score >= 75
    assert res.peer_group and res.peer_n >= 5


def test_cross_sectional_orientation_best_country():
    ref = _synthetic_reference()
    res = cross_sectional_economic(
        "CH", {"inflation": 1.0, "fx_reserves": 12.0, "debt_to_gdp": 40.0}, ref
    )
    assert res.percentiles["inflation"] <= 20
    assert res.percentiles["fx_reserves"] <= 20      # highest reserves → lowest risk
    assert res.score <= 35


def test_cross_sectional_deterministic():
    ref = _synthetic_reference()
    a = cross_sectional_economic("IT", {"inflation": 3.5, "fx_reserves": 6.0, "debt_to_gdp": 140.0}, ref)
    b = cross_sectional_economic("IT", {"inflation": 3.5, "fx_reserves": 6.0, "debt_to_gdp": 140.0}, ref)
    assert a.score == b.score
    assert a.percentiles == b.percentiles


def test_composite_two_modes_differ_and_carry_metadata():
    ref = _synthetic_reference()
    # A country whose OWN history is flat at high-debt levels: temporally it looks
    # calm, but cross-sectionally (vs peers + anchor) it is clearly extreme.
    indicators = {
        "inflation":   [13.5, 13.8, 14.0, 14.0, 14.0],
        "fx_reserves": [1.1, 1.0, 1.0, 1.0, 1.0],
        "debt_to_gdp": [178, 179, 180, 180, 180],
    }
    temporal = compute_composite(indicators=indicators, events=[], nlp_score=None,
                                 country="GR", mode="temporal")
    cross = compute_composite(indicators=indicators, events=[], nlp_score=None,
                              country="GR", mode="cross_sectional", baseline_ref=ref)

    assert temporal["mode"] == "temporal"
    assert cross["mode"] == "cross_sectional"
    assert cross["peer_group"]
    assert cross["peer_percentiles"]
    # A self-calm-but-globally-extreme country must read riskier cross-sectionally.
    assert cross["composite"] > temporal["composite"]


def test_cross_sectional_falls_back_to_temporal_without_reference():
    indicators = {"inflation": [2, 3, 4, 5, 6]}
    # mode requested but no baseline_ref → must degrade to temporal, not crash.
    res = compute_composite(indicators=indicators, events=[], nlp_score=None,
                            country="DE", mode="cross_sectional", baseline_ref=None)
    assert res["mode"] == "temporal"


def test_universe_taxonomy_complete():
    # Every income-grouped country has a region and vice-versa (no orphans).
    for c in INCOME_GROUP:
        assert c in REGION, f"{c} missing region"
    assert set(ANCHOR_ECONOMIES) <= set(INCOME_GROUP)
