# Sector Sentiment Signal Module — Design Specification

> **Date**: 2026-03-18
> **Status**: Approved
> **Scope**: Modular sentiment signal generator for a crypto trading bot. Produces per-sector sentiment signals consumed by a broader strategy engine alongside technical and other signals.

---

## 1. Context & Constraints

| Constraint | Value |
|-----------|-------|
| Capital | $1M USD |
| Duration | 10-day trading window |
| Positions | Long-only (buy & sell), no limit on count |
| Trading frequency | Any time, 5-minute intervals |
| Universe | 67 tokens (defined in `config/asset_universe.json`) |
| Scoring | Composite: strategy design + returns + risk-adjusted metrics (Sharpe, Sortino, Calmar) |
| Module role | One signal among several; does not own trading decisions |

### What This Module Owns

- News ingestion, deduplication, pre-filtering
- LLM-based sector classification and sentiment scoring
- Per-sector signal aggregation (sentiment, momentum, catalyst detection)
- Output of `SectorSignalSet` every 5 minutes

### What This Module Does NOT Own

- Position sizing, order execution, portfolio risk management
- Signal combination with technical/other signals
- Exit rules (strategy engine consumes sentiment signals as one input)
- The broader trading strategy redesign

---

## 2. Sector Taxonomy

### 6 Canonical Sectors

| Sector ID | Label | Sentiment Weight | Lookback Candidates | Default Decay Lambda | Regime |
|-----------|-------|-----------------|---------------------|---------------------|--------|
| `l1_infra` | L1/Infrastructure | 0.2 | [1d, 3d, 7d] | 0.1 | persistent_co_mover |
| `defi` | DeFi | 0.3 | [12h, 1d, 3d] | 0.3 | persistent_co_mover |
| `ai_compute` | AI/Compute | 0.6 | [4h, 12h, 1d] | 0.5 | event_driven |
| `meme` | Meme | 0.9 | [1h, 4h, 12h] | 2.0 | pure_sentiment |
| `store_of_value` | Store of Value | 0.1 | [3d, 7d] | 0.1 | weakly_connected |
| `other` | Other/Emerging | 0.4 | [4h, 1d, 3d] | 0.5 | mixed |

Sentiment weight = how much the sector's trading signal should rely on sentiment vs. other signals. Initial values from research; replaced by optimizer output after backtesting.

Lookback candidates = response windows to grid-search per sector during optimization, based on the Economic Change & Restructuring 2025 wavelet study showing different sectors respond at different time frequencies.

### Token-to-Sector Mapping

| Sector | Tokens |
|--------|--------|
| **l1_infra** | BTC, ETH, SOL, AVAX, SUI, NEAR, SEI, APT, TON, ADA, DOT, ICP, XRP, XLM, HBAR, TRX, BNB, POL, ARB, LINEA, HEMI |
| **defi** | AAVE, UNI, CRV, PENDLE, LINK, LISTA, ENA, ONDO, CAKE, EIGEN |
| **ai_compute** | FET, TAO, WLD, VIRTUAL |
| **meme** | DOGE, SHIB, PEPE, BONK, WIF, FLOKI, PENGU, 1000CHEEMS, TRUMP, PUMP |
| **store_of_value** | PAXG, LTC, ZEC |
| **other** | OPEN, S, OMNI, AVNT, EDEN, FORM, WLFI, BIO, MIRA, PLUME, ASTER, BMT, STO, SOMI, XPL, CFX, TUT, ZEN, FIL |

**Dual-routing**: Some tokens receive signals from two sectors. In `config/sector_map.json`, these tokens have a `secondary` field. When computing sector signals, dual-routed tokens appear in their primary sector's allocation. The secondary sector's catalyst signals are also forwarded to them, but at 50% weight. Dual-routed tokens:
- NEAR: primary `l1_infra`, secondary `ai_compute` (based on NVIDIA GTC evidence)
- BTC: primary `l1_infra`, secondary `store_of_value`

**Note**: The underlying research references tokens not in the trading universe (RNDR, GRASS, AGIX). The 67-token universe is constrained by the hackathon exchange. The sector framework and sentiment propagation mechanics apply regardless of which specific tokens are available.

Mapping populated via CoinGecko API (`pycoingecko` library) + manual verification. Script at `scripts/build_sector_map.py`.

---

## 3. Data Ingestion Pipeline

### Sources (priority order, extensible)

| Rank | Source | Method | Frequency | Signal Type |
|------|--------|--------|-----------|-------------|
| 1 | CryptoPanic | REST API | Every 5 min | Aggregated news + community votes |
| 2 | Crypto News RSS | RSS parse (CoinDesk, CoinTelegraph, Decrypt, The Block) | Every 5 min | Professional reporting |
| 3 | Twitter/X | API or scraping (key accounts) | Every 5 min | Breaking news, noisy |
| 4 | Reddit | Reddit API (r/cryptocurrency, project subs) | Every 30 min | Community sentiment |

Additional sources can be added by: (1) adding entry to `config/sources.json`, (2) implementing a fetcher function returning `list[ArticleInput]`.

### Processing Flow

1. **Fetch** from all enabled sources in parallel
2. **Deduplicate** by exact URL match + headline Jaccard similarity (threshold > 0.7)
3. **Keyword pre-filter** (no LLM): check for token names/tickers, sector keywords, high-impact keywords ("partnership", "hack", "SEC", "ETF", "listing", "launch", "upgrade")
4. **Score relevance** 0-1; discard if < 0.1
5. **Flag catalysts**: `is_catalyst = True` if high-impact keyword + mentioned ticker match
6. **Store** to SQLite with `processed = false`

### Article Cache (SQLite)

```sql
articles(
  id TEXT PRIMARY KEY,
  timestamp DATETIME,
  source TEXT,
  headline TEXT,
  body_snippet TEXT,
  url TEXT,
  mentioned_tickers JSON,
  source_sentiment REAL,
  relevance_score REAL,
  is_catalyst BOOLEAN,
  matched_sectors JSON,
  processed BOOLEAN DEFAULT 0,
  llm_sector TEXT,
  llm_secondary_sector TEXT,
  llm_sentiment REAL,
  llm_magnitude TEXT,
  llm_confidence REAL,
  llm_cross_market BOOLEAN,
  llm_reasoning TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

SQLite chosen for: zero setup, single file, stdlib, sufficient for estimated ~5,000 rows (roughly 500 unique articles/day x 10 days; articles are deduplicated and stored once regardless of how many tokens they mention). Later migration to AWS database planned.

---

## 4. LLM Classification & Sentiment Scoring

### Model Cascade

| Role | Model | Cost | When Used |
|------|-------|------|-----------|
| Batch (primary) | Hunter Alpha (OpenRouter) | Free | Every 30 min, process article backlog |
| Fast path (real-time) | GPT-5.4 Nano (OpenRouter) | $0.20/$1.25 per M tokens | Catalyst detected, needs immediate classification |
| Fallback | Nemotron Nano (OpenRouter) | $0.05/$0.20 per M tokens | When Hunter Alpha or GPT-5.4 Nano unavailable |

### Two Processing Paths

**Fast path** (catalyst detected by pre-filter):
- Model: GPT-5.4 Nano
- Single prompt: classify sector + score sentiment in one call
- Latency target: < 3 seconds
- Immediately updates sector scores + emits catalyst signal

**Batch path** (non-catalyst, relevance > 0.1):
- Model: Hunter Alpha
- Two-step prompt: (1) sector classification, (2) sentiment scoring
- Runs every 30 minutes on unprocessed article backlog
- Higher accuracy from separated classification and scoring

Two-step for batch based on research Insight 6: separating classification from scoring improves accuracy. Single-step for fast path because latency matters more.

### Prompt Design

**Fast path system prompt:**
```
You are a crypto news classifier. Given a headline and snippet, output JSON only.

Sectors: l1_infra, defi, ai_compute, meme, store_of_value, other

Rules:
- Classify into the single most affected sector
- If equity news maps to a crypto sector (e.g., NVIDIA -> ai_compute), set cross_market: true
- Score sentiment from the perspective of price impact over 1-7 days
- magnitude reflects expected price move size, not certainty

Output format:
{
  "primary_sector": "<primary sector affected>",
  "secondary_sector": "<if applicable, else null>",
  "sentiment": <float -1.0 to 1.0>,
  "magnitude": "<low|medium|high>",
  "confidence": <float 0 to 1>,
  "cross_market": <bool>,
  "reasoning": "<one sentence>"
}
```

**Batch path step 1 (classification) system prompt:**
```
You are a crypto sector classifier. Given a news article, determine which crypto sector it most affects.

Sectors and descriptions:
- l1_infra: Layer 1 blockchains, infrastructure, scaling solutions
- defi: Decentralized finance protocols, lending, DEXes, yield
- ai_compute: AI tokens, compute networks, machine learning projects
- meme: Meme coins, community-driven tokens, social tokens
- store_of_value: Bitcoin-like stores of value, gold-pegged, privacy coins
- other: Tokens that don't fit above categories

Rules:
- Consider cross-market signals: equity news (e.g., NVIDIA, Google AI) that maps to crypto sectors
- If the article affects multiple sectors, pick the primary and note secondary
- confidence reflects how clearly the article maps to a single sector

Output JSON only:
{
  "primary_sector": "<sector>",
  "secondary_sector": "<sector or null>",
  "confidence": <float 0 to 1>,
  "cross_market": <bool>
}
```

**Batch path step 2 (scoring) system prompt:**
```
You are a crypto sentiment scorer. Given a news article and its classified sector, score the sentiment impact.

Rules:
- Score from -1.0 (extremely bearish) to +1.0 (extremely bullish)
- Consider: Is this news likely to move token prices in this sector up or down over the next 1-7 days?
- magnitude reflects expected price move size: low (<2%), medium (2-8%), high (>8%)
- confidence reflects how certain you are in the sentiment assessment

Output JSON only:
{
  "sentiment": <float -1.0 to 1.0>,
  "magnitude": "<low|medium|high>",
  "confidence": <float 0 to 1>,
  "reasoning": "<one sentence>"
}
```

### Sector Sentiment Aggregation

For each sector, every 5 minutes:

1. Gather all classified articles within the sector's lookback window
2. Apply temporal decay: `weight(article) = exp(-lambda * hours_since_publication)` where lambda is calibrated per sector
3. Weight by source_weight: CryptoPanic (1.0) > News RSS (0.8) > Twitter (0.6) > Reddit (0.4)
4. Weight by magnitude: high = 3x, medium = 1x, low = 0.3x
5. Compute weighted average: `sector_sentiment = sum(sentiment_i * decay_i * source_weight_i * magnitude_i) / sum(decay_i * source_weight_i * magnitude_i)`
6. Compute momentum: `sector_momentum = sector_sentiment_now - sector_sentiment_lookback_ago`
7. Compute sector confidence: `sector_confidence = min(1.0, article_count / 10) * mean(llm_confidence_i)` — scales with both article volume and individual classification certainty
8. Detect catalyst: if any single article has magnitude=high AND |sentiment| > `catalyst_threshold` (default 0.7, optimized per Section 7) AND within last 30 min, then `catalyst_active = true`

### Error Handling

- LLM returns invalid JSON: retry once, fall back to next model in cascade
- LLM returns unknown sector: map to `other`
- LLM timeout: skip article for batch; use keyword pre-filter sector assignment as fallback for fast path
- No articles in lookback window: output sentiment=0, confidence=0 (neutral, low confidence)

---

## 5. Module Architecture

### Directory Structure

```
SingleRepo-WEB3-Hackathon/
  utils/
    llm_client.py                  # Universal LLM client (OpenRouter -> OpenAI fallback)
  news_sentiment/
    __init__.py
    models.py                      # ArticleInput, ClassificationOutput
    processors.py                  # Fetch, dedupe, pre-filter, SQLite storage
    prompter.py                    # System prompts, prompt builders, LLM calls
  sentiment_score/
    __init__.py
    models.py                      # ScoredArticle, SectorSignal, SectorSignalSet
    processors.py                  # Temporal decay, aggregation, momentum, catalysts
    prompter.py                    # Batch sentiment scoring prompts + LLM calls
  pipeline/
    orchestrator.py                # Main loop coordinator
  config/
    sector_map.json                # Token -> sector assignments
    sector_config.json             # Per-sector parameters
    sources.json                   # Data source registry
  scripts/
    build_sector_map.py            # CoinGecko API -> sector_map.json
  data/
    trading_bot.db               # Shared SQLite database (articles + all other tables)
```

### Key Pydantic Models

**`news_sentiment/models.py`:**

- `ArticleInput`: Normalized article from any source (id, timestamp, source, headline, body_snippet, url, mentioned_tickers, source_sentiment, relevance_score, is_catalyst, matched_sectors)
- `ClassificationOutput`: LLM classification result (primary_sector, secondary_sector, sentiment, magnitude, confidence, cross_market, reasoning)

**`sentiment_score/models.py`:**

- `ScoredArticle`: Article with final sector + sentiment + computed weights (article_id, timestamp, primary_sector, sentiment, magnitude, source, source_weight, decay_weight)
- `SectorSignal`: Aggregated signal for one sector (sector, sentiment, momentum, catalyst_active, catalyst_details, article_count, confidence)
- `SectorSignalSet`: Complete output — all sector signals at a point in time (timestamp, sectors: dict[str, SectorSignal], metadata)

### LLM Client (`utils/llm_client.py`)

Based on existing pattern: OpenRouter primary, OpenAI fallback, OpenAI SDK for both.

Additions to the existing pattern:
- `OPENROUTER_MODEL_FAST` env var for fast-path model selection
- `get_llm_client_fast()` function returning fast-path client
- `fast: bool = False` parameter on `call_llm()` to select client

```
.env:
  OPENROUTER_API_KEY=xxx
  OPENROUTER_MODEL=openrouter/hunter-alpha
  OPENROUTER_MODEL_FAST=openai/gpt-5.4-nano
  OPENAI_API_KEY=xxx
  OPENAI_MODEL=gpt-5.4-nano
```

---

## 6. Pipeline Orchestration

### Main Loop

The `SentimentPipeline` class exposes a `tick()` method called every 5 minutes by the trading bot. Each tick:

1. Fetch new articles from all enabled sources (parallel)
2. Deduplicate + keyword pre-filter
3. Store to SQLite
4. Fast path: classify catalysts immediately (GPT-5.4 Nano)
5. Batch path: every 30 min, process unprocessed backlog (Hunter Alpha)
6. Aggregate: compute `SectorSignalSet` from all scored articles
7. Return `SectorSignalSet` to strategy engine

### Integration with Trading Bot

```
monitor_bot.py (existing 5-min loop)
  -> pipeline.tick() returns SectorSignalSet
  -> Strategy engine combines sentiment signal with technical + other signals
  -> Final trading decision
```

### Rate Limit Management

| Model | Rate Limit | Strategy |
|-------|-----------|----------|
| Hunter Alpha | ~20 req/min (free) | Queue articles, process sequentially with 3s spacing |
| GPT-5.4 Nano | ~60 req/min (paid) | Immediate, retry once on 429 |
| Nemotron | ~20 req/min (free) | Fallback only, same queuing |

### Logging

Each tick logs to `logs/sentiment_pipeline.log`:
- articles_fetched, articles_after_dedup, articles_after_filter
- catalysts_detected, fast_path_classified, batch_processed
- sectors_with_signal, strongest_signal
- llm_calls, llm_cost_usd, processing_time_ms

---

## 7. Backtesting & Hyperparameter Optimization

### Approach: Synthetic Sentiment Replay

Use historical price data (Kraken API, already available) to generate synthetic sentiment signals from price momentum, then optimize aggregation and trading parameters.

This tests whether the aggregation math and trading logic produce good risk-adjusted returns given sentiment-like signals. LLM classification accuracy is validated separately with a hand-labeled set of 50-100 articles.

**Scope note**: The backtester tests the full signal-to-trade pipeline (sentiment signal generation through to simulated position entry/exit) to produce meaningful risk-adjusted metrics. Parameters like `entry_threshold` and `num_sectors_to_hold` are optimized here because they cannot be meaningfully tuned in isolation from the signal. These optimized values are then handed to the strategy engine as recommended defaults.

### Parameter Space

Per-sector parameters (grid-searched independently):

| Parameter | Search Space |
|-----------|-------------|
| lookback_hours | [1, 4, 12, 24, 72, 168] |
| decay_lambda | [0.1, 0.3, 0.5, 1.0, 2.0] |
| momentum_lookback_hours | [4, 12, 24, 72] |
| entry_threshold | [0.1, 0.2, 0.3, 0.5] |
| catalyst_threshold | [0.5, 0.6, 0.7, 0.8] |

Global parameters (grid-searched after sector params fixed):

| Parameter | Search Space |
|-----------|-------------|
| num_sectors_to_hold | [1, 2, 3, 4] |
| max_sector_weight | [0.25, 0.33, 0.50] |
| rebalance_interval_hours | [1, 4, 12, 24] |

### Optimization Strategy

Two-phase, per-sector then global:
1. Fix global params to reasonable defaults
2. Grid search each sector's params independently (1,920 x 6 sectors = 11,520 evals)
3. Fix sector params to best results
4. Grid search global params (48 evals)

### Scoring Function

```
score = 0.35 * normalize(sharpe) + 0.35 * normalize(sortino)
      + 0.20 * normalize(calmar) + 0.10 * normalize(total_return)
```

Heavy on Sharpe/Sortino per stated objective. Calmar penalizes drawdowns. Small return component prevents zero-risk-zero-return solutions.

### LLM Accuracy Validation

One-time quality check: collect 50-100 recent crypto articles, hand-label sector + sentiment, run through pipeline, measure accuracy. If < 70%, iterate on prompts before deploying.

---

## 8. Configuration & Extensibility

### Config Files

- `config/sector_map.json` — Token-to-sector assignments
- `config/sector_config.json` — Per-sector parameters (initial values, replaced by optimizer)
- `config/sources.json` — Data source registry (add sources without code changes)

### Adding a New Source

1. Add entry to `config/sources.json` with id, type, priority, source_weight, config
2. Implement fetcher function in `news_sentiment/processors.py` returning `list[ArticleInput]`
3. No other changes needed

### Dependencies (additions to requirements.txt)

```
openai>=1.0.0
pydantic>=2.0.0
feedparser>=6.0.0
pycoingecko>=3.0.0
```

### Deployment Roadmap (single day)

```
Morning:    Build pipeline + sector map + LLM prompts
Midday:     Validate LLM accuracy (50-100 articles) + build synthetic backtest
Afternoon:  Optimize parameters + integrate with trading bot + dry run
Evening:    Go live -> 10-day trading window begins
```

---

## 9. Research Foundation

This design synthesizes findings from:

| Finding | Source | Design Impact |
|---------|--------|--------------|
| Weighted sentiment improves Sharpe by 37% | QuantConnect sector rotation | Market-cap weighting within sectors |
| Peak attention = worst returns | CoinGecko 2025 narratives | Trade momentum (rate of change), not level |
| Positive equity sentiment propagates; negative does not | European Journal of Finance 2025 | Bias toward detecting positive catalysts |
| Different sectors respond at different frequencies | Economic Change & Restructuring 2025 | Per-sector lookback window calibration |
| NVIDIA -> AI tokens within hours, 30-40% retracement within week | Empirical event data | Fast path for catalysts, event-driven regime |
| Three connectedness regimes (persistent, event-driven, weak) | Cogent Economics 2025 | Per-sector sentiment weights and regime labels |
| Separate classification from scoring improves accuracy | NLP best practices | Two-step batch path |
