# Signal Scoring Guide

How raw market data becomes BUY/SELL/HOLD decisions.

---

## Pipeline Overview

```
Raw Data (APIs)
    ↓
Sub-Signals (-1 to +1 each)
    ↓
Category Scores (-1 to +1 each)
    ↓
Composite Score (-1 to +1)
    ↓
Override Rules (soft penalty / hard block)
    ↓
Decision: BUY / SELL / HOLD
```

---

## 1. Derivatives Signals

### 1a. Funding Rate → "Who's paying whom in perpetual futures?"

Perpetual futures have no expiry. To keep the perp price anchored to spot, exchanges charge a funding rate every 8 hours. When longs outnumber shorts, longs pay shorts (positive funding). When shorts outnumber longs, shorts pay longs (negative funding).

| Funding Rate | What It Means | Score Direction |
|-------------|---------------|-----------------|
| +0.05% (0.0005) | Longs paying shorts, overcrowded long | Negative (bearish contrarian) |
| -0.05% (-0.0005) | Shorts paying longs, overcrowded short | Positive (bullish contrarian) |
| 0.00% | Balanced market | Neutral (0) |
| +0.20% (0.002) | Extreme long crowding, liquidation cascade risk | Capped at -1.0 |

**Formula:**
```
score = -rate / cap
cap = 0.002 (default, configurable)
clamped to [-1.0, +1.0]
```

The sign is inverted because this is a contrarian signal: when everyone is long, the smart money expects a pullback.

**Unit convention:** Funding rates are stored as decimal fractions. 0.01% = 0.0001. Config thresholds use the same convention.

### 1b. Open Interest + Price Divergence → "Is leverage confirming or diverging from price?"

Open interest = total outstanding leveraged positions (longs + shorts combined). OI alone isn't directional — the OI/price relationship tells the story.

| OI Change | Price Change | Interpretation | Score |
|-----------|-------------|----------------|-------|
| Rising | Rising | New money entering, confirming uptrend | Positive |
| Rising | Falling | New shorts piling in, bearish continuation | Negative |
| Falling | Rising | Short squeeze / deleveraging, weak conviction | Near zero |
| Falling | Falling | Long liquidation / deleveraging, weak conviction | Near zero |

**Formula:**
```
if oi_change <= 0:
    score = price_change * 0.3          # muted — deleveraging
else:
    score = oi_change * price_change * 10   # scaled interaction
clamped to [-1.0, +1.0]
```

When OI is falling, it means positions are closing — regardless of price direction, this signals declining conviction, so the score moves toward zero.

### 1c. Long/Short Ratio → "What's the crowd positioning?"

From Coinalyze. Measures the ratio of long to short positions across exchanges.

| Ratio | Meaning | Score |
|-------|---------|-------|
| 3.0 | 3x more longs than shorts | Negative (contrarian bearish) |
| 1.0 | Balanced | Neutral (~0) |
| 0.4 | 2.5x more shorts than longs | Positive (contrarian bullish) |

**Formula:** Uses log-scale for symmetry around 1.0:
```
log_ratio = ln(ratio)
score = -log_ratio / ln(extreme_threshold)
extreme_threshold = 2.0 (default)
```

### 1d. Derivatives Combined Score

```
derivatives_score = (0.4 * funding_score + 0.35 * oi_divergence_score + 0.25 * long_short_score)
```

Sub-weights are configurable in `config/derivatives_config.json`.

### 1e. Cross-Exchange Aggregation

Funding rates from Binance and Bybit are aggregated using OI-weighted average — the exchange with more open interest has more influence on the aggregated rate. Open interest is summed across exchanges for the total market view.

---

## 2. On-Chain Signals

### 2a. Exchange Net Flow → "Is crypto moving to or from exchanges?"

When large amounts of crypto flow into exchanges, it typically means holders are preparing to sell. When crypto flows out, holders are moving to cold storage (accumulation).

| Net Flow | Meaning | Score |
|----------|---------|-------|
| Positive (inflow > outflow) | Selling pressure incoming | Negative |
| Negative (outflow > inflow) | Accumulation | Positive |
| Near average | Business as usual | Near zero |

**Formula:** Normalized by 30-day statistics to detect unusual flows:
```
z_score = (netflow - avg_30d) / std_30d
score = -z_score / 3.0    # inverted, capped at ~3 sigma
```

Example with real data:
```
inflow  = 24,060 ETH
outflow = 27,418 ETH
netflow = -3,358 ETH  (more leaving exchanges → accumulation → positive score)
```

**Data source:** CoinMetrics Community API (`FlowInExNtv`, `FlowOutExNtv`). Daily resolution. Only BTC and ETH have exchange flow data on the free tier. Other assets get this sub-score as 0 with remaining weights renormalized.

### 2b. NUPL (Net Unrealized Profit/Loss) → "Where are we in the market cycle?"

NUPL measures what percentage of the total market cap is unrealized profit. It's a cycle indicator — high values mean most holders are in profit (euphoria), low values mean most are underwater (capitulation).

**Computed from MVRV:**
```
NUPL = 1 - (1 / MVRV)
where MVRV = Market Value / Realized Value
```

| NUPL | Cycle Phase | Score |
|------|-------------|-------|
| > 0.75 | Euphoria (most holders in heavy profit) | -1.0 (don't buy at the top) |
| 0.5 - 0.75 | Belief / optimism | Slightly negative |
| 0.25 - 0.5 | Mid-cycle | Near zero |
| 0 - 0.25 | Hope / early recovery | Slightly positive |
| < 0 | Capitulation (most holders underwater) | +1.0 (cycle bottom opportunity) |

**Formula:** Linear interpolation between NUPL = -0.25 (score = +1) and NUPL = 0.75 (score = -1):
```
score = 1.0 - (nupl + 0.25) / 1.0 * 2.0
clamped to [-1.0, +1.0]
```

**Data source:** CoinMetrics Community API (`CapMVRVCur`). Daily resolution. When MVRV is 0 (metric unavailable for an asset), NUPL defaults to 0 and this sub-score contributes nothing.

### 2c. Active Address Growth → "Is anyone using this chain?"

Tracks the 30-day trend in unique active addresses. Growing usage suggests fundamental demand; declining usage suggests waning interest.

| 30-Day Growth | Meaning | Score |
|--------------|---------|-------|
| +10% | Strong growth | +0.5 |
| +2% | Moderate growth | +0.1 |
| 0% | Flat | 0 |
| -10% | Declining interest | -0.5 |

**Formula:**
```
growth_rate = (today_addresses - 30d_ago_addresses) / 30d_ago_addresses
score = growth_rate * 5.0
clamped to [-1.0, +1.0]
```

**Data source:** CoinMetrics Community API (`AdrActCnt`). Daily resolution.

### 2d. Whale Activity → "What are the big wallets doing?"

Monitors large ERC-20 transfers (>$1M) to/from known exchange addresses. Large transfers to exchanges signal potential selling; transfers from exchanges signal accumulation.

| Direction | Meaning | Score |
|-----------|---------|-------|
| Net to exchange | Whales depositing to sell | Negative |
| Net from exchange | Whales withdrawing to hold | Positive |
| No activity | Nothing notable | Zero |

**Formula:**
```
net = from_exchange_usd - to_exchange_usd
score = net / scale
scale = $10,000,000 (default)
```

**Data source:** Etherscan API (`tokentx` endpoint). Near real-time (5-min polling). Only covers ETH-ecosystem tokens. Non-ETH assets (BTC, SOL, etc.) have no whale tracking — this sub-score is set to None and the remaining sub-weights are renormalized so the on-chain score isn't permanently muted.

### 2e. On-Chain Combined Score

```
on_chain_score = weighted_average(
    exchange_flow * 0.3,
    nupl * 0.25,
    active_addresses * 0.15,
    whale_activity * 0.3
)
```

When whale data is missing (non-ETH assets), whale weight is excluded and the remaining weights are renormalized: `0.3 + 0.25 + 0.15 = 0.7` becomes the new denominator.

Sub-weights configurable in `config/onchain_config.json`.

---

## 3. Composite Scoring

### 3a. Weighted Sum

All signal categories produce a -1 to +1 score. The composite scorer combines them:

```
raw_composite = normalize(
    0.35 * technical_score
  + 0.25 * derivatives_score
  + 0.15 * on_chain_score
  + 0.10 * multi_timeframe_score
  + 0.15 * sentiment_score
)
```

**Normalization:** Weights are divided by their sum at runtime (`w_i / sum(w)`), guaranteeing the output stays in [-1, +1] even if weights are changed independently during optimization.

Weights configurable in `config/composite_config.json`.

### 3b. Two-Tier Override Rules

After computing the weighted sum, override rules can modify the score. Two tiers:

**Soft overrides** — multiply the score by a penalty factor (default 0.2):

| Rule | Condition | Action | Rationale |
|------|-----------|--------|-----------|
| O1a | Funding > +0.10% | Positive score × 0.2 | Overcrowded longs, elevated risk |
| O2a | Funding < -0.10% | Negative score × 0.2 | Overcrowded shorts, squeeze risk |
| O3a | NUPL > 0.75 | Positive score × 0.2 | Market euphoria |
| O4a | NUPL < 0 | Negative score × 0.2 | Market capitulation |
| O5 | 4h trend opposes signal | Score × 0.5 | Counter-trend protection |
| O6 | Catalyst detected | Score × 1.5 | High-impact news acceleration |

**Hard overrides** — clamp the score to 0 (complete block):

| Rule | Condition | Action | Rationale |
|------|-----------|--------|-----------|
| O1b | Funding > +0.20% | Clamp positive score to 0 | Extreme leverage, cascade imminent |
| O2b | Funding < -0.20% | Clamp negative score to 0 | Extreme short crowding |
| O3b | NUPL > 0.90 | Clamp positive score to 0 | Extreme euphoria, historical top |
| O4b | NUPL < -0.25 | Clamp negative score to 0 | Extreme capitulation, historical bottom |

**Stacking order:**
1. O6 catalyst boost applied first
2. Soft penalties applied multiplicatively (e.g., O1a + O3a = score × 0.2 × 0.2 = score × 0.04)
3. Hard clamps applied last (after soft penalties)

All override thresholds configurable in `config/composite_config.json` under `overrides`.

### 3c. Decision Thresholds

```
final_score > +0.3  → BUY
final_score < -0.3  → SELL
otherwise           → HOLD
```

Both thresholds stored as positive magnitudes. Asymmetric thresholds allowed (e.g., higher bar for buys than sells). Configurable in `config/composite_config.json` under `thresholds`.

---

## 4. Data Availability by Asset

Not all assets have all metrics. The system handles missing data gracefully:

| Data | Available For | Missing Behavior |
|------|--------------|------------------|
| Funding rates | Assets with perpetual futures on Binance/Bybit (~35-40 of 67) | Asset excluded from derivatives scoring |
| Open interest | Same as funding rates | Same |
| Exchange flows | BTC, ETH only (CoinMetrics free tier) | Sub-score = 0, weights renormalized |
| MVRV / NUPL | ~20 assets on CoinMetrics | Sub-score = 0, weights renormalized |
| Active addresses | ~20 assets on CoinMetrics | Sub-score = 0, weights renormalized |
| Whale tracking | ETH-ecosystem tokens only (Etherscan) | Sub-score = None, weights renormalized |

When a sub-score is missing, it contributes 0 to the weighted average and the remaining weights are renormalized so the combined score still uses the full [-1, +1] range.

---

## 5. Configuration Files

| File | What It Controls |
|------|-----------------|
| `config/derivatives_config.json` | Funding rate neutral band, OI lookback periods, long/short extreme threshold, sub-weights |
| `config/onchain_config.json` | CoinMetrics poll schedule, whale transfer threshold ($1M), whale rolling window (4h), flow normalization (30d), NUPL thresholds, sub-weights |
| `config/composite_config.json` | Category weights, buy/sell thresholds, all override thresholds and multipliers |

All values are starting defaults intended to be optimized via grid search backtesting.

---

## 6. Inspecting the Pipeline

Run each step and inspect JSON output:

```bash
python -m scripts.fetch.derivatives --assets BTC ETH SOL    # → data/derivatives/
python -m scripts.fetch.onchain --assets BTC ETH             # → data/onchain/
python -m scripts.score.derivatives --assets BTC ETH SOL     # → data/derivatives_scores/
python -m scripts.score.onchain --assets BTC ETH             # → data/onchain_scores/
python -m scripts.score.composite --assets BTC ETH SOL       # → data/composite/
python -m scripts.inspect.show_db --tables                   # list all DB tables
python -m scripts.inspect.show_db --table signal_log         # see logged decisions
```
