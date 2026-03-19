# Flags — Known Issues & Future Work

Items that need attention but are not blocking current development.

---

## Current State (as of 2026-03-19)

### What's built and working
- **News fetching** (`scripts/fetch_news.py`): CryptoPanic API (no filter, 20 recent posts, 24h delayed on free tier) + 3 RSS feeds (CoinDesk, CoinTelegraph, Decrypt, real-time). Age filter at 48h. Dedup via URL + Jaccard against last 200 DB articles.
- **Sector classification** (`news_sentiment/`): LLM classifies each article into 6 sectors (l1_infra, defi, ai_compute, meme, store_of_value, other). Fast path for catalysts, batch path for rest. Uses OpenAI GPT-5.4 Nano.
- **Evidence-based sector scoring** (`sentiment_score/`): Per-sector scoring (v2). Deterministic summary of articles + market evidence (Kraken prices, funding rate, previous sentiment, article velocity) fed into ONE LLM call per sector. Replaces old per-article scoring (42% LLM cost reduction).
- **Pipeline orchestrator** (`pipeline/orchestrator.py`): 5-min tick cycle. CryptoPanic every tick, RSS every 15 min. Batch classification every 30 min. Sector scoring every tick.
- **Composite scorer** (`composite/`): Weighted sum of 5 signals (technical, derivatives, on-chain, multi-timeframe, sentiment) + two-tier override rules (soft penalties + hard clamps) -> BUY/SELL/HOLD. Deterministic.
- **Derivatives** (`derivatives/`): Binance/Bybit funding rates + OI collection + scoring.
- **On-chain** (`on_chain/`): CoinMetrics exchange flows, MVRV/NUPL, active addresses.
- **Config**: 67 tokens across 6 sectors. Sector map, sector config, source config, composite config all in `config/`.
- **Tests**: 318 passing across all modules.

### What's NOT working or stubbed
- **technicals/** — stub only, SMA/BB regime detection still in `sma-prediction/`
- **Whale tracking** — code exists, not wired up (no API key)
- **Coinalyze long/short** — code exists, not fetched
- **Full pipeline orchestration** — only sentiment pipeline runs in orchestrator, derivatives/on-chain/composite are separate CLI scripts
- **Automated scheduling** — no cron/daemon, all manual

### Key data flow
```
fetch_news.py -> news_sentiment/ (classify) -> sentiment_score/ (evidence-based sector score)
                                                        |
derivatives/collectors -> derivatives/processors ------>|
on_chain/collectors -> on_chain/processors ----------->|-> composite/scorer -> BUY/SELL/HOLD
technicals/ (stub) ---------------------------------->|
```

---

## Sentiment Pipeline

### Per-asset sentiment differentiation
- **Status:** Flagged
- **Impact:** All tokens in a sector share the same sentiment score (-0.35 for all 21 l1_infra tokens). No differentiation based on which token was actually mentioned in the news.
- **Fix:** Add per-asset weighting layer in `composite/adapters.py`:
  - Tokens mentioned in articles get full sector score
  - Tokens not mentioned get dampened score (e.g., 50%)
  - Use `mentioned_tickers` frequency from `build_sector_summary()` to weight
- **Both levels needed:** Keep sector-level signal (for sector rotation) AND add per-asset signal (for token selection within sector)

### Sector classification prompt refinement
- **Status:** Flagged for separate iteration
- **Impact:** ~20% of articles classified as "other" (largest bucket). Cross-sector confusion exists (e.g., Bitcoin articles sometimes classified as store_of_value vs l1_infra inconsistently).
- **Fix:** Improve LLM prompts in `news_sentiment/prompter.py`:
  - Add more descriptive sector definitions with examples
  - Add few-shot examples of correct classification
  - Reduce "other" bucket by refining sector boundaries
  - Test with hand-labeled set of 50 articles, target >80% accuracy

### Evaluation framework (QA + LLM-as-a-judge)
- **Status:** Flagged
- **Impact:** No systematic way to measure prompt quality or track improvement over iterations.
- **Fix:** Build evaluation pipeline:
  - Hand-label 50-100 articles (sector + sentiment direction)
  - Run classification pipeline, measure accuracy
  - Use LLM-as-a-judge for reasoning quality assessment
  - Track metrics over prompt iterations

### Per-sector + equity scoring prompt fine-tuning
- **Status:** v2 implemented with a single generic prompt for all sectors. Needs specialization.
- **Impact:** One-size-fits-all prompt doesn't capture sector-specific dynamics. Meme coins respond differently to sentiment than L1 infrastructure. Equity cross-market signals (NVIDIA -> ai_compute) need their own scoring logic.
- **Architecture:** Each sector gets its own fine-tuned prompt pair:
  - **SYSTEM prompt**: Sector-specific rules, scoring biases, and behavioral guidelines. Rule-based — explicit if/then scoring heuristics baked into the system prompt (e.g., "For meme sector: social velocity > 3x baseline = score >= +0.5").
  - **INPUT prompt**: Structured evidence template (prices, funding, articles). Same structure across sectors but sector-specific field emphasis.
  - **Equity prompt**: Separate prompt for cross-market equity signals (e.g., NVIDIA earnings, Fed rate decisions) that map to crypto sectors. Different scoring rules — equity signals propagate asymmetrically (bullish propagates, bearish does not per research).
- **Prompts to create:**
  - `SECTOR_SCORE_SYSTEM_L1_INFRA` — usage-driven, slow sentiment response, weight on-chain metrics higher
  - `SECTOR_SCORE_SYSTEM_DEFI` — TVL-aware, protocol-specific, weight fundamentals
  - `SECTOR_SCORE_SYSTEM_AI_COMPUTE` — event-driven, equity cross-market sensitive, fast response
  - `SECTOR_SCORE_SYSTEM_MEME` — pure sentiment, social velocity dominant, fast decay
  - `SECTOR_SCORE_SYSTEM_STORE_OF_VALUE` — macro-driven, low sentiment weight, long horizon
  - `SECTOR_SCORE_SYSTEM_OTHER` — conservative default, low confidence
  - `EQUITY_CROSS_MARKET_SYSTEM` — maps equity news to crypto sector impact, asymmetric (bullish only)
- **Fix:** Implement prompt selection in `score_sector()` based on sector ID. Store prompts in `sentiment_score/prompts/` directory or as constants in `prompter.py`.

---

## Data Sources

### CryptoPanic free tier has 24-hour delay
- **Status:** Workaround in place (age filter set to 48h)
- **Impact:** CryptoPanic articles arrive 24-25h delayed. Usable for trend sentiment, not breaking news detection. RSS feeds (CoinDesk, CoinTelegraph, Decrypt) provide real-time articles.
- **Fix options:**
  - Pay for CryptoPanic Pro ($49/mo) for real-time access
  - Replace with a different real-time news aggregator
  - Accept delay — sentiment trends don't need minute-level freshness

### Whale tracking (Etherscan) not wired up
- **Status:** `EtherscanCollector` code exists but `scripts/fetch/onchain.py` doesn't call it
- **Impact:** `whale_score` is always null, whale sub-weight gets renormalized out
- **Fix:** Need Etherscan API key (free registration) + exchange address labels from `brianleect/etherscan-labels` repo + add Etherscan fetch step to onchain CLI

### Coinalyze long/short ratio not fetched
- **Status:** `CoinalyzeCollector` code exists but not called by fetch scripts
- **Impact:** `long_short_score` is always 0 (25% of derivatives signal weight is dead)
- **Fix:** Need free Coinalyze API key (registration) + add to `scripts/fetch/derivatives.py`

### CoinMetrics limited coverage
- **Status:** Only BTC/ETH have exchange flow data. ~15 assets have MVRV + active addresses. ~45 assets have no on-chain data.
- **Impact:** On-chain signal only works for a fraction of the universe. Tiered approach in place (auto-renormalize weights for missing data).
- **Fix options:**
  - Add Santiment free tier (22 assets with real-time active addresses, 30 with lagged MVRV)
  - Add DeFiLlama TVL as activity proxy for 24 DeFi/L1 assets
  - Accept — on-chain is a slow-moving cycle indicator, not critical for 5-min trading

---

## Scoring & Weights

### Composite weights need backtesting optimization
- **Status:** Using default starting weights (`tech=0.35, deriv=0.25, onchain=0.15, mtf=0.10, sentiment=0.15`)
- **Impact:** Weights are educated guesses, not optimized for risk-adjusted returns
- **Fix:** Run grid search backtesting across historical data once all signal generators are producing real data

### Derivatives scores are small in calm markets
- **Status:** Combined scores typically 0.01-0.04 during calm conditions
- **Impact:** Derivatives signal is quiet most of the time (~52% of days), loud during extremes (~2% of days). This is by design — it's a risk management signal, not a trade initiator.
- **Evidence:** Real historical data scored in `data/derivatives_scores/real_historical_scored.csv`. Peak: TRUMP +0.44 (March 14, funding -0.17% + OI +67%).
- **Fix options:**
  - Rescale scoring functions (reduce normalization caps) to amplify signal
  - Upweight derivatives in composite for assets where it's the primary signal
  - Accept — wait for backtesting to determine optimal scaling

### Scoring functions may need rescaling
- **Status:** `score_funding_rate` caps at `rate / 0.002`. Typical funding (0.01%) produces score of 0.05. Extreme funding (0.20%) produces 1.0.
- **Impact:** The 0.002 cap was chosen to make 0.20% = extreme = score of 1.0. But if typical market conditions rarely exceed 0.05%, the signal is always in the low range.
- **Fix:** After collecting more historical data, adjust the cap based on actual funding rate distribution percentiles (e.g., set cap = 95th percentile of absolute funding rates).

---

## Infrastructure

### technicals/ module is a stub
- **Status:** Only `__init__.py` exists. SMA/BB regime detection still lives in `sma-prediction/trading_strategy.py`
- **Impact:** Technical signal is mocked (hardcoded 0.0) in composite scoring
- **Fix:** Extract `make_optimized_trading_decision` from `sma-prediction/trading_strategy.py`, wrap to output -1 to +1 score

### Pipeline orchestrator only handles sentiment
- **Status:** `pipeline/orchestrator.py` runs the sentiment pipeline (news fetch -> classify -> aggregate). Does not orchestrate derivatives/on-chain/composite.
- **Impact:** Full pipeline requires manual CLI steps. No automated 5-min loop for all signals.
- **Fix:** Extend orchestrator to call all collectors -> signal generators -> composite scorer in a unified tick.

### No automated scheduling
- **Status:** All scripts are manual CLI invocations
- **Impact:** Need to manually run fetch/score scripts
- **Fix:** Add cron job or persistent daemon that runs the full pipeline every 5 minutes
