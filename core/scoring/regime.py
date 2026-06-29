"""
Monetary-regime classifier.

A central bank can be hawkish for two very different reasons:

  * *proactive* tightening from a position of strength (inflation contained,
    growth solid) - this is mildly risk-*reducing*; or
  * *crisis-defence* tightening into high inflation with thin FX reserves -
    this is strongly risk-*raising*.

The NLP scorer measures hawkishness on a single axis and cannot tell these
apart. This module reads the hawkishness level together with the economic
sub-scorer's own per-indicator risk detail to tag which regime a country is in.

It is deliberately a *context tag*, not a silent multiplier: it annotates the
explanation without mutating the published composite (which stays comparable and
calibrated). Pure standard library - no numpy, no dependencies.
"""

from __future__ import annotations

# Economic `detail` values are oriented risk (0-100, higher = worse).
_HAWKISH = 65.0      # nlp_sentiment at/above this reads hawkish
_DOVISH = 35.0       # at/below this reads dovish
_HIGH_INFLATION = 65.0
_THIN_RESERVES = 60.0
_CONTAINED_INFLATION = 55.0
_SOLID_GROWTH = 45.0   # low gdp_growth *risk* == solid growth


def classify_nlp_regime(
    nlp_score: float | None,
    economic_detail: dict[str, float] | None,
) -> dict:
    """
    Return a regime tag for the monetary stance.

    Args:
        nlp_score: NLP hawkishness sub-score (0-100, higher = more hawkish).
        economic_detail: economic component `detail` (per-indicator risk 0-100;
            keys include inflation, fx_reserves, gdp_growth).

    Returns a dict with:
        regime: crisis_hawkish | proactive_hawkish | ambiguous_hawkish |
                neutral | dovish | unknown
        label:  short human label
        note:   one-line plain-language reading
        suggested_multiplier: how a regime-aware model *would* re-weight the NLP
            risk (1.0 = no change). Reported, not applied - surfacing it keeps the
            published score comparable while making the asymmetry explicit.
    """
    if nlp_score is None:
        return {
            "regime": "unknown",
            "label": "No central-bank signal",
            "note": "No recent central-bank statement to read a stance from.",
            "suggested_multiplier": 1.0,
        }

    d = economic_detail or {}
    inflation = d.get("inflation")
    reserves = d.get("fx_reserves")
    growth = d.get("gdp_growth")

    if nlp_score >= _HAWKISH:
        if (inflation is not None and inflation >= _HIGH_INFLATION
                and reserves is not None and reserves >= _THIN_RESERVES):
            return {
                "regime": "crisis_hawkish",
                "label": "Crisis-defence tightening",
                "note": ("Hawkish into high inflation and thin FX reserves - the "
                         "central bank is defending the currency, not normalising."),
                "suggested_multiplier": 1.3,
            }
        if (growth is not None and growth <= _SOLID_GROWTH
                and (inflation is None or inflation <= _CONTAINED_INFLATION)):
            return {
                "regime": "proactive_hawkish",
                "label": "Pre-emptive normalisation",
                "note": ("Hawkish from a position of strength - solid growth, "
                         "contained inflation. Tightening is precautionary."),
                "suggested_multiplier": 0.85,
            }
        return {
            "regime": "ambiguous_hawkish",
            "label": "Hawkish, mixed backdrop",
            "note": "Hawkish stance without a clear strength-or-crisis signal.",
            "suggested_multiplier": 1.0,
        }

    if nlp_score <= _DOVISH:
        return {
            "regime": "dovish",
            "label": "Accommodative",
            "note": "Dovish / supportive central-bank language.",
            "suggested_multiplier": 1.0,
        }

    return {
        "regime": "neutral",
        "label": "Balanced / data-dependent",
        "note": "Neutral central-bank tone, no strong directional bias.",
        "suggested_multiplier": 1.0,
    }
