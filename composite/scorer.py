"""Composite scoring: normalized weighted sum + two-tier override rules.

See spec Section 7 for full override rule table and stacking semantics.
"""
from composite.models import CompositeScore, OverrideEvent, TradingDecision


def compute_weighted_sum(
    technical: float, derivatives: float, on_chain: float,
    mtf: float, sentiment: float, weights: dict,
) -> float:
    """Compute normalized weighted sum of all sub-scores.
    Weights are normalized by their sum to guarantee output in [-1, +1].
    """
    raw = (
        technical * weights["technical"]
        + derivatives * weights["derivatives"]
        + on_chain * weights["on_chain"]
        + mtf * weights["multi_timeframe"]
        + sentiment * weights["sentiment"]
    )
    total_w = sum(weights.values())
    if total_w == 0:
        return 0.0
    return raw / total_w


def apply_overrides(
    score: float, funding_rate: float, nupl: float,
    tf_opposition: bool, catalyst_sentiment: float,
    config: dict,
) -> dict:
    """Apply two-tier override rules to the composite score.

    Order: O6 (catalyst boost) first, then soft penalties, then hard clamps.
    Soft multipliers stack multiplicatively.
    Returns dict with final_score and overrides_fired list.
    """
    overrides = []
    current = score

    # O6: Catalyst boost (applied first)
    if abs(catalyst_sentiment) > config["catalyst_sentiment_threshold"]:
        before = current
        direction = 1.0 if catalyst_sentiment > 0 else -1.0
        if direction * current > 0:  # boost only if score aligns with catalyst
            current *= config["catalyst_boost_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O6", tier="soft",
            condition=f"catalyst_sentiment={catalyst_sentiment:.2f}",
            action=f"score * {config['catalyst_boost_multiplier']}",
            score_before=before, score_after=current,
        ))

    # O1a/O2a: Funding rate soft penalties
    if funding_rate > config["funding_soft_threshold"] and current > 0:
        before = current
        current *= config["soft_penalty_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O1a", tier="soft",
            condition=f"funding={funding_rate:.6f} > {config['funding_soft_threshold']}",
            action=f"score * {config['soft_penalty_multiplier']}",
            score_before=before, score_after=current,
        ))
    elif funding_rate < -config["funding_soft_threshold"] and current < 0:
        before = current
        current *= config["soft_penalty_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O2a", tier="soft",
            condition=f"funding={funding_rate:.6f} < -{config['funding_soft_threshold']}",
            action=f"score * {config['soft_penalty_multiplier']}",
            score_before=before, score_after=current,
        ))

    # O3a/O4a: NUPL soft penalties
    if nupl > config["nupl_soft_high"] and current > 0:
        before = current
        current *= config["soft_penalty_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O3a", tier="soft",
            condition=f"nupl={nupl:.3f} > {config['nupl_soft_high']}",
            action=f"score * {config['soft_penalty_multiplier']}",
            score_before=before, score_after=current,
        ))
    elif nupl < config["nupl_soft_low"] and current < 0:
        before = current
        current *= config["soft_penalty_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O4a", tier="soft",
            condition=f"nupl={nupl:.3f} < {config['nupl_soft_low']}",
            action=f"score * {config['soft_penalty_multiplier']}",
            score_before=before, score_after=current,
        ))

    # O5: Timeframe opposition
    if tf_opposition:
        before = current
        current *= config["tf_opposition_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O5", tier="soft",
            condition="4h_opposes_signal",
            action=f"score * {config['tf_opposition_multiplier']}",
            score_before=before, score_after=current,
        ))

    # Hard clamps (applied after all soft multipliers)
    # O1b: Extreme positive funding
    if funding_rate > config["funding_hard_threshold"] and current > 0:
        before = current
        current = 0.0
        overrides.append(OverrideEvent(
            rule_id="O1b", tier="hard",
            condition=f"funding={funding_rate:.6f} > {config['funding_hard_threshold']}",
            action="clamp to max 0",
            score_before=before, score_after=current,
        ))
    # O2b: Extreme negative funding
    elif funding_rate < -config["funding_hard_threshold"] and current < 0:
        before = current
        current = 0.0
        overrides.append(OverrideEvent(
            rule_id="O2b", tier="hard",
            condition=f"funding={funding_rate:.6f} < -{config['funding_hard_threshold']}",
            action="clamp to min 0",
            score_before=before, score_after=current,
        ))

    # O3b: Extreme NUPL high
    if nupl > config["nupl_hard_high"] and current > 0:
        before = current
        current = 0.0
        overrides.append(OverrideEvent(
            rule_id="O3b", tier="hard",
            condition=f"nupl={nupl:.3f} > {config['nupl_hard_high']}",
            action="clamp to max 0",
            score_before=before, score_after=current,
        ))
    # O4b: Extreme NUPL low
    elif nupl < config["nupl_hard_low"] and current < 0:
        before = current
        current = 0.0
        overrides.append(OverrideEvent(
            rule_id="O4b", tier="hard",
            condition=f"nupl={nupl:.3f} < {config['nupl_hard_low']}",
            action="clamp to min 0",
            score_before=before, score_after=current,
        ))

    return {"final_score": current, "overrides_fired": overrides}


def make_optimized_trading_decision(
    asset: str,
    scores: dict,
    weights: dict,
    thresholds: dict,
    override_inputs: dict,
    override_config: dict,
) -> CompositeScore:
    """Full composite scoring pipeline: weighted sum -> overrides -> decision."""
    raw = compute_weighted_sum(
        technical=scores.get("technical", 0),
        derivatives=scores.get("derivatives", 0),
        on_chain=scores.get("on_chain", 0),
        mtf=scores.get("multi_timeframe", 0),
        sentiment=scores.get("sentiment", 0),
        weights=weights,
    )

    override_result = apply_overrides(
        score=raw,
        funding_rate=override_inputs.get("funding_rate", 0),
        nupl=override_inputs.get("nupl", 0.5),
        tf_opposition=override_inputs.get("tf_opposition", False),
        catalyst_sentiment=override_inputs.get("catalyst_sentiment", 0),
        config=override_config,
    )

    final = override_result["final_score"]
    buy_t = thresholds.get("buy_default", 0.3)
    sell_t = thresholds.get("sell_default", 0.3)

    if final > buy_t:
        decision = "BUY"
    elif final < -sell_t:
        decision = "SELL"
    else:
        decision = "HOLD"

    return CompositeScore(
        asset=asset,
        technical_score=scores.get("technical", 0),
        derivatives_score=scores.get("derivatives", 0),
        on_chain_score=scores.get("on_chain", 0),
        mtf_score=scores.get("multi_timeframe", 0),
        sentiment_score=scores.get("sentiment", 0),
        raw_composite=raw,
        final_score=final,
        overrides_fired=override_result["overrides_fired"],
        decision=decision,
    )
