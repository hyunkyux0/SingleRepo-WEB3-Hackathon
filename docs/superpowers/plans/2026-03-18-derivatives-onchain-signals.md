# Derivatives & On-Chain Signals Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build derivatives signal generators (funding rates, OI, long/short ratio), on-chain signal generators (exchange flows, NUPL, active addresses, whale tracking), and a composite scorer that combines all signal sources into BUY/SELL/HOLD decisions.

**Architecture:** Modular pipeline — independent data collectors write to a shared SQLite database, signal generators read from SQLite and output -1 to +1 scores, and a composite scorer combines scores via normalized weighted sum with two-tier override rules. Each module follows the pattern: `models.py` (Pydantic), `collectors.py` (API fetching), `processors.py` (scoring logic).

**Tech Stack:** Python 3.8+, SQLite (stdlib), Pydantic 2.x, requests, coinmetrics-api-client

**Spec:** `docs/superpowers/specs/2026-03-18-derivatives-onchain-signal-module-design.md`

---

## File Map

### Already Existing (no changes needed)

| File | Status |
|------|--------|
| `utils/__init__.py` | EXISTS — empty package init |
| `utils/llm_client.py` | EXISTS — OpenRouter/OpenAI LLM client |
| `config/asset_universe.json` | EXISTS — 68 crypto pairs |
| `config/sector_map.json` | EXISTS — token-to-sector mapping |
| `config/sector_config.json` | EXISTS — per-sector parameters |
| `config/sources.json` | EXISTS — news source registry |
| `news_sentiment/*` | EXISTS — complete (4 files) |
| `sentiment_score/*` | EXISTS — complete (4 files) |

### Existing Files (modify)

| File | Change |
|------|--------|
| `requirements.txt` | Add pydantic, coinmetrics-api-client |
| `utils/db.py` | Extend existing DataStore: add 6 new table DDLs, update signal_log schema, add domain-specific CRUD methods and pruning |

### New Files (create)

| File | Responsibility |
|------|---------------|
| `config/derivatives_config.json` | Funding rate thresholds, OI params, sub-weights |
| `config/onchain_config.json` | NUPL thresholds, whale params, sub-weights |
| `config/composite_config.json` | Composite weights, override rules, buy/sell thresholds |
| `derivatives/__init__.py` | Package init |
| `derivatives/models.py` | FundingSnapshot, OISnapshot, LongShortRatio, DerivativesSignal |
| `derivatives/collectors.py` | BinanceCollector, BybitCollector, CoinalyzeCollector |
| `derivatives/processors.py` | Funding score, OI divergence score, long/short score, combined |
| `on_chain/__init__.py` | Package init |
| `on_chain/models.py` | ExchangeFlow, WhaleTransfer, OnChainDaily, OnChainSignal |
| `on_chain/collectors.py` | CoinMetricsCollector, EtherscanCollector |
| `on_chain/processors.py` | Exchange flow score, NUPL score, active addr score, whale score |
| `composite/__init__.py` | Package init |
| `composite/models.py` | CompositeScore, OverrideEvent, TradingDecision |
| `composite/scorer.py` | Normalized weighted sum + two-tier overrides |
| `composite/adapters.py` | SectorSignalSet → per-asset sentiment score *(deferred — depends on sentiment module)* |
| `scripts/discover_assets.py` | Query Binance/Bybit for perps, rank by OI, build registry |
| `tests/test_db.py` | DataStore extension tests |
| `tests/test_derivatives_models.py` | Derivatives Pydantic model tests |
| `tests/test_derivatives_collectors.py` | Collector tests (mocked HTTP) |
| `tests/test_derivatives_processors.py` | Derivatives scoring logic tests |
| `tests/test_onchain_models.py` | On-chain model tests |
| `tests/test_onchain_collectors.py` | On-chain collector tests (mocked HTTP) |
| `tests/test_onchain_processors.py` | On-chain scoring logic tests |
| `tests/test_composite_scorer.py` | Composite scorer tests |
| `tests/test_composite_overrides.py` | Override rule tests |
| `tests/test_asset_discovery.py` | Asset discovery tests |

---

## Chunk 1: Foundation — SQLite Schema + DataStore + Config

### Task 1: Install dependencies and create config files

**Files:**
- Modify: `requirements.txt`
- Create: `config/derivatives_config.json`
- Create: `config/onchain_config.json`
- Create: `config/composite_config.json`

**Note:** `config/asset_universe.json`, `config/sector_map.json`, `config/sector_config.json`, `config/sources.json` already exist. `utils/__init__.py` and `utils/llm_client.py` already exist. No action needed for these.

- [ ] **Step 1: Update requirements.txt**

Add to `requirements.txt`:
```
pydantic>=2.0.0
coinmetrics-api-client>=2024.1
```

- [ ] **Step 2: Create config/derivatives_config.json**

```json
{
  "polling_interval_seconds": 300,
  "funding_rate_neutral_band": [-0.0001, 0.0001],
  "oi_lookback_periods": 12,
  "long_short_extreme_threshold": 2.0,
  "sub_weights": {
    "funding": 0.4,
    "oi_divergence": 0.35,
    "long_short": 0.25
  }
}
```

- [ ] **Step 3: Create config/onchain_config.json**

```json
{
  "coinmetrics_poll_hour_utc": 0,
  "whale_transfer_threshold_usd": 1000000,
  "whale_rolling_window_hours": 4,
  "exchange_flow_normalization_days": 30,
  "nupl_thresholds": {
    "euphoria": 0.75,
    "capitulation": 0.0
  },
  "sub_weights": {
    "exchange_flow": 0.3,
    "nupl": 0.25,
    "active_addresses": 0.15,
    "whale_activity": 0.3
  }
}
```

- [ ] **Step 4: Create config/composite_config.json**

```json
{
  "weights": {
    "technical": 0.35,
    "derivatives": 0.25,
    "on_chain": 0.15,
    "multi_timeframe": 0.10,
    "sentiment": 0.15
  },
  "thresholds": {
    "buy_default": 0.3,
    "sell_default": 0.3
  },
  "overrides": {
    "funding_soft_threshold": 0.001,
    "funding_hard_threshold": 0.002,
    "nupl_soft_high": 0.75,
    "nupl_hard_high": 0.90,
    "nupl_soft_low": 0.0,
    "nupl_hard_low": -0.25,
    "soft_penalty_multiplier": 0.2,
    "tf_opposition_multiplier": 0.5,
    "catalyst_boost_multiplier": 1.5,
    "catalyst_sentiment_threshold": 0.7
  }
}
```

- [ ] **Step 5: Install dependencies**

```bash
pip install -r requirements.txt
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt config/derivatives_config.json config/onchain_config.json config/composite_config.json
git commit -m "feat: add config files and dependencies for derivatives/on-chain modules"
```

---

### Task 2: Extend existing DataStore — add new tables and domain CRUD

**Files:**
- Modify: `utils/db.py` (EXISTS — has generic DataStore with `articles` + `signal_log` tables)
- Create: `tests/test_db.py`

**Context:** `utils/db.py` already has a working `DataStore` class with context manager, generic `execute`/`fetchall`/`fetchone`/`commit` methods, and 2 tables (`articles`, `signal_log`). We need to:
1. Add 6 new table DDLs to `_TABLES` list (asset_registry, funding_rates, open_interest, long_short_ratio, on_chain_daily, whale_transfers, ohlc_data)
2. Update `signal_log` schema to include composite scorer fields
3. Add domain-specific helper methods (save_funding_rates, get_latest_funding, etc.)
4. Add prune_old_data method

- [ ] **Step 1: Write DataStore tests**

```python
# tests/test_db.py
import pytest
import os
import tempfile
from datetime import datetime, timedelta
from utils.db import DataStore


@pytest.fixture
def db():
    """Create a temporary DataStore for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = DataStore(db_path=path)
    yield store
    store.close()
    os.unlink(path)


class TestSchema:
    def test_tables_created(self, db):
        tables = db.list_tables()
        expected = [
            "asset_registry", "funding_rates", "open_interest",
            "long_short_ratio", "on_chain_daily", "whale_transfers",
            "ohlc_data", "signal_log",
        ]
        for t in expected:
            assert t in tables, f"Missing table: {t}"


class TestAssetRegistry:
    def test_save_and_get_active_assets(self, db):
        rows = [
            {"asset": "BTC", "has_perps": True, "exchange_sources": '["binance","bybit"]',
             "oi_rank": 1, "excluded_reason": None},
            {"asset": "SOMI", "has_perps": False, "exchange_sources": '[]',
             "oi_rank": None, "excluded_reason": "No perps available"},
        ]
        db.save_asset_registry(rows)
        active = db.get_active_assets()
        assert active == ["BTC"]

    def test_upsert_replaces(self, db):
        db.save_asset_registry([{"asset": "BTC", "has_perps": True,
                                  "exchange_sources": '["binance"]', "oi_rank": 1,
                                  "excluded_reason": None}])
        db.save_asset_registry([{"asset": "BTC", "has_perps": True,
                                  "exchange_sources": '["binance","bybit"]', "oi_rank": 1,
                                  "excluded_reason": None}])
        active = db.get_active_assets()
        assert active == ["BTC"]


class TestFundingRates:
    def test_save_and_get_latest(self, db):
        now = datetime.utcnow()
        rows = [
            {"asset": "BTC", "timestamp": now - timedelta(minutes=10),
             "exchange": "binance", "rate": 0.0001},
            {"asset": "BTC", "timestamp": now,
             "exchange": "binance", "rate": 0.0002},
            {"asset": "BTC", "timestamp": now,
             "exchange": "bybit", "rate": 0.00015},
        ]
        db.save_funding_rates(rows)
        latest = db.get_latest_funding("BTC")
        assert len(latest) == 2  # binance + bybit at latest timestamp
        assert all(r["rate"] > 0 for r in latest)

    def test_get_latest_empty(self, db):
        latest = db.get_latest_funding("BTC")
        assert latest == []


class TestOpenInterest:
    def test_save_and_get_history(self, db):
        now = datetime.utcnow()
        rows = [
            {"asset": "ETH", "timestamp": now - timedelta(hours=2),
             "exchange": "binance", "oi_value": 100000, "oi_usd": 300000000},
            {"asset": "ETH", "timestamp": now,
             "exchange": "binance", "oi_value": 110000, "oi_usd": 330000000},
        ]
        db.save_open_interest(rows)
        history = db.get_oi_history("ETH", lookback_hours=4)
        assert len(history) == 2


class TestOnChainDaily:
    def test_save_and_get(self, db):
        from datetime import date
        rows = [
            {"asset": "BTC", "date": date(2026, 3, 17),
             "exchange_inflow_native": 500.0, "exchange_outflow_native": 300.0,
             "exchange_netflow_native": 200.0, "mvrv": 2.5,
             "nupl_computed": 0.6, "active_addresses": 900000},
            {"asset": "BTC", "date": date(2026, 3, 18),
             "exchange_inflow_native": 400.0, "exchange_outflow_native": 600.0,
             "exchange_netflow_native": -200.0, "mvrv": 2.4,
             "nupl_computed": 0.583, "active_addresses": 920000},
        ]
        db.save_on_chain_daily(rows)
        result = db.get_on_chain("BTC", lookback_days=7)
        assert len(result) == 2
        assert result[0]["date"] <= result[1]["date"]


class TestWhaleTransfers:
    def test_save_and_get_recent(self, db):
        now = datetime.utcnow()
        rows = [
            {"tx_hash": "0xabc", "asset": "ETH", "timestamp": now,
             "from_address": "0x123", "to_address": "0x456",
             "value_usd": 2000000, "direction": "to_exchange",
             "exchange_label": "binance"},
        ]
        db.save_whale_transfers(rows)
        since = now - timedelta(hours=4)
        result = db.get_recent_whale_transfers("ETH", since=since)
        assert len(result) == 1
        assert result[0]["direction"] == "to_exchange"

    def test_duplicate_tx_hash_ignored(self, db):
        now = datetime.utcnow()
        row = {"tx_hash": "0xabc", "asset": "ETH", "timestamp": now,
               "from_address": "0x1", "to_address": "0x2",
               "value_usd": 1000000, "direction": "to_exchange",
               "exchange_label": "binance"}
        db.save_whale_transfers([row])
        db.save_whale_transfers([row])  # duplicate
        result = db.get_recent_whale_transfers("ETH", since=now - timedelta(hours=1))
        assert len(result) == 1


class TestSignalLog:
    def test_log_signal(self, db):
        entry = {
            "asset": "BTC", "timestamp": datetime.utcnow(),
            "technical_score": 0.5, "derivatives_score": -0.2,
            "on_chain_score": 0.1, "mtf_score": 0.8,
            "sentiment_score": 0.3, "raw_composite": 0.35,
            "final_score": 0.28, "overrides_fired": '["O1a"]',
            "decision": "HOLD", "metadata": '{}',
        }
        db.log_signal(entry)
        # No assertion needed beyond not throwing — log is write-only


class TestPruning:
    def test_prune_old_funding_rates(self, db):
        old = datetime.utcnow() - timedelta(days=45)
        recent = datetime.utcnow()
        db.save_funding_rates([
            {"asset": "BTC", "timestamp": old, "exchange": "binance", "rate": 0.0001},
            {"asset": "BTC", "timestamp": recent, "exchange": "binance", "rate": 0.0002},
        ])
        db.prune_old_data()
        latest = db.get_latest_funding("BTC")
        assert len(latest) == 1
        assert latest[0]["rate"] == 0.0002
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /workspace/SingleRepo-WEB3-Hackathon && python -m pytest tests/test_db.py -v
```
Expected: FAIL — `utils.db` module does not exist

- [ ] **Step 3: Extend utils/db.py — add new table DDLs and domain methods**

The existing `utils/db.py` has a `_TABLES` list and generic query methods. We need to:
- Add new table DDLs to `_TABLES`
- Update `signal_log` to match composite scorer schema
- Add domain-specific CRUD methods to the `DataStore` class

Add these table DDLs to the `_TABLES` list in `utils/db.py` (after existing `articles` and `signal_log` entries):

First, add these DDL strings to the `_TABLES` list in `utils/db.py`:

```python
# Append these to the _TABLES list after the existing articles and signal_log entries.
# ALSO replace the existing signal_log DDL with updated schema (see below).

"""
CREATE TABLE IF NOT EXISTS asset_registry (
    asset TEXT PRIMARY KEY,
    has_perps BOOLEAN,
    exchange_sources TEXT,
    oi_rank INTEGER,
    excluded_reason TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS funding_rates (
    asset TEXT,
    timestamp TIMESTAMP,
    exchange TEXT,
    rate REAL,
    PRIMARY KEY (asset, timestamp, exchange)
);

CREATE TABLE IF NOT EXISTS open_interest (
    asset TEXT,
    timestamp TIMESTAMP,
    exchange TEXT,
    oi_value REAL,
    oi_usd REAL,
    PRIMARY KEY (asset, timestamp, exchange)
);

CREATE TABLE IF NOT EXISTS long_short_ratio (
    asset TEXT,
    timestamp TIMESTAMP,
    ratio REAL,
    source TEXT,
    PRIMARY KEY (asset, timestamp, source)
);

CREATE TABLE IF NOT EXISTS on_chain_daily (
    asset TEXT,
    date DATE,
    exchange_inflow_native REAL,
    exchange_outflow_native REAL,
    exchange_netflow_native REAL,
    mvrv REAL,
    nupl_computed REAL,
    active_addresses INTEGER,
    PRIMARY KEY (asset, date)
);

CREATE TABLE IF NOT EXISTS whale_transfers (
    tx_hash TEXT PRIMARY KEY,
    asset TEXT,
    timestamp TIMESTAMP,
    from_address TEXT,
    to_address TEXT,
    value_usd REAL,
    direction TEXT,
    exchange_label TEXT
);

CREATE TABLE IF NOT EXISTS ohlc_data (
    asset TEXT,
    timestamp TIMESTAMP,
    interval TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    vwap REAL,
    PRIMARY KEY (asset, timestamp, interval)
);

CREATE TABLE IF NOT EXISTS signal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset TEXT,
    timestamp TIMESTAMP,
    technical_score REAL,
    derivatives_score REAL,
    on_chain_score REAL,
    mtf_score REAL,
    sentiment_score REAL,
    raw_composite REAL,
    final_score REAL,
    overrides_fired TEXT,
    decision TEXT,
    metadata TEXT
);
"""


Then replace the existing `signal_log` DDL in `_TABLES` with:
```python
"""
CREATE TABLE IF NOT EXISTS signal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset TEXT, timestamp TIMESTAMP,
    technical_score REAL, derivatives_score REAL, on_chain_score REAL,
    mtf_score REAL, sentiment_score REAL,
    raw_composite REAL, final_score REAL,
    overrides_fired TEXT, decision TEXT, metadata TEXT
)
"""
```

Add imports to the top of `utils/db.py` (after existing imports):
```python
from datetime import datetime, timedelta, date
```

Then add these domain-specific methods to the existing `DataStore` class:
```python
    # -- Asset Registry -- (add to DataStore class)

    def save_asset_registry(self, rows: list[dict]):
        for r in rows:
            self._conn.execute(
                """INSERT OR REPLACE INTO asset_registry
                   (asset, has_perps, exchange_sources, oi_rank, excluded_reason, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (r["asset"], r["has_perps"], r.get("exchange_sources", "[]"),
                 r.get("oi_rank"), r.get("excluded_reason"),
                 datetime.utcnow()),
            )
        self._conn.commit()

    def get_active_assets(self) -> list[str]:
        cur = self._conn.execute(
            "SELECT asset FROM asset_registry WHERE has_perps = 1 AND excluded_reason IS NULL ORDER BY oi_rank"
        )
        return [row["asset"] for row in cur.fetchall()]

    # -- Funding Rates --

    def save_funding_rates(self, rows: list[dict]):
        for r in rows:
            ts = r["timestamp"] if isinstance(r["timestamp"], str) else r["timestamp"].isoformat()
            self._conn.execute(
                "INSERT OR REPLACE INTO funding_rates (asset, timestamp, exchange, rate) VALUES (?, ?, ?, ?)",
                (r["asset"], ts, r["exchange"], r["rate"]),
            )
        self._conn.commit()

    def get_latest_funding(self, asset: str) -> list[dict]:
        cur = self._conn.execute(
            """SELECT * FROM funding_rates
               WHERE asset = ? AND timestamp = (
                   SELECT MAX(timestamp) FROM funding_rates WHERE asset = ?
               )""",
            (asset, asset),
        )
        return [dict(row) for row in cur.fetchall()]

    # -- Open Interest --

    def save_open_interest(self, rows: list[dict]):
        for r in rows:
            ts = r["timestamp"] if isinstance(r["timestamp"], str) else r["timestamp"].isoformat()
            self._conn.execute(
                "INSERT OR REPLACE INTO open_interest (asset, timestamp, exchange, oi_value, oi_usd) VALUES (?, ?, ?, ?, ?)",
                (r["asset"], ts, r["exchange"], r["oi_value"], r["oi_usd"]),
            )
        self._conn.commit()

    def get_oi_history(self, asset: str, lookback_hours: int = 24) -> list[dict]:
        since = (datetime.utcnow() - timedelta(hours=lookback_hours)).isoformat()
        cur = self._conn.execute(
            "SELECT * FROM open_interest WHERE asset = ? AND timestamp >= ? ORDER BY timestamp",
            (asset, since),
        )
        return [dict(row) for row in cur.fetchall()]

    # -- Long/Short Ratio --

    def save_long_short_ratio(self, rows: list[dict]):
        for r in rows:
            ts = r["timestamp"] if isinstance(r["timestamp"], str) else r["timestamp"].isoformat()
            self._conn.execute(
                "INSERT OR REPLACE INTO long_short_ratio (asset, timestamp, ratio, source) VALUES (?, ?, ?, ?)",
                (r["asset"], ts, r["ratio"], r["source"]),
            )
        self._conn.commit()

    # -- On-Chain Daily --

    def save_on_chain_daily(self, rows: list[dict]):
        for r in rows:
            d = r["date"] if isinstance(r["date"], str) else r["date"].isoformat()
            self._conn.execute(
                """INSERT OR REPLACE INTO on_chain_daily
                   (asset, date, exchange_inflow_native, exchange_outflow_native,
                    exchange_netflow_native, mvrv, nupl_computed, active_addresses)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["asset"], d, r["exchange_inflow_native"], r["exchange_outflow_native"],
                 r["exchange_netflow_native"], r["mvrv"], r["nupl_computed"],
                 r["active_addresses"]),
            )
        self._conn.commit()

    def get_on_chain(self, asset: str, lookback_days: int = 30) -> list[dict]:
        since = (date.today() - timedelta(days=lookback_days)).isoformat()
        cur = self._conn.execute(
            "SELECT * FROM on_chain_daily WHERE asset = ? AND date >= ? ORDER BY date",
            (asset, since),
        )
        return [dict(row) for row in cur.fetchall()]

    # -- Whale Transfers --

    def save_whale_transfers(self, rows: list[dict]):
        for r in rows:
            ts = r["timestamp"] if isinstance(r["timestamp"], str) else r["timestamp"].isoformat()
            self._conn.execute(
                """INSERT OR IGNORE INTO whale_transfers
                   (tx_hash, asset, timestamp, from_address, to_address,
                    value_usd, direction, exchange_label)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["tx_hash"], r["asset"], ts, r["from_address"],
                 r["to_address"], r["value_usd"], r["direction"],
                 r.get("exchange_label")),
            )
        self._conn.commit()

    def get_recent_whale_transfers(self, asset: str, since: datetime) -> list[dict]:
        since_str = since.isoformat()
        cur = self._conn.execute(
            "SELECT * FROM whale_transfers WHERE asset = ? AND timestamp >= ? ORDER BY timestamp",
            (asset, since_str),
        )
        return [dict(row) for row in cur.fetchall()]

    # -- OHLC --

    def save_ohlc(self, rows: list[dict]):
        for r in rows:
            ts = r["timestamp"] if isinstance(r["timestamp"], str) else r["timestamp"].isoformat()
            self._conn.execute(
                """INSERT OR REPLACE INTO ohlc_data
                   (asset, timestamp, interval, open, high, low, close, volume, vwap)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["asset"], ts, r["interval"], r["open"], r["high"],
                 r["low"], r["close"], r["volume"], r.get("vwap")),
            )
        self._conn.commit()

    def get_ohlc(self, asset: str, interval: str, lookback: int = 100) -> list[dict]:
        cur = self._conn.execute(
            """SELECT * FROM ohlc_data
               WHERE asset = ? AND interval = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (asset, interval, lookback),
        )
        rows = [dict(row) for row in cur.fetchall()]
        rows.reverse()  # oldest first
        return rows

    # -- Signal Log --

    def log_signal(self, entry: dict):
        ts = entry["timestamp"] if isinstance(entry["timestamp"], str) else entry["timestamp"].isoformat()
        self._conn.execute(
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
        self._conn.commit()

    # -- Pruning --

    def prune_old_data(self):
        """Remove data older than retention thresholds. See spec Section 8."""
        now = datetime.utcnow()
        cutoffs = {
            "funding_rates": (now - timedelta(days=30)).isoformat(),
            "open_interest": (now - timedelta(days=30)).isoformat(),
            "long_short_ratio": (now - timedelta(days=30)).isoformat(),
            "whale_transfers": (now - timedelta(days=90)).isoformat(),
            "ohlc_data": (now - timedelta(days=365)).isoformat(),
        }
        for table, cutoff in cutoffs.items():
            self._conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,))

        # on_chain_daily uses 'date' column
        on_chain_cutoff = (date.today() - timedelta(days=365)).isoformat()
        self._conn.execute("DELETE FROM on_chain_daily WHERE date < ?", (on_chain_cutoff,))

        self._conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /workspace/SingleRepo-WEB3-Hackathon && python -m pytest tests/test_db.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add utils/db.py tests/test_db.py
git commit -m "feat: extend DataStore with derivatives/on-chain tables and CRUD methods"
```

---

## Chunk 2: Derivatives Module — Models, Collectors, Processors

### Task 3: Derivatives Pydantic models

**Files:**
- Create: `derivatives/__init__.py`
- Create: `derivatives/models.py`
- Create: `tests/test_derivatives_models.py`

- [ ] **Step 1: Write model tests**

```python
# tests/test_derivatives_models.py
import pytest
from datetime import datetime
from derivatives.models import FundingSnapshot, OISnapshot, LongShortRatio, DerivativesSignal


class TestFundingSnapshot:
    def test_valid(self):
        f = FundingSnapshot(asset="BTC", timestamp=datetime.utcnow(),
                            exchange="binance", rate=0.0001)
        assert f.rate == 0.0001

    def test_rate_stored_as_decimal(self):
        """Funding rates stored as decimal fractions, not percentages."""
        f = FundingSnapshot(asset="BTC", timestamp=datetime.utcnow(),
                            exchange="binance", rate=0.0001)
        assert f.rate == 0.0001  # 0.01%


class TestOISnapshot:
    def test_valid(self):
        o = OISnapshot(asset="ETH", timestamp=datetime.utcnow(),
                       exchange="bybit", oi_value=50000.0, oi_usd=150000000.0)
        assert o.oi_usd == 150000000.0


class TestLongShortRatio:
    def test_valid(self):
        ls = LongShortRatio(asset="BTC", timestamp=datetime.utcnow(),
                            ratio=1.5, source="coinalyze")
        assert ls.ratio == 1.5


class TestDerivativesSignal:
    def test_score_clamped(self):
        s = DerivativesSignal(asset="BTC", funding_score=-0.5,
                              oi_divergence_score=0.3, long_short_score=0.1,
                              combined_score=0.0)
        assert -1.0 <= s.combined_score <= 1.0

    def test_from_sub_scores(self):
        s = DerivativesSignal.from_sub_scores(
            asset="BTC", funding_score=-0.5,
            oi_divergence_score=0.3, long_short_score=0.1,
            weights={"funding": 0.4, "oi_divergence": 0.35, "long_short": 0.25},
        )
        expected = (-0.5 * 0.4 + 0.3 * 0.35 + 0.1 * 0.25)
        assert abs(s.combined_score - expected) < 1e-6
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_derivatives_models.py -v
```
Expected: FAIL — module not found

- [ ] **Step 3: Implement derivatives/models.py**

```python
# derivatives/__init__.py
```

```python
# derivatives/models.py
"""Pydantic models for derivatives data and signals."""
from datetime import datetime
from pydantic import BaseModel, Field


class FundingSnapshot(BaseModel):
    """A single funding rate observation from one exchange.
    Rate is stored as a decimal fraction (0.01% = 0.0001)."""
    asset: str
    timestamp: datetime
    exchange: str
    rate: float


class OISnapshot(BaseModel):
    """Open interest snapshot from one exchange."""
    asset: str
    timestamp: datetime
    exchange: str
    oi_value: float  # in native units
    oi_usd: float    # in USD


class LongShortRatio(BaseModel):
    """Long/short ratio from an aggregator."""
    asset: str
    timestamp: datetime
    ratio: float
    source: str


class DerivativesSignal(BaseModel):
    """Combined derivatives signal for one asset."""
    asset: str
    funding_score: float = Field(ge=-1.0, le=1.0)
    oi_divergence_score: float = Field(ge=-1.0, le=1.0)
    long_short_score: float = Field(ge=-1.0, le=1.0)
    combined_score: float = Field(ge=-1.0, le=1.0)

    @classmethod
    def from_sub_scores(cls, asset: str, funding_score: float,
                        oi_divergence_score: float, long_short_score: float,
                        weights: dict) -> "DerivativesSignal":
        total_w = sum(weights.values())
        combined = (
            funding_score * weights["funding"]
            + oi_divergence_score * weights["oi_divergence"]
            + long_short_score * weights["long_short"]
        ) / total_w
        combined = max(-1.0, min(1.0, combined))
        return cls(asset=asset, funding_score=funding_score,
                   oi_divergence_score=oi_divergence_score,
                   long_short_score=long_short_score,
                   combined_score=combined)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_derivatives_models.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add derivatives/ tests/test_derivatives_models.py
git commit -m "feat: add derivatives Pydantic models"
```

---

### Task 4: Derivatives collectors (Binance, Bybit, Coinalyze)

**Files:**
- Create: `derivatives/collectors.py`
- Create: `tests/test_derivatives_collectors.py`

- [ ] **Step 1: Write collector tests (mocked HTTP)**

```python
# tests/test_derivatives_collectors.py
import pytest
from unittest.mock import patch, MagicMock
from derivatives.collectors import BinanceCollector, BybitCollector, CoinalyzeCollector


class TestBinanceCollector:
    def test_poll_interval(self):
        c = BinanceCollector()
        assert c.poll_interval_seconds() == 300

    @patch("derivatives.collectors.requests.get")
    def test_collect_funding_rates(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [
                {"symbol": "BTCUSDT", "fundingRate": "0.00010000",
                 "fundingTime": 1710000000000, "markPrice": "65000.00"},
            ],
        )
        c = BinanceCollector()
        rows = c.collect_funding_rates(["BTC"])
        assert len(rows) == 1
        assert rows[0]["asset"] == "BTC"
        assert rows[0]["rate"] == 0.0001
        assert rows[0]["exchange"] == "binance"

    @patch("derivatives.collectors.requests.get")
    def test_collect_open_interest(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"symbol": "BTCUSDT", "openInterest": "12345.678",
                          "time": 1710000000000},
        )
        c = BinanceCollector()
        rows = c.collect_open_interest(["BTC"])
        assert len(rows) == 1
        assert rows[0]["oi_value"] == 12345.678

    @patch("derivatives.collectors.requests.get")
    def test_handles_api_error(self, mock_get):
        mock_get.side_effect = Exception("timeout")
        c = BinanceCollector()
        rows = c.collect_funding_rates(["BTC"])
        assert rows == []


class TestBybitCollector:
    @patch("derivatives.collectors.requests.get")
    def test_collect_funding_rates(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "retCode": 0,
                "result": {
                    "list": [
                        {"symbol": "BTCUSDT", "fundingRate": "0.000150",
                         "fundingRateTimestamp": "1710000000000"},
                    ]
                }
            },
        )
        c = BybitCollector()
        rows = c.collect_funding_rates(["BTC"])
        assert len(rows) == 1
        assert rows[0]["rate"] == 0.00015


class TestCoinalyzeCollector:
    @patch("derivatives.collectors.requests.get")
    def test_collect_long_short_ratio(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [
                {"t": 1710000000, "o": 1.2, "h": 1.5, "l": 1.1, "c": 1.3},
            ],
        )
        c = CoinalyzeCollector(api_key="test_key")
        rows = c.collect_long_short_ratio(["BTC"])
        assert len(rows) == 1
        assert rows[0]["ratio"] == 1.3  # use close value
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_derivatives_collectors.py -v
```
Expected: FAIL — module not found

- [ ] **Step 3: Implement derivatives/collectors.py**

```python
# derivatives/collectors.py
"""Data collectors for derivatives exchanges.

Each collector implements BaseCollector contract (spec Section 5):
  collect(assets) -> list[dict]
  poll_interval_seconds() -> int

Collectors never write to DB directly — the orchestrator
calls collect(), then passes results to DataStore.

Symbol mapping: universe uses "BTC/USD" format. Binance uses "BTCUSDT",
Bybit uses "BTCUSDT", Coinalyze uses "BTCUSD_PERP.A".
"""
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# --- Symbol mapping ---

# Map base asset (BTC, ETH) to exchange-specific perpetual symbols
def _to_binance_symbol(asset: str) -> str:
    return f"{asset}USDT"

def _to_bybit_symbol(asset: str) -> str:
    return f"{asset}USDT"

def _to_coinalyze_symbol(asset: str) -> str:
    return f"{asset}USD_PERP.A"


class BaseCollector(ABC):
    """Base interface for all data collectors (spec Section 5)."""
    @abstractmethod
    def collect(self, assets: list[str]) -> list[dict]:
        ...
    @abstractmethod
    def poll_interval_seconds(self) -> int:
        ...


class BinanceCollector(BaseCollector):
    """Collects funding rates and open interest from Binance Futures.
    No API key required. Base URL: https://fapi.binance.com"""

    BASE_URL = "https://fapi.binance.com"

    def poll_interval_seconds(self) -> int:
        return 300

    def collect(self, assets: list[str]) -> list[dict]:
        """Collect all derivatives data for given assets."""
        funding = self.collect_funding_rates(assets)
        oi = self.collect_open_interest(assets)
        return {"funding_rates": funding, "open_interest": oi}

    def collect_funding_rates(self, assets: list[str]) -> list[dict]:
        rows = []
        for asset in assets:
            symbol = _to_binance_symbol(asset)
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/fapi/v1/fundingRate",
                    params={"symbol": symbol, "limit": 1},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                if data:
                    entry = data[0]
                    rows.append({
                        "asset": asset,
                        "timestamp": datetime.utcfromtimestamp(entry["fundingTime"] / 1000),
                        "exchange": "binance",
                        "rate": float(entry["fundingRate"]),
                    })
            except Exception as e:
                logger.warning(f"Binance funding rate failed for {asset}: {e}")
        return rows

    def collect_open_interest(self, assets: list[str]) -> list[dict]:
        rows = []
        for asset in assets:
            symbol = _to_binance_symbol(asset)
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/fapi/v1/openInterest",
                    params={"symbol": symbol},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                rows.append({
                    "asset": asset,
                    "timestamp": datetime.utcfromtimestamp(data["time"] / 1000),
                    "exchange": "binance",
                    "oi_value": float(data["openInterest"]),
                    "oi_usd": 0.0,  # Binance OI endpoint returns native units only
                })
            except Exception as e:
                logger.warning(f"Binance OI failed for {asset}: {e}")
        return rows


class BybitCollector(BaseCollector):
    """Collects funding rates and OI from Bybit v5.
    No API key required. Base URL: https://api.bybit.com"""

    BASE_URL = "https://api.bybit.com"

    def poll_interval_seconds(self) -> int:
        return 300

    def collect(self, assets: list[str]) -> list[dict]:
        funding = self.collect_funding_rates(assets)
        oi = self.collect_open_interest(assets)
        return {"funding_rates": funding, "open_interest": oi}

    def collect_funding_rates(self, assets: list[str]) -> list[dict]:
        rows = []
        for asset in assets:
            symbol = _to_bybit_symbol(asset)
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/v5/market/funding/history",
                    params={"category": "linear", "symbol": symbol, "limit": 1},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("retCode") == 0 and data["result"]["list"]:
                    entry = data["result"]["list"][0]
                    rows.append({
                        "asset": asset,
                        "timestamp": datetime.utcfromtimestamp(
                            int(entry["fundingRateTimestamp"]) / 1000
                        ),
                        "exchange": "bybit",
                        "rate": float(entry["fundingRate"]),
                    })
            except Exception as e:
                logger.warning(f"Bybit funding rate failed for {asset}: {e}")
        return rows

    def collect_open_interest(self, assets: list[str]) -> list[dict]:
        rows = []
        for asset in assets:
            symbol = _to_bybit_symbol(asset)
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/v5/market/open-interest",
                    params={"category": "linear", "symbol": symbol,
                            "intervalTime": "5min", "limit": 1},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("retCode") == 0 and data["result"]["list"]:
                    entry = data["result"]["list"][0]
                    rows.append({
                        "asset": asset,
                        "timestamp": datetime.utcfromtimestamp(
                            int(entry["timestamp"]) / 1000
                        ),
                        "exchange": "bybit",
                        "oi_value": float(entry["openInterest"]),
                        "oi_usd": 0.0,
                    })
            except Exception as e:
                logger.warning(f"Bybit OI failed for {asset}: {e}")
        return rows


class CoinalyzeCollector(BaseCollector):
    """Collects aggregated OI, funding, and long/short ratios from Coinalyze.
    Requires free API key. Base URL: https://api.coinalyze.net/v1"""

    BASE_URL = "https://api.coinalyze.net/v1"

    def __init__(self, api_key: str):
        self._api_key = api_key

    def poll_interval_seconds(self) -> int:
        return 300

    def collect(self, assets: list[str]) -> list[dict]:
        funding = self.collect_funding_rates(assets)
        oi = self.collect_open_interest(assets)
        ls = self.collect_long_short_ratio(assets)
        return {"funding_rates": funding, "open_interest": oi, "long_short_ratio": ls}

    def _get(self, endpoint: str, params: dict) -> Optional[list]:
        try:
            resp = requests.get(
                f"{self.BASE_URL}/{endpoint}",
                params=params,
                headers={"api_key": self._api_key},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Coinalyze {endpoint} failed: {e}")
            return None

    def collect_long_short_ratio(self, assets: list[str]) -> list[dict]:
        rows = []
        for asset in assets:
            symbol = _to_coinalyze_symbol(asset)
            data = self._get("long-short-ratio-history", {
                "symbols": symbol, "resolution": "5min", "limit": 1,
            })
            if data and len(data) > 0:
                entry = data[0]
                rows.append({
                    "asset": asset,
                    "timestamp": datetime.utcfromtimestamp(entry["t"]),
                    "ratio": entry["c"],  # close value of the candle
                    "source": "coinalyze",
                })
        return rows

    def collect_funding_rates(self, assets: list[str]) -> list[dict]:
        rows = []
        for asset in assets:
            symbol = _to_coinalyze_symbol(asset)
            data = self._get("funding-rate-history", {
                "symbols": symbol, "resolution": "5min", "limit": 1,
            })
            if data and len(data) > 0:
                entry = data[0]
                rows.append({
                    "asset": asset,
                    "timestamp": datetime.utcfromtimestamp(entry["t"]),
                    "exchange": "coinalyze_agg",
                    "rate": entry["c"],
                })
        return rows

    def collect_open_interest(self, assets: list[str]) -> list[dict]:
        rows = []
        for asset in assets:
            symbol = _to_coinalyze_symbol(asset)
            data = self._get("open-interest-history", {
                "symbols": symbol, "resolution": "5min", "limit": 1,
            })
            if data and len(data) > 0:
                entry = data[0]
                rows.append({
                    "asset": asset,
                    "timestamp": datetime.utcfromtimestamp(entry["t"]),
                    "exchange": "coinalyze_agg",
                    "oi_value": entry["c"],
                    "oi_usd": 0.0,
                })
        return rows
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_derivatives_collectors.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add derivatives/collectors.py tests/test_derivatives_collectors.py
git commit -m "feat: add Binance, Bybit, Coinalyze derivatives collectors"
```

---

### Task 5: Derivatives signal processor

**Files:**
- Create: `derivatives/processors.py`
- Create: `tests/test_derivatives_processors.py`

- [ ] **Step 1: Write processor tests**

```python
# tests/test_derivatives_processors.py
import pytest
from derivatives.processors import (
    score_funding_rate,
    score_oi_divergence,
    score_long_short_ratio,
    generate_derivatives_signal,
)
from derivatives.models import DerivativesSignal


class TestFundingScore:
    def test_neutral_funding(self):
        assert score_funding_rate(0.0) == 0.0

    def test_positive_funding_negative_score(self):
        """Positive funding = overcrowded longs = bearish = negative score."""
        score = score_funding_rate(0.0005)  # 0.05%
        assert score < 0

    def test_negative_funding_positive_score(self):
        """Negative funding = overcrowded shorts = bullish = positive score."""
        score = score_funding_rate(-0.0005)
        assert score > 0

    def test_clamped_to_range(self):
        assert -1.0 <= score_funding_rate(0.01) <= 1.0
        assert -1.0 <= score_funding_rate(-0.01) <= 1.0

    def test_linear_scaling(self):
        s1 = score_funding_rate(0.0002)
        s2 = score_funding_rate(0.0004)
        assert s2 < s1  # more positive funding = more negative score


class TestOIDivergence:
    def test_rising_oi_rising_price(self):
        """Rising OI + rising price = trend confirmation = positive."""
        score = score_oi_divergence(oi_change_pct=0.05, price_change_pct=0.03)
        assert score > 0

    def test_rising_oi_falling_price(self):
        """Rising OI + falling price = bearish continuation = negative."""
        score = score_oi_divergence(oi_change_pct=0.05, price_change_pct=-0.03)
        assert score < 0

    def test_falling_oi(self):
        """Falling OI = deleveraging = toward 0."""
        score = score_oi_divergence(oi_change_pct=-0.05, price_change_pct=0.03)
        assert abs(score) < 0.3

    def test_clamped(self):
        assert -1.0 <= score_oi_divergence(1.0, 1.0) <= 1.0


class TestLongShortRatio:
    def test_neutral_ratio(self):
        """Ratio near 1.0 = balanced = neutral."""
        score = score_long_short_ratio(1.0, extreme_threshold=2.0)
        assert abs(score) < 0.1

    def test_extreme_long(self):
        """High ratio = lots of longs = contrarian bearish = negative."""
        score = score_long_short_ratio(3.0, extreme_threshold=2.0)
        assert score < 0

    def test_extreme_short(self):
        """Low ratio = lots of shorts = contrarian bullish = positive."""
        score = score_long_short_ratio(0.4, extreme_threshold=2.0)
        assert score > 0


class TestGenerateDerivativesSignal:
    def test_returns_signal(self):
        signal = generate_derivatives_signal(
            asset="BTC",
            funding_rate=0.0001,
            oi_change_pct=0.02,
            price_change_pct=0.01,
            long_short_ratio=1.2,
            config={
                "long_short_extreme_threshold": 2.0,
                "sub_weights": {"funding": 0.4, "oi_divergence": 0.35, "long_short": 0.25},
            },
        )
        assert isinstance(signal, DerivativesSignal)
        assert signal.asset == "BTC"
        assert -1.0 <= signal.combined_score <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_derivatives_processors.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement derivatives/processors.py**

```python
# derivatives/processors.py
"""Scoring logic for derivatives sub-signals.

All scores output in range [-1, +1].
Funding rates are decimal fractions (0.01% = 0.0001).
"""
from derivatives.models import DerivativesSignal


def score_funding_rate(rate: float, cap: float = 0.002) -> float:
    """Convert funding rate to a score.
    Positive funding -> negative score (overcrowded longs = bearish).
    Negative funding -> positive score (overcrowded shorts = bullish).
    Linearly scaled, capped at +-cap.
    """
    normalized = -rate / cap  # invert: positive funding = negative score
    return max(-1.0, min(1.0, normalized))


def score_oi_divergence(oi_change_pct: float, price_change_pct: float) -> float:
    """Score based on OI/price relationship.
    Rising OI + rising price = trend confirmation (+).
    Rising OI + falling price = bearish continuation (-).
    Falling OI = deleveraging, reduces conviction toward 0.
    """
    if oi_change_pct <= 0:
        # Deleveraging — muted signal
        return price_change_pct * 0.3

    # OI rising: direction determined by price
    raw = oi_change_pct * price_change_pct * 10  # scale factor
    return max(-1.0, min(1.0, raw))


def score_long_short_ratio(ratio: float, extreme_threshold: float = 2.0) -> float:
    """Contrarian signal from long/short ratio.
    Ratio > extreme -> bearish (too many longs).
    Ratio < 1/extreme -> bullish (too many shorts).
    Near 1.0 -> neutral.
    """
    if ratio <= 0:
        return 0.0
    # Log scale: ratio of 2.0 -> 0.693, ratio of 0.5 -> -0.693
    import math
    log_ratio = math.log(ratio)
    log_extreme = math.log(extreme_threshold)
    normalized = -log_ratio / log_extreme  # invert: high ratio = negative
    return max(-1.0, min(1.0, normalized))


def aggregate_funding_rate_oi_weighted(
    rates: list[dict],
) -> float:
    """OI-weighted average funding rate across exchanges (spec Section 2).
    Each entry: {"exchange": str, "rate": float, "oi_usd": float}.
    Falls back to simple average if OI data is missing.
    """
    total_oi = sum(r.get("oi_usd", 0) for r in rates)
    if total_oi <= 0:
        # Fallback: simple average
        return sum(r["rate"] for r in rates) / len(rates) if rates else 0.0
    return sum(r["rate"] * r.get("oi_usd", 0) for r in rates) / total_oi


def aggregate_open_interest(oi_rows: list[dict]) -> float:
    """Sum OI across exchanges for total market OI (spec Section 2)."""
    return sum(r.get("oi_value", 0) for r in oi_rows)


def generate_derivatives_signal(
    asset: str,
    funding_rate: float,
    oi_change_pct: float,
    price_change_pct: float,
    long_short_ratio: float,
    config: dict,
) -> DerivativesSignal:
    """Combine all derivatives sub-signals into one score."""
    fs = score_funding_rate(funding_rate)
    oi = score_oi_divergence(oi_change_pct, price_change_pct)
    ls = score_long_short_ratio(long_short_ratio, config["long_short_extreme_threshold"])

    return DerivativesSignal.from_sub_scores(
        asset=asset,
        funding_score=fs,
        oi_divergence_score=oi,
        long_short_score=ls,
        weights=config["sub_weights"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_derivatives_processors.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add derivatives/processors.py tests/test_derivatives_processors.py
git commit -m "feat: add derivatives signal scoring (funding, OI divergence, long/short)"
```

---

## Chunk 3: On-Chain Module — Models, Collectors, Processors

### Task 6: On-chain Pydantic models

**Files:**
- Create: `on_chain/__init__.py`
- Create: `on_chain/models.py`
- Create: `tests/test_onchain_models.py`

- [ ] **Step 1: Write model tests**

```python
# tests/test_onchain_models.py
import pytest
from datetime import datetime, date
from on_chain.models import ExchangeFlow, WhaleTransfer, OnChainDaily, OnChainSignal


class TestExchangeFlow:
    def test_netflow_computed(self):
        ef = ExchangeFlow(asset="BTC", date=date(2026, 3, 18),
                          inflow=500.0, outflow=300.0)
        assert ef.netflow == 200.0


class TestWhaleTransfer:
    def test_valid(self):
        wt = WhaleTransfer(
            tx_hash="0xabc", asset="ETH", timestamp=datetime.utcnow(),
            from_address="0x1", to_address="0x2", value_usd=2000000,
            direction="to_exchange", exchange_label="binance",
        )
        assert wt.direction == "to_exchange"


class TestOnChainDaily:
    def test_nupl_from_mvrv(self):
        ocd = OnChainDaily(asset="BTC", date=date(2026, 3, 18),
                           exchange_inflow_native=500, exchange_outflow_native=300,
                           exchange_netflow_native=200, mvrv=2.5,
                           nupl_computed=0.6, active_addresses=900000)
        # NUPL = 1 - 1/MVRV = 1 - 1/2.5 = 0.6
        assert abs(ocd.nupl_computed - (1 - 1 / ocd.mvrv)) < 0.01


class TestOnChainSignal:
    def test_score_range(self):
        s = OnChainSignal(asset="BTC", exchange_flow_score=0.3,
                          nupl_score=-0.2, active_addr_score=0.5,
                          whale_score=0.0, combined_score=0.2, confidence=0.8)
        assert -1.0 <= s.combined_score <= 1.0

    def test_from_sub_scores_with_renormalization(self):
        """When whale data is missing (score=None), renormalize weights."""
        s = OnChainSignal.from_sub_scores(
            asset="BTC",
            exchange_flow_score=0.6, nupl_score=-0.4,
            active_addr_score=0.2, whale_score=None,
            weights={"exchange_flow": 0.3, "nupl": 0.25,
                     "active_addresses": 0.15, "whale_activity": 0.3},
            confidence=0.9,
        )
        # whale excluded, weights renormalized: 0.3+0.25+0.15=0.7
        expected = (0.6 * 0.3 + (-0.4) * 0.25 + 0.2 * 0.15) / 0.7
        assert abs(s.combined_score - expected) < 1e-6
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_onchain_models.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement on_chain/models.py**

```python
# on_chain/__init__.py
```

```python
# on_chain/models.py
"""Pydantic models for on-chain data and signals."""
from datetime import datetime, date as date_type
from typing import Optional
from pydantic import BaseModel, Field, computed_field


class ExchangeFlow(BaseModel):
    asset: str
    date: date_type
    inflow: float
    outflow: float

    @computed_field
    @property
    def netflow(self) -> float:
        return self.inflow - self.outflow


class WhaleTransfer(BaseModel):
    tx_hash: str
    asset: str
    timestamp: datetime
    from_address: str
    to_address: str
    value_usd: float
    direction: str  # 'to_exchange', 'from_exchange', 'unknown'
    exchange_label: Optional[str] = None


class OnChainDaily(BaseModel):
    asset: str
    date: date_type
    exchange_inflow_native: float
    exchange_outflow_native: float
    exchange_netflow_native: float
    mvrv: float
    nupl_computed: float
    active_addresses: int


class OnChainSignal(BaseModel):
    asset: str
    exchange_flow_score: float = Field(ge=-1.0, le=1.0)
    nupl_score: float = Field(ge=-1.0, le=1.0)
    active_addr_score: float = Field(ge=-1.0, le=1.0)
    whale_score: float = Field(ge=-1.0, le=1.0)
    combined_score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)

    @classmethod
    def from_sub_scores(
        cls, asset: str, exchange_flow_score: float,
        nupl_score: float, active_addr_score: float,
        whale_score: Optional[float], weights: dict,
        confidence: float,
    ) -> "OnChainSignal":
        """Combine sub-scores. If whale_score is None, renormalize weights."""
        scores = {
            "exchange_flow": exchange_flow_score,
            "nupl": nupl_score,
            "active_addresses": active_addr_score,
        }
        effective_weights = {
            "exchange_flow": weights["exchange_flow"],
            "nupl": weights["nupl"],
            "active_addresses": weights["active_addresses"],
        }
        if whale_score is not None:
            scores["whale_activity"] = whale_score
            effective_weights["whale_activity"] = weights["whale_activity"]

        total_w = sum(effective_weights.values())
        combined = sum(
            scores[k] * effective_weights[k] for k in scores
        ) / total_w if total_w > 0 else 0.0
        combined = max(-1.0, min(1.0, combined))

        return cls(
            asset=asset,
            exchange_flow_score=exchange_flow_score,
            nupl_score=nupl_score,
            active_addr_score=active_addr_score,
            whale_score=whale_score if whale_score is not None else 0.0,
            combined_score=combined,
            confidence=confidence,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_onchain_models.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add on_chain/ tests/test_onchain_models.py
git commit -m "feat: add on-chain Pydantic models with weight renormalization"
```

---

### Task 7: On-chain collectors (CoinMetrics, Etherscan)

**Files:**
- Create: `on_chain/collectors.py`
- Create: `tests/test_onchain_collectors.py`

- [ ] **Step 1: Write collector tests**

```python
# tests/test_onchain_collectors.py
import pytest
from unittest.mock import patch, MagicMock
from on_chain.collectors import CoinMetricsCollector, EtherscanCollector


class TestCoinMetricsCollector:
    @patch("on_chain.collectors.requests.get")
    def test_collect_daily(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {
                        "asset": "btc",
                        "time": "2026-03-18T00:00:00.000000000Z",
                        "FlowInExNtv": "500.0",
                        "FlowOutExNtv": "300.0",
                        "AdrActCnt": "900000",
                        "CapMVRVCur": "2.5",
                    }
                ]
            },
        )
        c = CoinMetricsCollector()
        rows = c.collect(["BTC"])
        assert len(rows) == 1
        assert rows[0]["asset"] == "BTC"
        assert rows[0]["mvrv"] == 2.5
        assert abs(rows[0]["nupl_computed"] - 0.6) < 0.01

    @patch("on_chain.collectors.requests.get")
    def test_missing_asset_returns_empty(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": []},
        )
        c = CoinMetricsCollector()
        rows = c.collect(["SOMI"])
        assert rows == []


class TestEtherscanCollector:
    @patch("on_chain.collectors.requests.get")
    def test_collect_whale_transfers(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "status": "1",
                "result": [
                    {
                        "hash": "0xabc123",
                        "from": "0xsender",
                        "to": "0xbinance_hot_wallet",
                        "value": "2000000000000000000000",  # 2000 ETH
                        "timeStamp": "1710720000",
                        "tokenSymbol": "ETH",
                        "tokenDecimal": "18",
                    }
                ],
            },
        )
        c = EtherscanCollector(
            api_key="test",
            exchange_addresses={"0xbinance_hot_wallet": "binance"},
            eth_price_usd=3000.0,
        )
        rows = c.collect_whale_transfers(min_value_usd=1000000)
        assert len(rows) == 1
        assert rows[0]["direction"] == "to_exchange"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_onchain_collectors.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement on_chain/collectors.py**

```python
# on_chain/collectors.py
"""On-chain data collectors: CoinMetrics (daily) and Etherscan (real-time whale transfers)."""
import logging
from datetime import datetime, date, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class CoinMetricsCollector:
    """Collects daily on-chain metrics from CoinMetrics Community API.
    No API key required. Rate limit: 10 req/6s."""

    BASE_URL = "https://community-api.coinmetrics.io/v4"

    # CoinMetrics uses lowercase asset IDs — discovered at runtime
    _coverage_cache: dict[str, str] = {}  # asset -> cm_id, populated by check_coverage()

    def check_coverage(self, assets: list[str]) -> dict[str, str]:
        """Runtime coverage check: query CoinMetrics catalog to discover
        which assets are available (spec Section 2 coverage note).
        Returns dict mapping asset -> coinmetrics_id for available assets.
        Caches result for subsequent calls.
        """
        if self._coverage_cache:
            return self._coverage_cache
        try:
            resp = requests.get(
                f"{self.BASE_URL}/catalog/assets",
                params={"assets": ",".join(a.lower() for a in assets)},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            for entry in data:
                cm_id = entry.get("asset", "")
                upper = cm_id.upper()
                if upper in assets:
                    self._coverage_cache[upper] = cm_id
        except Exception as e:
            logger.warning(f"CoinMetrics coverage check failed: {e}")
            # Fallback: try common assets
            for a in assets:
                self._coverage_cache[a] = a.lower()
        logger.info(f"CoinMetrics coverage: {len(self._coverage_cache)}/{len(assets)} assets available")
        return self._coverage_cache

    def poll_interval_seconds(self) -> int:
        return 86400  # once daily

    def collect(self, assets: list[str]) -> list[dict]:
        rows = []
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        coverage = self.check_coverage(assets)
        for asset in assets:
            cm_asset = coverage.get(asset)
            if not cm_asset:
                logger.debug(f"CoinMetrics: no coverage for {asset}, skipping")
                continue
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/timeseries/asset-metrics",
                    params={
                        "assets": cm_asset,
                        "metrics": "FlowInExNtv,FlowOutExNtv,AdrActCnt,CapMVRVCur",
                        "start_time": yesterday,
                        "end_time": yesterday,
                        "frequency": "1d",
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
                if not data:
                    continue

                entry = data[0]
                inflow = float(entry.get("FlowInExNtv", 0) or 0)
                outflow = float(entry.get("FlowOutExNtv", 0) or 0)
                mvrv = float(entry.get("CapMVRVCur", 0) or 0)
                nupl = (1 - 1 / mvrv) if mvrv > 0 else 0.0
                active = int(float(entry.get("AdrActCnt", 0) or 0))

                rows.append({
                    "asset": asset,
                    "date": yesterday,
                    "exchange_inflow_native": inflow,
                    "exchange_outflow_native": outflow,
                    "exchange_netflow_native": inflow - outflow,
                    "mvrv": mvrv,
                    "nupl_computed": nupl,
                    "active_addresses": active,
                })
            except Exception as e:
                logger.warning(f"CoinMetrics failed for {asset}: {e}")

        return rows


class EtherscanCollector:
    """Collects large ERC-20 transfers and classifies whale movements.
    Requires free API key. Rate limit: 3 calls/sec, 100K/day.

    Only covers ETH-ecosystem tokens. Non-ETH assets (BTC, SOL, etc.)
    do not get whale tracking data — see spec Section 11."""

    BASE_URL = "https://api.etherscan.io/api"

    def __init__(self, api_key: str, exchange_addresses: dict[str, str],
                 eth_price_usd: float = 3000.0):
        """
        Args:
            api_key: Etherscan API key (free tier).
            exchange_addresses: dict mapping address -> exchange label.
                Sourced from brianleect/etherscan-labels repo.
            eth_price_usd: Current ETH price for USD value estimation.
        """
        self._api_key = api_key
        self._exchange_addresses = {k.lower(): v for k, v in exchange_addresses.items()}
        self._eth_price_usd = eth_price_usd

    def poll_interval_seconds(self) -> int:
        return 300

    def collect_whale_transfers(self, min_value_usd: float = 1_000_000) -> list[dict]:
        """Poll Etherscan for recent large ERC-20 transfers to/from exchange addresses.
        Iterates over monitored exchange addresses from etherscan-labels repo.
        Uses tokentx endpoint per spec Section 11."""
        rows = []
        seen_hashes = set()

        for address, label in self._exchange_addresses.items():
            try:
                resp = requests.get(
                    self.BASE_URL,
                    params={
                        "module": "account",
                        "action": "tokentx",  # ERC-20 transfers per spec
                        "address": address,
                        "sort": "desc",
                        "page": 1,
                        "offset": 50,  # last 50 transfers
                        "apikey": self._api_key,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") != "1":
                    continue

                for tx in data.get("result", []):
                    tx_hash = tx.get("hash", "")
                    if tx_hash in seen_hashes:
                        continue
                    seen_hashes.add(tx_hash)

                    value_raw = int(tx.get("value", 0))
                    decimals = int(tx.get("tokenDecimal", 18))
                    value_native = value_raw / (10 ** decimals)
                    value_usd = value_native * self._eth_price_usd

                    if value_usd < min_value_usd:
                        continue

                    from_addr = tx.get("from", "").lower()
                    to_addr = tx.get("to", "").lower()

                    if to_addr == address:
                        direction = "to_exchange"
                    elif from_addr == address:
                        direction = "from_exchange"
                    else:
                        continue

                    rows.append({
                        "tx_hash": tx_hash,
                        "asset": tx.get("tokenSymbol", "ETH"),
                        "timestamp": datetime.utcfromtimestamp(int(tx["timeStamp"])),
                        "from_address": from_addr,
                        "to_address": to_addr,
                        "value_usd": value_usd,
                        "direction": direction,
                        "exchange_label": label,
                    })

            except Exception as e:
                logger.warning(f"Etherscan collection failed for {address}: {e}")

        return rows
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_onchain_collectors.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add on_chain/collectors.py tests/test_onchain_collectors.py
git commit -m "feat: add CoinMetrics and Etherscan on-chain collectors"
```

---

### Task 8: On-chain signal processor

**Files:**
- Create: `on_chain/processors.py`
- Create: `tests/test_onchain_processors.py`

- [ ] **Step 1: Write processor tests**

```python
# tests/test_onchain_processors.py
import pytest
from on_chain.processors import (
    score_exchange_flow,
    score_nupl,
    score_active_addresses,
    score_whale_activity,
    generate_on_chain_signal,
)
from on_chain.models import OnChainSignal


class TestExchangeFlowScore:
    def test_net_inflow_negative(self):
        """Net inflow = selling pressure = negative score."""
        score = score_exchange_flow(netflow=200.0, avg_30d_netflow=0.0, std_30d=100.0)
        assert score < 0

    def test_net_outflow_positive(self):
        """Net outflow = accumulation = positive score."""
        score = score_exchange_flow(netflow=-200.0, avg_30d_netflow=0.0, std_30d=100.0)
        assert score > 0

    def test_clamped(self):
        assert -1.0 <= score_exchange_flow(10000, 0, 100) <= 1.0


class TestNUPLScore:
    def test_euphoria_negative(self):
        """NUPL > 0.75 = euphoria = negative score."""
        score = score_nupl(0.8)
        assert score < 0

    def test_capitulation_positive(self):
        """NUPL < 0 = capitulation = positive score."""
        score = score_nupl(-0.1)
        assert score > 0

    def test_neutral(self):
        """NUPL around 0.4 = mid-cycle = near zero."""
        score = score_nupl(0.4)
        assert abs(score) < 0.5

    def test_clamped(self):
        assert -1.0 <= score_nupl(1.5) <= 1.0
        assert -1.0 <= score_nupl(-1.0) <= 1.0


class TestActiveAddresses:
    def test_growing_positive(self):
        score = score_active_addresses(growth_rate_30d=0.1)
        assert score > 0

    def test_declining_negative(self):
        score = score_active_addresses(growth_rate_30d=-0.1)
        assert score < 0


class TestWhaleActivity:
    def test_net_to_exchange_negative(self):
        """Net transfers to exchanges = sell pressure = negative."""
        score = score_whale_activity(
            to_exchange_usd=5000000, from_exchange_usd=1000000
        )
        assert score < 0

    def test_net_from_exchange_positive(self):
        """Net transfers from exchanges = accumulation = positive."""
        score = score_whale_activity(
            to_exchange_usd=1000000, from_exchange_usd=5000000
        )
        assert score > 0

    def test_no_transfers_neutral(self):
        score = score_whale_activity(to_exchange_usd=0, from_exchange_usd=0)
        assert score == 0.0


class TestGenerateOnChainSignal:
    def test_returns_signal_with_whale(self):
        signal = generate_on_chain_signal(
            asset="ETH", netflow=100.0, avg_30d_netflow=50.0, std_30d=80.0,
            nupl=0.5, active_addr_growth=0.05,
            whale_to_exchange_usd=2000000, whale_from_exchange_usd=1000000,
            config={
                "sub_weights": {"exchange_flow": 0.3, "nupl": 0.25,
                                "active_addresses": 0.15, "whale_activity": 0.3},
            },
        )
        assert isinstance(signal, OnChainSignal)
        assert signal.confidence > 0

    def test_returns_signal_without_whale(self):
        """Non-ETH assets: whale data absent, weights renormalized."""
        signal = generate_on_chain_signal(
            asset="BTC", netflow=100.0, avg_30d_netflow=50.0, std_30d=80.0,
            nupl=0.5, active_addr_growth=0.05,
            whale_to_exchange_usd=None, whale_from_exchange_usd=None,
            config={
                "sub_weights": {"exchange_flow": 0.3, "nupl": 0.25,
                                "active_addresses": 0.15, "whale_activity": 0.3},
            },
        )
        assert isinstance(signal, OnChainSignal)
        assert signal.whale_score == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_onchain_processors.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement on_chain/processors.py**

```python
# on_chain/processors.py
"""Scoring logic for on-chain sub-signals.

All scores output in range [-1, +1].
"""
from typing import Optional
from on_chain.models import OnChainSignal


def score_exchange_flow(netflow: float, avg_30d_netflow: float, std_30d: float) -> float:
    """Score based on exchange net flow relative to 30-day average.
    Net inflow (positive) = selling pressure = negative score.
    Net outflow (negative) = accumulation = positive score.
    Normalized by standard deviation to detect unusual flows.
    """
    if std_30d <= 0:
        return 0.0
    z_score = (netflow - avg_30d_netflow) / std_30d
    normalized = -z_score / 3.0  # invert: inflow = negative score; cap at ~3 sigma
    return max(-1.0, min(1.0, normalized))


def score_nupl(nupl: float) -> float:
    """Score based on NUPL (Net Unrealized Profit/Loss).
    > 0.75 = euphoria = negative (cycle top risk).
    < 0 = capitulation = positive (cycle bottom opportunity).
    Linear interpolation between.
    """
    # Map NUPL to score: 0.75 -> -1, 0.375 -> 0, 0 -> +1
    # Using linear mapping: score = -nupl / 0.375 + 1
    # But with clamp at extremes
    midpoint = 0.375
    if nupl >= 0.75:
        return -1.0
    elif nupl <= -0.25:
        return 1.0
    else:
        # Linear interpolation: nupl=0.75 -> -1.0, nupl=-0.25 -> 1.0
        score = 1.0 - (nupl - (-0.25)) / (0.75 - (-0.25)) * 2.0
        return max(-1.0, min(1.0, score))


def score_active_addresses(growth_rate_30d: float) -> float:
    """Score based on 30-day active address growth rate.
    Growing = positive (fundamental demand).
    Declining = negative (waning interest).
    """
    # 10% growth -> score of +0.5, -10% -> -0.5
    normalized = growth_rate_30d * 5.0
    return max(-1.0, min(1.0, normalized))


def score_whale_activity(to_exchange_usd: float, from_exchange_usd: float,
                         scale: float = 10_000_000) -> float:
    """Score based on net whale transfer direction.
    Net to exchange = sell pressure = negative.
    Net from exchange = accumulation = positive.
    """
    total = to_exchange_usd + from_exchange_usd
    if total == 0:
        return 0.0
    net = from_exchange_usd - to_exchange_usd
    normalized = net / scale
    return max(-1.0, min(1.0, normalized))


def generate_on_chain_signal(
    asset: str,
    netflow: float, avg_30d_netflow: float, std_30d: float,
    nupl: float, active_addr_growth: float,
    whale_to_exchange_usd: Optional[float],
    whale_from_exchange_usd: Optional[float],
    config: dict,
) -> OnChainSignal:
    """Combine all on-chain sub-signals into one score."""
    ef_score = score_exchange_flow(netflow, avg_30d_netflow, std_30d)
    nupl_s = score_nupl(nupl)
    addr_s = score_active_addresses(active_addr_growth)

    whale_s = None
    if whale_to_exchange_usd is not None and whale_from_exchange_usd is not None:
        whale_s = score_whale_activity(whale_to_exchange_usd, whale_from_exchange_usd)

    has_data = any([netflow != 0, nupl != 0, active_addr_growth != 0])
    confidence = 0.8 if has_data else 0.0

    return OnChainSignal.from_sub_scores(
        asset=asset,
        exchange_flow_score=ef_score,
        nupl_score=nupl_s,
        active_addr_score=addr_s,
        whale_score=whale_s,
        weights=config["sub_weights"],
        confidence=confidence,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_onchain_processors.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add on_chain/processors.py tests/test_onchain_processors.py
git commit -m "feat: add on-chain signal scoring (exchange flow, NUPL, active addr, whale)"
```

---

## Chunk 4: Composite Scorer — Weighted Sum + Overrides

### Task 9: Composite scorer models

**Files:**
- Create: `composite/__init__.py`
- Create: `composite/models.py`

- [ ] **Step 1: Create composite models**

```python
# composite/__init__.py
```

```python
# composite/models.py
"""Models for the composite scoring system."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class OverrideEvent(BaseModel):
    """Record of a single override rule firing."""
    rule_id: str          # e.g. "O1a"
    tier: str             # "soft" or "hard"
    condition: str        # human-readable condition that triggered
    action: str           # what happened to the score
    score_before: float
    score_after: float


class CompositeScore(BaseModel):
    """Full composite scoring result for one asset."""
    asset: str
    technical_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    derivatives_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    on_chain_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    mtf_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    sentiment_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    raw_composite: float = Field(ge=-1.0, le=1.0)
    final_score: float  # can exceed [-1,1] briefly before clamping in edge cases
    overrides_fired: list[OverrideEvent] = []
    decision: str = "HOLD"  # BUY, SELL, HOLD
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TradingDecision(BaseModel):
    """Simplified output for the execution layer."""
    asset: str
    decision: str  # BUY, SELL, HOLD
    score: float
    confidence: float = 1.0
```

- [ ] **Step 2: Commit**

```bash
git add composite/
git commit -m "feat: add composite scorer Pydantic models"
```

---

### Task 10: Composite scorer — weighted sum + two-tier overrides

**Files:**
- Create: `composite/scorer.py`
- Create: `tests/test_composite_scorer.py`
- Create: `tests/test_composite_overrides.py`

- [ ] **Step 1: Write scorer tests**

```python
# tests/test_composite_scorer.py
import pytest
from composite.scorer import compute_weighted_sum, apply_overrides, make_trading_decision


class TestWeightedSum:
    def test_default_weights_sum(self):
        """Weights are normalized — changing one doesn't break output range."""
        score = compute_weighted_sum(
            technical=1.0, derivatives=1.0, on_chain=1.0, mtf=1.0, sentiment=1.0,
            weights={"technical": 0.35, "derivatives": 0.25, "on_chain": 0.15,
                     "multi_timeframe": 0.10, "sentiment": 0.15},
        )
        assert abs(score - 1.0) < 1e-6  # all +1 -> +1

    def test_mixed_signals(self):
        score = compute_weighted_sum(
            technical=0.8, derivatives=-0.5, on_chain=0.2, mtf=0.5, sentiment=0.0,
            weights={"technical": 0.35, "derivatives": 0.25, "on_chain": 0.15,
                     "multi_timeframe": 0.10, "sentiment": 0.15},
        )
        assert -1.0 <= score <= 1.0

    def test_normalization(self):
        """Unnormalized weights still produce correct result."""
        s1 = compute_weighted_sum(
            technical=0.5, derivatives=0.3, on_chain=0.1, mtf=0.2, sentiment=0.4,
            weights={"technical": 7, "derivatives": 5, "on_chain": 3,
                     "multi_timeframe": 2, "sentiment": 3},
        )
        s2 = compute_weighted_sum(
            technical=0.5, derivatives=0.3, on_chain=0.1, mtf=0.2, sentiment=0.4,
            weights={"technical": 0.35, "derivatives": 0.25, "on_chain": 0.15,
                     "multi_timeframe": 0.10, "sentiment": 0.15},
        )
        assert abs(s1 - s2) < 1e-6
```

```python
# tests/test_composite_overrides.py
import pytest
from composite.scorer import apply_overrides


DEFAULT_CONFIG = {
    "funding_soft_threshold": 0.001,
    "funding_hard_threshold": 0.002,
    "nupl_soft_high": 0.75,
    "nupl_hard_high": 0.90,
    "nupl_soft_low": 0.0,
    "nupl_hard_low": -0.25,
    "soft_penalty_multiplier": 0.2,
    "tf_opposition_multiplier": 0.5,
    "catalyst_boost_multiplier": 1.5,
    "catalyst_sentiment_threshold": 0.7,
}


class TestSoftOverrides:
    def test_funding_soft_penalty(self):
        """Funding > 0.001 penalizes positive scores."""
        result = apply_overrides(
            score=0.5, funding_rate=0.0012, nupl=0.5,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == pytest.approx(0.5 * 0.2, abs=1e-6)

    def test_funding_soft_no_effect_on_negative(self):
        """Positive funding soft override only affects positive scores."""
        result = apply_overrides(
            score=-0.5, funding_rate=0.0012, nupl=0.5,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == -0.5  # unchanged

    def test_nupl_euphoria_soft(self):
        result = apply_overrides(
            score=0.6, funding_rate=0.0, nupl=0.8,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == pytest.approx(0.6 * 0.2, abs=1e-6)

    def test_stacking_multiplicative(self):
        """O1a + O3a stack: 0.5 * 0.2 * 0.2 = 0.02."""
        result = apply_overrides(
            score=0.5, funding_rate=0.0012, nupl=0.8,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == pytest.approx(0.5 * 0.2 * 0.2, abs=1e-6)


class TestHardOverrides:
    def test_funding_hard_clamps_to_zero(self):
        result = apply_overrides(
            score=0.8, funding_rate=0.003, nupl=0.5,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] <= 0.0

    def test_nupl_hard_clamps(self):
        result = apply_overrides(
            score=0.8, funding_rate=0.0, nupl=0.95,
            tf_opposition=False, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] <= 0.0


class TestCatalystBoost:
    def test_catalyst_applied_before_penalties(self):
        """O6 applies first, then O1a penalizes the boosted score."""
        result = apply_overrides(
            score=0.4, funding_rate=0.0012, nupl=0.5,
            tf_opposition=False, catalyst_sentiment=0.8,
            config=DEFAULT_CONFIG,
        )
        # O6: 0.4 * 1.5 = 0.6, then O1a: 0.6 * 0.2 = 0.12
        assert result["final_score"] == pytest.approx(0.4 * 1.5 * 0.2, abs=1e-6)

    def test_catalyst_below_threshold_ignored(self):
        result = apply_overrides(
            score=0.4, funding_rate=0.0, nupl=0.5,
            tf_opposition=False, catalyst_sentiment=0.3,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == 0.4


class TestTFOpposition:
    def test_tf_opposition_reduces(self):
        result = apply_overrides(
            score=0.6, funding_rate=0.0, nupl=0.5,
            tf_opposition=True, catalyst_sentiment=0.0,
            config=DEFAULT_CONFIG,
        )
        assert result["final_score"] == pytest.approx(0.6 * 0.5, abs=1e-6)


class TestMakeDecision:
    def test_buy(self):
        from composite.scorer import make_optimized_trading_decision
        d = make_optimized_trading_decision(
            asset="BTC",
            scores={"technical": 0.8, "derivatives": 0.5, "on_chain": 0.3,
                    "multi_timeframe": 0.7, "sentiment": 0.4},
            weights={"technical": 0.35, "derivatives": 0.25, "on_chain": 0.15,
                     "multi_timeframe": 0.10, "sentiment": 0.15},
            thresholds={"buy_default": 0.3, "sell_default": 0.3},
            override_inputs={"funding_rate": 0.0, "nupl": 0.5,
                             "tf_opposition": False, "catalyst_sentiment": 0.0},
            override_config=DEFAULT_CONFIG,
        )
        assert d.decision == "BUY"

    def test_sell(self):
        from composite.scorer import make_optimized_trading_decision
        d = make_optimized_trading_decision(
            asset="BTC",
            scores={"technical": -0.8, "derivatives": -0.5, "on_chain": -0.3,
                    "multi_timeframe": -0.7, "sentiment": -0.4},
            weights={"technical": 0.35, "derivatives": 0.25, "on_chain": 0.15,
                     "multi_timeframe": 0.10, "sentiment": 0.15},
            thresholds={"buy_default": 0.3, "sell_default": 0.3},
            override_inputs={"funding_rate": 0.0, "nupl": 0.5,
                             "tf_opposition": False, "catalyst_sentiment": 0.0},
            override_config=DEFAULT_CONFIG,
        )
        assert d.decision == "SELL"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_composite_scorer.py tests/test_composite_overrides.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement composite/scorer.py**

```python
# composite/scorer.py
"""Composite scoring: normalized weighted sum + two-tier override rules.

See spec Section 7 for full override rule table and stacking semantics.
"""
from composite.models import CompositeScore, OverrideEvent, TradingDecision


def compute_weighted_sum(
    technical: float, derivatives: float, on_chain: float,
    mtf: float, sentiment: float, weights: dict,
) -> float:
    """Compute normalized weighted sum of all sub-scores.
    Weights are normalized by their sum to guarantee output in [-1, +1].
    """
    raw = (
        technical * weights["technical"]
        + derivatives * weights["derivatives"]
        + on_chain * weights["on_chain"]
        + mtf * weights["multi_timeframe"]
        + sentiment * weights["sentiment"]
    )
    total_w = sum(weights.values())
    if total_w == 0:
        return 0.0
    return raw / total_w


def apply_overrides(
    score: float, funding_rate: float, nupl: float,
    tf_opposition: bool, catalyst_sentiment: float,
    config: dict,
) -> dict:
    """Apply two-tier override rules to the composite score.

    Order: O6 (catalyst boost) first, then soft penalties, then hard clamps.
    Soft multipliers stack multiplicatively.
    Returns dict with final_score and overrides_fired list.
    """
    overrides = []
    current = score

    # O6: Catalyst boost (applied first)
    if abs(catalyst_sentiment) > config["catalyst_sentiment_threshold"]:
        before = current
        direction = 1.0 if catalyst_sentiment > 0 else -1.0
        if direction * current > 0:  # boost only if score aligns with catalyst
            current *= config["catalyst_boost_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O6", tier="soft",
            condition=f"catalyst_sentiment={catalyst_sentiment:.2f}",
            action=f"score * {config['catalyst_boost_multiplier']}",
            score_before=before, score_after=current,
        ))

    # O1a/O2a: Funding rate soft penalties
    if funding_rate > config["funding_soft_threshold"] and current > 0:
        before = current
        current *= config["soft_penalty_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O1a", tier="soft",
            condition=f"funding={funding_rate:.6f} > {config['funding_soft_threshold']}",
            action=f"score * {config['soft_penalty_multiplier']}",
            score_before=before, score_after=current,
        ))
    elif funding_rate < -config["funding_soft_threshold"] and current < 0:
        before = current
        current *= config["soft_penalty_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O2a", tier="soft",
            condition=f"funding={funding_rate:.6f} < -{config['funding_soft_threshold']}",
            action=f"score * {config['soft_penalty_multiplier']}",
            score_before=before, score_after=current,
        ))

    # O3a/O4a: NUPL soft penalties
    if nupl > config["nupl_soft_high"] and current > 0:
        before = current
        current *= config["soft_penalty_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O3a", tier="soft",
            condition=f"nupl={nupl:.3f} > {config['nupl_soft_high']}",
            action=f"score * {config['soft_penalty_multiplier']}",
            score_before=before, score_after=current,
        ))
    elif nupl < config["nupl_soft_low"] and current < 0:
        before = current
        current *= config["soft_penalty_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O4a", tier="soft",
            condition=f"nupl={nupl:.3f} < {config['nupl_soft_low']}",
            action=f"score * {config['soft_penalty_multiplier']}",
            score_before=before, score_after=current,
        ))

    # O5: Timeframe opposition
    if tf_opposition:
        before = current
        current *= config["tf_opposition_multiplier"]
        overrides.append(OverrideEvent(
            rule_id="O5", tier="soft",
            condition="4h_opposes_signal",
            action=f"score * {config['tf_opposition_multiplier']}",
            score_before=before, score_after=current,
        ))

    # Hard clamps (applied after all soft multipliers)
    # O1b: Extreme positive funding
    if funding_rate > config["funding_hard_threshold"] and current > 0:
        before = current
        current = 0.0
        overrides.append(OverrideEvent(
            rule_id="O1b", tier="hard",
            condition=f"funding={funding_rate:.6f} > {config['funding_hard_threshold']}",
            action="clamp to max 0",
            score_before=before, score_after=current,
        ))
    # O2b: Extreme negative funding
    elif funding_rate < -config["funding_hard_threshold"] and current < 0:
        before = current
        current = 0.0
        overrides.append(OverrideEvent(
            rule_id="O2b", tier="hard",
            condition=f"funding={funding_rate:.6f} < -{config['funding_hard_threshold']}",
            action="clamp to min 0",
            score_before=before, score_after=current,
        ))

    # O3b: Extreme NUPL high
    if nupl > config["nupl_hard_high"] and current > 0:
        before = current
        current = 0.0
        overrides.append(OverrideEvent(
            rule_id="O3b", tier="hard",
            condition=f"nupl={nupl:.3f} > {config['nupl_hard_high']}",
            action="clamp to max 0",
            score_before=before, score_after=current,
        ))
    # O4b: Extreme NUPL low
    elif nupl < config["nupl_hard_low"] and current < 0:
        before = current
        current = 0.0
        overrides.append(OverrideEvent(
            rule_id="O4b", tier="hard",
            condition=f"nupl={nupl:.3f} < {config['nupl_hard_low']}",
            action="clamp to min 0",
            score_before=before, score_after=current,
        ))

    return {"final_score": current, "overrides_fired": overrides}


def make_optimized_trading_decision(
    asset: str,
    scores: dict,
    weights: dict,
    thresholds: dict,
    override_inputs: dict,
    override_config: dict,
) -> CompositeScore:
    """Full composite scoring pipeline: weighted sum -> overrides -> decision."""
    raw = compute_weighted_sum(
        technical=scores.get("technical", 0),
        derivatives=scores.get("derivatives", 0),
        on_chain=scores.get("on_chain", 0),
        mtf=scores.get("multi_timeframe", 0),
        sentiment=scores.get("sentiment", 0),
        weights=weights,
    )

    override_result = apply_overrides(
        score=raw,
        funding_rate=override_inputs.get("funding_rate", 0),
        nupl=override_inputs.get("nupl", 0.5),
        tf_opposition=override_inputs.get("tf_opposition", False),
        catalyst_sentiment=override_inputs.get("catalyst_sentiment", 0),
        config=override_config,
    )

    final = override_result["final_score"]
    buy_t = thresholds.get("buy_default", 0.3)
    sell_t = thresholds.get("sell_default", 0.3)

    if final > buy_t:
        decision = "BUY"
    elif final < -sell_t:
        decision = "SELL"
    else:
        decision = "HOLD"

    return CompositeScore(
        asset=asset,
        technical_score=scores.get("technical", 0),
        derivatives_score=scores.get("derivatives", 0),
        on_chain_score=scores.get("on_chain", 0),
        mtf_score=scores.get("multi_timeframe", 0),
        sentiment_score=scores.get("sentiment", 0),
        raw_composite=raw,
        final_score=final,
        overrides_fired=override_result["overrides_fired"],
        decision=decision,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_composite_scorer.py tests/test_composite_overrides.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add composite/scorer.py tests/test_composite_scorer.py tests/test_composite_overrides.py
git commit -m "feat: add composite scorer with normalized weights and two-tier overrides"
```

---

## Chunk 5: Asset Discovery + Integration Wiring

### Task 11: Asset discovery script

**Files:**
- Create: `scripts/discover_assets.py`
- Create: `tests/test_asset_discovery.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_asset_discovery.py
import pytest
import json
from unittest.mock import patch, MagicMock
from scripts.discover_assets import discover_active_assets


@patch("scripts.discover_assets.requests.get")
def test_discover_filters_and_ranks(mock_get):
    """Assets not in universe or without perps are excluded."""
    universe = ["BTC/USD", "ETH/USD", "SOMI/USD"]

    # Binance returns BTC and ETH perps
    binance_resp = MagicMock(status_code=200)
    binance_resp.json.return_value = {
        "symbols": [
            {"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL"},
            {"symbol": "ETHUSDT", "status": "TRADING", "contractType": "PERPETUAL"},
        ]
    }
    # Binance OI for BTC
    btc_oi = MagicMock(status_code=200)
    btc_oi.json.return_value = {"symbol": "BTCUSDT", "openInterest": "50000", "time": 1710000000000}
    # Binance OI for ETH
    eth_oi = MagicMock(status_code=200)
    eth_oi.json.return_value = {"symbol": "ETHUSDT", "openInterest": "30000", "time": 1710000000000}

    mock_get.side_effect = [binance_resp, btc_oi, eth_oi]

    result = discover_active_assets(universe, max_assets=40)
    assets = [r["asset"] for r in result]
    assert "BTC" in assets
    assert "ETH" in assets
    # SOMI has no perps -> excluded
    somi = [r for r in result if r["asset"] == "SOMI"]
    assert somi[0]["excluded_reason"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_asset_discovery.py -v
```

- [ ] **Step 3: Implement scripts/discover_assets.py**

```python
# scripts/discover_assets.py
"""Discover which assets in the universe have perpetual futures.

Queries Binance Futures for available contracts, intersects with universe,
ranks by OI, returns asset_registry rows.
"""
import json
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def _load_universe(path: str = "config/asset_universe.json") -> list[str]:
    with open(path) as f:
        pairs = json.load(f)
    return [p.split("/")[0] for p in pairs]


def discover_active_assets(
    universe: Optional[list[str]] = None, max_assets: int = 40,
) -> list[dict]:
    """Query Binance for available perps, intersect with universe, rank by OI.

    Returns list of asset_registry dicts ready for DataStore.save_asset_registry().
    """
    if universe is None:
        universe = _load_universe()
    else:
        universe = [p.split("/")[0] if "/" in p else p for p in universe]

    # Get available Binance perpetual contracts
    try:
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=15,
        )
        resp.raise_for_status()
        symbols = resp.json().get("symbols", [])
    except Exception as e:
        logger.error(f"Failed to query Binance exchangeInfo: {e}")
        symbols = []

    perp_map = {}
    for s in symbols:
        if s.get("contractType") == "PERPETUAL" and s.get("status") == "TRADING":
            base = s["symbol"].replace("USDT", "")
            perp_map[base] = s["symbol"]

    # Fetch OI for each universe asset that has perps
    results = []
    for asset in universe:
        if asset not in perp_map:
            results.append({
                "asset": asset, "has_perps": False,
                "exchange_sources": "[]", "oi_rank": None,
                "excluded_reason": f"No perpetual contract on Binance for {asset}",
            })
            continue

        try:
            oi_resp = requests.get(
                "https://fapi.binance.com/fapi/v1/openInterest",
                params={"symbol": perp_map[asset]}, timeout=10,
            )
            oi_resp.raise_for_status()
            oi_val = float(oi_resp.json().get("openInterest", 0))
        except Exception:
            oi_val = 0

        results.append({
            "asset": asset, "has_perps": True,
            "exchange_sources": '["binance"]',
            "oi_rank": None,  # set after sorting
            "excluded_reason": None,
            "_oi_value": oi_val,
        })

    # Rank by OI and apply max_assets cutoff
    active = [r for r in results if r["has_perps"]]
    active.sort(key=lambda x: x.get("_oi_value", 0), reverse=True)

    for i, r in enumerate(active):
        r["oi_rank"] = i + 1
        if i >= max_assets:
            r["excluded_reason"] = f"OI rank {i+1} exceeds max_assets={max_assets}"
        r.pop("_oi_value", None)

    # Clean up excluded entries
    for r in results:
        r.pop("_oi_value", None)

    return results


if __name__ == "__main__":
    results = discover_active_assets()
    active = [r for r in results if r["has_perps"] and r["excluded_reason"] is None]
    excluded = [r for r in results if r["excluded_reason"] is not None]
    print(f"Active: {len(active)}, Excluded: {len(excluded)}")
    for r in active[:10]:
        print(f"  {r['asset']:8s} rank={r['oi_rank']}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_asset_discovery.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/discover_assets.py tests/test_asset_discovery.py
git commit -m "feat: add asset discovery script (Binance perps, OI ranking)"
```

---

### Task 12: Run all tests end-to-end

- [ ] **Step 1: Run full test suite**

```bash
cd /workspace/SingleRepo-WEB3-Hackathon && python -m pytest tests/ -v --tb=short
```
Expected: All PASS

- [ ] **Step 2: Commit any fixes if needed**

---

## Summary

| Chunk | Tasks | What it builds |
|-------|-------|---------------|
| 1 | 1-2 | Config files, SQLite DataStore |
| 2 | 3-5 | Derivatives models, collectors (Binance/Bybit/Coinalyze), processors |
| 3 | 6-8 | On-chain models, collectors (CoinMetrics/Etherscan), processors |
| 4 | 9-10 | Composite scorer (weighted sum + two-tier overrides) |
| 5 | 11-12 | Asset discovery, full integration test |

**Not in this plan (deferred to separate plans):**
- `technicals/` module (wrapping existing `trading_strategy.py`) — separate plan
- `composite/adapters.py` (sentiment SectorSignalSet → per-asset score) — depends on sentiment module being built
- `pipeline/orchestrator.py` (unified tick scheduler) — depends on all modules being ready
- Backtesting + parameter optimization — depends on all signal generators
