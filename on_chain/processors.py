"""Scoring logic for on-chain sub-signals.

All scores output in range [-1, +1].
"""
from typing import Optional
from on_chain.models import OnChainSignal


def score_exchange_flow(netflow: float, avg_30d_netflow: float, std_30d: float) -> float:
    """Score based on exchange net flow relative to 30-day average.
    Net inflow (positive) = selling pressure = negative score.
    Net outflow (negative) = accumulation = positive score.
    Normalized by standard deviation to detect unusual flows.
    """
    if std_30d <= 0:
        return 0.0
    z_score = (netflow - avg_30d_netflow) / std_30d
    normalized = -z_score / 3.0  # invert: inflow = negative score; cap at ~3 sigma
    return max(-1.0, min(1.0, normalized))


def score_nupl(nupl: float) -> float:
    """Score based on NUPL (Net Unrealized Profit/Loss).
    > 0.75 = euphoria = negative (cycle top risk).
    < 0 = capitulation = positive (cycle bottom opportunity).
    Linear interpolation between.
    """
    if nupl >= 0.75:
        return -1.0
    elif nupl <= -0.25:
        return 1.0
    else:
        # Linear interpolation: nupl=0.75 -> -1.0, nupl=-0.25 -> 1.0
        score = 1.0 - (nupl - (-0.25)) / (0.75 - (-0.25)) * 2.0
        return max(-1.0, min(1.0, score))


def score_active_addresses(growth_rate_30d: float) -> float:
    """Score based on 30-day active address growth rate.
    Growing = positive (fundamental demand).
    Declining = negative (waning interest).
    """
    # 10% growth -> score of +0.5, -10% -> -0.5
    normalized = growth_rate_30d * 5.0
    return max(-1.0, min(1.0, normalized))


def score_whale_activity(to_exchange_usd: float, from_exchange_usd: float,
                         scale: float = 10_000_000) -> float:
    """Score based on net whale transfer direction.
    Net to exchange = sell pressure = negative.
    Net from exchange = accumulation = positive.
    """
    total = to_exchange_usd + from_exchange_usd
    if total == 0:
        return 0.0
    net = from_exchange_usd - to_exchange_usd
    normalized = net / scale
    return max(-1.0, min(1.0, normalized))


def generate_on_chain_signal(
    asset: str,
    netflow: float, avg_30d_netflow: float, std_30d: float,
    nupl: float, active_addr_growth: float,
    whale_to_exchange_usd: Optional[float],
    whale_from_exchange_usd: Optional[float],
    config: dict,
) -> OnChainSignal:
    """Combine all on-chain sub-signals into one score."""
    ef_score = score_exchange_flow(netflow, avg_30d_netflow, std_30d)
    nupl_s = score_nupl(nupl)
    addr_s = score_active_addresses(active_addr_growth)

    whale_s = None
    if whale_to_exchange_usd is not None and whale_from_exchange_usd is not None:
        whale_s = score_whale_activity(whale_to_exchange_usd, whale_from_exchange_usd)

    has_data = any([netflow != 0, nupl != 0, active_addr_growth != 0])
    confidence = 0.8 if has_data else 0.0

    return OnChainSignal.from_sub_scores(
        asset=asset,
        exchange_flow_score=ef_score,
        nupl_score=nupl_s,
        active_addr_score=addr_s,
        whale_score=whale_s,
        weights=config["sub_weights"],
        confidence=confidence,
    )
