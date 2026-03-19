# pipeline

Unified tick scheduler coordinating the full sentiment pipeline. The `SentimentPipeline` class orchestrates news fetching, LLM classification (fast and batch paths), and signal aggregation on a configurable interval.

## Files

### orchestrator.py

**SentimentPipeline class:**

```python
from pipeline.orchestrator import SentimentPipeline
from pathlib import Path

with SentimentPipeline(db_path=Path("data/trading_bot.db")) as pipeline:
    signal_set = pipeline.tick()  # returns SectorSignalSet
```

**Constructor parameters:**
- `db_path` -- SQLite database path (default: `data/trading_bot.db`)
- `sector_map_path` -- Path to `config/sector_map.json`
- `sector_config_path` -- Path to `config/sector_config.json`
- `sources_config_path` -- Path to `config/sources.json`
- `batch_interval_min` -- Minutes between batch LLM runs (default: 30)

**Lifecycle:**
- `open()` -- Opens DataStore, loads all config files
- `close()` -- Commits and closes the database
- Supports context manager (`with ... as pipeline:`)

**Tick flow (7 steps):**

```
1. Fetch       -- fetch_all_sources() from CryptoPanic + RSS feeds
2. Deduplicate -- URL match vs DB + Jaccard headline similarity
3. Pre-filter  -- keyword_prefilter() scores relevance, detects catalysts
4. Store       -- INSERT OR IGNORE into SQLite articles table
5. Fast path   -- classify_article_fast() for catalyst articles (immediate)
6. Batch path  -- classify_article_batch() + score_article_batch() for
                  unprocessed backlog (runs every batch_interval_min)
7. Aggregate   -- compute_sector_signals() produces SectorSignalSet
```

**Batch timing:**
- Batch processing runs on the first tick and then every `batch_interval_min` (default: 30 minutes)
- `_batch_due()` compares elapsed time since last batch run
- The fast path runs on every tick regardless of batch timing

**RateLimiter class:**
- Simple token-bucket rate limiter: one call per `60 / calls_per_minute` seconds
- Default: 20 calls/minute for batch LLM processing
- `wait()` blocks until enough time has elapsed since the last call

**Metadata/logging output:**
Each tick appends metadata to the `SectorSignalSet`:
- `articles_fetched`, `articles_after_dedup`, `articles_after_filter`, `articles_stored`
- `catalysts_detected`, `fast_path_classified`, `batch_processed`
- `llm_calls`, `processing_time_ms`

## Integration with Trading Bot

The trading bot calls `pipeline.tick()` on a 5-minute interval. The returned `SectorSignalSet` is converted to per-asset sentiment scores via `composite/adapters.py` and then fed into the composite scorer alongside technical, derivatives, and on-chain signals.
