"""Unified tick scheduler for the sentiment signal pipeline.

Coordinates news fetching, LLM classification (fast + batch paths),
and signal aggregation on a 5-minute interval.

Usage::

    with SentimentPipeline(db_path=Path("data/trading_bot.db")) as pipeline:
        signal_set = pipeline.tick()  # returns SectorSignalSet
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from news_sentiment.models import ArticleInput, ClassificationOutput
from news_sentiment.processors import (
    deduplicate,
    dict_to_article,
    get_unprocessed_articles,
    keyword_prefilter,
    load_sector_map,
    mark_processed,
    store_articles,
)
from news_sentiment.prompter import classify_article_batch, classify_article_fast
from scripts.fetch_news import fetch_all as fetch_all_sources, deduplicate as raw_dedup
from sentiment_score.models import SectorSignalSet
from sentiment_score.processors import compute_sector_signals, load_sector_config
from sentiment_score.prompter import score_article_batch
from utils.db import DataStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """Simple token-bucket rate limiter.

    Args:
        calls_per_minute: Maximum calls per minute.
    """

    def __init__(self, calls_per_minute: int) -> None:
        self.interval = 60.0 / max(calls_per_minute, 1)
        self._last_call: float = 0.0

    def wait(self) -> None:
        """Block until enough time has elapsed since the last call."""
        now = time.monotonic()
        elapsed = now - self._last_call
        if self._last_call > 0 and elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last_call = time.monotonic()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class SentimentPipeline:
    """Orchestrates the full sentiment signal pipeline.

    Call :meth:`tick` every 5 minutes. It returns a
    :class:`SectorSignalSet` for consumption by the strategy engine.

    Args:
        db_path: Path to the SQLite database file.
        sector_map_path: Path to ``config/sector_map.json``.
        sector_config_path: Path to ``config/sector_config.json``.
        sources_config_path: Path to ``config/sources.json``.
        batch_interval_min: Minutes between batch LLM processing runs.
    """

    def __init__(
        self,
        db_path: Path = Path("data/trading_bot.db"),
        sector_map_path: str = "config/sector_map.json",
        sector_config_path: str = "config/sector_config.json",
        batch_interval_min: int = 30,
    ) -> None:
        self._db_path = db_path
        self._sector_map_path = sector_map_path
        self._sector_config_path = sector_config_path
        self._batch_interval = timedelta(minutes=batch_interval_min)

        self._db: DataStore | None = None
        self._sector_map: dict[str, Any] = {}
        self._sector_config: dict[str, Any] = {}
        self._last_batch_time: datetime | None = None

        self._batch_limiter = RateLimiter(calls_per_minute=20)

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> SentimentPipeline:
        """Open the database and load configuration files."""
        self._db = DataStore(db_path=self._db_path)
        self._db.open()
        self._sector_map = load_sector_map(self._sector_map_path)
        self._sector_config = load_sector_config(self._sector_config_path)
        logger.info("SentimentPipeline opened (db=%s)", self._db_path)
        return self

    def close(self) -> None:
        """Close the database connection."""
        if self._db is not None:
            self._db.close()
            self._db = None
            logger.info("SentimentPipeline closed")

    def __enter__(self) -> SentimentPipeline:
        return self.open()

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- batch timing --------------------------------------------------------

    def _batch_due(self) -> bool:
        """Return True if enough time has passed for a batch run."""
        if self._last_batch_time is None:
            return True
        return datetime.now(tz=timezone.utc) - self._last_batch_time >= self._batch_interval

    # -- main tick -----------------------------------------------------------

    def tick(self) -> SectorSignalSet:
        """Run one pipeline cycle and return the current sector signals.

        Steps:
        1. Fetch new articles from all enabled sources.
        2. Deduplicate and keyword pre-filter.
        3. Store to SQLite.
        4. Fast path: classify catalyst articles immediately.
        5. Batch path: if interval elapsed, process unprocessed backlog.
        6. Aggregate all scored articles into sector signals.
        7. Return the SectorSignalSet.

        Returns:
            A :class:`SectorSignalSet` with signals for all 6 sectors.
        """
        assert self._db is not None, "Pipeline not opened. Use 'with' or call open()."
        tick_start = time.monotonic()

        # 1. Fetch (via scripts/fetch_news.py — sole fetching layer)
        raw_dicts = fetch_all_sources()
        raw_dicts = raw_dedup(raw_dicts)
        raw_articles = [dict_to_article(d) for d in raw_dicts]

        # 2. Deduplicate against DB + pre-filter
        deduped = deduplicate(raw_articles, self._db)
        filtered = keyword_prefilter(deduped, self._sector_map)

        # 3. Store
        stored_count = store_articles(filtered, self._db)

        # 4. Fast path — classify catalysts immediately
        catalysts = [a for a in filtered if a.is_catalyst]
        fast_classified = 0
        llm_calls = 0
        for article in catalysts:
            classification = classify_article_fast(article)
            mark_processed(article.id, classification, self._db)
            fast_classified += 1
            llm_calls += 1  # single-shot fast classify

        # 5. Batch path — process unprocessed backlog every batch_interval
        batch_processed = 0
        if self._batch_due():
            unprocessed = get_unprocessed_articles(self._db)
            for article in unprocessed:
                self._batch_limiter.wait()

                # Step 1: classify sector
                classification = classify_article_batch(article)

                # Step 2: score sentiment
                score_result = score_article_batch(
                    article.headline, article.body_snippet,
                    classification.primary_sector,
                )

                # Merge score into classification
                full_classification = ClassificationOutput(
                    primary_sector=classification.primary_sector,
                    secondary_sector=classification.secondary_sector,
                    sentiment=score_result["sentiment"],
                    magnitude=score_result["magnitude"],
                    confidence=score_result.get("confidence", classification.confidence),
                    cross_market=classification.cross_market,
                    reasoning=score_result.get("reasoning", ""),
                )

                mark_processed(article.id, full_classification, self._db)
                batch_processed += 1
                llm_calls += 2  # classify + score

            self._last_batch_time = datetime.now(tz=timezone.utc)

        # 6. Aggregate
        signal_set = compute_sector_signals(self._db, self._sector_config)

        # 7. Logging
        tick_ms = (time.monotonic() - tick_start) * 1000
        signal_set.metadata.update({
            "articles_fetched": len(raw_articles),
            "articles_after_dedup": len(deduped),
            "articles_after_filter": len(filtered),
            "articles_stored": stored_count,
            "catalysts_detected": len(catalysts),
            "fast_path_classified": fast_classified,
            "batch_processed": batch_processed,
            "llm_calls": llm_calls,
            "processing_time_ms": round(tick_ms, 1),
        })

        strongest = max(
            signal_set.sectors.values(),
            key=lambda s: abs(s.sentiment),
            default=None,
        )
        logger.info(
            "tick: fetched=%d filtered=%d stored=%d fast=%d batch=%d "
            "llm_calls=%d strongest=%s(%.2f) time=%.0fms",
            len(raw_articles), len(filtered), stored_count,
            fast_classified, batch_processed, llm_calls,
            strongest.sector if strongest else "none",
            strongest.sentiment if strongest else 0.0,
            tick_ms,
        )

        return signal_set
