"""
DataStore abstraction over SQLite.

Provides a thin, thread-safe wrapper around SQLite for local persistence.
All database access should go through this module so that a future migration
(e.g. to AWS RDS / DynamoDB) requires changes in only one place.

Usage::

    from utils.db import DataStore

    with DataStore() as db:
        db.execute("INSERT INTO signal_log (timestamp, asset) VALUES (?, ?)",
                   (ts, "BTC/USD"))
        rows = db.fetchall("SELECT * FROM signal_log WHERE asset = ?",
                           ("BTC/USD",))
"""

import logging
import sqlite3
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any, Optional, Sequence

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "trading_bot.db"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL: table definitions
# ---------------------------------------------------------------------------

_TABLES: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS articles (
        id                  TEXT PRIMARY KEY,
        timestamp           DATETIME,
        source              TEXT,
        headline            TEXT,
        body_snippet        TEXT,
        url                 TEXT,
        mentioned_tickers   JSON,
        source_sentiment    REAL,
        relevance_score     REAL,
        is_catalyst         BOOLEAN,
        matched_sectors     JSON,
        processed           BOOLEAN DEFAULT 0,
        llm_sector          TEXT,
        llm_secondary_sector TEXT,
        llm_sentiment       REAL,
        llm_magnitude       TEXT,
        llm_confidence      REAL,
        llm_cross_market    BOOLEAN,
        llm_reasoning       TEXT,
        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS signal_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        asset           TEXT,
        timestamp       TIMESTAMP,
        technical_score REAL,
        derivatives_score REAL,
        on_chain_score  REAL,
        mtf_score       REAL,
        sentiment_score REAL,
        raw_composite   REAL,
        final_score     REAL,
        overrides_fired TEXT,
        decision        TEXT,
        metadata        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS asset_registry (
        asset            TEXT PRIMARY KEY,
        has_perps        BOOLEAN,
        exchange_sources TEXT,
        oi_rank          INTEGER,
        excluded_reason  TEXT,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS funding_rates (
        asset     TEXT,
        timestamp TIMESTAMP,
        exchange  TEXT,
        rate      REAL,
        PRIMARY KEY (asset, timestamp, exchange)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS open_interest (
        asset     TEXT,
        timestamp TIMESTAMP,
        exchange  TEXT,
        oi_value  REAL,
        oi_usd    REAL,
        PRIMARY KEY (asset, timestamp, exchange)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS long_short_ratio (
        asset     TEXT,
        timestamp TIMESTAMP,
        ratio     REAL,
        source    TEXT,
        PRIMARY KEY (asset, timestamp, source)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS on_chain_daily (
        asset                   TEXT,
        date                    DATE,
        exchange_inflow_native  REAL,
        exchange_outflow_native REAL,
        exchange_netflow_native REAL,
        mvrv                    REAL,
        nupl_computed           REAL,
        active_addresses        INTEGER,
        PRIMARY KEY (asset, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS whale_transfers (
        tx_hash        TEXT PRIMARY KEY,
        asset          TEXT,
        timestamp      TIMESTAMP,
        from_address   TEXT,
        to_address     TEXT,
        value_usd      REAL,
        direction      TEXT,
        exchange_label TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ohlc_data (
        asset     TEXT,
        timestamp TIMESTAMP,
        interval  TEXT,
        open      REAL,
        high      REAL,
        low       REAL,
        close     REAL,
        volume    REAL,
        vwap      REAL,
        PRIMARY KEY (asset, timestamp, interval)
    )
    """,
]


# ---------------------------------------------------------------------------
# DataStore
# ---------------------------------------------------------------------------


class DataStore:
    """Thread-safe SQLite data store with context-manager support.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Defaults to
        ``data/trading_bot.db`` relative to the project root.
        Parent directories are created automatically if they do not exist.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    # -- connection lifecycle -----------------------------------------------

    def open(self) -> "DataStore":
        """Open the database connection and initialise tables.

        Returns *self* so callers can do ``db = DataStore().open()``.
        """
        if self._conn is not None:
            return self

        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

        self.init_tables()
        logger.debug("DataStore opened: %s", self._db_path)
        return self

    def close(self) -> None:
        """Commit pending changes and close the connection."""
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None
            logger.debug("DataStore closed: %s", self._db_path)

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> "DataStore":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        self.close()

    # -- table initialisation -----------------------------------------------

    def init_tables(self) -> None:
        """Create all required tables if they do not already exist."""
        conn = self._get_conn()
        for ddl in _TABLES:
            conn.execute(ddl)
        conn.commit()

    # -- query helpers ------------------------------------------------------

    def execute(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> sqlite3.Cursor:
        """Execute a single SQL statement and return the cursor.

        Changes are **not** auto-committed; call :pymeth:`commit` or rely on
        the context manager to commit on exit.
        """
        return self._get_conn().execute(sql, params)

    def executemany(
        self,
        sql: str,
        params_seq: Sequence[Sequence[Any]],
    ) -> sqlite3.Cursor:
        """Execute a SQL statement against each parameter set."""
        return self._get_conn().executemany(sql, params_seq)

    def fetchone(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> Optional[sqlite3.Row]:
        """Execute *sql* and return the first row, or ``None``."""
        return self._get_conn().execute(sql, params).fetchone()

    def fetchall(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> list[sqlite3.Row]:
        """Execute *sql* and return all matching rows."""
        return self._get_conn().execute(sql, params).fetchall()

    def commit(self) -> None:
        """Explicitly commit the current transaction."""
        self._get_conn().commit()

    # -- asset registry -----------------------------------------------------

    def save_asset_registry(self, rows: list[dict]) -> None:
        conn = self._get_conn()
        for r in rows:
            conn.execute(
                """INSERT OR REPLACE INTO asset_registry
                   (asset, has_perps, exchange_sources, oi_rank, excluded_reason, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (r["asset"], r["has_perps"], r.get("exchange_sources", "[]"),
                 r.get("oi_rank"), r.get("excluded_reason"), datetime.utcnow().isoformat()),
            )
        conn.commit()

    def get_active_assets(self) -> list[str]:
        rows = self.fetchall(
            "SELECT asset FROM asset_registry WHERE has_perps = 1 AND excluded_reason IS NULL ORDER BY oi_rank"
        )
        return [row["asset"] for row in rows]

    # -- funding rates ------------------------------------------------------

    def save_funding_rates(self, rows: list[dict]) -> None:
        conn = self._get_conn()
        for r in rows:
            ts = r["timestamp"] if isinstance(r["timestamp"], str) else r["timestamp"].isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO funding_rates (asset, timestamp, exchange, rate) VALUES (?, ?, ?, ?)",
                (r["asset"], ts, r["exchange"], r["rate"]),
            )
        conn.commit()

    def get_latest_funding(self, asset: str) -> list[dict]:
        rows = self.fetchall(
            """SELECT * FROM funding_rates
               WHERE asset = ? AND timestamp = (
                   SELECT MAX(timestamp) FROM funding_rates WHERE asset = ?
               )""",
            (asset, asset),
        )
        return [dict(row) for row in rows]

    # -- open interest ------------------------------------------------------

    def save_open_interest(self, rows: list[dict]) -> None:
        conn = self._get_conn()
        for r in rows:
            ts = r["timestamp"] if isinstance(r["timestamp"], str) else r["timestamp"].isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO open_interest (asset, timestamp, exchange, oi_value, oi_usd) VALUES (?, ?, ?, ?, ?)",
                (r["asset"], ts, r["exchange"], r["oi_value"], r["oi_usd"]),
            )
        conn.commit()

    def get_oi_history(self, asset: str, lookback_hours: int = 24) -> list[dict]:
        since = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
        rows = self.fetchall(
            "SELECT * FROM open_interest WHERE asset = ? AND timestamp >= ? ORDER BY timestamp",
            (asset, since),
        )
        return [dict(row) for row in rows]

    # -- long/short ratio ---------------------------------------------------

    def save_long_short_ratio(self, rows: list[dict]) -> None:
        conn = self._get_conn()
        for r in rows:
            ts = r["timestamp"] if isinstance(r["timestamp"], str) else r["timestamp"].isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO long_short_ratio (asset, timestamp, ratio, source) VALUES (?, ?, ?, ?)",
                (r["asset"], ts, r["ratio"], r["source"]),
            )
        conn.commit()

    # -- on-chain daily -----------------------------------------------------

    def save_on_chain_daily(self, rows: list[dict]) -> None:
        conn = self._get_conn()
        for r in rows:
            d = r["date"] if isinstance(r["date"], str) else r["date"].isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO on_chain_daily
                   (asset, date, exchange_inflow_native, exchange_outflow_native,
                    exchange_netflow_native, mvrv, nupl_computed, active_addresses)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["asset"], d, r["exchange_inflow_native"], r["exchange_outflow_native"],
                 r["exchange_netflow_native"], r["mvrv"], r["nupl_computed"],
                 r["active_addresses"]),
            )
        conn.commit()

    def get_on_chain(self, asset: str, lookback_days: int = 30) -> list[dict]:
        since = (date.today() - timedelta(days=lookback_days)).isoformat()
        rows = self.fetchall(
            "SELECT * FROM on_chain_daily WHERE asset = ? AND date >= ? ORDER BY date",
            (asset, since),
        )
        return [dict(row) for row in rows]

    # -- whale transfers ----------------------------------------------------

    def save_whale_transfers(self, rows: list[dict]) -> None:
        conn = self._get_conn()
        for r in rows:
            ts = r["timestamp"] if isinstance(r["timestamp"], str) else r["timestamp"].isoformat()
            conn.execute(
                """INSERT OR IGNORE INTO whale_transfers
                   (tx_hash, asset, timestamp, from_address, to_address,
                    value_usd, direction, exchange_label)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["tx_hash"], r["asset"], ts, r["from_address"],
                 r["to_address"], r["value_usd"], r["direction"],
                 r.get("exchange_label")),
            )
        conn.commit()

    def get_recent_whale_transfers(self, asset: str, since: datetime) -> list[dict]:
        since_str = since.isoformat()
        rows = self.fetchall(
            "SELECT * FROM whale_transfers WHERE asset = ? AND timestamp >= ? ORDER BY timestamp",
            (asset, since_str),
        )
        return [dict(row) for row in rows]

    # -- ohlc ---------------------------------------------------------------

    def save_ohlc(self, rows: list[dict]) -> None:
        conn = self._get_conn()
        for r in rows:
            ts = r["timestamp"] if isinstance(r["timestamp"], str) else r["timestamp"].isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO ohlc_data
                   (asset, timestamp, interval, open, high, low, close, volume, vwap)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["asset"], ts, r["interval"], r["open"], r["high"],
                 r["low"], r["close"], r["volume"], r.get("vwap")),
            )
        conn.commit()

    def get_ohlc(self, asset: str, interval: str, lookback: int = 100) -> list[dict]:
        rows = self.fetchall(
            """SELECT * FROM ohlc_data
               WHERE asset = ? AND interval = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (asset, interval, lookback),
        )
        result = [dict(row) for row in rows]
        result.reverse()
        return result

    # -- signal log ---------------------------------------------------------

    def log_signal(self, entry: dict) -> None:
        ts = entry["timestamp"] if isinstance(entry["timestamp"], str) else entry["timestamp"].isoformat()
        self._get_conn().execute(
            """INSERT INTO signal_log
               (asset, timestamp, technical_score, derivatives_score,
                on_chain_score, mtf_score, sentiment_score,
                raw_composite, final_score, overrides_fired, decision, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry["asset"], ts, entry.get("technical_score", 0),
             entry.get("derivatives_score", 0), entry.get("on_chain_score", 0),
             entry.get("mtf_score", 0), entry.get("sentiment_score", 0),
             entry.get("raw_composite", 0), entry.get("final_score", 0),
             entry.get("overrides_fired", "[]"), entry.get("decision", "HOLD"),
             entry.get("metadata", "{}")),
        )
        self.commit()

    # -- pruning ------------------------------------------------------------

    def prune_old_data(self) -> None:
        """Remove data older than retention thresholds (spec Section 8)."""
        now = datetime.utcnow()
        cutoffs = {
            "funding_rates": (now - timedelta(days=30)).isoformat(),
            "open_interest": (now - timedelta(days=30)).isoformat(),
            "long_short_ratio": (now - timedelta(days=30)).isoformat(),
            "whale_transfers": (now - timedelta(days=90)).isoformat(),
            "ohlc_data": (now - timedelta(days=365)).isoformat(),
        }
        conn = self._get_conn()
        for table, cutoff in cutoffs.items():
            conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,))
        on_chain_cutoff = (date.today() - timedelta(days=365)).isoformat()
        conn.execute("DELETE FROM on_chain_daily WHERE date < ?", (on_chain_cutoff,))
        conn.commit()

    def list_tables(self) -> list[str]:
        rows = self.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [row["name"] for row in rows]

    # -- internal -----------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Return the active connection, raising if the store is closed."""
        if self._conn is None:
            raise RuntimeError(
                "DataStore is not open. Use 'with DataStore() as db:' "
                "or call db.open() first."
            )
        return self._conn
