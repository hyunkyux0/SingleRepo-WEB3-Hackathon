import pytest
from composite.scorer import apply_overrides


DEFAULT_CONFIG = {
    "funding_soft_threshold": 0.001,
    "funding_hard_threshold": 0.002,
    "nupl_soft_high": 0.75,
    "nupl_hard_high": 0.90,
    "nupl_soft_low": 0.0,
    "nupl_hard_low": -0.25,
    "soft_penalty_multiplier": 0.2,
    "tf_opposition_multiplier": 0.5,
    "catalyst_boost_multiplier": 1.5,
    "catalyst_sentiment_threshold": 0.7,
}


class TestSoftOverrides:
    def test_funding_soft_penalty(self):
        """Funding > 0.001 penalizes positive scores."""
        result = apply_overrides(
            score=0.5, funding_rate=0.0012, nupl=0.5,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == pytest.approx(0.5 * 0.2, abs=1e-6)

    def test_funding_soft_no_effect_on_negative(self):
        """Positive funding soft override only affects positive scores."""
        result = apply_overrides(
            score=-0.5, funding_rate=0.0012, nupl=0.5,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == -0.5  # unchanged

    def test_nupl_euphoria_soft(self):
        result = apply_overrides(
            score=0.6, funding_rate=0.0, nupl=0.8,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == pytest.approx(0.6 * 0.2, abs=1e-6)

    def test_stacking_multiplicative(self):
        """O1a + O3a stack: 0.5 * 0.2 * 0.2 = 0.02."""
        result = apply_overrides(
            score=0.5, funding_rate=0.0012, nupl=0.8,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == pytest.approx(0.5 * 0.2 * 0.2, abs=1e-6)


class TestHardOverrides:
    def test_funding_hard_clamps_to_zero(self):
        result = apply_overrides(
            score=0.8, funding_rate=0.003, nupl=0.5,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] <= 0.0

    def test_nupl_hard_clamps(self):
        result = apply_overrides(
            score=0.8, funding_rate=0.0, nupl=0.95,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] <= 0.0


class TestCatalystBoost:
    def test_catalyst_applied_before_penalties(self):
        """O6 applies first, then O1a penalizes the boosted score."""
        result = apply_overrides(
            score=0.4, funding_rate=0.0012, nupl=0.5,
            tf_opposition=False, catalyst_sentiment=0.8,
            config=DEFAULT_CONFIG,
        )
        # O6: 0.4 * 1.5 = 0.6, then O1a: 0.6 * 0.2 = 0.12
        assert result["final_score"] == pytest.approx(0.4 * 1.5 * 0.2, abs=1e-6)

    def test_catalyst_below_threshold_ignored(self):
        result = apply_overrides(
            score=0.4, funding_rate=0.0, nupl=0.5,
            tf_opposition=False, catalyst_sentiment=0.3,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == 0.4


class TestTFOpposition:
    def test_tf_opposition_reduces(self):
        result = apply_overrides(
            score=0.6, funding_rate=0.0, nupl=0.5,
            tf_opposition=True, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == pytest.approx(0.6 * 0.5, abs=1e-6)


class TestMakeDecision:
    def test_buy(self):
        from composite.scorer import make_optimized_trading_decision
        d = make_optimized_trading_decision(
            asset="BTC",
            scores={"technical": 0.8, "derivatives": 0.5, "on_chain": 0.3,
                    "multi_timeframe": 0.7, "sentiment": 0.4},
            weights={"technical": 0.35, "derivatives": 0.25, "on_chain": 0.15,
                     "multi_timeframe": 0.10, "sentiment": 0.15},
            thresholds={"buy_default": 0.3, "sell_default": 0.3},
            override_inputs={"funding_rate": 0.0, "nupl": 0.5,
                             "tf_opposition": False, "catalyst_sentiment": 0.0},
            override_config=DEFAULT_CONFIG,
        )
        assert d.decision == "BUY"

    def test_sell(self):
        from composite.scorer import make_optimized_trading_decision
        d = make_optimized_trading_decision(
            asset="BTC",
            scores={"technical": -0.8, "derivatives": -0.5, "on_chain": -0.3,
                    "multi_timeframe": -0.7, "sentiment": -0.4},
            weights={"technical": 0.35, "derivatives": 0.25, "on_chain": 0.15,
                     "multi_timeframe": 0.10, "sentiment": 0.15},
            thresholds={"buy_default": 0.3, "sell_default": 0.3},
            override_inputs={"funding_rate": 0.0, "nupl": 0.5,
                             "tf_opposition": False, "catalyst_sentiment": 0.0},
            override_config=DEFAULT_CONFIG,
        )
        assert d.decision == "SELL"
