"""Scoring logic for derivatives sub-signals.

All scores output in range [-1, +1].
Funding rates are decimal fractions (0.01% = 0.0001).
"""
import math

from derivatives.models import DerivativesSignal


def score_funding_rate(rate: float, cap: float = 0.002) -> float:
    """Convert funding rate to a score.
    Positive funding -> negative score (overcrowded longs = bearish).
    Negative funding -> positive score (overcrowded shorts = bullish).
    Linearly scaled, capped at +-cap.
    """
    normalized = -rate / cap  # invert: positive funding = negative score
    return max(-1.0, min(1.0, normalized))


def score_oi_divergence(oi_change_pct: float, price_change_pct: float) -> float:
    """Score based on OI/price relationship.
    Rising OI + rising price = trend confirmation (+).
    Rising OI + falling price = bearish continuation (-).
    Falling OI = deleveraging, reduces conviction toward 0.
    """
    if oi_change_pct <= 0:
        # Deleveraging -- muted signal
        return max(-1.0, min(1.0, price_change_pct * 0.3))

    # OI rising: direction determined by price
    raw = oi_change_pct * price_change_pct * 10  # scale factor
    return max(-1.0, min(1.0, raw))


def score_long_short_ratio(ratio: float, extreme_threshold: float = 2.0) -> float:
    """Contrarian signal from long/short ratio.
    Ratio > extreme -> bearish (too many longs).
    Ratio < 1/extreme -> bullish (too many shorts).
    Near 1.0 -> neutral.
    """
    if ratio <= 0:
        return 0.0
    log_ratio = math.log(ratio)
    log_extreme = math.log(extreme_threshold)
    normalized = -log_ratio / log_extreme  # invert: high ratio = negative
    return max(-1.0, min(1.0, normalized))


def aggregate_funding_rate_oi_weighted(
    rates: list[dict],
) -> float:
    """OI-weighted average funding rate across exchanges (spec Section 2).
    Each entry: {"exchange": str, "rate": float, "oi_usd": float}.
    Falls back to simple average if OI data is missing.
    """
    total_oi = sum(r.get("oi_usd", 0) for r in rates)
    if total_oi <= 0:
        # Fallback: simple average
        return sum(r["rate"] for r in rates) / len(rates) if rates else 0.0
    return sum(r["rate"] * r.get("oi_usd", 0) for r in rates) / total_oi


def aggregate_open_interest(oi_rows: list[dict]) -> float:
    """Sum OI across exchanges for total market OI (spec Section 2)."""
    return sum(r.get("oi_value", 0) for r in oi_rows)


def generate_derivatives_signal(
    asset: str,
    funding_rate: float,
    oi_change_pct: float,
    price_change_pct: float,
    long_short_ratio: float,
    config: dict,
) -> DerivativesSignal:
    """Combine all derivatives sub-signals into one score."""
    fs = score_funding_rate(funding_rate)
    oi = score_oi_divergence(oi_change_pct, price_change_pct)
    ls = score_long_short_ratio(long_short_ratio, config["long_short_extreme_threshold"])

    return DerivativesSignal.from_sub_scores(
        asset=asset,
        funding_score=fs,
        oi_divergence_score=oi,
        long_short_score=ls,
        weights=config["sub_weights"],
    )
