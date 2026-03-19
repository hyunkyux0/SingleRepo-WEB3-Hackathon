"""Data processing functions for the news sentiment pipeline.

Handles deduplication, keyword-based pre-filtering, and SQLite persistence
via the shared :class:`utils.db.DataStore`.

Note: News fetching is handled exclusively by ``scripts/fetch_news.py``.
This module only processes articles it receives.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from news_sentiment.models import ArticleInput, ClassificationOutput
from utils.db import DataStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# High-impact keywords used for catalyst detection and relevance scoring
# ---------------------------------------------------------------------------

HIGH_IMPACT_KEYWORDS: set[str] = {
    "partnership",
    "hack",
    "sec",
    "etf",
    "listing",
    "launch",
    "upgrade",
    "exploit",
    "breach",
    "acquisition",
}

# Additional sector-related keywords that boost relevance
SECTOR_KEYWORDS: set[str] = {
    "gpu",
    "nvidia",
    "defi",
    "tvl",
    "lending",
    "dex",
    "yield",
    "staking",
    "layer 1",
    "l1",
    "rollup",
    "zk",
    "meme",
    "memecoin",
    "nft",
    "ai",
    "compute",
    "mining",
    "halving",
    "fork",
    "airdrop",
    "regulation",
    "compliance",
}

# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------


def load_sector_map(path: str) -> dict[str, Any]:
    """Load the token-to-sector mapping from *path*.

    Args:
        path: Filesystem path to ``config/sector_map.json``.

    Returns:
        Parsed JSON object mapping ``"TICKER/USD"`` to sector info.
    """
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Dict-to-model conversion
# ---------------------------------------------------------------------------


def dict_to_article(d: dict[str, Any]) -> ArticleInput:
    """Convert a raw article dict (from scripts/fetch_news.py) to ArticleInput.

    Args:
        d: Dict with keys: id, timestamp, source, headline, body_snippet,
           url, mentioned_tickers, source_sentiment.

    Returns:
        An :class:`ArticleInput` instance.
    """
    ts_raw = d.get("timestamp", "")
    try:
        ts = datetime.fromisoformat(ts_raw)
    except (ValueError, TypeError):
        ts = datetime.now(tz=timezone.utc)

    return ArticleInput(
        id=d.get("id", hashlib.sha256(str(d).encode()).hexdigest()[:16]),
        timestamp=ts,
        source=d.get("source", "unknown"),
        headline=d.get("headline", ""),
        body_snippet=d.get("body_snippet", ""),
        url=d.get("url", ""),
        mentioned_tickers=d.get("mentioned_tickers", []),
        source_sentiment=d.get("source_sentiment"),
    )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity between two strings based on word tokens.

    Args:
        a: First string.
        b: Second string.

    Returns:
        Jaccard similarity coefficient (0.0 to 1.0).
    """
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def deduplicate(
    articles: list[ArticleInput], db: DataStore
) -> list[ArticleInput]:
    """Remove duplicate articles.

    Deduplication uses three strategies:

    1. **Exact URL match** against articles already stored in the database.
    2. **Headline similarity** via Jaccard coefficient > 0.7 against the
       last 200 articles in the database.
    3. **Headline similarity** within the incoming batch.

    Args:
        articles: Incoming articles to deduplicate.
        db: An open :class:`DataStore` for checking existing URLs and headlines.

    Returns:
        Deduplicated list of articles.
    """
    if not articles:
        return []

    # 1. Remove articles whose URL already exists in DB
    existing_urls: set[str] = set()
    rows = db.fetchall("SELECT url FROM articles WHERE url != ''")
    for row in rows:
        existing_urls.add(row["url"])

    unique: list[ArticleInput] = []
    for art in articles:
        if art.url and art.url in existing_urls:
            continue
        unique.append(art)

    # 2. Fetch recent DB headlines for Jaccard comparison
    db_headlines: list[str] = []
    recent_rows = db.fetchall(
        "SELECT headline FROM articles ORDER BY timestamp DESC LIMIT 200"
    )
    for row in recent_rows:
        if row["headline"]:
            db_headlines.append(row["headline"])

    # 3. Remove near-duplicates against DB + within batch (Jaccard > 0.7)
    deduped: list[ArticleInput] = []
    for art in unique:
        is_dup = False
        # Check against DB headlines
        for db_hl in db_headlines:
            if _jaccard_similarity(art.headline, db_hl) > 0.7:
                is_dup = True
                break
        # Check against already-kept batch articles
        if not is_dup:
            for kept in deduped:
                if _jaccard_similarity(art.headline, kept.headline) > 0.7:
                    is_dup = True
                    break
        if not is_dup:
            deduped.append(art)

    removed = len(articles) - len(deduped)
    if removed > 0:
        logger.info("Deduplication removed %d articles (%d -> %d)", removed, len(articles), len(deduped))

    return deduped


# ---------------------------------------------------------------------------
# Keyword pre-filter
# ---------------------------------------------------------------------------


def keyword_prefilter(
    articles: list[ArticleInput], sector_map: dict[str, Any]
) -> list[ArticleInput]:
    """Score relevance and flag catalysts using keyword matching.

    For each article:

    - Check headline for token names/tickers from *sector_map*.
    - Check for sector-related keywords (GPU, NVIDIA, DeFi, TVL, etc.).
    - Check for high-impact keywords (partnership, hack, SEC, ETF, ...).
    - Set ``relevance_score`` (0-1), ``is_catalyst``, ``matched_sectors``,
      ``mentioned_tickers``.
    - Filter out articles with ``relevance_score < 0.1``.

    Args:
        articles: Articles to score and filter.
        sector_map: Parsed ``config/sector_map.json``.

    Returns:
        Filtered list with relevance annotations populated.
    """
    # Build lookup structures from sector_map
    # sector_map keys are like "BTC/USD" -> {"primary": "l1_infra", ...}
    ticker_to_sectors: dict[str, list[str]] = {}
    all_tickers: set[str] = set()

    for pair, info in sector_map.items():
        ticker = pair.split("/")[0].upper()
        all_tickers.add(ticker)
        sectors: list[str] = []
        if info.get("primary"):
            sectors.append(info["primary"])
        if info.get("secondary"):
            sectors.append(info["secondary"])
        ticker_to_sectors[ticker] = sectors

    # Build word-boundary regex patterns for each ticker to avoid
    # false positives (e.g. single-char ticker "S" matching inside "sports").
    ticker_patterns: dict[str, re.Pattern[str]] = {}
    for ticker in all_tickers:
        ticker_patterns[ticker] = re.compile(
            r"\b" + re.escape(ticker.lower()) + r"\b"
        )

    filtered: list[ArticleInput] = []

    for art in articles:
        headline_lower = art.headline.lower()
        body_lower = art.body_snippet.lower() if art.body_snippet else ""

        score = 0.0
        matched_sectors: set[str] = set()
        mentioned_tickers: list[str] = list(art.mentioned_tickers)  # preserve existing
        is_catalyst = False

        # 1. Check for token tickers in headline using word-boundary matching
        for ticker, pattern in ticker_patterns.items():
            if pattern.search(headline_lower):
                score += 0.3
                if ticker not in mentioned_tickers:
                    mentioned_tickers.append(ticker)
                for sector in ticker_to_sectors.get(ticker, []):
                    matched_sectors.add(sector)

        # 2. Check for sector keywords
        combined_text = headline_lower + " " + body_lower
        for kw in SECTOR_KEYWORDS:
            if kw in combined_text:
                score += 0.15
                break  # count sector keyword match once

        # 3. Check for high-impact keywords
        found_high_impact = False
        for kw in HIGH_IMPACT_KEYWORDS:
            if kw in combined_text:
                score += 0.25
                found_high_impact = True
                break  # count high-impact match once

        # 4. Catalyst detection: high-impact keyword + mentioned ticker
        if found_high_impact and mentioned_tickers:
            is_catalyst = True
            score += 0.2

        # 5. Baseline relevance for crypto-related content
        crypto_terms = {"crypto", "bitcoin", "ethereum", "blockchain", "token", "coin", "web3"}
        if any(term in combined_text for term in crypto_terms):
            score += 0.1

        # Clamp score to [0, 1]
        score = min(1.0, score)

        # Filter out low-relevance articles
        if score < 0.1:
            continue

        # Update article fields
        art_updated = art.model_copy(
            update={
                "relevance_score": score,
                "is_catalyst": is_catalyst,
                "matched_sectors": sorted(matched_sectors),
                "mentioned_tickers": mentioned_tickers,
            }
        )
        filtered.append(art_updated)

    removed = len(articles) - len(filtered)
    logger.info(
        "Keyword pre-filter: %d -> %d articles (removed %d, catalysts: %d)",
        len(articles),
        len(filtered),
        removed,
        sum(1 for a in filtered if a.is_catalyst),
    )
    return filtered


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------


def store_articles(articles: list[ArticleInput], db: DataStore) -> int:
    """Insert articles into the SQLite ``articles`` table.

    Existing articles (by ``id``) are silently skipped via
    ``INSERT OR IGNORE``.

    Args:
        articles: Articles to store.
        db: An open :class:`DataStore`.

    Returns:
        Number of rows actually inserted.
    """
    if not articles:
        return 0

    sql = """
        INSERT OR IGNORE INTO articles (
            id, timestamp, source, headline, body_snippet, url,
            mentioned_tickers, source_sentiment, relevance_score,
            is_catalyst, matched_sectors, processed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
    """

    rows_before = db.fetchone("SELECT COUNT(*) AS cnt FROM articles")
    count_before = rows_before["cnt"] if rows_before else 0

    params_seq = [
        (
            art.id,
            art.timestamp.isoformat(),
            art.source,
            art.headline,
            art.body_snippet,
            art.url,
            json.dumps(art.mentioned_tickers),
            art.source_sentiment,
            art.relevance_score,
            art.is_catalyst,
            json.dumps(art.matched_sectors),
        )
        for art in articles
    ]

    db.executemany(sql, params_seq)
    db.commit()

    rows_after = db.fetchone("SELECT COUNT(*) AS cnt FROM articles")
    count_after = rows_after["cnt"] if rows_after else 0
    inserted = count_after - count_before

    logger.info("store_articles: inserted %d of %d articles", inserted, len(articles))
    return inserted


def get_unprocessed_articles(db: DataStore) -> list[ArticleInput]:
    """Query SQLite for articles with ``processed = 0``.

    Args:
        db: An open :class:`DataStore`.

    Returns:
        List of :class:`ArticleInput` objects awaiting LLM classification.
    """
    rows = db.fetchall(
        "SELECT * FROM articles WHERE processed = 0 ORDER BY timestamp ASC"
    )

    articles: list[ArticleInput] = []
    for row in rows:
        try:
            tickers = json.loads(row["mentioned_tickers"]) if row["mentioned_tickers"] else []
            sectors = json.loads(row["matched_sectors"]) if row["matched_sectors"] else []

            articles.append(
                ArticleInput(
                    id=row["id"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    source=row["source"],
                    headline=row["headline"],
                    body_snippet=row["body_snippet"] or "",
                    url=row["url"] or "",
                    mentioned_tickers=tickers,
                    source_sentiment=row["source_sentiment"],
                    relevance_score=row["relevance_score"] or 0.0,
                    is_catalyst=bool(row["is_catalyst"]),
                    matched_sectors=sectors,
                )
            )
        except Exception:
            logger.exception("Failed to parse article row id=%s", row["id"])
            continue

    logger.info("get_unprocessed_articles: found %d articles", len(articles))
    return articles


def mark_processed(
    article_id: str,
    classification: ClassificationOutput,
    db: DataStore,
) -> None:
    """Update an article row with LLM classification results and mark processed.

    Args:
        article_id: The article's primary key.
        classification: The LLM classification output to persist.
        db: An open :class:`DataStore`.
    """
    sql = """
        UPDATE articles SET
            processed = 1,
            llm_sector = ?,
            llm_secondary_sector = ?,
            llm_sentiment = ?,
            llm_magnitude = ?,
            llm_confidence = ?,
            llm_cross_market = ?,
            llm_reasoning = ?
        WHERE id = ?
    """
    db.execute(
        sql,
        (
            classification.primary_sector,
            classification.secondary_sector,
            classification.sentiment,
            classification.magnitude,
            classification.confidence,
            classification.cross_market,
            classification.reasoning,
            article_id,
        ),
    )
    db.commit()
    logger.debug("Marked article %s as processed (sector=%s)", article_id, classification.primary_sector)
