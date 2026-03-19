# sentiment_score

Per-sector signal aggregation from LLM-classified articles. Takes processed articles from the database, applies temporal decay and source/magnitude weighting, computes per-sector sentiment, momentum, confidence, and catalyst status, and produces a `SectorSignalSet` consumed by the pipeline orchestrator.

## Files

### models.py

**ScoredArticle** -- Article with computed weights:
- `article_id`, `timestamp`, `primary_sector`
- `sentiment` (-1.0 to 1.0), `magnitude` (low/medium/high)
- `source`, `source_weight`, `decay_weight`

**SectorSignal** -- Aggregated signal for one sector:
- `sector`, `sentiment` (weighted average, -1 to 1)
- `momentum` (rate of change vs previous window)
- `catalyst_active` (bool), `catalyst_details` (dict)
- `article_count`, `confidence`

**SectorSignalSet** -- Complete output at a point in time:
- `timestamp`, `sectors` (dict mapping sector name to SectorSignal), `metadata`

### processors.py

Core aggregation logic:

**Weight system:**
- Source weights: cryptopanic=1.0, rss_*=0.8, twitter=0.6, reddit=0.4, default=0.5
- Magnitude weights: high=3.0, medium=1.0, low=0.3
- Temporal decay: `exp(-decay_lambda * hours_elapsed)`, where `decay_lambda` varies by sector

**Aggregation formula (weighted sentiment):**
```
For each article i:
    w_i = decay_weight_i * source_weight_i * magnitude_weight_i

weighted_sentiment = sum(sentiment_i * w_i) / sum(w_i)
```

**Key functions:**

| Function | Purpose |
|----------|---------|
| `compute_decay(hours, lambda)` | Exponential decay: `exp(-lambda * hours)` |
| `get_source_weight(source)` | Credibility weight by source name |
| `get_magnitude_weight(magnitude)` | Multiplier by magnitude level |
| `build_scored_articles(db, sector, lookback)` | Query DB, compute weights for each article |
| `aggregate_sector_signal(scored, sector, config, db)` | Full signal: sentiment + momentum + catalyst + confidence |
| `compute_sector_signals(db, sector_config)` | Iterate all 6 sectors, return SectorSignalSet |

**Momentum computation:**
- Current window: `[now - lookback, now]`
- Previous window: `[now - 2*lookback, now - lookback]`
- Momentum = current_sentiment - previous_sentiment

**Catalyst detection criteria:**
- Article magnitude = "high"
- |sentiment| > sector's catalyst_threshold
- Published within last 30 minutes

**Confidence formula:**
```
confidence = min(1.0, article_count / 10) * mean(llm_confidence)
```

### prompter.py

Batch-path step 2: sentiment scoring for articles that were classified (sector-assigned) by `news_sentiment.prompter.classify_article_batch`.

**`score_article_batch(headline, snippet, sector)`** -- Calls the batch LLM model with the article's headline, snippet, and assigned sector. Returns a dict with:
- `sentiment` (-1.0 to 1.0), `magnitude` (low/medium/high)
- `confidence` (0-1), `reasoning` (one sentence)

Retries once on JSON parse failure. Falls back to neutral (sentiment=0.0, magnitude=low) on total failure.

## Output

`SectorSignalSet` is consumed by the pipeline orchestrator (`pipeline/orchestrator.py`), which passes it downstream to the composite scoring system via the sector-to-asset adapter.
