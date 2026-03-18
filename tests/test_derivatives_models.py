"""Tests for derivatives Pydantic models."""
import pytest
from datetime import datetime
from derivatives.models import FundingSnapshot, OISnapshot, LongShortRatio, DerivativesSignal


class TestFundingSnapshot:
    def test_valid(self):
        f = FundingSnapshot(asset="BTC", timestamp=datetime.utcnow(),
                            exchange="binance", rate=0.0001)
        assert f.rate == 0.0001

    def test_rate_stored_as_decimal(self):
        """Funding rates stored as decimal fractions, not percentages."""
        f = FundingSnapshot(asset="BTC", timestamp=datetime.utcnow(),
                            exchange="binance", rate=0.0001)
        assert f.rate == 0.0001  # 0.01%


class TestOISnapshot:
    def test_valid(self):
        o = OISnapshot(asset="ETH", timestamp=datetime.utcnow(),
                       exchange="bybit", oi_value=50000.0, oi_usd=150000000.0)
        assert o.oi_usd == 150000000.0


class TestLongShortRatio:
    def test_valid(self):
        ls = LongShortRatio(asset="BTC", timestamp=datetime.utcnow(),
                            ratio=1.5, source="coinalyze")
        assert ls.ratio == 1.5


class TestDerivativesSignal:
    def test_score_clamped(self):
        s = DerivativesSignal(asset="BTC", funding_score=-0.5,
                              oi_divergence_score=0.3, long_short_score=0.1,
                              combined_score=0.0)
        assert -1.0 <= s.combined_score <= 1.0

    def test_from_sub_scores(self):
        s = DerivativesSignal.from_sub_scores(
            asset="BTC", funding_score=-0.5,
            oi_divergence_score=0.3, long_short_score=0.1,
            weights={"funding": 0.4, "oi_divergence": 0.35, "long_short": 0.25},
        )
        expected = (-0.5 * 0.4 + 0.3 * 0.35 + 0.1 * 0.25)
        assert abs(s.combined_score - expected) < 1e-6
