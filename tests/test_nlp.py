"""Tests for NLP modules: lexicon, hybrid scorer, and aspect-based sentiment."""

import pytest

from core.nlp.lexicon import lexicon_score, hawkish_dovish_label
from core.nlp.sentiment import analyse_statement, SentimentResult
from core.nlp.aspect_scorer import aspect_sentiment_score, aggregate_aspect_scores, AspectScores


class TestLexicon:
    def test_hawkish_text_positive(self):
        text = "The committee is prepared to raise rates to combat elevated inflation."
        raw, _ = lexicon_score(text)
        assert raw > 0

    def test_dovish_text_negative(self):
        text = "The board decided to cut rates and support growth with accommodative policy."
        raw, _ = lexicon_score(text)
        assert raw < 0

    def test_negation_flips(self):
        positive = "The bank will raise rates decisively."
        negated = "The bank will not raise rates."
        raw_pos, _ = lexicon_score(positive)
        raw_neg, _ = lexicon_score(negated)
        assert raw_pos > raw_neg

    def test_stress_terms_raise(self):
        calm = "The economy is growing steadily."
        stressed = "The crisis and turmoil in financial markets require emergency intervention."
        raw_calm, _ = lexicon_score(calm)
        raw_stress, _ = lexicon_score(stressed)
        assert raw_stress > raw_calm


class TestHybridScorer:
    _HAWKISH = (
        "The committee is firmly committed to returning inflation to target. "
        "Upside risks to inflation remain elevated. We stand prepared to act decisively "
        "with further rate increases if needed. Inflationary pressures are persistent."
    )
    _DOVISH = (
        "The board voted to cut rates by 25 basis points in a data-dependent manner. "
        "Inflation is declining and returning to target. We support growth with "
        "accommodative policy. The soft landing scenario remains our base case."
    )
    _SHORT = "OK."

    def test_score_in_range(self):
        result = analyse_statement(self._HAWKISH)
        assert isinstance(result, SentimentResult)
        assert 0 <= result.score <= 100

    def test_hawkish_scores_higher_than_dovish(self):
        h = analyse_statement(self._HAWKISH)
        d = analyse_statement(self._DOVISH)
        assert h.score > d.score

    def test_short_text_neutral(self):
        result = analyse_statement(self._SHORT)
        assert result.score == 50.0

    def test_result_has_drivers_and_label(self):
        result = analyse_statement(self._HAWKISH)
        assert isinstance(result.label, str)
        assert isinstance(result.drivers, list)


class TestAspectScorer:
    _MONETARY = (
        "The committee voted to raise the policy rate by 25 basis points. "
        "Inflation remains elevated above our 2% target. Rate hikes will continue "
        "until price stability is restored. Monetary policy remains restrictive."
    )
    _FISCAL = (
        "The fiscal deficit has widened significantly. Public debt trajectory is "
        "concerning. Budget consolidation is urgently needed to restore fiscal space. "
        "Tax revenue has underperformed projections."
    )
    _BANKING = (
        "Bank non-performing loan ratios have risen sharply. Financial stability risks "
        "are elevated. Capital adequacy buffers need to be strengthened. "
        "Credit risk in the banking sector has increased."
    )

    def test_returns_aspect_scores(self):
        result = aspect_sentiment_score(self._MONETARY)
        assert isinstance(result, AspectScores)
        assert 0 <= result.overall <= 100

    def test_monetary_aspect_detected(self):
        result = aspect_sentiment_score(self._MONETARY)
        assert result.monetary_policy is not None

    def test_fiscal_aspect_detected(self):
        result = aspect_sentiment_score(self._FISCAL)
        assert result.fiscal_policy is not None

    def test_financial_stability_detected(self):
        result = aspect_sentiment_score(self._BANKING)
        assert result.financial_stability is not None

    def test_mixed_text_hits_multiple_aspects(self):
        mixed = self._MONETARY + " " + self._FISCAL + " " + self._BANKING
        result = aspect_sentiment_score(mixed)
        non_none = sum(1 for v in [
            result.monetary_policy, result.fiscal_policy, result.financial_stability
        ] if v is not None)
        assert non_none >= 2

    def test_hawkish_monetary_scores_higher(self):
        hawkish = aspect_sentiment_score(
            "Rate hike is needed urgently. Inflation is dangerously elevated above target. "
            "Restrictive monetary policy must be maintained for longer. Prepared to act."
        )
        dovish = aspect_sentiment_score(
            "Rate cut will support growth and accommodative policy is appropriate. "
            "Inflation is declining and returning to target. Easing monetary conditions."
        )
        h_mon = hawkish.monetary_policy or 50.0
        d_mon = dovish.monetary_policy or 50.0
        assert h_mon > d_mon

    def test_aggregate_time_weights(self):
        scores = [
            AspectScores(monetary_policy=80.0, overall=75.0),
            AspectScores(monetary_policy=40.0, overall=45.0),
            AspectScores(monetary_policy=30.0, overall=35.0),
        ]
        agg = aggregate_aspect_scores(scores)
        assert agg.monetary_policy is not None
        # Most recent (80.0) dominates over older (40.0, 30.0) → weighted avg > 50
        assert agg.monetary_policy > 50.0

    def test_empty_text_returns_default(self):
        result = aspect_sentiment_score("")
        assert result.overall == 50.0
        assert result.sentence_count == 0
