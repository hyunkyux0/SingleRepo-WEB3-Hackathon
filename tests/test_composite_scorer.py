import pytest
from composite.scorer import compute_weighted_sum, apply_overrides, make_optimized_trading_decision


class TestWeightedSum:
    def test_default_weights_sum(self):
        """Weights are normalized — changing one doesn't break output range."""
        score = compute_weighted_sum(
            technical=1.0, derivatives=1.0, on_chain=1.0, mtf=1.0, sentiment=1.0,
            weights={"technical": 0.35, "derivatives": 0.25, "on_chain": 0.15,
                     "multi_timeframe": 0.10, "sentiment": 0.15},
        )
        assert abs(score - 1.0) < 1e-6  # all +1 -> +1

    def test_mixed_signals(self):
        score = compute_weighted_sum(
            technical=0.8, derivatives=-0.5, on_chain=0.2, mtf=0.5, sentiment=0.0,
            weights={"technical": 0.35, "derivatives": 0.25, "on_chain": 0.15,
                     "multi_timeframe": 0.10, "sentiment": 0.15},
        )
        assert -1.0 <= score <= 1.0

    def test_normalization(self):
        """Unnormalized weights still produce correct result."""
        s1 = compute_weighted_sum(
            technical=0.5, derivatives=0.3, on_chain=0.1, mtf=0.2, sentiment=0.4,
            weights={"technical": 7, "derivatives": 5, "on_chain": 3,
                     "multi_timeframe": 2, "sentiment": 3},
        )
        s2 = compute_weighted_sum(
            technical=0.5, derivatives=0.3, on_chain=0.1, mtf=0.2, sentiment=0.4,
            weights={"technical": 0.35, "derivatives": 0.25, "on_chain": 0.15,
                     "multi_timeframe": 0.10, "sentiment": 0.15},
        )
        assert abs(s1 - s2) < 1e-6
