"""
NLP sub-scorer.

Converts a central bank statement sentiment score (0–100) into a risk
contribution. Hawkish language during high-inflation regimes = higher risk.
"""


def nlp_risk_score(sentiment_score: float | None) -> float:
    """
    Takes a raw sentiment score (0 = dovish/stable, 100 = hawkish/risk) and
    returns a risk contribution on the same 0–100 scale.

    The raw DistilBERT score is already on [0, 100]; this function is a
    pass-through but exists as an extension point for calibration.
    """
    if sentiment_score is None:
        return 50.0  # neutral fallback
    return float(max(0.0, min(100.0, sentiment_score)))
