# derivatives

Derivatives market data collection and scoring. Collects funding rates, open interest, and long/short ratios from multiple exchanges, then converts them into a normalized signal in [-1, +1].

## Files

### collectors.py

Three collector classes, all implementing the `BaseCollector` interface (`collect(assets)` and `poll_interval_seconds()`). Collectors never write to the database directly -- the orchestrator calls `collect()` and passes results to `DataStore`.

**Symbol mapping:**
- Universe format: `"BTC/USD"` (base asset extracted as `"BTC"`)
- Binance: `"BTCUSDT"`
- Bybit: `"BTCUSDT"`
- Coinalyze: `"BTCUSD_PERP.A"`

| Collector | API | Auth | Data Collected | Poll Interval |
|-----------|-----|------|----------------|---------------|
| `BinanceCollector` | `https://fapi.binance.com` | None | Funding rates (`/fapi/v1/fundingRate`), Open interest (`/fapi/v1/openInterest`) | 300s |
| `BybitCollector` | `https://api.bybit.com` | None | Funding rates (`/v5/market/funding/history`), Open interest (`/v5/market/open-interest`) | 300s |
| `CoinalyzeCollector` | `https://api.coinalyze.net/v1` | API key (header) | Funding rates, Open interest, Long/short ratios (`/long-short-ratio-history`) | 300s |

Each `collect()` method returns a dict with keys `"funding_rates"`, `"open_interest"`, and optionally `"long_short_ratio"`, each containing a list of dicts ready for `DataStore` persistence.

### models.py

**FundingSnapshot** -- Single funding rate observation from one exchange. Rate stored as decimal fraction (0.01% = 0.0001).

**OISnapshot** -- Open interest snapshot from one exchange. Contains both native units and USD value.

**LongShortRatio** -- Long/short ratio from an aggregator. Ratio > 1 means more longs than shorts.

**DerivativesSignal** -- Combined derivatives signal for one asset:
- `funding_score`, `oi_divergence_score`, `long_short_score` (each in [-1, 1])
- `combined_score` -- weighted combination using config sub-weights
- `from_sub_scores()` class method normalizes weights and clamps to [-1, 1]

### processors.py

Scoring functions that convert raw market data into normalized signals:

**`score_funding_rate(rate, cap=0.002)`**
- Contrarian: positive funding (overcrowded longs) yields negative score
- Formula: `-rate / cap`, clamped to [-1, 1]

**`score_oi_divergence(oi_change_pct, price_change_pct)`**
- Rising OI + rising price = trend confirmation (positive)
- Rising OI + falling price = bearish continuation (negative)
- Falling OI = deleveraging, muted signal (scaled by 0.3)

**`score_long_short_ratio(ratio, extreme_threshold=2.0)`**
- Contrarian: high ratio (many longs) yields negative score
- Uses log-normalized inversion: `-log(ratio) / log(threshold)`

**`aggregate_funding_rate_oi_weighted(rates)`**
- OI-weighted average funding rate across exchanges
- Falls back to simple average if OI data is missing

**`generate_derivatives_signal(asset, ...)`**
- Combines all sub-scores using configured weights
- Default weights: funding=0.4, oi_divergence=0.35, long_short=0.25
