"""Tests for utils/db.py — DataStore abstraction over SQLite."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from utils.db import DataStore


@pytest.fixture
def tmp_db(tmp_path):
    """Provide a DataStore backed by a temporary database."""
    db_path = tmp_path / "test.db"
    with DataStore(db_path=db_path) as db:
        yield db


# ── Connection lifecycle ─────────────────────────────────────────────────


class TestConnectionLifecycle:
    def test_open_creates_file(self, tmp_path):
        db_path = tmp_path / "sub" / "dir" / "test.db"
        db = DataStore(db_path=db_path)
        db.open()
        assert db_path.exists()
        db.close()

    def test_open_is_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = DataStore(db_path=db_path)
        db.open()
        db.open()  # should not raise
        db.close()

    def test_close_is_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = DataStore(db_path=db_path)
        db.open()
        db.close()
        db.close()  # should not raise

    def test_context_manager(self, tmp_path):
        db_path = tmp_path / "test.db"
        with DataStore(db_path=db_path) as db:
            db.execute("SELECT 1")
        # After context exit, store should be closed
        with pytest.raises(RuntimeError):
            db.execute("SELECT 1")

    def test_closed_store_raises_on_execute(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = DataStore(db_path=db_path)
        with pytest.raises(RuntimeError, match="not open"):
            db.execute("SELECT 1")

    def test_closed_store_raises_on_fetchone(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = DataStore(db_path=db_path)
        with pytest.raises(RuntimeError, match="not open"):
            db.fetchone("SELECT 1")

    def test_closed_store_raises_on_fetchall(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = DataStore(db_path=db_path)
        with pytest.raises(RuntimeError, match="not open"):
            db.fetchall("SELECT 1")


# ── Table creation ───────────────────────────────────────────────────────


class TestTableCreation:
    def test_articles_table_exists(self, tmp_db):
        tables = tmp_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        names = {r["name"] for r in tables}
        assert "articles" in names

    def test_signal_log_table_exists(self, tmp_db):
        tables = tmp_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        names = {r["name"] for r in tables}
        assert "signal_log" in names

    def test_articles_columns(self, tmp_db):
        cursor = tmp_db.execute("PRAGMA table_info(articles)")
        cols = {row["name"] for row in cursor.fetchall()}
        expected = {
            "id", "timestamp", "source", "headline", "body_snippet",
            "url", "mentioned_tickers", "source_sentiment", "relevance_score",
            "is_catalyst", "matched_sectors", "processed", "llm_sector",
            "llm_secondary_sector", "llm_sentiment", "llm_magnitude",
            "llm_confidence", "llm_cross_market", "llm_reasoning", "created_at",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_init_tables_is_idempotent(self, tmp_db):
        tmp_db.init_tables()  # should not raise even if tables exist
        count = tmp_db.fetchone("SELECT COUNT(*) as cnt FROM articles")
        assert count["cnt"] >= 0


# ── CRUD operations ──────────────────────────────────────────────────────


class TestCRUD:
    def test_insert_and_fetch_article(self, tmp_db):
        tmp_db.execute(
            "INSERT INTO articles (id, timestamp, source, headline) "
            "VALUES (?, ?, ?, ?)",
            ("art1", "2026-03-18T10:00:00", "cryptopanic", "Test headline"),
        )
        tmp_db.commit()
        row = tmp_db.fetchone("SELECT * FROM articles WHERE id = ?", ("art1",))
        assert row is not None
        assert row["headline"] == "Test headline"
        assert row["source"] == "cryptopanic"

    def test_insert_duplicate_id_ignored(self, tmp_db):
        tmp_db.execute(
            "INSERT OR IGNORE INTO articles (id, timestamp, source, headline) "
            "VALUES (?, ?, ?, ?)",
            ("dup1", "2026-03-18T10:00:00", "rss", "First"),
        )
        tmp_db.execute(
            "INSERT OR IGNORE INTO articles (id, timestamp, source, headline) "
            "VALUES (?, ?, ?, ?)",
            ("dup1", "2026-03-18T11:00:00", "rss", "Second"),
        )
        tmp_db.commit()
        row = tmp_db.fetchone("SELECT * FROM articles WHERE id = ?", ("dup1",))
        assert row["headline"] == "First"  # first insert wins

    def test_fetchall_returns_list(self, tmp_db):
        for i in range(5):
            tmp_db.execute(
                "INSERT INTO articles (id, timestamp, source, headline) "
                "VALUES (?, ?, ?, ?)",
                (f"multi{i}", "2026-03-18T10:00:00", "rss", f"Article {i}"),
            )
        tmp_db.commit()
        rows = tmp_db.fetchall("SELECT * FROM articles")
        assert len(rows) == 5

    def test_fetchone_returns_none_for_missing(self, tmp_db):
        row = tmp_db.fetchone(
            "SELECT * FROM articles WHERE id = ?", ("nonexistent",)
        )
        assert row is None

    def test_executemany(self, tmp_db):
        params = [
            (f"batch{i}", "2026-03-18T10:00:00", "rss", f"Batch {i}")
            for i in range(10)
        ]
        tmp_db.executemany(
            "INSERT INTO articles (id, timestamp, source, headline) "
            "VALUES (?, ?, ?, ?)",
            params,
        )
        tmp_db.commit()
        count = tmp_db.fetchone("SELECT COUNT(*) as cnt FROM articles")
        assert count["cnt"] == 10

    def test_signal_log_autoincrement(self, tmp_db):
        tmp_db.execute(
            "INSERT INTO signal_log (timestamp, asset, decision, final_score) "
            "VALUES (?, ?, ?, ?)",
            ("2026-03-18T10:00:00", "BTC", "BUY", 0.5),
        )
        tmp_db.execute(
            "INSERT INTO signal_log (timestamp, asset, decision, final_score) "
            "VALUES (?, ?, ?, ?)",
            ("2026-03-18T10:05:00", "ETH", "SELL", -0.3),
        )
        tmp_db.commit()
        rows = tmp_db.fetchall("SELECT id FROM signal_log ORDER BY id")
        assert rows[0]["id"] == 1
        assert rows[1]["id"] == 2

    def test_row_factory_dict_access(self, tmp_db):
        tmp_db.execute(
            "INSERT INTO articles (id, timestamp, source, headline) "
            "VALUES (?, ?, ?, ?)",
            ("dict1", "2026-03-18T10:00:00", "rss", "Dict test"),
        )
        tmp_db.commit()
        row = tmp_db.fetchone("SELECT * FROM articles WHERE id = ?", ("dict1",))
        # Should support dict-like access
        assert row["id"] == "dict1"
        assert row["headline"] == "Dict test"

    def test_wal_journal_mode(self, tmp_db):
        row = tmp_db.fetchone("PRAGMA journal_mode")
        assert row[0] == "wal"
