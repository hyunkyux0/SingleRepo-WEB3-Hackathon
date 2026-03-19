"""Tests for scripts/fetch_news.py — fetching, age cutoff, deduplication."""

from datetime import datetime, timedelta, timezone

import pytest

from scripts.fetch_news import _filter_by_age, deduplicate, _jaccard_similarity


class TestAgeFilter:
    def test_old_articles_filtered(self):
        now = datetime.now(tz=timezone.utc)
        articles = [
            {"timestamp": (now - timedelta(hours=2)).isoformat(), "headline": "Recent"},
            {"timestamp": (now - timedelta(hours=30)).isoformat(), "headline": "Old"},
        ]
        result = _filter_by_age(articles, max_age_hours=24)
        assert len(result) == 1
        assert result[0]["headline"] == "Recent"

    def test_no_timestamp_kept(self):
        articles = [{"headline": "No timestamp"}]
        result = _filter_by_age(articles, max_age_hours=24)
        assert len(result) == 1

    def test_empty_timestamp_kept(self):
        articles = [{"timestamp": "", "headline": "Empty ts"}]
        result = _filter_by_age(articles, max_age_hours=24)
        assert len(result) == 1

    def test_all_recent_kept(self):
        now = datetime.now(tz=timezone.utc)
        articles = [
            {"timestamp": (now - timedelta(hours=i)).isoformat(), "headline": f"Art {i}"}
            for i in range(5)
        ]
        result = _filter_by_age(articles, max_age_hours=24)
        assert len(result) == 5

    def test_custom_max_age(self):
        now = datetime.now(tz=timezone.utc)
        articles = [
            {"timestamp": (now - timedelta(hours=3)).isoformat(), "headline": "3h old"},
            {"timestamp": (now - timedelta(hours=7)).isoformat(), "headline": "7h old"},
        ]
        result = _filter_by_age(articles, max_age_hours=5)
        assert len(result) == 1
        assert result[0]["headline"] == "3h old"

    def test_unparseable_timestamp_kept(self):
        articles = [{"timestamp": "not-a-date", "headline": "Bad ts"}]
        result = _filter_by_age(articles, max_age_hours=24)
        assert len(result) == 1

    def test_empty_list(self):
        assert _filter_by_age([], max_age_hours=24) == []


class TestFetchDeduplication:
    def test_removes_duplicate_urls(self):
        articles = [
            {"url": "https://x.com/1", "headline": "First"},
            {"url": "https://x.com/1", "headline": "Duplicate URL"},
        ]
        result = deduplicate(articles)
        assert len(result) == 1
        assert result[0]["headline"] == "First"

    def test_removes_similar_headlines(self):
        articles = [
            {"url": "", "headline": "Bitcoin price surges to new record high today"},
            {"url": "", "headline": "Bitcoin price surges to new record high"},
        ]
        result = deduplicate(articles)
        assert len(result) == 1

    def test_keeps_different_articles(self):
        articles = [
            {"url": "https://a.com/1", "headline": "Bitcoin rallies"},
            {"url": "https://b.com/2", "headline": "Ethereum DeFi protocol launches"},
        ]
        result = deduplicate(articles)
        assert len(result) == 2

    def test_empty_list(self):
        assert deduplicate([]) == []


class TestJaccardSimilarity:
    def test_identical(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_different(self):
        assert _jaccard_similarity("cat dog", "fish bird") == 0.0

    def test_empty(self):
        assert _jaccard_similarity("", "test") == 0.0
