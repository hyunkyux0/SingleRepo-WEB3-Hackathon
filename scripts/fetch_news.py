#!/usr/bin/env python3
"""Fetch crypto news from CryptoPanic and RSS feeds.

Standalone script that fetches articles, deduplicates them, and saves
raw JSON output to data/raw_news/ for inspection and downstream processing.

Usage:
    python scripts/fetch_news.py
    python scripts/fetch_news.py --sources cryptopanic
    python scripts/fetch_news.py --sources rss
    python scripts/fetch_news.py --limit 10
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import feedparser
import requests

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fetch_news")

OUTPUT_DIR = PROJECT_ROOT / "data" / "raw_news"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


def fetch_cryptopanic() -> list[dict]:
    """Fetch recent posts from the CryptoPanic API.

    Returns list of normalized article dicts.
    """
    api_key = os.getenv("CRYPTOPANIC_API_KEY", "")
    if not api_key:
        logger.warning("CRYPTOPANIC_API_KEY not set; skipping")
        return []

    # API format: /api/{plan}/v2/posts/ — "developer" is the free-tier plan name
    # No filter = all recent posts chronologically (20 per page)
    url = f"https://cryptopanic.com/api/developer/v2/posts/?auth_token={api_key}&public=true"

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("CryptoPanic API request failed")
        return []

    articles: list[dict] = []
    for item in data.get("results", []):
        try:
            ts_raw = item.get("published_at") or item.get("created_at", "")
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))

            tickers: list[str] = []
            for cur in item.get("currencies", []) or []:
                code = cur.get("code", "")
                if code:
                    tickers.append(code.upper())

            votes = item.get("votes", {}) or {}
            pos = votes.get("positive", 0)
            neg = votes.get("negative", 0)
            source_sentiment = None
            if pos + neg > 0:
                source_sentiment = round((pos - neg) / (pos + neg), 4)

            article_url = item.get("url", "") or ""
            article_id = hashlib.sha256(
                (article_url or item.get("title", "") + ts_raw).encode()
            ).hexdigest()[:16]

            articles.append({
                "id": article_id,
                "timestamp": ts.isoformat(),
                "source": "cryptopanic",
                "headline": item.get("title", ""),
                "body_snippet": (item.get("body", "") or "")[:500],
                "url": article_url,
                "mentioned_tickers": tickers,
                "source_sentiment": source_sentiment,
            })
        except Exception:
            logger.exception("Failed to parse CryptoPanic item: %s", item.get("title", ""))
            continue

    logger.info("CryptoPanic: fetched %d articles", len(articles))
    return articles


def fetch_rss(feed_url: str, source_id: str = "rss") -> list[dict]:
    """Fetch articles from an RSS feed.

    Args:
        feed_url: URL of the RSS feed.
        source_id: Identifier for this source (e.g. "rss_coindesk").

    Returns list of normalized article dicts.
    """
    try:
        feed = feedparser.parse(feed_url)
    except Exception:
        logger.exception("RSS fetch failed for %s", feed_url)
        return []

    if feed.bozo and not feed.entries:
        logger.warning("RSS feed returned no entries: %s", feed_url)
        return []

    articles: list[dict] = []
    for entry in feed.entries:
        try:
            ts: datetime
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                ts = datetime.fromtimestamp(
                    time.mktime(entry.published_parsed), tz=timezone.utc
                )
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                ts = datetime.fromtimestamp(
                    time.mktime(entry.updated_parsed), tz=timezone.utc
                )
            else:
                ts = datetime.now(tz=timezone.utc)

            headline = entry.get("title", "")
            link = entry.get("link", "")
            summary = entry.get("summary", "") or ""
            body_snippet = re.sub(r"<[^>]+>", "", summary)[:500]

            article_id = hashlib.sha256(
                (link or headline + str(ts)).encode()
            ).hexdigest()[:16]

            articles.append({
                "id": article_id,
                "timestamp": ts.isoformat(),
                "source": source_id,
                "headline": headline,
                "body_snippet": body_snippet,
                "url": link,
                "mentioned_tickers": [],
                "source_sentiment": None,
            })
        except Exception:
            logger.exception("Failed to parse RSS entry: %s", entry.get("title", ""))
            continue

    logger.info("%s: fetched %d articles", source_id, len(articles))
    return articles


# Default RSS feeds
RSS_FEEDS: list[dict[str, str]] = [
    {"url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "id": "rss_coindesk"},
    {"url": "https://cointelegraph.com/rss", "id": "rss_cointelegraph"},
    {"url": "https://decrypt.co/feed", "id": "rss_decrypt"},
]


def fetch_all(
    sources: list[str] | None = None,
) -> list[dict]:
    """Fetch from all enabled sources in parallel.

    Args:
        sources: List of source types to fetch. None = all.
                 Options: "cryptopanic", "rss"

    Returns combined list of article dicts.
    """
    all_articles: list[dict] = []
    fetch_crypto = sources is None or "cryptopanic" in sources
    fetch_rss_feeds = sources is None or "rss" in sources

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}

        if fetch_crypto:
            futures[executor.submit(fetch_cryptopanic)] = "cryptopanic"

        if fetch_rss_feeds:
            for feed in RSS_FEEDS:
                futures[executor.submit(fetch_rss, feed["url"], feed["id"])] = feed["id"]

        for future in as_completed(futures):
            source_id = futures[future]
            try:
                articles = future.result()
                all_articles.extend(articles)
            except Exception:
                logger.exception("Fetcher failed for %s", source_id)

    logger.info("Total fetched: %d articles from %d sources", len(all_articles), len(futures))
    all_articles = _filter_by_age(all_articles)
    return all_articles


# ---------------------------------------------------------------------------
# Age filter
# ---------------------------------------------------------------------------


def _filter_by_age(
    articles: list[dict], max_age_hours: float = 48,
) -> list[dict]:
    """Discard articles older than max_age_hours.

    Articles without a parseable timestamp are kept by default.

    Args:
        articles: List of article dicts.
        max_age_hours: Maximum article age in hours.

    Returns:
        Filtered list with old articles removed.
    """
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    result = []
    for art in articles:
        ts_str = art.get("timestamp", "")
        if not ts_str:
            result.append(art)
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                result.append(art)
        except (ValueError, TypeError):
            result.append(art)
    removed = len(articles) - len(result)
    if removed > 0:
        logger.info("Age filter: removed %d articles older than %.0fh", removed, max_age_hours)
    return result


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _jaccard_similarity(a: str, b: str) -> float:
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def deduplicate(articles: list[dict]) -> list[dict]:
    """Remove duplicate articles by URL and headline similarity."""
    seen_urls: set[str] = set()
    deduped: list[dict] = []

    for art in articles:
        url = art.get("url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)

        # Jaccard dedup within batch
        is_dup = False
        headline = art.get("headline", "")
        for kept in deduped:
            if _jaccard_similarity(headline, kept.get("headline", "")) > 0.7:
                is_dup = True
                break
        if not is_dup:
            deduped.append(art)

    removed = len(articles) - len(deduped)
    if removed > 0:
        logger.info("Deduplication: %d -> %d (removed %d)", len(articles), len(deduped), removed)
    return deduped


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def save_output(articles: list[dict], output_dir: Path = OUTPUT_DIR) -> Path:
    """Save articles to a timestamped JSON file in output_dir.

    Returns the path to the saved file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"news_{ts}.json"

    output = {
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "article_count": len(articles),
        "sources": list(set(a.get("source", "") for a in articles)),
        "articles": articles,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info("Saved %d articles to %s", len(articles), output_path)
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fetch crypto news articles")
    parser.add_argument(
        "--sources", nargs="+",
        choices=["cryptopanic", "rss"],
        help="Sources to fetch from (default: all)",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Limit number of articles (0 = no limit)",
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(OUTPUT_DIR),
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--no-dedup", action="store_true",
        help="Skip deduplication",
    )
    args = parser.parse_args()

    # Fetch
    articles = fetch_all(sources=args.sources)

    # Deduplicate
    if not args.no_dedup:
        articles = deduplicate(articles)

    # Limit
    if args.limit > 0:
        articles = articles[:args.limit]

    # Save
    output_path = save_output(articles, Path(args.output_dir))

    # Print summary
    print(f"\n{'='*60}")
    print(f"Fetched {len(articles)} articles")
    print(f"Sources: {', '.join(set(a['source'] for a in articles))}")
    print(f"Output:  {output_path}")
    print(f"{'='*60}")

    # Print first 5 headlines
    print("\nSample headlines:")
    for i, art in enumerate(articles[:5]):
        sentiment = art.get("source_sentiment")
        sent_str = f" [sent={sentiment:.2f}]" if sentiment is not None else ""
        tickers = art.get("mentioned_tickers", [])
        tick_str = f" [{', '.join(tickers)}]" if tickers else ""
        print(f"  {i+1}. [{art['source']}]{tick_str}{sent_str} {art['headline'][:80]}")

    if len(articles) > 5:
        print(f"  ... and {len(articles) - 5} more")


if __name__ == "__main__":
    main()
