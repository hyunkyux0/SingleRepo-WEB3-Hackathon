"""Tests for the news_sentiment module — models, processors, and prompter."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from news_sentiment.models import ArticleInput, ClassificationOutput
from news_sentiment.processors import (
    load_sector_map,
    load_sources_config,
    _jaccard_similarity,
    deduplicate,
    keyword_prefilter,
    store_articles,
    get_unprocessed_articles,
    mark_processed,
)
from news_sentiment.prompter import (
    VALID_SECTORS,
    FAST_CLASSIFY_SYSTEM,
    BATCH_CLASSIFY_SYSTEM,
    build_fast_classify_prompt,
    build_batch_classify_prompt,
    _strip_code_fences,
    _validate_sector,
    _default_classification,
    classify_article_fast,
    classify_article_batch,
)
from utils.db import DataStore


NOW = datetime.now(tz=timezone.utc)


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "test.db"
    with DataStore(db_path=db_path) as db:
        yield db


@pytest.fixture
def sector_map():
    return load_sector_map("config/sector_map.json")


def _make_article(id="t1", headline="Test", **kwargs):
    defaults = dict(timestamp=NOW, source="rss", headline=headline)
    defaults.update(kwargs)
    return ArticleInput(id=id, **defaults)


# ═════════════════════════════════════════════════════════════════════════
# Models
# ═════════════════════════════════════════════════════════════════════════


class TestArticleInput:
    def test_full_construction(self):
        art = _make_article(
            id="full1",
            headline="BTC up",
            body_snippet="Bitcoin...",
            url="https://x.com/1",
            mentioned_tickers=["BTC"],
            source_sentiment=0.5,
            relevance_score=0.8,
            is_catalyst=True,
            matched_sectors=["l1_infra"],
        )
        assert art.id == "full1"
        assert art.is_catalyst is True
        assert art.mentioned_tickers == ["BTC"]

    def test_defaults(self):
        art = _make_article()
        assert art.body_snippet == ""
        assert art.url == ""
        assert art.mentioned_tickers == []
        assert art.source_sentiment is None
        assert art.relevance_score == 0.0
        assert art.is_catalyst is False
        assert art.matched_sectors == []

    def test_model_copy_preserves_id(self):
        art = _make_article(id="copy1")
        art2 = art.model_copy(update={"relevance_score": 0.9})
        assert art2.id == "copy1"
        assert art2.relevance_score == 0.9


class TestClassificationOutput:
    def test_full_construction(self):
        cls = ClassificationOutput(
            primary_sector="ai_compute",
            secondary_sector="l1_infra",
            sentiment=0.85,
            magnitude="high",
            confidence=0.9,
            cross_market=True,
            reasoning="NVIDIA impact",
        )
        assert cls.primary_sector == "ai_compute"
        assert cls.sentiment == 0.85

    def test_defaults(self):
        cls = ClassificationOutput(
            primary_sector="other", sentiment=0.0, magnitude="low"
        )
        assert cls.secondary_sector is None
        assert cls.confidence == 0.0
        assert cls.cross_market is False
        assert cls.reasoning == ""

    def test_extreme_sentiment_values(self):
        cls = ClassificationOutput(
            primary_sector="meme", sentiment=-1.0, magnitude="high"
        )
        assert cls.sentiment == -1.0


# ═════════════════════════════════════════════════════════════════════════
# Processors — Config loaders
# ═════════════════════════════════════════════════════════════════════════


class TestConfigLoaders:
    def test_sector_map_has_67_tokens(self):
        sm = load_sector_map("config/sector_map.json")
        assert len(sm) == 67

    def test_sector_map_all_have_primary(self):
        sm = load_sector_map("config/sector_map.json")
        for token, info in sm.items():
            assert "primary" in info, f"{token} missing primary"
            assert info["primary"] in VALID_SECTORS

    def test_sector_map_dual_routing(self):
        sm = load_sector_map("config/sector_map.json")
        assert sm["NEAR/USD"]["secondary"] == "ai_compute"
        assert sm["BTC/USD"]["secondary"] == "store_of_value"

    def test_sources_config_structure(self):
        sc = load_sources_config("config/sources.json")
        assert "sources" in sc
        for s in sc["sources"]:
            assert "id" in s
            assert "type" in s
            assert "enabled" in s
            assert "source_weight" in s


# ═════════════════════════════════════════════════════════════════════════
# Processors — Jaccard similarity
# ═════════════════════════════════════════════════════════════════════════


class TestJaccardSimilarity:
    def test_identical_strings(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert _jaccard_similarity("cat dog", "fish bird") == 0.0

    def test_partial_overlap(self):
        sim = _jaccard_similarity("bitcoin price rises", "bitcoin price drops")
        assert 0.3 < sim < 0.8  # 2/4 overlap

    def test_near_duplicate_headlines(self):
        a = "Bitcoin surges to new all-time high amid ETF approval"
        b = "Bitcoin surges to new all-time high following ETF approval"
        assert _jaccard_similarity(a, b) > 0.7

    def test_empty_first(self):
        assert _jaccard_similarity("", "test") == 0.0

    def test_empty_second(self):
        assert _jaccard_similarity("test", "") == 0.0

    def test_both_empty(self):
        assert _jaccard_similarity("", "") == 0.0

    def test_case_insensitive(self):
        assert _jaccard_similarity("BITCOIN", "bitcoin") == 1.0


# ═════════════════════════════════════════════════════════════════════════
# Processors — Keyword pre-filter
# ═════════════════════════════════════════════════════════════════════════


class TestKeywordPrefilter:
    def test_ticker_match_boosts_relevance(self, sector_map):
        articles = [_make_article(id="t1", headline="FET announces new AI partnership")]
        result = keyword_prefilter(articles, sector_map)
        assert len(result) == 1
        assert result[0].relevance_score > 0.1
        assert "FET" in result[0].mentioned_tickers
        assert "ai_compute" in result[0].matched_sectors

    def test_high_impact_keyword_boosts_relevance(self, sector_map):
        articles = [_make_article(id="t2", headline="Major crypto exchange listing announced")]
        result = keyword_prefilter(articles, sector_map)
        assert len(result) == 1
        assert result[0].relevance_score >= 0.25

    def test_irrelevant_article_filtered(self, sector_map):
        articles = [_make_article(id="t3", headline="Weather forecast for next week")]
        result = keyword_prefilter(articles, sector_map)
        assert len(result) == 0

    def test_catalyst_detection(self, sector_map):
        articles = [
            _make_article(id="c1", headline="FET partnership with Google announced")
        ]
        result = keyword_prefilter(articles, sector_map)
        assert len(result) == 1
        assert result[0].is_catalyst is True

    def test_no_catalyst_without_ticker(self, sector_map):
        articles = [
            _make_article(id="c2", headline="New crypto exchange listing announced")
        ]
        result = keyword_prefilter(articles, sector_map)
        # Has high-impact keyword but no specific ticker -> not catalyst
        if result:
            assert result[0].is_catalyst is False

    def test_sector_keywords_boost(self, sector_map):
        articles = [_make_article(id="sk1", headline="New DeFi protocol launches with high TVL")]
        result = keyword_prefilter(articles, sector_map)
        assert len(result) == 1
        assert result[0].relevance_score >= 0.15

    def test_crypto_baseline_boost(self, sector_map):
        articles = [_make_article(id="cb1", headline="Blockchain technology advances")]
        result = keyword_prefilter(articles, sector_map)
        assert len(result) == 1  # 'blockchain' is a crypto term

    def test_short_ticker_no_false_positive(self, sector_map):
        # Ticker "S" should not match inside words like "sports"
        articles = [_make_article(id="fp1", headline="Sports news today is exciting")]
        result = keyword_prefilter(articles, sector_map)
        # Should be filtered out — no crypto relevance
        assert len(result) == 0

    def test_short_ticker_standalone_match(self, sector_map):
        # Ticker "S" as standalone word should match
        articles = [_make_article(id="fp2", headline="Token S launches new partnership")]
        result = keyword_prefilter(articles, sector_map)
        assert len(result) == 1
        assert "S" in result[0].mentioned_tickers

    def test_relevance_capped_at_1(self, sector_map):
        # Article with many matches should still cap at 1.0
        articles = [
            _make_article(
                id="cap1",
                headline="BTC ETF SEC partnership launch upgrade exploit breach",
            )
        ]
        result = keyword_prefilter(articles, sector_map)
        if result:
            assert result[0].relevance_score <= 1.0

    def test_preserves_existing_tickers(self, sector_map):
        articles = [
            _make_article(
                id="pres1",
                headline="FET announces partnership",
                mentioned_tickers=["EXISTING"],
            )
        ]
        result = keyword_prefilter(articles, sector_map)
        assert "EXISTING" in result[0].mentioned_tickers
        assert "FET" in result[0].mentioned_tickers

    def test_empty_input(self, sector_map):
        result = keyword_prefilter([], sector_map)
        assert result == []


# ═════════════════════════════════════════════════════════════════════════
# Processors — Deduplication
# ═════════════════════════════════════════════════════════════════════════


class TestDeduplicate:
    def test_url_dedup_against_db(self, tmp_db):
        # Store an article first
        store_articles(
            [_make_article(id="existing1", headline="Old news", url="https://x.com/1")],
            tmp_db,
        )
        # Try to add same URL
        new = [_make_article(id="new1", headline="Different", url="https://x.com/1")]
        result = deduplicate(new, tmp_db)
        assert len(result) == 0

    def test_jaccard_dedup_within_batch(self, tmp_db):
        articles = [
            _make_article(id="j1", headline="Bitcoin price surges to new record high today"),
            _make_article(id="j2", headline="Bitcoin price surges to new record high"),
        ]
        result = deduplicate(articles, tmp_db)
        assert len(result) == 1
        assert result[0].id == "j1"  # keeps first

    def test_different_articles_kept(self, tmp_db):
        articles = [
            _make_article(id="d1", headline="Bitcoin rallies on ETF news"),
            _make_article(id="d2", headline="Ethereum DeFi protocol launches"),
        ]
        result = deduplicate(articles, tmp_db)
        assert len(result) == 2

    def test_empty_url_not_deduped(self, tmp_db):
        store_articles(
            [_make_article(id="e1", headline="First", url="")],
            tmp_db,
        )
        new = [_make_article(id="e2", headline="Completely different article", url="")]
        result = deduplicate(new, tmp_db)
        assert len(result) == 1  # empty URLs don't match

    def test_empty_input(self, tmp_db):
        assert deduplicate([], tmp_db) == []


# ═════════════════════════════════════════════════════════════════════════
# Processors — SQLite persistence
# ═════════════════════════════════════════════════════════════════════════


class TestSQLitePersistence:
    def test_store_articles_returns_count(self, tmp_db):
        articles = [_make_article(id=f"s{i}", headline=f"Art {i}") for i in range(3)]
        assert store_articles(articles, tmp_db) == 3

    def test_store_articles_duplicate_ignored(self, tmp_db):
        art = _make_article(id="dup1", headline="Test")
        store_articles([art], tmp_db)
        assert store_articles([art], tmp_db) == 0  # already exists

    def test_store_empty_list(self, tmp_db):
        assert store_articles([], tmp_db) == 0

    def test_get_unprocessed(self, tmp_db):
        store_articles(
            [_make_article(id=f"u{i}", headline=f"Unp {i}") for i in range(5)],
            tmp_db,
        )
        result = get_unprocessed_articles(tmp_db)
        assert len(result) == 5

    def test_mark_processed_updates_fields(self, tmp_db):
        store_articles([_make_article(id="mp1", headline="Mark test")], tmp_db)

        cls = ClassificationOutput(
            primary_sector="defi",
            secondary_sector="l1_infra",
            sentiment=-0.5,
            magnitude="medium",
            confidence=0.7,
            cross_market=False,
            reasoning="DeFi negative news",
        )
        mark_processed("mp1", cls, tmp_db)

        row = tmp_db.fetchone("SELECT * FROM articles WHERE id = ?", ("mp1",))
        assert row["processed"] == 1
        assert row["llm_sector"] == "defi"
        assert row["llm_secondary_sector"] == "l1_infra"
        assert row["llm_sentiment"] == -0.5
        assert row["llm_magnitude"] == "medium"
        assert row["llm_confidence"] == 0.7

    def test_mark_processed_reduces_unprocessed_count(self, tmp_db):
        store_articles(
            [_make_article(id=f"r{i}", headline=f"Reduce {i}") for i in range(3)],
            tmp_db,
        )
        assert len(get_unprocessed_articles(tmp_db)) == 3

        cls = ClassificationOutput(primary_sector="other", sentiment=0.0, magnitude="low")
        mark_processed("r0", cls, tmp_db)
        assert len(get_unprocessed_articles(tmp_db)) == 2

    def test_stored_article_preserves_json_fields(self, tmp_db):
        art = _make_article(
            id="json1",
            headline="JSON test",
            mentioned_tickers=["BTC", "ETH"],
            matched_sectors=["l1_infra"],
        )
        store_articles([art], tmp_db)
        result = get_unprocessed_articles(tmp_db)
        assert result[0].mentioned_tickers == ["BTC", "ETH"]
        assert result[0].matched_sectors == ["l1_infra"]


# ═════════════════════════════════════════════════════════════════════════
# Prompter — helpers
# ═════════════════════════════════════════════════════════════════════════


class TestPrompterHelpers:
    def test_strip_code_fences_plain_json(self):
        assert _strip_code_fences('{"a": 1}') == '{"a": 1}'

    def test_strip_code_fences_json_block(self):
        assert _strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_strip_code_fences_bare_block(self):
        assert _strip_code_fences('```\n{"a": 1}\n```') == '{"a": 1}'

    def test_strip_code_fences_with_whitespace(self):
        result = _strip_code_fences('  \n```json\n{"a": 1}\n```\n  ')
        assert result == '{"a": 1}'

    def test_validate_sector_valid(self):
        for s in VALID_SECTORS:
            assert _validate_sector(s) == s

    def test_validate_sector_case_insensitive(self):
        assert _validate_sector("DEFI") == "defi"
        assert _validate_sector("AI_COMPUTE") == "ai_compute"

    def test_validate_sector_strips_whitespace(self):
        assert _validate_sector("  l1_infra  ") == "l1_infra"

    def test_validate_sector_unknown_maps_to_other(self):
        assert _validate_sector("gaming") == "other"

    def test_validate_sector_none_returns_none(self):
        assert _validate_sector(None) is None

    def test_validate_sector_null_string_returns_none(self):
        assert _validate_sector("null") is None

    def test_validate_sector_empty_returns_none(self):
        assert _validate_sector("") is None

    def test_default_classification(self):
        d = _default_classification()
        assert d.primary_sector == "other"
        assert d.sentiment == 0.0
        assert d.magnitude == "low"
        assert d.confidence == 0.0


# ═════════════════════════════════════════════════════════════════════════
# Prompter — prompt builders
# ═════════════════════════════════════════════════════════════════════════


class TestPromptBuilders:
    def test_fast_prompt_includes_headline(self):
        art = _make_article(headline="NVIDIA AI chip launch")
        prompt = build_fast_classify_prompt(art)
        assert "NVIDIA AI chip launch" in prompt

    def test_fast_prompt_includes_tickers(self):
        art = _make_article(headline="Test", mentioned_tickers=["BTC", "ETH"])
        prompt = build_fast_classify_prompt(art)
        assert "BTC" in prompt
        assert "ETH" in prompt

    def test_fast_prompt_includes_prematched_sectors(self):
        art = _make_article(headline="Test", matched_sectors=["ai_compute"])
        prompt = build_fast_classify_prompt(art)
        assert "ai_compute" in prompt

    def test_fast_prompt_omits_empty_fields(self):
        art = _make_article(headline="Test")
        prompt = build_fast_classify_prompt(art)
        assert "Snippet:" not in prompt
        assert "Mentioned tickers:" not in prompt

    def test_batch_prompt_no_prematched_sectors(self):
        art = _make_article(headline="Test", matched_sectors=["defi"])
        prompt = build_batch_classify_prompt(art)
        assert "Pre-matched" not in prompt

    def test_batch_prompt_includes_snippet(self):
        art = _make_article(headline="Test", body_snippet="Some body text here")
        prompt = build_batch_classify_prompt(art)
        assert "Some body text here" in prompt

    def test_system_prompts_have_all_sectors(self):
        for sector in VALID_SECTORS:
            assert sector in FAST_CLASSIFY_SYSTEM
            if sector != "other":  # "other" may just say "don't fit above"
                assert sector in BATCH_CLASSIFY_SYSTEM


# ═════════════════════════════════════════════════════════════════════════
# Prompter — classify functions (mocked LLM)
# ═════════════════════════════════════════════════════════════════════════


class TestClassifyFunctions:
    def _mock_llm_response(self, response_json):
        """Create a mock for call_llm that returns the given JSON string."""
        return patch(
            "news_sentiment.prompter.call_llm",
            return_value=(json.dumps(response_json), {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, "openrouter/test-model"),
        )

    def test_classify_fast_valid_response(self):
        response = {
            "primary_sector": "ai_compute",
            "secondary_sector": "l1_infra",
            "sentiment": 0.8,
            "magnitude": "high",
            "confidence": 0.9,
            "cross_market": True,
            "reasoning": "NVIDIA impact on AI tokens",
        }
        with self._mock_llm_response(response):
            art = _make_article(headline="NVIDIA AI chip")
            result = classify_article_fast(art)
            assert result.primary_sector == "ai_compute"
            assert result.secondary_sector == "l1_infra"
            assert result.sentiment == 0.8
            assert result.magnitude == "high"
            assert result.confidence == 0.9
            assert result.cross_market is True

    def test_classify_fast_clamps_sentiment(self):
        response = {
            "primary_sector": "meme",
            "sentiment": 2.5,  # out of range
            "magnitude": "high",
            "confidence": 0.5,
        }
        with self._mock_llm_response(response):
            result = classify_article_fast(_make_article(headline="Test"))
            assert result.sentiment == 1.0  # clamped

    def test_classify_fast_clamps_negative_sentiment(self):
        response = {
            "primary_sector": "defi",
            "sentiment": -3.0,  # out of range
            "magnitude": "low",
            "confidence": 0.5,
        }
        with self._mock_llm_response(response):
            result = classify_article_fast(_make_article(headline="Test"))
            assert result.sentiment == -1.0

    def test_classify_fast_unknown_sector_to_other(self):
        response = {
            "primary_sector": "gaming",  # not valid
            "sentiment": 0.3,
            "magnitude": "medium",
            "confidence": 0.5,
        }
        with self._mock_llm_response(response):
            result = classify_article_fast(_make_article(headline="Test"))
            assert result.primary_sector == "other"

    def test_classify_fast_invalid_magnitude_defaults(self):
        response = {
            "primary_sector": "defi",
            "sentiment": 0.5,
            "magnitude": "extreme",  # not valid
            "confidence": 0.5,
        }
        with self._mock_llm_response(response):
            result = classify_article_fast(_make_article(headline="Test"))
            assert result.magnitude == "low"

    def test_classify_fast_json_error_returns_default(self):
        with patch(
            "news_sentiment.prompter.call_llm",
            return_value=("not valid json", {}, "test"),
        ):
            result = classify_article_fast(_make_article(headline="Test"))
            assert result.primary_sector == "other"
            assert result.sentiment == 0.0

    def test_classify_fast_code_fences_handled(self):
        response_text = '```json\n{"primary_sector": "defi", "sentiment": 0.4, "magnitude": "medium", "confidence": 0.7}\n```'
        with patch(
            "news_sentiment.prompter.call_llm",
            return_value=(response_text, {}, "test"),
        ):
            result = classify_article_fast(_make_article(headline="Test"))
            assert result.primary_sector == "defi"
            assert result.sentiment == 0.4

    def test_classify_batch_leaves_sentiment_at_zero(self):
        response = {
            "primary_sector": "l1_infra",
            "secondary_sector": None,
            "confidence": 0.85,
            "cross_market": False,
        }
        with self._mock_llm_response(response):
            result = classify_article_batch(_make_article(headline="Test"))
            assert result.primary_sector == "l1_infra"
            assert result.sentiment == 0.0  # not scored in batch classify
            assert result.magnitude == "low"  # default

    def test_classify_batch_json_error_returns_default(self):
        with patch(
            "news_sentiment.prompter.call_llm",
            return_value=("broken", {}, "test"),
        ):
            result = classify_article_batch(_make_article(headline="Test"))
            assert result.primary_sector == "other"

    def test_classify_fast_exception_returns_default(self):
        with patch(
            "news_sentiment.prompter.call_llm",
            side_effect=RuntimeError("API down"),
        ):
            result = classify_article_fast(_make_article(headline="Test"))
            assert result.primary_sector == "other"
            assert result.sentiment == 0.0
