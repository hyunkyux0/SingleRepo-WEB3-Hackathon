"""Tests for evidence-based sentiment v2 functions."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from sentiment_score.processors import (
    build_sector_summary,
    gather_evidence,
    fetch_current_prices,
)
from sentiment_score.prompter import (
    build_sector_score_prompt,
    score_sector,
)
from utils.db import DataStore


NOW = datetime.now(tz=timezone.utc)


def _insert(db, id, sector, headline, source="rss_coindesk",
            snippet="", tickers="[]", relevance=0.5, hours_ago=0,
            sentiment=0.0, magnitude="low", confidence=0.7,
            is_catalyst=0):
    ts = (NOW - timedelta(hours=hours_ago)).isoformat()
    db.execute(
        """INSERT OR IGNORE INTO articles
           (id, timestamp, source, headline, body_snippet, mentioned_tickers,
            relevance_score, is_catalyst, processed, llm_sector,
            llm_sentiment, llm_magnitude, llm_confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
        (id, ts, source, headline, snippet, tickers, relevance,
         is_catalyst, sector, sentiment, magnitude, confidence),
    )
    db.commit()


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "test.db"
    with DataStore(db_path=db_path) as db:
        yield db


@pytest.fixture
def sector_map():
    with open("config/sector_map.json") as f:
        return json.load(f)


# ═════════════════════════════════════════════════════════════════════════
# build_sector_summary
# ═════════════════════════════════════════════════════════════════════════


class TestBuildSectorSummary:
    def test_returns_correct_structure(self, tmp_db):
        _insert(tmp_db, "s1", "defi", "Uniswap v4 launches", hours_ago=1)
        _insert(tmp_db, "s2", "defi", "Aave proposal passes", hours_ago=2)
        result = build_sector_summary(tmp_db, "defi", lookback_hours=24)
        assert result["sector"] == "defi"
        assert result["article_count"] == 2
        assert len(result["top_headlines"]) == 2
        assert "velocity" in result
        assert "mentioned_tickers" in result
        assert "catalyst_count" in result

    def test_empty_sector(self, tmp_db):
        result = build_sector_summary(tmp_db, "meme", lookback_hours=24)
        assert result["article_count"] == 0
        assert result["top_headlines"] == []
        assert result["velocity"] == "steady"

    def test_limits_to_10_headlines(self, tmp_db):
        for i in range(15):
            _insert(tmp_db, f"lim{i}", "defi", f"Article {i}", hours_ago=i * 0.5)
        result = build_sector_summary(tmp_db, "defi", lookback_hours=24)
        assert len(result["top_headlines"]) <= 10

    def test_velocity_accelerating(self, tmp_db):
        for i in range(5):
            _insert(tmp_db, f"acc{i}", "ai_compute", f"AI news {i}", hours_ago=i)
        _insert(tmp_db, "acc_old", "ai_compute", "Old AI news", hours_ago=18)
        result = build_sector_summary(tmp_db, "ai_compute", lookback_hours=12)
        assert result["velocity"] == "accelerating"

    def test_velocity_decelerating(self, tmp_db):
        _insert(tmp_db, "dec0", "defi", "Recent", hours_ago=1)
        for i in range(5):
            _insert(tmp_db, f"dec{i+1}", "defi", f"Old {i}", hours_ago=15 + i)
        result = build_sector_summary(tmp_db, "defi", lookback_hours=12)
        assert result["velocity"] == "decelerating"

    def test_velocity_steady(self, tmp_db):
        for i in range(3):
            _insert(tmp_db, f"st_c{i}", "defi", f"Current {i}", hours_ago=i)
        for i in range(3):
            _insert(tmp_db, f"st_p{i}", "defi", f"Previous {i}", hours_ago=12 + i)
        result = build_sector_summary(tmp_db, "defi", lookback_hours=12)
        assert result["velocity"] == "steady"

    def test_includes_snippet_when_available(self, tmp_db):
        _insert(tmp_db, "snip1", "defi", "Headline", snippet="Body text here")
        result = build_sector_summary(tmp_db, "defi", lookback_hours=24)
        assert result["top_headlines"][0]["snippet"] == "Body text here"

    def test_empty_snippet_for_cryptopanic(self, tmp_db):
        _insert(tmp_db, "cp1", "defi", "CryptoPanic headline",
                source="cryptopanic", snippet="")
        result = build_sector_summary(tmp_db, "defi", lookback_hours=24)
        assert result["top_headlines"][0]["snippet"] == ""

    def test_mentioned_tickers_aggregated(self, tmp_db):
        _insert(tmp_db, "tk1", "defi", "UNI surges", tickers='["UNI"]')
        _insert(tmp_db, "tk2", "defi", "UNI and AAVE rally", tickers='["UNI", "AAVE"]')
        result = build_sector_summary(tmp_db, "defi", lookback_hours=24)
        assert result["mentioned_tickers"]["UNI"] == 2
        assert result["mentioned_tickers"]["AAVE"] == 1

    def test_catalyst_count(self, tmp_db):
        _insert(tmp_db, "cat1", "ai_compute", "FET partnership", is_catalyst=1)
        _insert(tmp_db, "cat2", "ai_compute", "NVIDIA news", is_catalyst=0)
        result = build_sector_summary(tmp_db, "ai_compute", lookback_hours=24)
        assert result["catalyst_count"] == 1

    def test_excludes_other_sectors(self, tmp_db):
        _insert(tmp_db, "sec1", "defi", "DeFi article")
        _insert(tmp_db, "sec2", "meme", "Meme article")
        result = build_sector_summary(tmp_db, "defi", lookback_hours=24)
        assert result["article_count"] == 1

    def test_excludes_old_articles(self, tmp_db):
        _insert(tmp_db, "old1", "defi", "Very old", hours_ago=50)
        _insert(tmp_db, "new1", "defi", "Recent", hours_ago=1)
        result = build_sector_summary(tmp_db, "defi", lookback_hours=24)
        assert result["article_count"] == 1


# ═════════════════════════════════════════════════════════════════════════
# fetch_current_prices
# ═════════════════════════════════════════════════════════════════════════


class TestFetchCurrentPrices:
    @patch("sentiment_score.processors.requests.get")
    def test_returns_prices(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "result": {
                "FETUSD": {
                    "c": ["1.42", "0.01"],
                    "o": "1.35",
                }
            }
        }
        mock_get.return_value.raise_for_status = lambda: None
        result = fetch_current_prices(["FET"])
        assert len(result) == 1
        assert result[0]["ticker"] == "FET"
        assert result[0]["price"] == 1.42

    @patch("sentiment_score.processors.requests.get")
    def test_handles_api_failure(self, mock_get):
        mock_get.side_effect = Exception("Network error")
        result = fetch_current_prices(["FET"])
        assert result == []

    @patch("sentiment_score.processors.requests.get")
    def test_computes_24h_change(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = {
            "result": {
                "XBTUSD": {
                    "c": ["84000", "0.5"],
                    "o": "86000",
                }
            }
        }
        result = fetch_current_prices(["BTC"])
        assert result[0]["change_24h_pct"] == pytest.approx(-2.326, abs=0.01)

    def test_empty_tickers(self):
        result = fetch_current_prices([])
        assert result == []

    @patch("sentiment_score.processors.requests.get")
    def test_max_5_tickers(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = {"result": {}}
        fetch_current_prices(["A", "B", "C", "D", "E", "F", "G"])
        # Should only request 5
        called_url = mock_get.call_args[0][0]
        pairs = called_url.split("pair=")[1].split(",")
        assert len(pairs) == 5


# ═════════════════════════════════════════════════════════════════════════
# gather_evidence
# ═════════════════════════════════════════════════════════════════════════


class TestGatherEvidence:
    @patch("sentiment_score.processors.fetch_current_prices")
    def test_returns_evidence_dict(self, mock_prices, sector_map):
        mock_prices.return_value = [
            {"ticker": "FET", "price": 1.42, "change_24h_pct": 5.1},
        ]
        summary = {"mentioned_tickers": {"FET": 3}}
        prev_signals = {"ai_compute": 0.2}
        result = gather_evidence("ai_compute", sector_map, summary, prev_signals)
        assert "token_prices" in result
        assert "previous_sentiment" in result
        assert result["previous_sentiment"] == 0.2
        assert len(result["token_prices"]) == 1

    @patch("sentiment_score.processors.fetch_current_prices")
    def test_no_previous_signals(self, mock_prices, sector_map):
        mock_prices.return_value = []
        summary = {"mentioned_tickers": {}}
        result = gather_evidence("defi", sector_map, summary, None)
        assert result["previous_sentiment"] == 0.0

    @patch("sentiment_score.processors.fetch_current_prices")
    def test_selects_sector_tokens(self, mock_prices, sector_map):
        mock_prices.return_value = []
        summary = {"mentioned_tickers": {}}
        gather_evidence("ai_compute", sector_map, summary, None)
        called_tickers = mock_prices.call_args[0][0]
        assert "FET" in called_tickers

    @patch("sentiment_score.processors.fetch_current_prices")
    def test_optional_fields_none_by_default(self, mock_prices, sector_map):
        mock_prices.return_value = []
        summary = {"mentioned_tickers": {}}
        result = gather_evidence("defi", sector_map, summary, None)
        assert result["funding_rate"] is None
        assert result["nupl"] is None
        assert result["exchange_net_flow"] is None

    @patch("sentiment_score.processors.fetch_current_prices")
    def test_missing_sector_in_previous(self, mock_prices, sector_map):
        mock_prices.return_value = []
        summary = {"mentioned_tickers": {}}
        result = gather_evidence("meme", sector_map, summary, {"defi": 0.5})
        assert result["previous_sentiment"] == 0.0


# ═════════════════════════════════════════════════════════════════════════
# build_sector_score_prompt
# ═════════════════════════════════════════════════════════════════════════


class TestBuildSectorScorePrompt:
    def test_includes_sector_and_headlines(self):
        summary = {
            "sector": "ai_compute", "article_count": 3, "velocity": "accelerating",
            "top_headlines": [
                {"headline": "NVIDIA AI chip", "snippet": "Details...",
                 "source": "rss_coindesk", "tickers": ["FET"],
                 "age_hours": 2.0, "is_catalyst": False},
            ],
            "mentioned_tickers": {"FET": 2}, "catalyst_count": 0,
        }
        evidence = {
            "token_prices": [{"ticker": "FET", "price": 1.42, "change_24h_pct": 5.1}],
            "previous_sentiment": -0.15,
            "funding_rate": None, "nupl": None, "exchange_net_flow": None,
        }
        prompt = build_sector_score_prompt(summary, evidence)
        assert "ai_compute" in prompt
        assert "NVIDIA AI chip" in prompt
        assert "FET" in prompt
        assert "1.42" in prompt
        assert "-0.15" in prompt

    def test_omits_none_signals(self):
        summary = {
            "sector": "defi", "article_count": 1, "velocity": "steady",
            "top_headlines": [{"headline": "Test", "snippet": "", "source": "rss",
                              "tickers": [], "age_hours": 1.0, "is_catalyst": False}],
            "mentioned_tickers": {}, "catalyst_count": 0,
        }
        evidence = {
            "token_prices": [], "previous_sentiment": 0.0,
            "funding_rate": None, "nupl": None, "exchange_net_flow": None,
        }
        prompt = build_sector_score_prompt(summary, evidence)
        assert "Funding rate" not in prompt
        assert "NUPL" not in prompt

    def test_includes_optional_signals_when_present(self):
        summary = {
            "sector": "defi", "article_count": 1, "velocity": "steady",
            "top_headlines": [], "mentioned_tickers": {}, "catalyst_count": 0,
        }
        evidence = {
            "token_prices": [], "previous_sentiment": 0.0,
            "funding_rate": 0.015, "nupl": 0.72, "exchange_net_flow": "inflow",
        }
        prompt = build_sector_score_prompt(summary, evidence)
        assert "Funding rate" in prompt
        assert "NUPL" in prompt
        assert "inflow" in prompt

    def test_catalyst_tag_in_headline(self):
        summary = {
            "sector": "ai_compute", "article_count": 1, "velocity": "steady",
            "top_headlines": [{"headline": "FET hack", "snippet": "",
                              "source": "rss", "tickers": [], "age_hours": 0.5,
                              "is_catalyst": True}],
            "mentioned_tickers": {}, "catalyst_count": 1,
        }
        evidence = {
            "token_prices": [], "previous_sentiment": 0.0,
            "funding_rate": None, "nupl": None, "exchange_net_flow": None,
        }
        prompt = build_sector_score_prompt(summary, evidence)
        assert "[CATALYST]" in prompt


# ═════════════════════════════════════════════════════════════════════════
# score_sector
# ═════════════════════════════════════════════════════════════════════════


_EMPTY_SUMMARY = {
    "sector": "meme", "article_count": 0, "velocity": "steady",
    "top_headlines": [], "mentioned_tickers": {}, "catalyst_count": 0,
}
_EMPTY_EVIDENCE = {
    "token_prices": [], "previous_sentiment": 0.0,
    "funding_rate": None, "nupl": None, "exchange_net_flow": None,
}
_FILLED_SUMMARY = {
    "sector": "ai_compute", "article_count": 3, "velocity": "accelerating",
    "top_headlines": [
        {"headline": "NVIDIA AI chip", "snippet": "", "source": "rss",
         "tickers": [], "age_hours": 1.0, "is_catalyst": False},
    ],
    "mentioned_tickers": {"FET": 2}, "catalyst_count": 0,
}


class TestScoreSector:
    def test_empty_sector_skips_llm(self):
        with patch("sentiment_score.prompter.call_llm") as mock_llm:
            result = score_sector(_EMPTY_SUMMARY, _EMPTY_EVIDENCE)
            mock_llm.assert_not_called()
            assert result["sentiment"] == 0.0
            assert result["confidence"] == 0.0

    def test_valid_response(self):
        response = {
            "sentiment": 0.45, "magnitude": "medium", "confidence": 0.8,
            "key_driver": "NVIDIA partnership",
            "reasoning": "Strong signal from NVIDIA. FET up 5%.",
        }
        with patch("sentiment_score.prompter.call_llm",
                   return_value=(json.dumps(response), {}, "openai/gpt-5.4-nano")):
            result = score_sector(_FILLED_SUMMARY, _EMPTY_EVIDENCE)
            assert result["sentiment"] == 0.45
            assert result["key_driver"] == "NVIDIA partnership"
            assert "NVIDIA" in result["reasoning"]

    def test_clamps_sentiment(self):
        response = {"sentiment": 5.0, "magnitude": "high", "confidence": 0.5,
                    "key_driver": "x", "reasoning": "y"}
        with patch("sentiment_score.prompter.call_llm",
                   return_value=(json.dumps(response), {}, "test")):
            result = score_sector(_FILLED_SUMMARY, _EMPTY_EVIDENCE)
            assert result["sentiment"] == 1.0

    def test_clamps_negative_sentiment(self):
        response = {"sentiment": -3.0, "magnitude": "low", "confidence": 0.5,
                    "key_driver": "x", "reasoning": "y"}
        with patch("sentiment_score.prompter.call_llm",
                   return_value=(json.dumps(response), {}, "test")):
            result = score_sector(_FILLED_SUMMARY, _EMPTY_EVIDENCE)
            assert result["sentiment"] == -1.0

    def test_invalid_magnitude_defaults(self):
        response = {"sentiment": 0.3, "magnitude": "extreme", "confidence": 0.5,
                    "key_driver": "x", "reasoning": "y"}
        with patch("sentiment_score.prompter.call_llm",
                   return_value=(json.dumps(response), {}, "test")):
            result = score_sector(_FILLED_SUMMARY, _EMPTY_EVIDENCE)
            assert result["magnitude"] == "low"

    def test_json_error_returns_default(self):
        with patch("sentiment_score.prompter.call_llm",
                   return_value=("not json", {}, "test")):
            result = score_sector(_FILLED_SUMMARY, _EMPTY_EVIDENCE)
            assert result["sentiment"] == 0.0
            assert result["confidence"] == 0.0

    def test_exception_returns_default(self):
        with patch("sentiment_score.prompter.call_llm",
                   side_effect=RuntimeError("API down")):
            result = score_sector(_FILLED_SUMMARY, _EMPTY_EVIDENCE)
            assert result["sentiment"] == 0.0

    def test_code_fences_handled(self):
        response_text = '```json\n{"sentiment": 0.6, "magnitude": "medium", "confidence": 0.8, "key_driver": "x", "reasoning": "y"}\n```'
        with patch("sentiment_score.prompter.call_llm",
                   return_value=(response_text, {}, "test")):
            result = score_sector(_FILLED_SUMMARY, _EMPTY_EVIDENCE)
            assert result["sentiment"] == 0.6
