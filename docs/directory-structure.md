# Project Directory Structure

```
SingleRepo-WEB3-Hackathon/
│
├── .env                                    # API keys (OpenRouter, Etherscan, etc.)
├── README.md                               # Project overview
├── requirements.txt                        # Python dependencies
├── universe.json                           # 67 crypto pairs (root copy)
│
├── config/                                 # Configuration files
│   ├── asset_universe.json                 # 67 crypto pairs (canonical location)
│   ├── composite_config.json               # Composite scorer weights, thresholds, override rules
│   ├── derivatives_config.json             # Funding rate thresholds, OI params, sub-weights
│   ├── onchain_config.json                 # NUPL thresholds, whale params, sub-weights
│   ├── sector_map.json                     # Token → sector assignments (l1_infra, defi, etc.)
│   ├── sector_config.json                  # Per-sector parameters (decay, lookback, etc.)
│   └── sources.json                        # News source registry (CryptoPanic, RSS feeds)
│
├── utils/                                  # Shared utilities
│   ├── __init__.py
│   ├── db.py                               # DataStore — SQLite abstraction (9 tables, CRUD, pruning)
│   └── llm_client.py                       # LLM client (OpenRouter primary, OpenAI fallback)
│
├── derivatives/                            # Phase 2 — Derivatives & funding rate signals
│   ├── __init__.py
│   ├── models.py                           # FundingSnapshot, OISnapshot, LongShortRatio, DerivativesSignal
│   ├── collectors.py                       # BinanceCollector, BybitCollector, CoinalyzeCollector
│   └── processors.py                       # Scoring: funding rate, OI divergence, long/short ratio
│
├── on_chain/                               # Phase 3 — On-chain analytics
│   ├── __init__.py
│   ├── models.py                           # ExchangeFlow, WhaleTransfer, OnChainDaily, OnChainSignal
│   ├── collectors.py                       # CoinMetricsCollector, EtherscanCollector
│   └── processors.py                       # Scoring: exchange flow, NUPL, active addresses, whale activity
│
├── composite/                              # Composite scorer — combines all signal sources
│   ├── __init__.py
│   ├── models.py                           # CompositeScore, OverrideEvent, TradingDecision
│   ├── scorer.py                           # Weighted sum + two-tier override rules → BUY/SELL/HOLD
│   └── adapters.py                         # SectorSignalSet → per-asset sentiment score via sector map
│
├── news_sentiment/                         # Sentiment — news ingestion & classification
│   ├── __init__.py
│   ├── models.py                           # ArticleInput, ClassificationOutput
│   ├── processors.py                       # Fetch, dedupe, keyword pre-filter, SQLite storage
│   └── prompter.py                         # LLM prompts for sector classification
│
├── sentiment_score/                        # Sentiment — scoring & aggregation
│   ├── __init__.py
│   ├── models.py                           # ScoredArticle, SectorSignal, SectorSignalSet
│   ├── processors.py                       # Temporal decay, aggregation, momentum, catalysts
│   └── prompter.py                         # LLM prompts for sentiment scoring
│
├── technicals/                             # Technical analysis (stub — to be refactored)
│   └── __init__.py                         # Placeholder for SMA/BB regime detection wrapper
│
├── pipeline/                               # Unified orchestrator
│   ├── __init__.py
│   └── orchestrator.py                     # SentimentPipeline — 5-min tick loop for news/sentiment
│
├── scripts/                                # CLI tools & utilities
│   ├── __init__.py
│   ├── discover_assets.py                  # Core: query Binance for perps, rank by OI
│   ├── build_sector_map.py                 # Core: CoinGecko API → sector_map.json
│   ├── fetch_news.py                       # Core: fetch news from CryptoPanic/RSS
│   ├── run_pipeline.py                     # Core: run full sentiment pipeline
│   │
│   ├── fetch/                              # Data fetching CLIs
│   │   ├── __init__.py
│   │   ├── discover.py                     # Asset discovery → data/asset_registry/
│   │   ├── derivatives.py                  # Binance/Bybit funding + OI → data/derivatives/
│   │   ├── onchain.py                      # CoinMetrics daily data → data/onchain/
│   │   └── market_data.py                  # Binance OHLCV (incremental CSV) → data/market_data/
│   │
│   ├── score/                              # Signal scoring CLIs
│   │   ├── __init__.py
│   │   ├── derivatives.py                  # Score derivatives signals → data/derivatives_scores/
│   │   ├── onchain.py                      # Score on-chain signals → data/onchain_scores/
│   │   ├── composite.py                    # Composite scorer → data/composite/
│   │   └── simulate_derivatives.py         # Regime simulation → data/derivatives_scores/simulated_regimes.csv
│   │
│   └── inspect/                            # Database inspection CLIs
│       ├── __init__.py
│       └── show_db.py                      # Dump any DB table to stdout as JSON
│
├── tests/                                  # Test suite (264 tests)
│   ├── test_db.py                          # DataStore CRUD + schema tests
│   ├── test_derivatives_models.py          # Derivatives Pydantic model tests
│   ├── test_derivatives_collectors.py      # Derivatives collector tests (mocked HTTP)
│   ├── test_derivatives_processors.py      # Derivatives scoring logic tests
│   ├── test_onchain_models.py              # On-chain model tests (weight renormalization)
│   ├── test_onchain_collectors.py          # On-chain collector tests (mocked HTTP)
│   ├── test_onchain_processors.py          # On-chain scoring tests
│   ├── test_composite_scorer.py            # Composite weighted sum tests
│   ├── test_composite_overrides.py         # Override rule tests (stacking, hard/soft)
│   ├── test_asset_discovery.py             # Asset discovery tests
│   ├── test_adapters.py                    # Sentiment adapter tests
│   ├── test_news_sentiment.py              # News ingestion tests
│   ├── test_sentiment_score.py             # Sentiment scoring tests
│   ├── test_fetch_news.py                  # News fetch tests
│   ├── test_orchestrator.py                # Pipeline orchestrator tests
│   ├── test_build_sector_map.py            # Sector map builder tests
│   ├── test_integration.py                 # Integration tests
│   └── test_sentiment_v2.py                # Sentiment v2 tests
│
├── data/                                   # Runtime data (all gitignored)
│   ├── trading_bot.db                      # SQLite — single DB for all tables
│   │
│   ├── asset_registry/                     # Asset discovery snapshots
│   │   └── <timestamp>_active.json
│   │
│   ├── market_data/                        # OHLCV price data (incremental CSV)
│   │   ├── BTC_5m.csv                      # Per-asset: timestamp,open,high,low,close,volume
│   │   ├── ETH_5m.csv
│   │   └── ...
│   │
│   ├── derivatives/                        # Raw derivatives fetch snapshots
│   │   ├── <timestamp>_binance.json
│   │   └── <timestamp>_bybit.json
│   │
│   ├── derivatives_scores/                 # Computed derivatives signal scores
│   │   ├── <timestamp>_scores.json
│   │   ├── simulated_regimes.csv           # Regime simulation results
│   │   ├── real_historical_data.csv        # Real Binance historical data
│   │   └── real_historical_scored.csv      # Real data scored through pipeline
│   │
│   ├── onchain/                            # Raw on-chain fetch snapshots
│   │   └── <date>_coinmetrics.json
│   │
│   ├── onchain_scores/                     # Computed on-chain signal scores
│   │   └── <timestamp>_scores.json
│   │
│   ├── composite/                          # Final BUY/SELL/HOLD decisions
│   │   └── <timestamp>_decisions.json
│   │
│   ├── raw_news/                           # Raw news articles (sentiment pipeline)
│   │   └── news_<timestamp>.json
│   │
│   ├── classified_news/                    # LLM-classified articles
│   │   └── classified_<timestamp>.json
│   │
│   ├── sentiment_signals/                  # Aggregated sentiment signals
│   │   └── signals_<timestamp>.json
│   │
│   └── pipeline_runs/                      # Full pipeline run logs
│       └── run_<timestamp>.json
│
├── sma-prediction/                         # Legacy — original trading strategy
│   ├── trading_strategy.py                 # SMA + Bollinger + regime detection (758 lines)
│   ├── trading_strategy_LEGACY.py          # Original version before enhancements
│   ├── backtest_sma.py                     # Backtesting framework
│   ├── multi_cryptocurrency_optimizer.py   # Grid search parameter optimizer
│   ├── prices.py                           # Kraken OHLC fetcher (legacy)
│   └── multi_crypto_optimizer_explained.md # Documentation
│
├── trading-bot/                            # Legacy — execution layer
│   ├── monitor_bot.py                      # 5-min monitoring loop (Roostoo execution)
│   ├── purchase_by_value.py                # Order placement helper
│   ├── firstoption.json                    # Portfolio allocation option 1
│   └── secondoption.json                   # Portfolio allocation option 2
│
├── crypto-roostoo-api/                     # Legacy — Roostoo exchange integration
│   ├── balance.py                          # Account balance queries
│   ├── trades.py                           # Order placement & execution
│   ├── utilities.py                        # Server time sync, exchange info
│   ├── manual_api_test.py                  # Manual API testing script
│   ├── .env                                # Roostoo API credentials
│   └── .env.example                        # Credential template
│
├── output/                                 # Legacy — optimization & research output
│   ├── optimized_strategy_parameters.json  # Per-crypto optimized params
│   ├── force_currency_allocation.json      # Portfolio capital allocation
│   ├── research_report.md                  # Original research report
│   ├── research_report_v2.md               # Expanded research with gap analysis
│   └── cluster_sentiment_research.md       # Correlation clustering analysis
│
└── docs/                                   # Documentation
    ├── directory-structure.md              # This file
    ├── manual-testing.md                   # Manual testing guide (REPL + CLI)
    ├── signal-scoring-guide.md             # How raw data → scores → decisions
    │
    ├── directory/
    │   └── unified_directory.md            # Target directory layout (design-time)
    │
    └── superpowers/
        ├── specs/                          # Design specifications
        │   ├── 2026-03-18-derivatives-onchain-signal-module-design.md
        │   ├── 2026-03-18-sector-sentiment-signal-module-design.md
        │   └── 2026-03-19-evidence-based-sentiment-v2-design.md
        │
        └── plans/                          # Implementation plans
            ├── 2026-03-18-derivatives-onchain-signals.md
            ├── 2026-03-18-remaining-sentiment-pipeline.md
            ├── 2026-03-19-evidence-based-sentiment-v2.md
            └── 2026-03-19-pipeline-cli-tools.md
```
