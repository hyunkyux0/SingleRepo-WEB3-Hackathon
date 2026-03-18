"""Tests for the sentiment_score module — models, processors, and prompter."""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from sentiment_score.models import ScoredArticle, SectorSignal, SectorSignalSet
from sentiment_score.processors import (
    load_sector_config,
    get_source_weight,
    get_magnitude_weight,
    compute_decay,
    build_scored_articles,
    aggregate_sector_signal,
    compute_sector_signals,
    _compute_weighted_sentiment,
)
from sentiment_score.prompter import (
    BATCH_SCORE_SYSTEM,
    build_batch_score_prompt,
    score_article_batch,
    _strip_code_fences,
    _default_score,
)
from utils.db import DataStore


NOW = datetime.now(tz=timezone.utc)


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "test.db"
    with DataStore(db_path=db_path) as db:
        yield db


@pytest.fixture
def sector_config():
    return load_sector_config("config/sector_config.json")


def _insert_article(db, id, sector, sentiment, magnitude="medium",
                     confidence=0.8, source="cryptopanic",
                     hours_ago=0, processed=1):
    """Helper to insert a processed article into the test DB."""
    ts = (NOW - timedelta(hours=hours_ago)).isoformat()
    db.execute(
        """INSERT OR IGNORE INTO articles
           (id, timestamp, source, headline, processed,
            llm_sector, llm_sentiment, llm_magnitude, llm_confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, ts, source, f"Article {id}", processed,
         sector, sentiment, magnitude, confidence),
    )
    db.commit()


# ═════════════════════════════════════════════════════════════════════════
# Models
# ═════════════════════════════════════════════════════════════════════════


class TestScoredArticle:
    def test_construction(self):
        art = ScoredArticle(
            article_id="a1", timestamp=NOW, primary_sector="defi",
            sentiment=0.5, magnitude="medium", source="cryptopanic",
            source_weight=1.0, decay_weight=0.9,
        )
        assert art.article_id == "a1"
        assert art.decay_weight == 0.9

    def test_default_decay_weight(self):
        art = ScoredArticle(
            article_id="a2", timestamp=NOW, primary_sector="meme",
            sentiment=-0.3, magnitude="low", source="reddit",
            source_weight=0.4,
        )
        assert art.decay_weight == 1.0


class TestSectorSignal:
    def test_construction(self):
        sig = SectorSignal(
            sector="ai_compute", sentiment=0.7, momentum=0.3,
            catalyst_active=True,
            catalyst_details={"article_id": "x", "sentiment": 0.9},
            article_count=5, confidence=0.85,
        )
        assert sig.catalyst_active is True
        assert sig.article_count == 5

    def test_defaults(self):
        sig = SectorSignal(sector="other", sentiment=0.0, momentum=0.0)
        assert sig.catalyst_active is False
        assert sig.catalyst_details is None
        assert sig.article_count == 0
        assert sig.confidence == 0.0


class TestSectorSignalSet:
    def test_construction(self):
        signals = {
            "defi": SectorSignal(sector="defi", sentiment=0.5, momentum=0.1),
            "meme": SectorSignal(sector="meme", sentiment=-0.2, momentum=-0.05),
        }
        sset = SectorSignalSet(timestamp=NOW, sectors=signals)
        assert len(sset.sectors) == 2
        assert sset.sectors["defi"].sentiment == 0.5

    def test_metadata_default(self):
        sset = SectorSignalSet(timestamp=NOW, sectors={})
        assert sset.metadata == {}


# ═════════════════════════════════════════════════════════════════════════
# Processors — Weight helpers
# ═════════════════════════════════════════════════════════════════════════


class TestSourceWeight:
    def test_cryptopanic(self):
        assert get_source_weight("cryptopanic") == 1.0

    def test_rss_named(self):
        assert get_source_weight("rss_coindesk") == 0.8
        assert get_source_weight("rss_cointelegraph") == 0.8

    def test_rss_unknown_prefix(self):
        assert get_source_weight("rss_custom") == 0.8

    def test_twitter(self):
        assert get_source_weight("twitter") == 0.6

    def test_reddit(self):
        assert get_source_weight("reddit") == 0.4

    def test_unknown_source(self):
        assert get_source_weight("telegram") == 0.5


class TestMagnitudeWeight:
    def test_high(self):
        assert get_magnitude_weight("high") == 3.0

    def test_medium(self):
        assert get_magnitude_weight("medium") == 1.0

    def test_low(self):
        assert get_magnitude_weight("low") == 0.3

    def test_case_insensitive(self):
        assert get_magnitude_weight("HIGH") == 3.0
        assert get_magnitude_weight("Medium") == 1.0

    def test_unknown_defaults_to_1(self):
        assert get_magnitude_weight("extreme") == 1.0


class TestComputeDecay:
    def test_zero_hours(self):
        assert compute_decay(0.0, 0.5) == 1.0

    def test_positive_decay(self):
        result = compute_decay(1.0, 0.5)
        assert abs(result - math.exp(-0.5)) < 1e-10

    def test_high_lambda_fast_decay(self):
        result = compute_decay(2.0, 2.0)
        assert result < 0.02  # exp(-4) ≈ 0.018

    def test_low_lambda_slow_decay(self):
        result = compute_decay(10.0, 0.1)
        assert result > 0.3  # exp(-1) ≈ 0.368

    def test_zero_lambda_no_decay(self):
        assert compute_decay(100.0, 0.0) == 1.0


class TestComputeWeightedSentiment:
    def test_single_article(self):
        articles = [
            ScoredArticle(
                article_id="s1", timestamp=NOW, primary_sector="defi",
                sentiment=0.8, magnitude="medium", source="cryptopanic",
                source_weight=1.0, decay_weight=1.0,
            )
        ]
        result = _compute_weighted_sentiment(articles)
        assert abs(result - 0.8) < 1e-10

    def test_weighted_average(self):
        articles = [
            ScoredArticle(
                article_id="w1", timestamp=NOW, primary_sector="defi",
                sentiment=1.0, magnitude="high", source="cryptopanic",
                source_weight=1.0, decay_weight=1.0,
            ),
            ScoredArticle(
                article_id="w2", timestamp=NOW, primary_sector="defi",
                sentiment=-1.0, magnitude="low", source="reddit",
                source_weight=0.4, decay_weight=0.5,
            ),
        ]
        # w1 weight = 1.0 * 1.0 * 3.0 = 3.0, contribution = 3.0
        # w2 weight = 0.5 * 0.4 * 0.3 = 0.06, contribution = -0.06
        # result = (3.0 - 0.06) / (3.0 + 0.06)
        result = _compute_weighted_sentiment(articles)
        expected = (3.0 - 0.06) / (3.0 + 0.06)
        assert abs(result - expected) < 1e-6

    def test_empty_list(self):
        assert _compute_weighted_sentiment([]) == 0.0


# ═════════════════════════════════════════════════════════════════════════
# Processors — Config loader
# ═════════════════════════════════════════════════════════════════════════


class TestLoadSectorConfig:
    def test_loads_all_sectors(self):
        cfg = load_sector_config("config/sector_config.json")
        expected = {"l1_infra", "defi", "ai_compute", "meme", "store_of_value", "other"}
        assert set(cfg.keys()) == expected

    def test_each_sector_has_required_fields(self):
        cfg = load_sector_config("config/sector_config.json")
        for sector, params in cfg.items():
            assert "sentiment_weight" in params, f"{sector} missing sentiment_weight"
            assert "lookback_hours" in params
            assert "decay_lambda" in params
            assert "catalyst_threshold" in params
            assert "regime" in params


# ═════════════════════════════════════════════════════════════════════════
# Processors — build_scored_articles
# ═════════════════════════════════════════════════════════════════════════


class TestBuildScoredArticles:
    def test_returns_articles_in_window(self, tmp_db):
        _insert_article(tmp_db, "bsa1", "defi", 0.5, hours_ago=1)
        _insert_article(tmp_db, "bsa2", "defi", 0.3, hours_ago=5)
        result = build_scored_articles(tmp_db, "defi", lookback_hours=10)
        assert len(result) == 2

    def test_excludes_outside_window(self, tmp_db):
        _insert_article(tmp_db, "bsa3", "defi", 0.5, hours_ago=1)
        _insert_article(tmp_db, "bsa4", "defi", 0.3, hours_ago=50)  # outside
        result = build_scored_articles(tmp_db, "defi", lookback_hours=24)
        assert len(result) == 1

    def test_excludes_wrong_sector(self, tmp_db):
        _insert_article(tmp_db, "bsa5", "defi", 0.5, hours_ago=1)
        _insert_article(tmp_db, "bsa6", "meme", 0.8, hours_ago=1)
        result = build_scored_articles(tmp_db, "defi", lookback_hours=24)
        assert len(result) == 1
        assert result[0].primary_sector == "defi"

    def test_excludes_unprocessed(self, tmp_db):
        _insert_article(tmp_db, "bsa7", "defi", 0.5, hours_ago=1, processed=0)
        result = build_scored_articles(tmp_db, "defi", lookback_hours=24)
        assert len(result) == 0

    def test_computes_source_weight(self, tmp_db):
        _insert_article(tmp_db, "bsa8", "defi", 0.5, source="cryptopanic", hours_ago=1)
        result = build_scored_articles(tmp_db, "defi", lookback_hours=24)
        assert result[0].source_weight == 1.0

    def test_computes_decay_weight(self, tmp_db):
        _insert_article(tmp_db, "bsa9", "defi", 0.5, hours_ago=0)
        result = build_scored_articles(tmp_db, "defi", lookback_hours=24)
        # Very recent article should have decay close to 1
        assert result[0].decay_weight > 0.9

    def test_empty_result(self, tmp_db):
        result = build_scored_articles(tmp_db, "ai_compute", lookback_hours=24)
        assert result == []


# ═════════════════════════════════════════════════════════════════════════
# Processors — aggregate_sector_signal
# ═════════════════════════════════════════════════════════════════════════


class TestAggregateSectorSignal:
    def test_basic_aggregation(self, tmp_db, sector_config):
        _insert_article(tmp_db, "agg1", "defi", 0.6, "medium", 0.8, hours_ago=1)
        _insert_article(tmp_db, "agg2", "defi", 0.4, "low", 0.7, hours_ago=2)
        scored = build_scored_articles(tmp_db, "defi", lookback_hours=24)
        signal = aggregate_sector_signal(scored, "defi", sector_config, tmp_db)
        assert signal.sector == "defi"
        assert signal.article_count == 2
        assert -1.0 <= signal.sentiment <= 1.0
        assert signal.confidence > 0

    def test_no_articles_produces_zero_signal(self, tmp_db, sector_config):
        signal = aggregate_sector_signal([], "defi", sector_config, tmp_db)
        assert signal.sentiment == 0.0
        assert signal.momentum == 0.0
        assert signal.confidence == 0.0
        assert signal.article_count == 0
        assert signal.catalyst_active is False

    def test_catalyst_detection(self, tmp_db, sector_config):
        # Insert a high-magnitude, high-sentiment article within last 30 min
        _insert_article(tmp_db, "cat1", "ai_compute", 0.9, "high", 0.95,
                        hours_ago=0.1)  # ~6 min ago
        scored = build_scored_articles(tmp_db, "ai_compute", lookback_hours=12)
        signal = aggregate_sector_signal(scored, "ai_compute", sector_config, tmp_db)
        assert signal.catalyst_active is True
        assert signal.catalyst_details is not None
        assert signal.catalyst_details["article_id"] == "cat1"

    def test_no_catalyst_when_old(self, tmp_db, sector_config):
        # Article is high-mag/high-sentiment but older than 30 min
        _insert_article(tmp_db, "cat2", "ai_compute", 0.9, "high", 0.95,
                        hours_ago=2)
        scored = build_scored_articles(tmp_db, "ai_compute", lookback_hours=12)
        signal = aggregate_sector_signal(scored, "ai_compute", sector_config, tmp_db)
        assert signal.catalyst_active is False

    def test_no_catalyst_when_low_sentiment(self, tmp_db, sector_config):
        # High magnitude but low sentiment
        _insert_article(tmp_db, "cat3", "ai_compute", 0.1, "high", 0.95,
                        hours_ago=0.1)
        scored = build_scored_articles(tmp_db, "ai_compute", lookback_hours=12)
        signal = aggregate_sector_signal(scored, "ai_compute", sector_config, tmp_db)
        assert signal.catalyst_active is False

    def test_momentum_positive(self, tmp_db, sector_config):
        # Articles in current window positive, previous window negative
        _insert_article(tmp_db, "mom1", "meme", 0.8, "medium", hours_ago=1)
        # Previous window: use meme lookback (4h), so previous = 4-8h ago
        _insert_article(tmp_db, "mom2", "meme", -0.5, "medium", hours_ago=6)
        scored = build_scored_articles(tmp_db, "meme", lookback_hours=4)
        signal = aggregate_sector_signal(scored, "meme", sector_config, tmp_db)
        assert signal.momentum > 0  # current positive, previous negative

    def test_confidence_scales_with_articles(self, tmp_db, sector_config):
        for i in range(10):
            _insert_article(tmp_db, f"conf{i}", "defi", 0.5, "medium", 0.8,
                            hours_ago=i * 0.5)
        scored = build_scored_articles(tmp_db, "defi", lookback_hours=24)
        signal = aggregate_sector_signal(scored, "defi", sector_config, tmp_db)
        # 10 articles -> min(1.0, 10/10) * 0.8 = 0.8
        assert abs(signal.confidence - 0.8) < 0.05

    def test_confidence_low_with_few_articles(self, tmp_db, sector_config):
        _insert_article(tmp_db, "conflo1", "defi", 0.5, "medium", 0.8, hours_ago=1)
        scored = build_scored_articles(tmp_db, "defi", lookback_hours=24)
        signal = aggregate_sector_signal(scored, "defi", sector_config, tmp_db)
        # 1 article -> min(1.0, 1/10) * 0.8 = 0.08
        assert signal.confidence < 0.15


# ═════════════════════════════════════════════════════════════════════════
# Processors — compute_sector_signals
# ═════════════════════════════════════════════════════════════════════════


class TestComputeSectorSignals:
    def test_returns_all_sectors(self, tmp_db, sector_config):
        signal_set = compute_sector_signals(tmp_db, sector_config)
        assert len(signal_set.sectors) == 6
        expected = {"l1_infra", "defi", "ai_compute", "meme", "store_of_value", "other"}
        assert set(signal_set.sectors.keys()) == expected

    def test_empty_db_produces_zero_signals(self, tmp_db, sector_config):
        signal_set = compute_sector_signals(tmp_db, sector_config)
        for sector, signal in signal_set.sectors.items():
            assert signal.sentiment == 0.0
            assert signal.momentum == 0.0
            assert signal.confidence == 0.0

    def test_metadata_populated(self, tmp_db, sector_config):
        _insert_article(tmp_db, "meta1", "defi", 0.5, hours_ago=1)
        signal_set = compute_sector_signals(tmp_db, sector_config)
        assert signal_set.metadata["sector_count"] == 6
        assert signal_set.metadata["total_articles"] == 1

    def test_timestamp_is_recent(self, tmp_db, sector_config):
        signal_set = compute_sector_signals(tmp_db, sector_config)
        age = (NOW - signal_set.timestamp).total_seconds()
        assert abs(age) < 5  # should be within a few seconds


# ═════════════════════════════════════════════════════════════════════════
# Prompter — helpers and prompt builder
# ═════════════════════════════════════════════════════════════════════════


class TestPrompterHelpers:
    def test_strip_code_fences(self):
        assert _strip_code_fences('{"a": 1}') == '{"a": 1}'
        assert _strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_default_score(self):
        d = _default_score()
        assert d["sentiment"] == 0.0
        assert d["magnitude"] == "low"
        assert d["confidence"] == 0.0

    def test_system_prompt_has_required_fields(self):
        assert "sentiment" in BATCH_SCORE_SYSTEM
        assert "magnitude" in BATCH_SCORE_SYSTEM
        assert "confidence" in BATCH_SCORE_SYSTEM

    def test_build_prompt_includes_sector(self):
        prompt = build_batch_score_prompt("Test headline", "Test snippet", "defi")
        assert "defi" in prompt
        assert "Test headline" in prompt
        assert "Test snippet" in prompt

    def test_build_prompt_omits_empty_snippet(self):
        prompt = build_batch_score_prompt("Test headline", "", "defi")
        assert "Snippet:" not in prompt


# ═════════════════════════════════════════════════════════════════════════
# Prompter — score_article_batch (mocked LLM)
# ═════════════════════════════════════════════════════════════════════════


class TestScoreArticleBatch:
    def _mock_llm(self, response_json):
        return patch(
            "sentiment_score.prompter.call_llm",
            return_value=(json.dumps(response_json), {}, "test/model"),
        )

    def test_valid_response(self):
        resp = {"sentiment": 0.7, "magnitude": "high", "confidence": 0.9, "reasoning": "Bullish"}
        with self._mock_llm(resp):
            result = score_article_batch("Headline", "Snippet", "defi")
            assert result["sentiment"] == 0.7
            assert result["magnitude"] == "high"
            assert result["confidence"] == 0.9

    def test_clamps_sentiment(self):
        resp = {"sentiment": 5.0, "magnitude": "low", "confidence": 0.5}
        with self._mock_llm(resp):
            result = score_article_batch("H", "S", "defi")
            assert result["sentiment"] == 1.0

    def test_clamps_negative_sentiment(self):
        resp = {"sentiment": -3.0, "magnitude": "low", "confidence": 0.5}
        with self._mock_llm(resp):
            result = score_article_batch("H", "S", "defi")
            assert result["sentiment"] == -1.0

    def test_invalid_magnitude_defaults(self):
        resp = {"sentiment": 0.5, "magnitude": "extreme", "confidence": 0.5}
        with self._mock_llm(resp):
            result = score_article_batch("H", "S", "defi")
            assert result["magnitude"] == "low"

    def test_json_error_returns_default(self):
        with patch("sentiment_score.prompter.call_llm", return_value=("bad json", {}, "test")):
            result = score_article_batch("H", "S", "defi")
            assert result["sentiment"] == 0.0
            assert result["magnitude"] == "low"

    def test_exception_returns_default(self):
        with patch("sentiment_score.prompter.call_llm", side_effect=RuntimeError("fail")):
            result = score_article_batch("H", "S", "defi")
            assert result["sentiment"] == 0.0

    def test_code_fences_handled(self):
        text = '```json\n{"sentiment": 0.6, "magnitude": "medium", "confidence": 0.8}\n```'
        with patch("sentiment_score.prompter.call_llm", return_value=(text, {}, "test")):
            result = score_article_batch("H", "S", "defi")
            assert result["sentiment"] == 0.6
