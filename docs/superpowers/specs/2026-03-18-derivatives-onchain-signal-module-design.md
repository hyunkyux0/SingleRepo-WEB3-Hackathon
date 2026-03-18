# Derivatives & On-Chain Signal Module — Design Specification

> **Date**: 2026-03-18
> **Status**: Approved
> **Scope**: Modular derivatives signal generator (Phase 2) and on-chain analytics signal generator (Phase 3) for a crypto trading bot. Produces per-asset sub-scores consumed by a composite scorer alongside technical and sentiment signals.

---

## 1. Context & Constraints

| Constraint | Value |
|-----------|-------|
| Capital | $1M USD |
| Duration | 10-day trading window |
| Positions | Long-only (buy & sell), no limit on count |
| Trading frequency | Any time, 5-minute intervals |
| Universe | 67 tokens (defined in `config/asset_universe.json`) |
| Active assets | Dynamic top ~30-40 by open interest (assets without perps data excluded with logged reason) |
| API budget | $0/month — all data sources are free tier |
| Execution exchange | Roostoo (paper trading) |
| Data sources (read-only) | Binance Futures, Bybit v5, Coinalyze, CoinMetrics Community, Etherscan |

### What These Modules Own

**Derivatives module:**
- Funding rate collection and aggregation across exchanges
- Open interest tracking and OI/price divergence detection
- Long/short ratio monitoring
- Output of `DerivativesSignal` per asset every 5 minutes

**On-chain module:**
- Exchange net flow monitoring (daily, CoinMetrics)
- Whale transfer tracking (near real-time, Etherscan)
- NUPL computation from MVRV
- Active address trend tracking
- Output of `OnChainSignal` per asset every 5 minutes (blending daily + real-time data)

### What These Modules Do NOT Own

- Position sizing, order execution, portfolio risk management
- Signal combination with technical/sentiment signals (owned by composite scorer)
- News ingestion or LLM classification (owned by sentiment module)
- The broader trading strategy design

### Integration With Existing System

These modules integrate with the sector sentiment module (spec: `2026-03-18-sector-sentiment-signal-module-design.md`). Both feed into a unified composite scorer. See `docs/directory/unified_directory.md` for the full integrated directory structure.

---

## 2. Data Sources & API Details

### Unit Convention

All funding rates are stored and compared as **decimal fractions** (e.g., 0.01% is stored as `0.0001`). This convention applies to database storage, config files, and override rule evaluation. The override table in Section 7 uses percentage notation for readability but all implementation uses decimal fractions.

### Phase 2: Derivatives Data (Free, 5-Minute Polling)

| API | Auth | Rate Limit | Data Provided |
|-----|------|------------|---------------|
| **Binance Futures** (`fapi.binance.com`) | No key needed | 2,400 weight/min | Funding rates (`/fapi/v1/fundingRate`), OI (`/fapi/v1/openInterest`) |
| **Bybit v5** (`api.bybit.com`) | No key needed | 600 req/5s | Funding rates (`/v5/market/funding/history`), OI (`/v5/market/open-interest`) |
| **Coinalyze** (`api.coinalyze.net`) | Free key required | 40 req/min | Aggregated OI, funding rates, long/short ratio, predicted funding |

Note: Liquidation event endpoints exist on Binance (`/fapi/v1/allForceOrders`) and Coinalyze (`/v1/liquidation-history`) but are **not consumed by any signal generator in the current phase**. They are collected speculatively for monitoring and future use (see Section 12).

At 5-minute polling with ~35 active assets: ~420 requests/hour across all sources — well within all rate limits.

### Phase 3: On-Chain Data (Free, Mixed Frequency)

| API | Auth | Rate Limit | Data Provided | Frequency |
|-----|------|------------|---------------|-----------|
| **CoinMetrics Community** (`community-api.coinmetrics.io/v4/`) | No key needed | 10 req/6s | Exchange inflow/outflow (`FlowInExNtv`/`FlowOutExNtv`), MVRV (`CapMVRVCur`), active addresses (`AdrActCnt`) | Daily |
| **Etherscan** (`api.etherscan.io`) | Free key required | 3 calls/sec, 100K/day | ERC-20 token transfers, address transaction history | Every 5 min |

**CoinMetrics coverage note**: CoinMetrics free tier primarily covers large-cap assets. At startup, run a coverage check to record which assets have CoinMetrics data. Assets without coverage receive on-chain score = 0 with confidence = 0 (neutral, not penalized). This is analogous to the perps discovery in Section 3.

### Price Data (Existing, Not Owned By This Spec)

| API | Auth | Rate Limit | Data Provided | Frequency |
|-----|------|------------|---------------|-----------|
| **Kraken** (`api.kraken.com`) | No key needed | ~15 req/min | OHLCVT candles (`/0/public/OHLC`), ticker data | Every 5 min |

Kraken OHLC collection is owned by the existing `technicals/` module (migrated from `sma-prediction/prices.py`). This spec consumes OHLC data from SQLite but does not own its collection.

### Binance + Bybit Aggregation Strategy

- **Funding rate**: OI-weighted average across exchanges (exchange with heavier OI is more representative)
- **Open interest**: Sum across exchanges for total market OI
- **Coinalyze**: Cross-check and fallback if one exchange API is down

---

## 3. Asset Discovery & Registry

### On Startup and Once Daily

1. Query Binance Futures + Bybit for list of available perpetual contracts
2. Intersect with `config/asset_universe.json`
3. Rank by open interest volume
4. Select top N (configurable, default ~30-40)
5. Assets in universe without perps data → excluded with a logged reason in `asset_registry` table
6. Small/illiquid assets with missing data → excluded rather than imputed. Document exclusion reason.
7. Store active asset list in `asset_registry` table

### Asset Registry Table

```sql
asset_registry (
    asset TEXT PRIMARY KEY,
    has_perps BOOLEAN,
    exchange_sources TEXT,       -- JSON: ["binance", "bybit"]
    oi_rank INTEGER,
    excluded_reason TEXT,        -- NULL if active, reason string if dropped
    updated_at TIMESTAMP
)
```

---

## 4. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Data Collectors                         │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌────────────┐  │
│  │ Binance   │ │ Bybit     │ │Coinalyze  │ │ CoinMetrics│  │
│  │ Futures   │ │ v5        │ │(free key) │ │ Community  │  │
│  │ -funding  │ │ -funding  │ │-agg OI    │ │ -ex flows  │  │
│  │ -OI       │ │ -OI       │ │-agg fund  │ │ -MVRV/NUPL │  │
│  │ -liq evts │ │ -liq evts │ │-long/short│ │ -active adr│  │
│  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └──────┬─────┘  │
│        │              │             │              │         │
│  ┌─────┴──────┐                              ┌────┴───────┐ │
│  │ Etherscan  │                              │  Kraken    │ │
│  │ -whale txs │                              │  -OHLC     │ │
│  │ -large xfr │                              │  -price    │ │
│  └─────┬──────┘                              └────┬───────┘ │
└────────┼──────────────────────────────────────────┼─────────┘
         │                                          │
         ▼                                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    SQLite Cache Layer                        │
│           data/trading_bot.db (single database)             │
│                                                             │
│  funding_rates │ open_interest │ long_short_ratio           │
│  on_chain_daily │ whale_transfers │ ohlc_data               │
│  asset_registry │ signal_log │ articles                     │
└────────┬──────────────────────────────────────────┬─────────┘
         │                                          │
         ▼                                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Signal Generators                         │
│  ┌────────────┐ ┌──────────────┐ ┌───────────┐ ┌─────────┐ │
│  │ Technical  │ │ Derivatives  │ │ On-Chain  │ │Sentiment│ │
│  │ (-1 to +1) │ │ (-1 to +1)   │ │ (-1 to +1)│ │(-1 to+1)│ │
│  │            │ │              │ │           │ │         │ │
│  │ -SMA/BB   │ │ -funding     │ │ -ex flow  │ │ -sector │ │
│  │ -regime   │ │ -OI diverg.  │ │ -whale    │ │ -news   │ │
│  │ -multi-TF │ │ -long/short  │ │ -NUPL     │ │ -catlyst│ │
│  │ (swappabl)│ │              │ │ -addr grw │ │         │ │
│  └─────┬──────┘ └──────┬───────┘ └─────┬─────┘ └────┬────┘ │
└────────┼───────────────┼───────────────┼────────────┼───────┘
         │               │               │            │
         ▼               ▼               ▼            ▼
┌─────────────────────────────────────────────────────────────┐
│                   Composite Scorer                          │
│                                                             │
│  weighted_sum = w_tech * technical + w_deriv * derivatives  │
│               + w_onchain * on_chain + w_mtf * multi_tf     │
│               + w_sentiment * sentiment                     │
│                                                             │
│  + two-tier override rules (soft penalty / hard block)      │
│  → final_score (-1 to +1)                                   │
│  → BUY (>threshold) / SELL (<-threshold) / HOLD             │
└─────────────────────────────────────────────────────────────┘
```

### Key Properties

- Each signal generator reads only from SQLite, outputs a single float (-1 to +1)
- Technical module is explicitly marked swappable — same interface, internals can change
- Sentiment module outputs `SectorSignalSet`; `composite/adapters.py` converts to per-asset score via sector map
- Weights and thresholds are optimizable via grid search
- Override rules are a separate, auditable list evaluated after the weighted sum

---

## 5. Data Collector Contract

Each collector implements the same interface:

```python
class BaseCollector:
    def collect(self, assets: list[str]) -> list[dict]  # fetch and return rows
    def poll_interval_seconds(self) -> int               # how often to call
```

All collectors write to SQLite via `utils/db.py` DataStore. Signal generators never call APIs directly.

**Note**: The `BaseCollector` contract applies to derivatives and on-chain modules. The sentiment module exposes a `SentimentPipeline.tick()` interface instead (see sentiment spec Section 6). The orchestrator calls both interfaces but they are not required to share a base class.

---

## 6. Signal Generators

### 6a. Derivatives Signal Generator → (-1 to +1)

**Inputs from SQLite**: funding rates, open interest, long/short ratio

| Sub-signal | Logic | Score range |
|-----------|-------|-------------|
| **Funding rate** | Normalized: 0 = neutral. Positive funding → negative score (overcrowded long = bearish risk). Negative funding → positive score (overcrowded short = bullish). Scaled linearly, capped at extremes. | -1 to +1 |
| **OI + price divergence** | Rising OI + rising price = trend confirmation (+). Rising OI + falling price = bearish continuation (-). Falling OI = deleveraging, reduces conviction toward 0. | -1 to +1 |
| **Long/short ratio** | From Coinalyze. Extreme long bias → bearish contrarian signal. Extreme short bias → bullish contrarian. | -1 to +1 |

**Combination**: Weighted average of sub-signals → single derivatives score (-1 to +1). Sub-weights tunable via optimization.

### 6b. On-Chain Signal Generator → (-1 to +1)

**Inputs from SQLite**: exchange flows, MVRV/NUPL, active addresses, whale transfers

| Sub-signal | Logic | Score range |
|-----------|-------|-------------|
| **Exchange net flow** | Net inflow (selling pressure) → negative. Net outflow (accumulation) → positive. Normalized by 30-day moving average to detect unusual flows. | -1 to +1 |
| **NUPL** (from MVRV) | `NUPL = 1 - 1/MVRV`. Above 0.75 → euphoria, score goes negative (cycle top risk). Below 0 → capitulation, score goes positive (cycle bottom opportunity). Linear interpolation between. | -1 to +1 |
| **Active address trend** | 30-day growth rate. Growing → positive. Declining → negative. Normalized. | -1 to +1 |
| **Whale activity** | Large transfers TO exchanges → negative (sell signal). Large transfers FROM exchanges → positive (accumulation). Measured as net direction of transfers above a size threshold (e.g., >$1M). | -1 to +1 |

**Combination**: Weighted average → single on-chain score (-1 to +1).

**Missing data handling**:
- Whale activity (Etherscan) only covers ERC-20 tokens. For non-ETH assets (BTC, SOL, etc.), whale sub-signal defaults to 0 (neutral) and remaining sub-weights are **renormalized** so the on-chain score isn't permanently muted for major assets.
- CoinMetrics may not cover all assets (see Section 2 coverage note). Assets without CoinMetrics data receive on-chain score = 0, confidence = 0.

**Mixed frequency handling**: Exchange flows, NUPL, and active addresses refresh daily (CoinMetrics). Whale activity refreshes every 5 min (Etherscan). The generator blends stale daily values with fresh whale data — daily values are held constant between refreshes.

### 6c. Technical Signal Generator → (-1 to +1) *(context only — owned by technicals/ module)*

Current implementation (SMA + Bollinger Bands + regime detection) wrapped to output -1 to +1 instead of BUY/SELL/HOLD. Marked as **swappable** — the only contract is:

```python
def generate(self, asset: str) -> float  # -1 to +1
```

### 6d. Multi-Timeframe Sub-Score *(context only — owned by technicals/ module)*

Computes trend direction on 5m, 1h, 4h candles:
- 3/3 aligned with signal direction → 1.0
- 2/3 aligned → 0.5
- 1/3 or 0/3 → 0.0

Feeds into composite scorer as a soft weight (per Q7 decision).

### 6e. Sentiment Signal *(context only — owned by sentiment module + composite/adapters.py)*

The sentiment module outputs `SectorSignalSet` (per-sector signals). `composite/adapters.py` converts to per-asset score:
1. Look up asset's primary sector in `config/sector_map.json`
2. Use that sector's sentiment signal as the asset's sentiment score
3. If asset has a secondary sector, blend at 50% weight

---

## 7. Composite Scorer

### Weighted Sum

```
final_score = w_tech * technical_score
            + w_deriv * derivatives_score
            + w_onchain * on_chain_score
            + w_mtf * multi_timeframe_score
            + w_sentiment * sentiment_score
```

- All weights are positive floats, optimizable via grid search
- Default starting weights (to be tuned): `w_tech=0.35, w_deriv=0.25, w_onchain=0.15, w_mtf=0.10, w_sentiment=0.15`
- **Normalization**: Weights are normalized at runtime by dividing each by the sum of all weights (`w_i / sum(w)`). This guarantees the weighted sum stays in [-1, +1] even after grid search changes individual weights independently.
- Final score range: -1 to +1

### Decision Thresholds

```
final_score > +buy_threshold  → BUY
final_score < -sell_threshold → SELL
otherwise                     → HOLD
```

- Both `buy_threshold` and `sell_threshold` are stored as **positive magnitudes** (e.g., `0.3`). The negation is applied in the comparison: `score < -sell_threshold`.
- Per-asset tunable parameters
- Asymmetric thresholds allowed (e.g., higher bar for buys than sells)

### Two-Tier Override Rules

Evaluated **after** the weighted sum. Two tiers: soft penalty (score × multiplier) and hard block (clamp to 0). Soft overrides handle elevated risk; hard overrides handle extreme "building is on fire" conditions.

| # | Condition | Tier | Action | Rationale |
|---|-----------|------|--------|-----------|
| O1a | Funding rate > +0.10% | Soft | Score × 0.2 (penalize buys) | Overcrowded longs, elevated liquidation risk |
| O1b | Funding rate > +0.20% | Hard | Clamp to max 0 (block buys) | Extreme leverage, liquidation cascade imminent |
| O2a | Funding rate < -0.10% | Soft | Score × 0.2 (penalize sells) | Overcrowded shorts, squeeze risk |
| O2b | Funding rate < -0.20% | Hard | Clamp to min 0 (block sells) | Extreme short crowding, squeeze imminent |
| O3a | NUPL > 0.75 | Soft | Score × 0.2 (penalize buys) | Market euphoria, elevated cycle top risk |
| O3b | NUPL > 0.90 | Hard | Clamp to max 0 (block buys) | Extreme euphoria, historically precedes major corrections |
| O4a | NUPL < 0 | Soft | Score × 0.2 (penalize sells) | Market capitulation, elevated cycle bottom signal |
| O4b | NUPL < -0.25 | Hard | Clamp to min 0 (block sells) | Extreme capitulation, historically precedes recoveries |
| O5 | 4h trend strongly opposes signal | Soft | Score × 0.5 | Prevents counter-trend entries on high timeframe |
| O6 | Catalyst detected (high magnitude, \|sentiment\| > 0.7) | Soft | Score × 1.5 in catalyst direction | High-impact news should accelerate entry |

**Override stacking semantics:**
- Overrides are evaluated in order
- Soft multipliers apply **multiplicatively** to the current score (e.g., O1a then O3a: `score × 0.2 × 0.2 = score × 0.04`)
- Hard clamps apply **after** all soft multipliers
- O6 (catalyst boost) applies **before** other soft penalties, so a catalyst in an overcrowded-funding environment results in `score × 1.5 × 0.2` — the catalyst signal is acknowledged but still dampened by risk
- Every override trigger is logged with timestamp, asset, original score, and adjusted score
- All thresholds stored in `config/composite_config.json`, tunable via optimization

### Function Signature

```python
def make_optimized_trading_decision(
    asset: str,
    weights: dict,          # w_tech, w_deriv, w_onchain, w_mtf, w_sentiment
    thresholds: dict,       # buy_threshold, sell_threshold
    override_config: dict   # soft/hard thresholds for each override
) -> tuple[str, float, dict]
    # returns (BUY/SELL/HOLD, final_score, debug_log)
```

The `debug_log` dict contains each sub-score, which overrides fired, pre/post-override scores, and per-sub-signal breakdowns.

---

## 8. SQLite Schema

### Database: `data/trading_bot.db`

```sql
-- Dynamic asset list, refreshed daily
CREATE TABLE asset_registry (
    asset TEXT PRIMARY KEY,
    has_perps BOOLEAN,
    exchange_sources TEXT,       -- JSON: ["binance", "bybit"]
    oi_rank INTEGER,
    excluded_reason TEXT,        -- NULL if active, reason if dropped
    updated_at TIMESTAMP
);

-- 5-min derivatives data
CREATE TABLE funding_rates (
    asset TEXT,
    timestamp TIMESTAMP,
    exchange TEXT,               -- binance, bybit, coinalyze_agg
    rate REAL,
    PRIMARY KEY (asset, timestamp, exchange)
);

CREATE TABLE open_interest (
    asset TEXT,
    timestamp TIMESTAMP,
    exchange TEXT,
    oi_value REAL,
    oi_usd REAL,
    PRIMARY KEY (asset, timestamp, exchange)
);

CREATE TABLE long_short_ratio (
    asset TEXT,
    timestamp TIMESTAMP,
    ratio REAL,
    source TEXT,
    PRIMARY KEY (asset, timestamp, source)
);

-- Daily on-chain data (CoinMetrics)
CREATE TABLE on_chain_daily (
    asset TEXT,
    date DATE,
    exchange_inflow_native REAL,
    exchange_outflow_native REAL,
    exchange_netflow_native REAL,
    mvrv REAL,
    nupl_computed REAL,         -- 1 - 1/mvrv
    active_addresses INTEGER,
    PRIMARY KEY (asset, date)
);

-- Near real-time whale transfers (Etherscan)
CREATE TABLE whale_transfers (
    tx_hash TEXT PRIMARY KEY,
    asset TEXT,
    timestamp TIMESTAMP,
    from_address TEXT,
    to_address TEXT,
    value_usd REAL,
    direction TEXT,             -- 'to_exchange', 'from_exchange', 'unknown'
    exchange_label TEXT         -- from etherscan-labels
);

-- OHLC price data (multiple intervals)
CREATE TABLE ohlc_data (
    asset TEXT,
    timestamp TIMESTAMP,
    interval TEXT,              -- '5m', '1h', '4h'
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    vwap REAL,
    PRIMARY KEY (asset, timestamp, interval)
);

-- Signal audit log
CREATE TABLE signal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset TEXT,
    timestamp TIMESTAMP,
    technical_score REAL,
    derivatives_score REAL,
    on_chain_score REAL,
    mtf_score REAL,
    sentiment_score REAL,
    raw_composite REAL,         -- before overrides
    final_score REAL,           -- after overrides
    overrides_fired TEXT,       -- JSON list
    decision TEXT,              -- BUY/SELL/HOLD
    metadata TEXT               -- JSON: sub-signal breakdown
);
```

Note: The `articles` table from the sentiment module spec is also in this database. See `2026-03-18-sector-sentiment-signal-module-design.md` Section 3 for its schema.

### DB Abstraction (`utils/db.py`)

```python
class DataStore:
    def __init__(self, db_path: str = "data/trading_bot.db")

    # Derivatives
    def save_funding_rates(self, rows: list[dict])
    def get_latest_funding(self, asset: str) -> dict
    def save_open_interest(self, rows: list[dict])
    def get_oi_history(self, asset: str, lookback_hours: int) -> list[dict]
    def save_long_short_ratio(self, rows: list[dict])

    # On-chain
    def save_on_chain_daily(self, rows: list[dict])
    def get_on_chain(self, asset: str, lookback_days: int) -> list[dict]
    def save_whale_transfers(self, rows: list[dict])
    def get_recent_whale_transfers(self, asset: str, since: datetime) -> list[dict]

    # Asset registry
    def save_asset_registry(self, rows: list[dict])
    def get_active_assets(self) -> list[str]

    # OHLC
    def save_ohlc(self, rows: list[dict])
    def get_ohlc(self, asset: str, interval: str, lookback: int) -> list[dict]

    # Signal log
    def log_signal(self, entry: dict)

    # Maintenance
    def prune_old_data(self)
```

When migrating to AWS, replace `DataStore` internals without touching collectors or signal generators.

### Data Retention

| Data | Retention | Reason |
|------|-----------|--------|
| Derivatives (5-min) | 30 days | Recent history sufficient for signal computation |
| On-chain daily | 1 year | Cycle indicators need long lookback |
| Whale transfers | 90 days | Medium-term trend context |
| OHLC | 1 year | Backtesting |
| Signal log | Indefinite | Small rows, valuable for backtesting and audit |

---

## 9. Orchestrator Tick Schedule

`pipeline/orchestrator.py` manages all modules in a unified loop:

| Frequency | Modules Ticked |
|-----------|---------------|
| Every 5 min | Derivatives collectors (Binance, Bybit, Coinalyze), Kraken OHLC, Etherscan whale transfers, Sentiment fetch + fast-path, All signal generators, Composite scorer |
| Every 30 min | Sentiment batch LLM processing |
| Once daily | CoinMetrics on-chain pull, Asset discovery refresh, Data pruning (retention policy) |

### Tick Order (every 5 minutes)

1. **Collect**: All data collectors run (can be parallelized)
2. **Generate**: Each signal generator reads fresh data from SQLite, outputs sub-score
3. **Score**: Composite scorer combines sub-scores, applies overrides
4. **Decide**: BUY/SELL/HOLD per asset
5. **Log**: Write to `signal_log` table
6. **Execute**: Pass decisions to Roostoo execution layer

---

## 10. Polling Strategy for Mixed-Frequency Data

On-chain metrics from CoinMetrics are daily resolution. The bot polls every 5 minutes. Strategy:

1. **Once daily** (e.g., 00:05 UTC): Pull CoinMetrics data (exchange flows, MVRV, active addresses). Cache in `on_chain_daily` table.
2. **Every 5 minutes**: Pull Etherscan for real-time whale movements and large transfers.
3. **Every 5 minutes**: On-chain signal generator blends:
   - Daily values (exchange flows, NUPL, active addresses) held constant between daily refreshes
   - Real-time whale activity updated every 5 minutes
4. **Result**: Composite on-chain score updates every 5 min (driven by whale data changes) with a stable daily baseline.

This is appropriate because exchange flows, NUPL, and active addresses are inherently slow-moving cycle indicators that don't change meaningfully in 5-minute intervals.

---

## 11. Whale Tracking Implementation

### Address Labels

Use [brianleect/etherscan-labels](https://github.com/brianleect/etherscan-labels) repository — 45K+ labeled addresses across 7 EVM chains, including exchange hot/cold wallets.

### Detection Logic

1. Poll Etherscan for recent token transfers above size threshold (default: >$1M USD)
2. Match `from_address` and `to_address` against labeled exchange addresses
3. Classify direction:
   - Known wallet → known exchange address = `to_exchange` (sell pressure)
   - Known exchange address → known wallet = `from_exchange` (accumulation)
   - Neither matched = `unknown` (excluded from scoring)
4. Aggregate net direction over rolling window (default: 4 hours)

### Etherscan API Usage

- Endpoint: `api.etherscan.io/api?module=account&action=tokentx`
- Covers ERC-20 tokens (ETH ecosystem)
- For non-ETH assets (BTC, SOL, etc.): whale tracking not available via Etherscan. These assets rely on daily CoinMetrics exchange flow data only. Document this limitation.

---

## 12. Error Handling

### API Failures

| Scenario | Behavior |
|----------|----------|
| Single exchange API down (e.g., Binance timeout) | Use data from remaining exchanges. Log warning. Coinalyze serves as cross-exchange fallback. |
| Both Binance + Bybit down simultaneously | Use Coinalyze aggregated data only. If Coinalyze also down, use most recent cached data from SQLite (stale but available). Log error. |
| Partial data (some assets returned, others not) | Process available assets normally. Missing assets use stale cached data if < 30 min old, otherwise derivatives score = 0 for that asset. |
| Rate limit hit (429 response) | Respect `Retry-After` header. Skip this tick for the affected collector. Stale cached data used until next successful poll. |
| CoinMetrics daily pull fails | Retry once after 5 min. If still failing, use previous day's cached data. Log error. |
| Etherscan rate limit or timeout | Skip whale transfer update for this tick. Previous whale data remains valid (4-hour rolling window). |

### Signal Generator Failures

| Scenario | Behavior |
|----------|----------|
| A signal generator throws an exception | That sub-score defaults to 0 (neutral). Remaining sub-scores are renormalized. Log error with stack trace. |
| All sub-scores for a category are 0 due to missing data | The category score is 0. The composite scorer still functions — this category simply contributes nothing. |

### General Principle

The system degrades gracefully: missing data produces neutral (0) scores rather than blocking the entire pipeline. Stale cached data is preferred over no data, with staleness tracked and logged.

---

## 13. Future Additions (Flagged, Not In Current Scope)

### Liquidation Heatmaps (Phase 2, Step 2.3)
- Predicting where future liquidation clusters sit requires estimating leverage positions across price levels
- CoinGlass Hobbyist ($29/month) provides this data via API
- Current scope uses free liquidation event data only (what already happened, from Binance/Bybit)
- Revisit when budget allows or CoinGlass adds a free tier

### DIY Real-Time Exchange Flows (Phase 3 Stretch Goal)
- Use Alchemy free tier webhooks on known exchange wallet addresses for real-time exchange flow tracking
- Replaces daily CoinMetrics resolution with near real-time
- Higher engineering effort, $0 cost
- Attempt after core Phases 2 & 3 are complete and stable

---

## 14. Configuration Files

### `config/derivatives_config.json`

```json
{
  "polling_interval_seconds": 300,
  "funding_rate_neutral_band": [-0.0001, 0.0001],
  "oi_lookback_periods": 12,
  "long_short_extreme_threshold": 2.0,
  "sub_weights": {
    "funding": 0.4,
    "oi_divergence": 0.35,
    "long_short": 0.25
  }
}
```

### `config/onchain_config.json`

```json
{
  "coinmetrics_poll_hour_utc": 0,
  "whale_transfer_threshold_usd": 1000000,
  "whale_rolling_window_hours": 4,
  "exchange_flow_normalization_days": 30,
  "nupl_thresholds": {
    "euphoria": 0.75,
    "capitulation": 0.0
  },
  "sub_weights": {
    "exchange_flow": 0.3,
    "nupl": 0.25,
    "active_addresses": 0.15,
    "whale_activity": 0.3
  }
}
```

### `config/composite_config.json`

```json
{
  "weights": {
    "technical": 0.35,
    "derivatives": 0.25,
    "on_chain": 0.15,
    "multi_timeframe": 0.10,
    "sentiment": 0.15
  },
  "thresholds": {
    "buy_default": 0.3,
    "sell_default": 0.3
  },
  "overrides": {
    "funding_soft_threshold": 0.001,
    "funding_hard_threshold": 0.002,
    "nupl_soft_high": 0.75,
    "nupl_hard_high": 0.90,
    "nupl_soft_low": 0.0,
    "nupl_hard_low": -0.25,
    "soft_penalty_multiplier": 0.2,
    "tf_opposition_multiplier": 0.5,
    "catalyst_boost_multiplier": 1.5,
    "catalyst_sentiment_threshold": 0.7
  }
}
```

All values are starting defaults. Intended to be optimized via grid search backtesting.

---

## 15. Dependencies (additions to requirements.txt)

```
requests>=2.28.0
pydantic>=2.0.0
coinmetrics-api-client>=2024.1
```

No additional paid services or API keys beyond what the sentiment module already requires. Binance and Bybit public endpoints need no authentication. Coinalyze and Etherscan require free API keys (registration only).

---

## 16. Build Order

Phase 2 (derivatives) and Phase 3 (on-chain) can be built in parallel since they are independent data sources feeding into the same composite scorer. The composite scorer itself should be built first as the integration point.

```
1. SQLite schema + DataStore abstraction (utils/db.py)     ← shared foundation
2. Composite scorer framework (composite/)                  ← integration point
3a. Derivatives collectors + signal generator (derivatives/) ← parallel
3b. On-chain collectors + signal generator (on_chain/)       ← parallel
3c. Technical signal wrapper (technicals/)                   ← parallel
4. Sentiment adapter (composite/adapters.py)                ← after sentiment module
5. Unified orchestrator (pipeline/orchestrator.py)          ← ties everything together
6. Backtesting + parameter optimization                     ← validate and tune
```

---

## 17. Research Foundation

| Finding | Source | Design Impact |
|---------|--------|--------------|
| Funding > +0.10% signals overcrowded longs | Crypto Market Microstructure: 24/7 Order Flow (SignalPilot) | Funding rate override thresholds |
| Rising OI + falling price = bearish continuation | Standard derivatives analysis | OI/price divergence sub-signal |
| Multi-timeframe analysis improves signal quality | Elder, 1993 — Triple Screen Trading System | Multi-TF soft weight in composite |
| Exchange net inflows correlate with selling pressure | Coin Bureau — OnChain Analysis 101 | Exchange flow sub-signal |
| NUPL > 0.75 historically precedes major corrections | Glassnode research | NUPL override thresholds |
| Active address growth signals fundamental demand | Glassnode standard metric | Active address trend sub-signal |
| CoinMetrics Community API provides free exchange flow data | Verified against live API | Primary on-chain data source at $0 |
| Etherscan free tier sufficient for whale tracking | API documentation | Whale transfer monitoring approach |
