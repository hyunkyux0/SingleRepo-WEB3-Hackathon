# Unified Directory Structure

> **Date**: 2026-03-18
> **Status**: Draft
> **Context**: Integrates derivatives/on-chain signals (Phase 2 & 3) with existing sentiment module and trading bot.

```
SingleRepo-WEB3-Hackathon/
  config/
    sector_map.json              # Token -> sector assignments (sentiment module)
    sector_config.json           # Per-sector parameters: weights, decay, lookback (sentiment module)
    sources.json                 # News data source registry (sentiment module)
    derivatives_config.json      # Funding rate thresholds, OI params, long/short ratio config
    onchain_config.json          # NUPL thresholds, whale transfer size, exchange flow normalization
    composite_config.json        # Composite scorer weights, override rules, buy/sell thresholds
    asset_universe.json          # Shared asset universe (renamed from universe.json)

  utils/
    llm_client.py                # Universal LLM client: OpenRouter primary, OpenAI fallback
    db.py                        # DataStore abstraction over SQLite (swappable to AWS later)

  news_sentiment/                # Sentiment module — news ingestion & classification
    __init__.py
    models.py                    # ArticleInput, ClassificationOutput
    processors.py                # Fetch, dedupe, pre-filter, SQLite storage
    prompter.py                  # System prompts, prompt builders, LLM calls

  sentiment_score/               # Sentiment module — scoring & aggregation
    __init__.py
    models.py                    # ScoredArticle, SectorSignal, SectorSignalSet
    processors.py                # Temporal decay, aggregation, momentum, catalysts
    prompter.py                  # Batch sentiment scoring prompts + LLM calls

  derivatives/                   # Phase 2 — derivatives & funding rate signals
    __init__.py
    models.py                    # FundingSnapshot, OISnapshot, LongShortRatio, DerivativesSignal
    collectors.py                # BinanceCollector, BybitCollector, CoinalyzeCollector
    processors.py                # Aggregate funding, compute OI divergence, long/short score

  on_chain/                      # Phase 3 — on-chain analytics
    __init__.py
    models.py                    # ExchangeFlow, WhaleTransfer, OnChainDaily, OnChainSignal
    collectors.py                # CoinMetricsCollector, EtherscanCollector
    processors.py                # Compute NUPL from MVRV, net flow score, whale activity score

  technicals/                    # Technical analysis signals (extracted from trading_strategy.py)
    __init__.py
    models.py                    # TechnicalSignal
    processors.py                # SMA, Bollinger Bands, regime detection, multi-timeframe scoring

  composite/                     # Composite scorer — combines all signal sources
    __init__.py
    models.py                    # CompositeScore, OverrideEvent, TradingDecision
    scorer.py                    # Weighted sum + override rules -> BUY/SELL/HOLD
    adapters.py                  # SectorSignalSet -> per-asset sentiment score via sector map

  pipeline/
    orchestrator.py              # Unified tick scheduler driving all modules

  data/
    trading_bot.db               # Single SQLite DB: articles + derivatives + on-chain + ohlc + signals

  scripts/
    build_sector_map.py          # CoinGecko API -> sector_map.json (existing)
    discover_assets.py           # Query Binance/Bybit for available perps, rank by OI, build active list

  trading-bot/                   # Existing execution layer
    monitor_bot.py               # 5-min monitoring loop, calls pipeline orchestrator
    logs/
      monitor_bot.log

  crypto-roostoo-api/            # Existing Roostoo exchange integration
    balance.py
    trades.py
    utilities.py

  sma-prediction/                # Existing (legacy, to be refactored into technicals/)
    trading_strategy.py
    backtest_sma.py
    multi_cryptocurrency_optimizer.py
    prices.py
    crypto_data/

  output/                        # Existing optimization & research output
    optimized_strategy_parameters.json
    force_currency_allocation.json
    research_report_v2.md
    cluster_sentiment_research.md

  docs/
    directory/
      unified_directory.md       # This file
    superpowers/
      specs/
        2026-03-18-sector-sentiment-signal-module-design.md
        2026-03-18-derivatives-onchain-signal-module-design.md

  logs/
    sentiment_pipeline.log       # Sentiment module logging
    derivatives_pipeline.log     # Derivatives module logging
    onchain_pipeline.log         # On-chain module logging
```

## Module Pattern

Every signal module follows the same structure:

```
module_name/
  __init__.py
  models.py          # Pydantic data models (inputs, outputs, intermediates)
  collectors.py      # Data fetching from external APIs -> SQLite
  processors.py      # Read from SQLite -> compute sub-scores -> output signal
```

Exception: `news_sentiment/` and `sentiment_score/` include `prompter.py` for LLM calls.

## Database

Single SQLite database at `data/trading_bot.db` containing all tables:

- `articles` — news article cache (sentiment module)
- `asset_registry` — dynamic asset list with perps availability
- `funding_rates` — 5-min funding rate snapshots per exchange
- `open_interest` — 5-min OI snapshots per exchange
- `long_short_ratio` — 5-min long/short ratio from Coinalyze
- `on_chain_daily` — daily CoinMetrics data (exchange flows, MVRV, active addresses)
- `whale_transfers` — near real-time large transfers from Etherscan
- `ohlc_data` — price candles at 5m, 1h, 4h intervals
- `signal_log` — audit trail of all composite scores and decisions

Accessed via `utils/db.py` DataStore abstraction for future AWS migration.

## Orchestrator Tick Schedule

| Frequency | Modules Ticked |
|-----------|---------------|
| Every 5 min | Sentiment fetch + fast-path, Derivatives collectors, Technicals, Whale transfers, Composite scorer |
| Every 30 min | Sentiment batch LLM processing |
| Once daily | CoinMetrics on-chain pull, Asset discovery refresh, Data pruning |

## Composite Score Formula

```
final_score = w_tech * technical_score
            + w_deriv * derivatives_score
            + w_onchain * on_chain_score
            + w_mtf * multi_timeframe_score
            + w_sentiment * sentiment_score

+ override rules evaluated after weighted sum
-> BUY / SELL / HOLD
```
