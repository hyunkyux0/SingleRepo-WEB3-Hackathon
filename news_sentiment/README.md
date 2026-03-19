# news_sentiment

News ingestion, deduplication, keyword pre-filtering, and LLM-based sector classification. This module is the first stage of the sentiment pipeline: it transforms raw news feeds into classified, sector-tagged articles stored in SQLite.

## Architecture

```
                          +------------------+
                          |  CryptoPanic API |
                          +--------+---------+
                                   |
                          +--------+---------+
                          |   RSS Feeds      |
                          |  (CoinDesk,      |
                          |   CoinTelegraph, |
                          |   Decrypt)       |
                          +--------+---------+
                                   |
                          fetch_all_sources()
                                   |
                                   v
                          +--------+---------+
                          |   Deduplicate    |
                          |  (URL + Jaccard  |
                          |   headline sim)  |
                          +--------+---------+
                                   |
                          keyword_prefilter()
                                   |
                                   v
                          +--------+---------+
                          |  store_articles  |
                          |  (SQLite)        |
                          +--------+---------+
                                   |
                    +--------------+--------------+
                    |                             |
              is_catalyst?                  batch backlog
                    |                             |
                    v                             v
          classify_article_fast()     classify_article_batch()
          (single-shot: sector +      (sector only; sentiment
           sentiment + magnitude)      scored separately in
                    |                  sentiment_score module)
                    v                             |
              mark_processed()           mark_processed()
```

## Files

### models.py

**ArticleInput** -- Normalized article from any source:
- `id`, `timestamp`, `source`, `headline`, `body_snippet`, `url`
- `mentioned_tickers` (list), `source_sentiment` (float, from CryptoPanic votes)
- `relevance_score`, `is_catalyst`, `matched_sectors` (populated by keyword_prefilter)

**ClassificationOutput** -- LLM classification result:
- `primary_sector`, `secondary_sector`
- `sentiment` (-1.0 to 1.0), `magnitude` (low/medium/high)
- `confidence` (0-1), `cross_market` (bool), `reasoning`

### processors.py

Ten public functions:

| Function | Purpose |
|----------|---------|
| `load_sector_map(path)` | Load `config/sector_map.json` |
| `load_sources_config(path)` | Load `config/sources.json` |
| `fetch_cryptopanic(config)` | Fetch from CryptoPanic API (hot posts, public) |
| `fetch_rss(config)` | Fetch from a single RSS feed |
| `fetch_all_sources(sources_config)` | Parallel fetch from all enabled sources |
| `deduplicate(articles, db)` | Remove duplicates: exact URL match (vs DB) + Jaccard headline similarity > 0.7 (within batch) |
| `keyword_prefilter(articles, sector_map)` | Score relevance, detect catalysts, filter out articles with relevance < 0.1 |
| `store_articles(articles, db)` | INSERT OR IGNORE into SQLite `articles` table |
| `get_unprocessed_articles(db)` | Query articles where `processed = 0` |
| `mark_processed(article_id, classification, db)` | Write LLM results and set `processed = 1` |

**Keyword prefilter scoring:**
- Token ticker match in headline: +0.3
- Sector keyword match (gpu, defi, tvl, etc.): +0.15
- High-impact keyword (partnership, hack, SEC, ETF, listing, etc.): +0.25
- Catalyst detection (high-impact + ticker match): +0.2
- Crypto baseline terms: +0.1
- Articles scoring below 0.1 are discarded

### prompter.py

Two LLM classification paths:

**Fast path (`classify_article_fast`):**
- Uses `call_llm(fast=True)` -- routed to `OPENROUTER_MODEL_FAST`
- Single-shot: returns sector + sentiment + magnitude + confidence + reasoning in one call
- Used for catalyst articles that need immediate classification
- Retries once on JSON parse failure, then falls back to default "other" classification

**Batch path (`classify_article_batch`):**
- Uses `call_llm(fast=False)` -- routed to `OPENROUTER_MODEL` (e.g., Hunter Alpha)
- Classification only: returns sector + confidence + cross_market
- Sentiment scoring happens separately in the `sentiment_score` module (step 2)
- Same retry behavior as fast path

Both paths validate sector output against the set: `{l1_infra, defi, ai_compute, meme, store_of_value, other}`. Unknown sectors are mapped to "other".
