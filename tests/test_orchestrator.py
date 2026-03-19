"""Tests for the pipeline orchestrator."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from pipeline.orchestrator import SentimentPipeline, RateLimiter
from news_sentiment.models import ClassificationOutput
from sentiment_score.models import SectorSignalSet


NOW = datetime.now(tz=timezone.utc)

# Raw article dicts (as returned by scripts/fetch_news.py)
_CATALYST_DICT = {
    "id": "cat1",
    "timestamp": NOW.isoformat(),
    "source": "cryptopanic",
    "headline": "FET partnership announced",
    "body_snippet": "",
    "url": "https://example.com/cat1",
    "mentioned_tickers": ["FET"],
    "source_sentiment": 0.8,
}

_BATCH_DICT = {
    "id": "batch1",
    "timestamp": NOW.isoformat(),
    "source": "rss_coindesk",
    "headline": "Ethereum DeFi TVL up",
    "body_snippet": "Total value locked rises",
    "url": "https://example.com/batch1",
    "mentioned_tickers": [],
    "source_sentiment": None,
}


def _identity(x):
    """Pass-through for mocking raw_dedup."""
    return x


@pytest.fixture
def pipeline(tmp_path):
    db_path = tmp_path / "test.db"
    return SentimentPipeline(
        db_path=db_path,
        sector_map_path="config/sector_map.json",
        sector_config_path="config/sector_config.json",
        batch_interval_min=30,
    )


# ═════════════════════════════════════════════════════════════════════════
# RateLimiter
# ═════════════════════════════════════════════════════════════════════════


class TestRateLimiter:
    def test_first_call_no_wait(self):
        rl = RateLimiter(calls_per_minute=60)
        start = time.monotonic()
        rl.wait()
        assert time.monotonic() - start < 0.1

    def test_respects_interval(self):
        rl = RateLimiter(calls_per_minute=600)
        rl.wait()
        start = time.monotonic()
        rl.wait()
        assert time.monotonic() - start >= 0.05

    def test_zero_calls_per_minute_safe(self):
        rl = RateLimiter(calls_per_minute=0)
        rl.wait()


# ═════════════════════════════════════════════════════════════════════════
# Pipeline lifecycle
# ═════════════════════════════════════════════════════════════════════════


class TestSentimentPipelineInit:
    def test_creates_db(self, pipeline, tmp_path):
        pipeline.open()
        assert (tmp_path / "test.db").exists()
        pipeline.close()

    def test_loads_configs(self, pipeline):
        pipeline.open()
        assert len(pipeline._sector_map) == 67
        assert len(pipeline._sector_config) == 6
        pipeline.close()

    def test_context_manager(self, pipeline):
        with pipeline:
            assert pipeline._db is not None
        assert pipeline._db is None

    def test_close_is_idempotent(self, pipeline):
        pipeline.open()
        pipeline.close()
        pipeline.close()

    def test_tick_without_open_raises(self, pipeline):
        with pytest.raises(AssertionError, match="not opened"):
            pipeline.tick()


# ═════════════════════════════════════════════════════════════════════════
# Batch timing
# ═════════════════════════════════════════════════════════════════════════


class TestBatchTiming:
    def test_batch_due_on_first_tick(self, pipeline):
        with pipeline:
            assert pipeline._batch_due() is True

    def test_batch_not_due_after_recent_run(self, pipeline):
        with pipeline:
            pipeline._last_batch_time = datetime.now(tz=timezone.utc)
            assert pipeline._batch_due() is False

    def test_batch_due_after_interval(self, pipeline):
        with pipeline:
            pipeline._last_batch_time = datetime.now(tz=timezone.utc) - timedelta(minutes=31)
            assert pipeline._batch_due() is True


# ═════════════════════════════════════════════════════════════════════════
# Tick — with mocked fetch layer
# ═════════════════════════════════════════════════════════════════════════


class TestSentimentPipelineTick:
    @patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
    @patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
    def test_tick_returns_sector_signal_set(self, mock_fetch, mock_dedup, pipeline):
        with pipeline:
            result = pipeline.tick()
            assert isinstance(result, SectorSignalSet)
            assert len(result.sectors) == 6

    @patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
    @patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
    def test_tick_with_no_articles_produces_zero_signals(self, mock_fetch, mock_dedup, pipeline):
        with pipeline:
            result = pipeline.tick()
            for signal in result.sectors.values():
                assert signal.sentiment == 0.0
                assert signal.confidence == 0.0

    @patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
    @patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
    def test_tick_metadata_populated(self, mock_fetch, mock_dedup, pipeline):
        with pipeline:
            result = pipeline.tick()
            assert "articles_fetched" in result.metadata
            assert "catalysts_detected" in result.metadata
            assert "fast_path_classified" in result.metadata
            assert "batch_processed" in result.metadata
            assert "llm_calls" in result.metadata
            assert "processing_time_ms" in result.metadata
            assert "total_articles" in result.metadata
            assert "sector_count" in result.metadata

    @patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
    @patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
    def test_tick_zero_llm_calls_with_no_articles(self, mock_fetch, mock_dedup, pipeline):
        with pipeline:
            result = pipeline.tick()
            assert result.metadata["llm_calls"] == 0
            assert result.metadata["articles_fetched"] == 0

    @patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
    @patch("pipeline.orchestrator.classify_article_fast")
    @patch("pipeline.orchestrator.fetch_all_sources")
    def test_tick_classifies_catalysts_fast(self, mock_fetch, mock_classify, mock_dedup, pipeline):
        mock_fetch.return_value = [_CATALYST_DICT]
        mock_classify.return_value = ClassificationOutput(
            primary_sector="ai_compute", sentiment=0.9,
            magnitude="high", confidence=0.95,
        )
        with pipeline:
            result = pipeline.tick()
            mock_classify.assert_called_once()
            assert result.metadata["fast_path_classified"] == 1
            assert result.metadata["llm_calls"] == 1

    @patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
    @patch("pipeline.orchestrator.score_article_batch")
    @patch("pipeline.orchestrator.classify_article_batch")
    @patch("pipeline.orchestrator.fetch_all_sources")
    def test_tick_batch_processes_non_catalysts(
        self, mock_fetch, mock_classify, mock_score, mock_dedup, pipeline
    ):
        mock_fetch.return_value = [_BATCH_DICT]
        mock_classify.return_value = ClassificationOutput(
            primary_sector="defi", sentiment=0.0,
            magnitude="low", confidence=0.7,
        )
        mock_score.return_value = {
            "sentiment": 0.4, "magnitude": "medium",
            "confidence": 0.75, "reasoning": "DeFi growth",
        }
        with pipeline:
            result = pipeline.tick()
            assert result.metadata["batch_processed"] == 1
            assert result.metadata["llm_calls"] == 2

    @patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
    @patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
    def test_tick_updates_last_batch_time(self, mock_fetch, mock_dedup, pipeline):
        with pipeline:
            assert pipeline._last_batch_time is None
            pipeline.tick()
            assert pipeline._last_batch_time is not None

    @patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
    @patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
    def test_second_tick_skips_batch_if_not_due(self, mock_fetch, mock_dedup, pipeline):
        with pipeline:
            pipeline.tick()
            first_batch_time = pipeline._last_batch_time
            pipeline.tick()
            assert pipeline._last_batch_time == first_batch_time
