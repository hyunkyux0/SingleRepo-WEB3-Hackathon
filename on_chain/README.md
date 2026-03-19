# on_chain

On-chain analytics collection and scoring. Collects daily metrics from CoinMetrics and real-time whale transfers from Etherscan, then produces a combined on-chain signal in [-1, +1].

## Files

### collectors.py

**CoinMetricsCollector**
- API: `https://community-api.coinmetrics.io/v4` (Community API, no key required)
- Rate limit: 10 requests per 6 seconds
- Poll interval: 86400s (once daily)
- Runtime coverage check: queries the CoinMetrics catalog to discover which assets are available, caches the result
- Collects daily metrics: `FlowInExNtv`, `FlowOutExNtv`, `AdrActCnt`, `CapMVRVCur`
- Computes NUPL from MVRV: `nupl = 1 - 1/mvrv` (when mvrv > 0)

**EtherscanCollector**
- API: `https://api.etherscan.io/api` (requires free API key)
- Rate limit: 3 calls/sec, 100K/day
- Poll interval: 300s (5 minutes)
- Covers ETH-ecosystem tokens only (BTC, SOL, etc. do not get whale tracking)
- Uses `tokentx` endpoint to monitor ERC-20 transfers to/from known exchange addresses
- Exchange address labels sourced from the `brianleect/etherscan-labels` repository
- Classifies transfers as `to_exchange` (sell pressure) or `from_exchange` (accumulation)
- Default minimum transfer threshold: $1,000,000 USD

### models.py

**ExchangeFlow** -- Daily exchange flow data with computed `netflow` property (inflow - outflow).

**WhaleTransfer** -- Single large transfer with direction (`to_exchange`, `from_exchange`, `unknown`) and optional `exchange_label`.

**OnChainDaily** -- Daily on-chain metrics: exchange flows, MVRV, NUPL, active addresses.

**OnChainSignal** -- Combined on-chain signal for one asset:
- `exchange_flow_score`, `nupl_score`, `active_addr_score`, `whale_score` (each in [-1, 1])
- `combined_score` -- weighted combination, with weight renormalization when whale data is unavailable
- `confidence` -- 0.8 if any data is present, 0.0 otherwise
- `from_sub_scores()` class method handles optional whale score by renormalizing weights

### processors.py

Scoring functions:

**`score_exchange_flow(netflow, avg_30d, std_30d)`**
- Net inflow (positive) = selling pressure = negative score
- Normalized by 30-day standard deviation (z-score / 3)
- Inverted: high inflow produces negative signal

**`score_nupl(nupl)`**
- NUPL >= 0.75 (euphoria) = -1.0 (cycle top risk)
- NUPL <= -0.25 (capitulation) = +1.0 (cycle bottom opportunity)
- Linear interpolation between

**`score_active_addresses(growth_rate_30d)`**
- Growth rate * 5.0, clamped to [-1, 1]
- 10% growth rate --> +0.5 score

**`score_whale_activity(to_exchange_usd, from_exchange_usd, scale=10M)`**
- Net direction: from_exchange - to_exchange
- Normalized by scale factor (default $10M)
- Net accumulation (from exchange) = positive signal

**`generate_on_chain_signal(asset, ...)`**
- Combines all sub-scores using configured weights
- Default weights: exchange_flow=0.3, nupl=0.25, active_addresses=0.15, whale_activity=0.3
- When whale data is unavailable (non-ETH assets), whale weight is redistributed to other components
