# composite

Combines all signal sources (technical, derivatives, on-chain, multi-timeframe, sentiment) into final BUY/SELL/HOLD trading decisions per asset. Implements a normalized weighted sum with a two-tier override system.

## Files

### adapters.py

**`sector_signal_to_asset_score(asset, signal_set, sector_map)`**

Converts sector-level sentiment signals into per-asset scores.

1. Looks up the asset's primary sector in `sector_map`
2. Extracts the corresponding `SectorSignal` from the `SectorSignalSet`
3. For dual-routed tokens (BTC, NEAR), includes the secondary sector signal at 50% weight
4. Propagates catalyst status from secondary sector if primary has no active catalyst

Returns a dict with: `sentiment`, `momentum`, `confidence`, `sector`, `catalyst_active`, `primary_sentiment`, `secondary_sentiment`.

### scorer.py

Three core functions implementing the composite scoring pipeline:

**`compute_weighted_sum(technical, derivatives, on_chain, mtf, sentiment, weights)`**

Normalized weighted sum of all sub-scores. Weights are divided by their sum to guarantee output in [-1, +1].

```
score = (tech * w_tech + deriv * w_deriv + chain * w_chain + mtf * w_mtf + sent * w_sent) / sum(weights)
```

Default weights from `composite_config.json`: technical=0.35, derivatives=0.25, on_chain=0.15, multi_timeframe=0.10, sentiment=0.15.

**`apply_overrides(score, funding_rate, nupl, tf_opposition, catalyst_sentiment, config)`**

Two-tier override system applied in this order:

| Rule | Tier | Condition | Action |
|------|------|-----------|--------|
| O6 | Soft | \|catalyst_sentiment\| > threshold AND score aligns with catalyst | score * catalyst_boost_multiplier (1.5x) |
| O1a | Soft | funding > soft_threshold (0.001) AND score > 0 | score * soft_penalty_multiplier (0.2x) |
| O2a | Soft | funding < -soft_threshold AND score < 0 | score * soft_penalty_multiplier (0.2x) |
| O3a | Soft | NUPL > soft_high (0.75) AND score > 0 | score * soft_penalty_multiplier (0.2x) |
| O4a | Soft | NUPL < soft_low (0.0) AND score < 0 | score * soft_penalty_multiplier (0.2x) |
| O5 | Soft | 4h timeframe opposes signal | score * tf_opposition_multiplier (0.5x) |
| O1b | Hard | funding > hard_threshold (0.002) AND score > 0 | clamp to 0 |
| O2b | Hard | funding < -hard_threshold AND score < 0 | clamp to 0 |
| O3b | Hard | NUPL > hard_high (0.90) AND score > 0 | clamp to 0 |
| O4b | Hard | NUPL < hard_low (-0.25) AND score < 0 | clamp to 0 |

Soft multipliers stack multiplicatively. Hard clamps are applied after all soft multipliers.

**`make_optimized_trading_decision(asset, scores, weights, thresholds, override_inputs, override_config)`**

Full pipeline: weighted sum, then overrides, then threshold-based decision:
- `final_score > buy_threshold (0.3)` --> BUY
- `final_score < -sell_threshold (0.3)` --> SELL
- Otherwise --> HOLD

### models.py

**OverrideEvent** -- Record of a single override rule firing:
- `rule_id` (e.g., "O1a"), `tier` ("soft"/"hard"), `condition`, `action`
- `score_before`, `score_after`

**CompositeScore** -- Full scoring result for one asset:
- Individual sub-scores: `technical_score`, `derivatives_score`, `on_chain_score`, `mtf_score`, `sentiment_score` (all in [-1, 1])
- `raw_composite` (weighted sum before overrides)
- `final_score` (after overrides)
- `overrides_fired` (list of OverrideEvent)
- `decision` ("BUY", "SELL", "HOLD")
- `timestamp`

**TradingDecision** -- Simplified output for the execution layer:
- `asset`, `decision`, `score`, `confidence`
