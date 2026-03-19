# WEB3 Hackathon - Multi-Signal Cryptocurrency Trading System

A comprehensive cryptocurrency trading system that combines five signal sources -- technical analysis, news sentiment, derivatives data, on-chain analytics, and multi-timeframe confirmation -- through a composite scoring engine. Automated execution is handled via the Roostoo exchange API. The system covers a 67-token universe organized into 6 sectors (L1 infrastructure, DeFi, AI/compute, meme, store of value, and other).

## Architecture

```
                           Signal Sources
                    +--------------------------+
                    |                          |
  +-------------+   +---------------+   +------------+
  | news_sentiment|   | derivatives   |   | on_chain   |
  | (CryptoPanic, |   | (funding rate,|   | (CoinMetrics|
  |  RSS feeds,   |   |  OI, L/S     |   |  exchange   |
  |  LLM classify)|   |  ratio)      |   |  flow, NUPL)|
  +------+--------+   +------+-------+   +------+-----+
         |                    |                  |
  +------+--------+          |                  |
  | sentiment_score|          |                  |
  | (sector aggr., |          |                  |
  |  decay, momentum)         |                  |
  +------+--------+          |                  |
         |                    |                  |
         |   +------------+  |   +-----------+  |
         |   | technicals |  |   | multi-TF  |  |
         |   | (SMA, BB,  |  |   | confirm.  |  |
         |   |  regime)   |  |   |           |  |
         |   +-----+------+  |   +-----+-----+  |
         |         |          |         |         |
         v         v          v         v         v
       +-------------------------------------------+
       |         Composite Scorer                   |
       |  (weighted sum + override rules)           |
       |  -> BUY / SELL / HOLD per asset            |
       +---------------------+---------------------+
                              |
                              v
       +-------------------------------------------+
       |           Trading Bot                      |
       |  (order execution via Roostoo API)         |
       +-------------------------------------------+
                              |
                              v
                    Roostoo Exchange
```

## Directory Structure

```
SingleRepo-WEB3-Hackathon/
|-- composite/                  # Composite scoring engine
|   |-- __init__.py
|   |-- adapters.py             # Signal adapter normalization
|   |-- models.py               # CompositeScore, TradingDecision, OverrideEvent
|   |-- scorer.py               # Weighted sum + two-tier override rules
|
|-- config/                     # All configuration files
|   |-- asset_universe.json     # 67 supported trading pairs
|   |-- composite_config.json   # Signal weights and override thresholds
|   |-- derivatives_config.json # Funding rate, OI, long/short config
|   |-- onchain_config.json     # Exchange flow, NUPL, whale thresholds
|   |-- sector_config.json      # Per-sector sentiment parameters
|   |-- sector_map.json         # Token-to-sector mapping (6 sectors)
|   |-- sources.json            # News source definitions (CryptoPanic, RSS feeds)
|
|-- crypto-roostoo-api/         # Roostoo exchange API client
|   |-- balance.py              # Account balance queries
|   |-- trades.py               # Order placement, query, cancellation
|   |-- utilities.py            # Server time, exchange info, ticker data
|   |-- manual_api_test.py      # Interactive API testing script
|
|-- derivatives/                # Derivatives signal module
|   |-- __init__.py
|   |-- collectors.py           # Funding rate, OI, long/short data collection
|   |-- models.py               # DerivativesSnapshot, DerivativesSignal
|   |-- processors.py           # Score computation from derivatives data
|
|-- news_sentiment/             # News ingestion and classification
|   |-- __init__.py
|   |-- models.py               # ArticleInput, ClassificationOutput
|   |-- processors.py           # Fetch, deduplicate, keyword filter, store
|   |-- prompter.py             # LLM-based article classification (fast + batch)
|
|-- on_chain/                   # On-chain analytics signal module
|   |-- __init__.py
|   |-- collectors.py           # CoinMetrics API data collection
|   |-- models.py               # OnChainSnapshot, OnChainSignal
|   |-- processors.py           # Exchange flow, NUPL, whale activity scoring
|
|-- pipeline/                   # Pipeline orchestration
|   |-- __init__.py
|   |-- orchestrator.py         # SentimentPipeline: 5-minute tick scheduler
|
|-- scripts/                    # Utility scripts
|   |-- __init__.py
|   |-- build_sector_map.py     # Generate sector_map.json from universe
|   |-- discover_assets.py      # Discover available trading pairs
|
|-- sentiment_score/            # Sentiment aggregation and scoring
|   |-- __init__.py
|   |-- models.py               # ScoredArticle, SectorSignal, SectorSignalSet
|   |-- processors.py           # Temporal decay, source weighting, sector aggregation
|   |-- prompter.py             # LLM-based sentiment magnitude scoring
|
|-- sma-prediction/             # Technical analysis strategy (original module)
|   |-- trading_strategy.py     # Regime detection, SMA crossover, BB mean reversion
|   |-- multi_cryptocurrency_optimizer.py  # Grid search parameter optimization
|   |-- backtest_sma.py         # Backtesting framework with commission modeling
|   |-- prices.py               # Kraken API OHLC data fetching
|   |-- trading_strategy_LEGACY.py
|
|-- technicals/                 # Technical analysis signal adapter
|   |-- __init__.py
|
|-- trading-bot/                # Automated trading bot
|   |-- monitor_bot.py          # Real-time account monitoring
|   |-- purchase_by_value.py    # Value-based order execution
|   |-- firstoption.json        # Portfolio allocation option 1
|   |-- secondoption.json       # Portfolio allocation option 2
|
|-- tests/                      # Test suite (270 tests)
|   |-- test_composite_scorer.py
|   |-- test_composite_overrides.py
|   |-- test_adapters.py
|   |-- test_derivatives_collectors.py
|   |-- test_derivatives_models.py
|   |-- test_derivatives_processors.py
|   |-- test_news_sentiment.py
|   |-- test_sentiment_score.py
|   |-- test_onchain_collectors.py
|   |-- test_onchain_models.py
|   |-- test_onchain_processors.py
|   |-- test_orchestrator.py
|   |-- test_integration.py
|   |-- test_asset_discovery.py
|   |-- test_build_sector_map.py
|   |-- test_db.py
|
|-- utils/                      # Shared utilities
|   |-- __init__.py
|   |-- db.py                   # DataStore (SQLite persistence)
|   |-- llm_client.py           # OpenRouter / OpenAI LLM client
|
|-- output/                     # Generated analysis results and research
|-- data/                       # Runtime data (SQLite DB, cached responses)
|-- logs/                       # Application logs
|-- docs/                       # Documentation and research
|-- universe.json               # Master list of 67 supported trading pairs
|-- requirements.txt            # Python dependencies
|-- .env                        # Environment variables (not committed)
|-- .gitignore
```

## Signal Modules

### news_sentiment

Fetches cryptocurrency news from CryptoPanic API and RSS feeds (CoinDesk, CoinTelegraph, Decrypt). Articles are deduplicated, filtered by keyword relevance, and classified by an LLM into sector-relevant sentiment labels. Supports both fast (per-article) and batch classification paths.

### sentiment_score

Aggregates classified articles into per-sector sentiment signals. Applies temporal decay (exponential, configurable lambda per sector), source weighting (CryptoPanic 1.0, RSS 0.8, Twitter 0.6, Reddit 0.4), and magnitude weighting (high 3.0, medium 1.0, low 0.3). Computes momentum as delta between current and prior-window signals. Detects catalyst events when sentiment exceeds sector-specific thresholds.

### derivatives

Collects derivatives market data: funding rates, open interest (OI), and long/short ratios. Scores each metric independently then combines via sub-weights (funding 0.4, OI divergence 0.35, long/short 0.25) into a single derivatives signal in [-1, +1].

### on_chain

Pulls on-chain data from CoinMetrics Community API: exchange flow (net deposits/withdrawals), NUPL (Net Unrealized Profit/Loss), active addresses, and whale transfer activity. Sub-weights: exchange flow 0.3, NUPL 0.25, active addresses 0.15, whale activity 0.3.

### technicals (sma-prediction)

Dual-mode adaptive trading strategy. Detects market regime (TREND vs RANGE) using 50-period MA slope and Bollinger Band width. In trending markets, uses SMA crossover (golden/death cross). In range-bound markets, uses Bollinger Band mean reversion. Per-asset parameters are optimized via grid search across SMA windows, slope thresholds, and BB parameters.

## Composite Scoring

The composite scorer combines all five signal sources into a single score per asset:

**Weighted sum** (configurable in `config/composite_config.json`):
- Technical: 0.35
- Derivatives: 0.25
- On-chain: 0.15
- Multi-timeframe: 0.10
- Sentiment: 0.15

**Override rules** modify the raw score:
- **Soft overrides**: Funding rate penalty (multiplier 0.2x when funding > 0.1%), NUPL euphoria/capitulation penalty, timeframe opposition penalty (0.5x), catalyst boost (1.5x when aligned)
- **Hard overrides**: Clamp score to zero when funding rate > 0.2% or NUPL > 0.90 / < -0.25

**Decision thresholds**: BUY when score > 0.3, SELL when score < -0.3, HOLD otherwise.

## Pipeline Orchestration

The `SentimentPipeline` in `pipeline/orchestrator.py` runs on a 5-minute tick cycle:

1. Fetch news from all enabled sources
2. Deduplicate and keyword-filter articles
3. Store new articles in SQLite database
4. Classify unprocessed articles via LLM (fast path for urgent, batch for rest)
5. Score article sentiment magnitude
6. Aggregate into per-sector signals with temporal decay and momentum
7. Return `SectorSignalSet` for consumption by composite scorer

Rate limiting is enforced via a token-bucket limiter to stay within LLM API quotas.

## Configuration

| File | Purpose |
|------|---------|
| `config/asset_universe.json` | Master list of 67 tradeable pairs |
| `config/sector_map.json` | Maps each token to primary/secondary sector |
| `config/sector_config.json` | Per-sector sentiment parameters (weight, lookback, decay, thresholds) |
| `config/composite_config.json` | Signal weights, BUY/SELL thresholds, override rule parameters |
| `config/derivatives_config.json` | Derivatives polling interval, neutral bands, sub-weights |
| `config/onchain_config.json` | On-chain polling schedule, whale thresholds, sub-weights |
| `config/sources.json` | News source definitions (API endpoints, RSS URLs, priorities) |
| `universe.json` | Root-level copy of the 67-pair universe |

## Quick Start

### Prerequisites

- Python 3.11+
- Roostoo exchange account with API credentials
- API keys for news and LLM services

### Installation

```bash
git clone <repository-url>
cd SingleRepo-WEB3-Hackathon
pip install -r requirements.txt
```

### Environment Setup

Create a `.env` file in the project root:

```env
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=openrouter/hunter-alpha
OPENROUTER_MODEL_FAST=openai/gpt-5.4-nano
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-5.4-nano
CRYPTOPANIC_API_KEY=your_cryptopanic_key
```

Create a `.env` file in `crypto-roostoo-api/`:

```env
ROOSTOO_API_KEY=your_roostoo_api_key
ROOSTOO_API_SECRET=your_roostoo_api_secret
BASE_URL=https://api.roostoo.com
```

### Running Tests

```bash
pytest
```

The test suite contains 270 tests covering all signal modules, composite scoring, pipeline orchestration, and integration scenarios.

### Starting the Bot

```bash
# Run strategy optimization (technical analysis)
cd sma-prediction
python multi_cryptocurrency_optimizer.py

# Start the trading bot
cd trading-bot
python monitor_bot.py
```

## Testing

The project has 270 tests organized by module:

- `test_composite_scorer.py`, `test_composite_overrides.py`, `test_adapters.py` -- Composite scoring engine
- `test_derivatives_collectors.py`, `test_derivatives_models.py`, `test_derivatives_processors.py` -- Derivatives signal
- `test_news_sentiment.py` -- News ingestion and classification
- `test_sentiment_score.py` -- Sentiment aggregation and scoring
- `test_onchain_collectors.py`, `test_onchain_models.py`, `test_onchain_processors.py` -- On-chain analytics
- `test_orchestrator.py` -- Pipeline orchestration
- `test_integration.py` -- End-to-end integration
- `test_asset_discovery.py`, `test_build_sector_map.py` -- Asset universe tooling
- `test_db.py` -- SQLite data store

Run the full suite:

```bash
pytest -v
```

## Supported Cryptocurrencies

67 tokens across 6 sectors:

| Sector | Count | Examples |
|--------|-------|----------|
| L1 Infrastructure | 21 | BTC, ETH, SOL, AVAX, SUI, NEAR, TON, ADA, DOT, XRP, BNB, ARB |
| DeFi | 10 | AAVE, UNI, CRV, PENDLE, LINK, ONDO, ENA, CAKE, EIGEN, LISTA |
| AI / Compute | 4 | FET, TAO, WLD, VIRTUAL |
| Meme | 10 | DOGE, SHIB, PEPE, BONK, WIF, FLOKI, TRUMP, PENGU, PUMP, 1000CHEEMS |
| Store of Value | 3 | PAXG, LTC, ZEC |
| Other | 19 | OPEN, S, OMNI, FIL, CFX, ZEN, BIO, PLUME, and others |

The full list is maintained in `config/asset_universe.json` and `config/sector_map.json`.

## Key Algorithms

### Sector Sentiment Aggregation

Each sector has distinct aggregation parameters reflecting its news sensitivity:

- **Temporal decay**: Exponential decay applied to article scores based on age. Lambda ranges from 0.1 (L1 infra, store of value -- slow decay, long memory) to 2.0 (meme -- fast decay, recency-biased).
- **Source weighting**: News sources are weighted by reliability (CryptoPanic 1.0, major RSS feeds 0.8, Twitter 0.6, Reddit 0.4).
- **Magnitude weighting**: High-impact articles weighted 3x, medium 1x, low 0.3x.
- **Momentum**: Delta between current and prior-window aggregate score, detecting sentiment acceleration.
- **Catalyst detection**: When aggregate sentiment exceeds a sector-specific threshold, a catalyst event is flagged to trigger override rules in the composite scorer.

### Composite Scoring

- **Weighted sum**: Five signal scores in [-1, +1] are combined via configurable weights, normalized to [-1, +1].
- **Override rules**: Two tiers. Soft overrides apply multiplicative penalties or boosts (stack multiplicatively). Hard overrides clamp score to zero. Applied in order: catalyst boost, then soft penalties, then hard clamps.
- **Decision mapping**: Final score maps to BUY (> 0.3), SELL (< -0.3), or HOLD.

### Regime Detection

- **MA slope analysis**: 50-period moving average slope, normalized by price. Slope above threshold indicates trend.
- **Bollinger Band width**: 20-period BB width normalized by price. Width above threshold indicates trending volatility.
- **Regime output**: TREND (either indicator positive) or RANGE (neither). Determines whether SMA crossover or mean reversion strategy is used.

### Catalyst Detection

When sector-level sentiment magnitude exceeds the configured catalyst threshold (e.g., 0.7 for L1 infra, 0.5 for meme), a catalyst event is emitted. The composite scorer applies a 1.5x boost if the catalyst direction aligns with the current composite score direction.

## Disclaimer

This software is for educational and research purposes only. Cryptocurrency trading involves significant financial risk. Always test with small amounts first, understand the risks involved, and never invest more than you can afford to lose. Verify all trading operations before execution.
