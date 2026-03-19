# Evidence-Based Sentiment Pipeline v2 — Design Specification

> **Date**: 2026-03-19
> **Status**: Approved
> **Scope**: Refactor the sentiment scoring pipeline from per-article LLM scoring to per-sector evidence-based scoring. Improve news fetching and deduplication.

---

## 1. Problem Statement

The current sentiment pipeline has three issues:

1. **Scoring is opinion-based**: The LLM generates sentiment scores with zero market context — no prices, no funding rates, no on-chain data. It guesses magnitude from the headline alone.
2. **Per-article scoring is expensive**: 201 LLM calls for 110 articles (2 calls each for batch path: classify + score). Most of this cost is in scoring, not classification.
3. **Poor sector discrimination**: 20% of articles land in the "other" bucket. CryptoPanic fetches only 5 "hot" posts instead of all recent posts.

## 2. Goals & Metrics

Priority order: **Direction accuracy > Sector accuracy > Magnitude calibration**

### news_sentiment (Sector Classification)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Sector accuracy | >80% | Hand-label 50 articles, compare to LLM output |
| "Other" bucket rate | <15% | Count from pipeline output (currently ~20%) |
| Cross-sector confusion | <5% | Articles about BTC classified as "meme" etc. |
| Catalyst precision | >70% | Of flagged catalysts, how many cite specific events |

### sentiment_score (Evidence-Based Sector Scoring)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Direction accuracy | >55% | Compare sentiment sign vs. actual sector price move 4-24h later |
| Magnitude correlation | r > 0.1 | Abs(sentiment) vs. abs(price change) |
| No-signal reliability | Higher vol with signal | Sectors with signal should show more price movement than those without |
| Evidence grounding | >90% | LLM reasoning must reference at least one market context input |

Evaluation method: QA + LLM-as-a-judge (to be refined separately).

Prompt refinement for sector classification is flagged for a separate iteration.

---

## 3. Architecture Change

```
BEFORE:
  For each article -> classify sector (LLM) -> score sentiment (LLM) -> aggregate
  = 2 LLM calls per article = ~201 calls for 110 articles

AFTER:
  For each article -> classify sector (LLM, unchanged)
  For each sector  -> deterministic summary + evidence -> score sector (1 LLM call)
  = ~110 classify + 6 score = ~116 calls (42% reduction)
```

### Module Responsibilities

**scripts/fetch_news.py** (data fetching — sole source):
- CryptoPanic API: remove `filter=hot`, fetch all recent posts
- RSS feeds: unchanged (CoinDesk, CoinTelegraph, Decrypt)
- Age cutoff: discard articles older than 24h at parse time
- Frequency: CryptoPanic every 5 min, RSS every 15 min

**news_sentiment/** (classification only — no scoring):
- `processors.py`: deduplicate, keyword prefilter, SQLite persistence, `dict_to_article()`
- `prompter.py`: `classify_article_fast()` (catalysts), `classify_article_batch()` (rest)
- Batch path classifies sector only, never scores sentiment
- No fetching — receives articles from orchestrator

**sentiment_score/** (evidence-based sector scoring):
- `processors.py`: `build_sector_summary()` (deterministic), `gather_evidence()` (prices/funding), aggregation math
- `prompter.py`: `score_sector()` — ONE LLM call per sector with article summaries + market evidence
- Replaces the per-article `score_article_batch()`

**pipeline/orchestrator.py** (tick coordinator):
- Calls `scripts/fetch_news` for data
- Calls `news_sentiment` for classification
- Calls `sentiment_score` for evidence-based sector scoring
- Returns `SectorSignalSet`

---

## 4. Fetching Changes

### CryptoPanic API

Current: `?filter=hot&public=true` — returns ~5 curated posts spanning days.
New: `?public=true` (no filter) — returns 20 most recent posts in a ~6 minute window.

Free tier ("developer" plan) limitations:
- 20 results per page, no pagination
- Fields: `title`, `description`, `published_at`, `created_at`, `kind`
- No `currencies`, `votes`, or `url` fields (require paid plan)

API endpoint: `https://cryptopanic.com/api/developer/v2/posts/`

### Fetch Frequency

| Source | Frequency | Rationale |
|--------|-----------|-----------|
| CryptoPanic | Every 5 min | Fast-changing 6-min window, aligns with tick interval |
| RSS feeds | Every 15 min | Content updates every 30-60 min; no point hitting more often |

Orchestrator tracks `_last_rss_fetch` separately from tick interval. CryptoPanic fetched every tick, RSS fetched when >= 15 min since last RSS fetch.

### Age Cutoff

Articles older than 24 hours are discarded at fetch time. The longest sector lookback (store_of_value, 72h) accumulates articles across ticks in the DB over time.

### Deduplication Improvements

| Layer | Current | New |
|-------|---------|-----|
| URL match | Against DB | Unchanged |
| Headline Jaccard > 0.7 | Within batch only | **Extended: also check against last 200 articles in DB** |
| Staleness | Not handled | **Discard > 24h at fetch time** |

---

## 5. Sector Summary (Deterministic)

New function `build_sector_summary()` in `sentiment_score/processors.py`.

No LLM — purely deterministic aggregation of classified articles for a sector.

### Input

All processed articles in the DB for a given sector within the lookback window.

### Output

```python
{
    "sector": "ai_compute",
    "article_count": 8,
    "velocity": "accelerating",    # based on article count in current vs previous window
    "top_headlines": [
        {
            "headline": "NVIDIA announces new AI training chip partnership",
            "snippet": "NVIDIA revealed a partnership with...",  # empty string if unavailable
            "source": "rss_coindesk",
            "tickers": ["FET", "NVDA"],
            "age_hours": 2.3,
            "is_catalyst": false,
        },
        ...  # up to 10, ranked by relevance_score descending
    ],
    "mentioned_tickers": {"FET": 4, "TAO": 2, "NVDA": 1},
    "catalyst_count": 1,
}
```

### Velocity Computation

```
articles_current_window = count in [now - lookback, now]
articles_previous_window = count in [now - 2*lookback, now - lookback]

if current > previous * 1.5: "accelerating"
elif current < previous * 0.5: "decelerating"
else: "steady"
```

### Headline Selection

Query: `SELECT * FROM articles WHERE processed=1 AND llm_sector=? AND timestamp >= ? ORDER BY relevance_score DESC LIMIT 10`. Uses `llm_sector` (post-LLM classification) not `matched_sectors` (pre-filter guess).

The `tickers` field per headline comes from `mentioned_tickers` column in the DB (populated by keyword prefilter from headline matching). Include `body_snippet` when available (RSS articles have it, CryptoPanic free tier does not).

---

## 6. Evidence Gathering

New function `gather_evidence()` in `sentiment_score/processors.py`.

### Function Signature

```python
def gather_evidence(sector: str, sector_map: dict, sector_summary: dict,
                    previous_signals: dict | None) -> dict:
```

- `sector_map`: parsed `config/sector_map.json` — used to find which tokens belong to this sector
- `sector_summary`: output of `build_sector_summary()` — `mentioned_tickers` used for token selection
- `previous_signals`: dict mapping sector -> previous sentiment score, stored in-memory on the `SentimentPipeline` instance (`self._previous_signals`). `None` on first tick (defaults to 0.0).

### Token Selection

Tokens for price lookup selected by: filter `sector_map` entries where `primary == sector`, take up to 5. If `sector_summary.mentioned_tickers` names tokens not in the sector, they're noted but not priced.

### Price Fetching

A new utility function `fetch_current_prices(tickers: list[str]) -> list[dict]` in `sentiment_score/processors.py` calls the Kraken API directly (simple REST call to `/0/public/Ticker?pair=FETUSD`). This does NOT use `sma-prediction/prices.py` (which fetches OHLC history). Returns `[{"ticker": "FET", "price": 1.42, "change_24h_pct": 5.1}]`. On API failure, returns empty list — the scoring prompt omits the prices section and the LLM scores based on news + velocity + previous sentiment only.

### Required Signals

| Signal | Source | Always available |
|--------|--------|:---:|
| Token prices + 24h change | Kraken REST API (new function) | Best-effort (graceful fallback) |
| Article count + velocity | Computed from `build_sector_summary()` | Yes |
| Previous sentiment score | In-memory on `SentimentPipeline` (`self._previous_signals`) | Yes (0.0 on first tick) |

### Nice-to-Have Signals

| Signal | Source | Available if |
|--------|--------|-------------|
| Funding rate | `derivatives/` module | Module has been populated |
| NUPL | `on_chain/` module | Module has been populated |
| Exchange net flow | `on_chain/` module | Module has been populated |

Nice-to-have signals are included when available, gracefully omitted when not. The scoring prompt adapts its market context section accordingly.

### Output

```python
{
    "token_prices": [
        {"ticker": "FET", "price": 1.42, "change_24h_pct": 5.1},
        {"ticker": "TAO", "price": 380.0, "change_24h_pct": -2.0},
    ],
    "funding_rate": 0.012,         # None if unavailable
    "previous_sentiment": -0.15,
    "nupl": 0.65,                  # None if unavailable
    "exchange_net_flow": "inflow", # None if unavailable
}
```

Token prices fetched for the top tokens in the sector (by market cap or by mention frequency in articles). Maximum 5 tokens per sector to keep the prompt concise.

---

## 7. Evidence-Based Scoring Prompt

Replaces `score_article_batch()` with `score_sector()`. ONE call per sector.

### System Prompt

```
You are scoring the net sentiment for a crypto sector.
Your score will be used as ONE input to a quantitative trading system.
Score conservatively — only strong, clear signals should produce extreme values.

Scoring rules:
- Score from -1.0 (extremely bearish) to +1.0 (extremely bullish)
- Score reflects expected NET price impact on this sector over the next 1-7 days
- Consider how news interacts with current market state:
  * Bullish news + already overleveraged long (high funding) = weaker signal
  * Bearish news + market already down significantly = potential reversal
  * High article velocity on same topic = stronger signal
  * Multiple independent bullish/bearish stories = stronger than a single story
- magnitude: low (<2% expected move), medium (2-8%), high (>8%)
- Your reasoning MUST reference at least one piece of market context evidence

Output JSON only:
{
  "sentiment": <float -1.0 to 1.0>,
  "magnitude": "<low|medium|high>",
  "confidence": <float 0 to 1>,
  "key_driver": "<the single most important factor driving the score>",
  "reasoning": "<2-3 sentences explaining score, referencing market context>"
}
```

### User Prompt Template

```
Sector: {sector}

=== Market Context ===
Sector tokens: {token_prices_formatted}
Article velocity: {article_count} articles in last {lookback}h ({velocity})
Previous sentiment score: {previous_sentiment}
{optional: Funding rate: {funding_rate}% ({interpretation})}
{optional: NUPL: {nupl} ({interpretation})}

=== News Events ({article_count} articles) ===
{for each headline in top_headlines:}
{i}. [{source}, {age_hours}h ago] {headline}
   {if snippet:} -> {snippet}
{endfor}

Score the net sentiment impact on the {sector} sector.
```

### Prompt Adaptation

The market context section is built dynamically:
- Velocity and previous sentiment always included (computed locally, cannot fail)
- Token prices included when Kraken API responds; omitted on failure (the LLM can still score based on news + velocity + previous sentiment)
- Optional fields (funding, NUPL, exchange flow) included only when non-None
- This avoids the LLM seeing "Funding rate: None" which could confuse it
- The scoring rules prompt says "MUST reference at least one piece of market context" — velocity and previous sentiment are always available, so this constraint is always satisfiable

---

## 8. Model Changes

### SectorSignal (updated)

Two new fields added:

```python
class SectorSignal(BaseModel):
    sector: str
    sentiment: float
    momentum: float
    catalyst_active: bool = False
    catalyst_details: dict | None = None
    article_count: int = 0
    confidence: float = 0.0
    key_driver: str = ""     # NEW
    reasoning: str = ""      # NEW
```

Downstream consumers (`composite/adapters.py`, `composite/scorer.py`) unaffected — they only read `sentiment`, `momentum`, `catalyst_active`, `confidence`.

---

## 9. Pipeline Orchestrator Changes

### New tick() Flow

```
tick():
  1. Fetch news (scripts/fetch_news — sole fetching layer)
     - CryptoPanic: every tick (5 min), no filter
     - RSS: every 15 min (tracked via self._last_rss_fetch)
     - Orchestrator calls fetch_all(sources=["cryptopanic"]) every tick,
       and fetch_all(sources=["cryptopanic", "rss"]) when RSS is due.
  2. Convert raw dicts to ArticleInput (via dict_to_article)
  3. Deduplicate against DB (URL + Jaccard against last 200)
  4. Keyword prefilter
  5. Store to SQLite
  6. Classify all articles into sectors:
     - Fast path: catalysts → classify_article_fast (sector + sentiment in one call)
     - Batch path: rest → classify_article_batch (sector only, sentiment=0.0)
  7. For each of the 6 sectors:
     a. build_sector_summary() — deterministic, from DB
     b. gather_evidence() — prices via Kraken, funding/NUPL if available
     c. score_sector() — ONE LLM call with summary + evidence
     (This REPLACES per-article scoring. Fast-path articles' individual sentiment
      is discarded — the sector-level score overrides it for consistency.)
  8. Build SectorSignalSet from score_sector outputs
  9. Store self._previous_signals for next tick's momentum/evidence
  10. Return SectorSignalSet
```

### Fast-Path vs Sector Scoring

Fast-path `classify_article_fast()` still returns per-article sentiment (for catalyst detection purposes), but this sentiment is NOT used as the sector score. The sector-level `score_sector()` produces the authoritative sentiment. Fast-path sentiment is only used to detect catalysts (magnitude=high AND |sentiment| > threshold within 30 min).

### Deprecation of score_article_batch

`score_article_batch()` in `sentiment_score/prompter.py` is **deprecated and no longer called** by the orchestrator. It is kept in the codebase for backward compatibility but may be removed in a future cleanup. Existing tests for `score_article_batch` remain valid as unit tests of that function — they do not need to be deleted.

### classify_article_batch Behavior

`classify_article_batch()` already returns `sentiment=0.0` and `magnitude="low"` — this is correct and intentional. No change to `ClassificationOutput` model. The orchestrator simply does not use these fields from batch-classified articles.

### LLM Call Budget

| Step | Calls | Model |
|------|-------|-------|
| Fast classify (catalysts) | ~15-20 per tick | GPT-5.4 Nano |
| Batch classify (rest) | ~80-100 per batch (every 30 min) | GPT-5.4 Nano |
| Score sectors | 6 per tick | GPT-5.4 Nano |
| **Total per tick** | **~21-26** | |
| **Total per batch tick** | **~101-126** | |

vs. current: ~201 per batch tick. **42% reduction**.

---

## 10. Files Changed

| File | Change |
|------|--------|
| `scripts/fetch_news.py` | Remove `filter=hot` from CryptoPanic, add 24h age cutoff |
| `news_sentiment/processors.py` | Extend Jaccard dedup to check last 200 DB articles |
| `sentiment_score/models.py` | Add `key_driver` and `reasoning` to `SectorSignal` |
| `sentiment_score/processors.py` | Add `build_sector_summary()`, `gather_evidence()`. Refactor `compute_sector_signals()` to use new scoring |
| `sentiment_score/prompter.py` | Replace `score_article_batch()` with `score_sector()` |
| `pipeline/orchestrator.py` | Update tick() to: skip per-article scoring, add sector summary + evidence + score_sector loop. Add per-source fetch tracking. |
| `config/sources.json` | Already updated (CryptoPanic base_url fixed) |

### Files NOT Changed

| File | Why |
|------|-----|
| `news_sentiment/prompter.py` | Classification prompts unchanged (refinement flagged for later) |
| `news_sentiment/models.py` | ArticleInput, ClassificationOutput unchanged |
| `composite/adapters.py` | Reads same SectorSignal fields |
| `composite/scorer.py` | Unchanged — deterministic scoring stays |

---

## 11. Flagged for Later

- **Sector classification prompt refinement**: Improve discrimination to reduce "other" bucket. Separate design iteration.
- **Evaluation framework**: QA + LLM-as-a-judge for systematic prompt quality measurement.
- **CryptoPanic paid tier evaluation**: Would give us `currencies`, `votes`, `url` fields and pagination.
