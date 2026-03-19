"""Integration test: full pipeline tick with mocked fetch layer and LLM."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from news_sentiment.models import ClassificationOutput
from pipeline.orchestrator import SentimentPipeline
from sentiment_score.models import SectorSignalSet
from composite.adapters import sector_signal_to_asset_score


NOW = datetime.now(tz=timezone.utc)

# Raw article dicts (as returned by scripts/fetch_news.py)
_MOCK_RAW_ARTICLES = [
    {
        "id": "int1",
        "timestamp": NOW.isoformat(),
        "source": "cryptopanic",
        "headline": "FET partnership with major cloud provider",
        "body_snippet": "AI token FET announces partnership",
        "url": "https://example.com/int1",
        "mentioned_tickers": ["FET"],
        "source_sentiment": 0.8,
    },
    {
        "id": "int2",
        "timestamp": NOW.isoformat(),
        "source": "rss_coindesk",
        "headline": "Ethereum DeFi TVL reaches new high",
        "body_snippet": "Total value locked in DeFi protocols hits record",
        "url": "https://example.com/int2",
        "mentioned_tickers": [],
        "source_sentiment": None,
    },
]


def _mock_fetch():
    return list(_MOCK_RAW_ARTICLES)


def _identity(x):
    return x


def _mock_classify_fast(article):
    return ClassificationOutput(
        primary_sector="ai_compute", sentiment=0.85,
        magnitude="high", confidence=0.9, cross_market=False,
    )


def _mock_classify_batch(article):
    return ClassificationOutput(
        primary_sector="defi", sentiment=0.0,
        magnitude="low", confidence=0.7,
    )


def _mock_score_batch(headline, snippet, sector):
    return {
        "sentiment": 0.4, "magnitude": "medium",
        "confidence": 0.75, "reasoning": "Positive DeFi growth",
    }


@patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
@patch("pipeline.orchestrator.fetch_all_sources", side_effect=_mock_fetch)
@patch("pipeline.orchestrator.classify_article_fast", side_effect=_mock_classify_fast)
@patch("pipeline.orchestrator.classify_article_batch", side_effect=_mock_classify_batch)
@patch("pipeline.orchestrator.score_article_batch", side_effect=_mock_score_batch)
def test_full_pipeline_tick(mock_score, mock_batch, mock_fast, mock_fetch, mock_dedup, tmp_path):
    """Full pipeline tick: fetch -> classify -> score -> aggregate."""
    db_path = tmp_path / "integration.db"
    with SentimentPipeline(db_path=db_path) as pipeline:
        result = pipeline.tick()

    assert isinstance(result, SectorSignalSet)
    assert len(result.sectors) == 6

    ai = result.sectors["ai_compute"]
    assert ai.article_count >= 1
    assert ai.sentiment > 0

    assert result.metadata["articles_fetched"] == 2
    assert result.metadata["catalysts_detected"] == 1
    assert result.metadata["fast_path_classified"] == 1
    assert result.metadata["llm_calls"] >= 1


@patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
@patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
def test_empty_tick_is_safe(mock_fetch, mock_dedup, tmp_path):
    """Pipeline produces zero signals when no articles are available."""
    db_path = tmp_path / "empty.db"
    with SentimentPipeline(db_path=db_path) as pipeline:
        result = pipeline.tick()

    assert isinstance(result, SectorSignalSet)
    assert all(s.sentiment == 0.0 for s in result.sectors.values())
    assert result.metadata["llm_calls"] == 0


@patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
@patch("pipeline.orchestrator.fetch_all_sources", side_effect=_mock_fetch)
@patch("pipeline.orchestrator.classify_article_fast", side_effect=_mock_classify_fast)
@patch("pipeline.orchestrator.classify_article_batch", side_effect=_mock_classify_batch)
@patch("pipeline.orchestrator.score_article_batch", side_effect=_mock_score_batch)
def test_pipeline_to_adapter_integration(
    mock_score, mock_batch, mock_fast, mock_fetch, mock_dedup, tmp_path
):
    """End-to-end: pipeline tick -> adapter produces per-asset score."""
    import json
    with open("config/sector_map.json") as f:
        sector_map = json.load(f)

    db_path = tmp_path / "e2e.db"
    with SentimentPipeline(db_path=db_path) as pipeline:
        signal_set = pipeline.tick()

    fet_score = sector_signal_to_asset_score("FET/USD", signal_set, sector_map)
    assert fet_score["sector"] == "ai_compute"
    assert fet_score["sentiment"] > 0

    doge_score = sector_signal_to_asset_score("DOGE/USD", signal_set, sector_map)
    assert doge_score["sector"] == "meme"
    assert doge_score["sentiment"] == 0.0


@patch("pipeline.orchestrator.raw_dedup", side_effect=_identity)
@patch("pipeline.orchestrator.fetch_all_sources", side_effect=_mock_fetch)
@patch("pipeline.orchestrator.classify_article_fast", side_effect=_mock_classify_fast)
@patch("pipeline.orchestrator.classify_article_batch", side_effect=_mock_classify_batch)
@patch("pipeline.orchestrator.score_article_batch", side_effect=_mock_score_batch)
def test_multiple_ticks_accumulate(
    mock_score, mock_batch, mock_fast, mock_fetch, mock_dedup, tmp_path
):
    """Multiple ticks should accumulate articles and update signals."""
    db_path = tmp_path / "multi.db"
    with SentimentPipeline(db_path=db_path) as pipeline:
        result1 = pipeline.tick()
        result2 = pipeline.tick()

    assert isinstance(result1, SectorSignalSet)
    assert isinstance(result2, SectorSignalSet)
