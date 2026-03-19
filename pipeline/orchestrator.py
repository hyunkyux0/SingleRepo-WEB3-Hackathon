"""Unified tick scheduler for the sentiment signal pipeline (v2).

Coordinates news fetching, LLM classification, and evidence-based
per-sector scoring on a 5-minute interval.

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
from sentiment_score.models import SectorSignal, SectorSignalSet
from sentiment_score.processors import (
    build_sector_summary,
    gather_evidence,
    load_sector_config,
)
from sentiment_score.prompter import score_sector
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
        batch_interval_min: Minutes between batch LLM classification runs.
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
        self._last_rss_fetch: datetime | None = None
        self._previous_signals: dict[str, float] = {}

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

    # -- timing helpers ------------------------------------------------------

    def _batch_due(self) -> bool:
        """Return True if enough time has passed for a batch classification run."""
        if self._last_batch_time is None:
            return True
        return datetime.now(tz=timezone.utc) - self._last_batch_time >= self._batch_interval

    def _rss_due(self) -> bool:
        """Return True if enough time has passed for an RSS fetch (15 min)."""
        if self._last_rss_fetch is None:
            return True
        return (datetime.now(tz=timezone.utc) - self._last_rss_fetch).total_seconds() >= 900

    # -- main tick -----------------------------------------------------------

    def tick(self) -> SectorSignalSet:
        """Run one pipeline cycle and return the current sector signals.

        v2 flow:
        1. Fetch news (CryptoPanic every tick, RSS every 15 min).
        2. Deduplicate + keyword pre-filter.
        3. Store to SQLite.
        4. Classify articles into sectors (fast path for catalysts, batch for rest).
        5. Score each sector with evidence (ONE LLM call per sector).
        6. Return SectorSignalSet.

        Returns:
            A :class:`SectorSignalSet` with signals for all 6 sectors.
        """
        assert self._db is not None, "Pipeline not opened. Use 'with' or call open()."
        tick_start = time.monotonic()

        # 1. Fetch (CryptoPanic every tick, RSS every 15 min)
        if self._rss_due():
            raw_dicts = fetch_all_sources()
            self._last_rss_fetch = datetime.now(tz=timezone.utc)
        else:
            raw_dicts = fetch_all_sources(sources=["cryptopanic"])
        raw_dicts = raw_dedup(raw_dicts)
        raw_articles = [dict_to_article(d) for d in raw_dicts]

        # 2. Deduplicate against DB + pre-filter
        deduped = deduplicate(raw_articles, self._db)
        filtered = keyword_prefilter(deduped, self._sector_map)

        # 3. Store
        stored_count = store_articles(filtered, self._db)

        # 4. Classify all articles into sectors
        catalysts = [a for a in filtered if a.is_catalyst]
        fast_classified = 0
        llm_calls = 0

        # Fast path: catalysts get single-shot classification + sentiment
        for article in catalysts:
            classification = classify_article_fast(article)
            mark_processed(article.id, classification, self._db)
            fast_classified += 1
            llm_calls += 1

        # Batch path: classify remaining (sector only, no per-article scoring)
        batch_classified = 0
        if self._batch_due():
            unprocessed = get_unprocessed_articles(self._db)
            for article in unprocessed:
                self._batch_limiter.wait()
                classification = classify_article_batch(article)
                mark_processed(article.id, classification, self._db)
                batch_classified += 1
                llm_calls += 1
            self._last_batch_time = datetime.now(tz=timezone.utc)

        # 5. Score each sector with evidence (ONE LLM call per sector)
        now = datetime.now(tz=timezone.utc)
        sectors: dict[str, SectorSignal] = {}

        for sector, cfg in self._sector_config.items():
            lookback_hours = float(cfg.get("lookback_hours", 24))
            catalyst_threshold = float(cfg.get("catalyst_threshold", 0.7))

            # Build summary + gather evidence
            summary = build_sector_summary(self._db, sector, lookback_hours)
            evidence = gather_evidence(
                sector, self._sector_map, summary, self._previous_signals
            )

            # Score sector (skips LLM if 0 articles)
            score_result = score_sector(summary, evidence)
            if summary["article_count"] > 0:
                llm_calls += 1

            # Catalyst detection from fast-path articles
            catalyst_active = False
            catalyst_details = None
            catalyst_cutoff = now - timedelta(minutes=30)

            catalyst_rows = self._db.fetchall(
                """SELECT id, llm_sentiment, llm_magnitude, timestamp
                   FROM articles WHERE processed=1 AND llm_sector=?
                   AND llm_magnitude='high' AND timestamp>=?""",
                (sector, catalyst_cutoff.isoformat()),
            )
            for row in catalyst_rows:
                if row["llm_sentiment"] is not None and abs(row["llm_sentiment"]) > catalyst_threshold:
                    catalyst_active = True
                    catalyst_details = {
                        "article_id": row["id"],
                        "sentiment": row["llm_sentiment"],
                        "timestamp": row["timestamp"],
                    }
                    break

            # Tick-based momentum
            prev_sent = self._previous_signals.get(sector, 0.0)
            momentum = score_result["sentiment"] - prev_sent

            sectors[sector] = SectorSignal(
                sector=sector,
                sentiment=score_result["sentiment"],
                momentum=momentum,
                catalyst_active=catalyst_active,
                catalyst_details=catalyst_details,
                article_count=summary["article_count"],
                confidence=score_result["confidence"],
                key_driver=score_result.get("key_driver", ""),
                reasoning=score_result.get("reasoning", ""),
            )

        signal_set = SectorSignalSet(
            timestamp=now,
            sectors=sectors,
            metadata={
                "sector_count": len(sectors),
                "total_articles": sum(s.article_count for s in sectors.values()),
            },
        )

        # Store previous signals for next tick
        self._previous_signals = {s: sig.sentiment for s, sig in sectors.items()}

        # Logging metadata
        tick_ms = (time.monotonic() - tick_start) * 1000
        signal_set.metadata.update({
            "articles_fetched": len(raw_articles),
            "articles_after_dedup": len(deduped),
            "articles_after_filter": len(filtered),
            "articles_stored": stored_count,
            "catalysts_detected": len(catalysts),
            "fast_path_classified": fast_classified,
            "batch_classified": batch_classified,
            "llm_calls": llm_calls,
            "processing_time_ms": round(tick_ms, 1),
        })

        strongest = max(sectors.values(), key=lambda s: abs(s.sentiment), default=None)
        logger.info(
            "tick: fetched=%d filtered=%d fast=%d batch=%d sector_scores=%d "
            "llm_calls=%d strongest=%s(%.2f) time=%.0fms",
            len(raw_articles), len(filtered), fast_classified, batch_classified,
            len([s for s in sectors.values() if s.article_count > 0]),
            llm_calls,
            strongest.sector if strongest else "none",
            strongest.sentiment if strongest else 0.0,
            tick_ms,
        )

        return signal_set
