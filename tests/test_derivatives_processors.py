"""Tests for derivatives signal scoring logic."""
import pytest
from derivatives.processors import (
    score_funding_rate,
    score_oi_divergence,
    score_long_short_ratio,
    generate_derivatives_signal,
)
from derivatives.models import DerivativesSignal


class TestFundingScore:
    def test_neutral_funding(self):
        assert score_funding_rate(0.0) == 0.0

    def test_positive_funding_negative_score(self):
        """Positive funding = overcrowded longs = bearish = negative score."""
        score = score_funding_rate(0.0005)  # 0.05%
        assert score < 0

    def test_negative_funding_positive_score(self):
        """Negative funding = overcrowded shorts = bullish = positive score."""
        score = score_funding_rate(-0.0005)
        assert score > 0

    def test_clamped_to_range(self):
        assert -1.0 <= score_funding_rate(0.01) <= 1.0
        assert -1.0 <= score_funding_rate(-0.01) <= 1.0

    def test_linear_scaling(self):
        s1 = score_funding_rate(0.0002)
        s2 = score_funding_rate(0.0004)
        assert s2 < s1  # more positive funding = more negative score


class TestOIDivergence:
    def test_rising_oi_rising_price(self):
        """Rising OI + rising price = trend confirmation = positive."""
        score = score_oi_divergence(oi_change_pct=0.05, price_change_pct=0.03)
        assert score > 0

    def test_rising_oi_falling_price(self):
        """Rising OI + falling price = bearish continuation = negative."""
        score = score_oi_divergence(oi_change_pct=0.05, price_change_pct=-0.03)
        assert score < 0

    def test_falling_oi(self):
        """Falling OI = deleveraging = toward 0."""
        score = score_oi_divergence(oi_change_pct=-0.05, price_change_pct=0.03)
        assert abs(score) < 0.3

    def test_clamped(self):
        assert -1.0 <= score_oi_divergence(1.0, 1.0) <= 1.0


class TestLongShortRatio:
    def test_neutral_ratio(self):
        """Ratio near 1.0 = balanced = neutral."""
        score = score_long_short_ratio(1.0, extreme_threshold=2.0)
        assert abs(score) < 0.1

    def test_extreme_long(self):
        """High ratio = lots of longs = contrarian bearish = negative."""
        score = score_long_short_ratio(3.0, extreme_threshold=2.0)
        assert score < 0

    def test_extreme_short(self):
        """Low ratio = lots of shorts = contrarian bullish = positive."""
        score = score_long_short_ratio(0.4, extreme_threshold=2.0)
        assert score > 0


class TestGenerateDerivativesSignal:
    def test_returns_signal(self):
        signal = generate_derivatives_signal(
            asset="BTC",
            funding_rate=0.0001,
            oi_change_pct=0.02,
            price_change_pct=0.01,
            long_short_ratio=1.2,
            config={
                "long_short_extreme_threshold": 2.0,
                "sub_weights": {"funding": 0.4, "oi_divergence": 0.35, "long_short": 0.25},
            },
        )
        assert isinstance(signal, DerivativesSignal)
        assert signal.asset == "BTC"
        assert -1.0 <= signal.combined_score <= 1.0
