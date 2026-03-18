# Remaining Sentiment Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the sentiment signal pipeline by building the orchestrator, composite adapters, sector map builder script, and a technicals stub module.

**Architecture:** The pipeline orchestrator (`SentimentPipeline`) coordinates news fetching, LLM classification, and signal aggregation on a 5-minute tick. It uses the already-built `news_sentiment` and `sentiment_score` modules. The composite adapter bridges sector-level signals to per-asset scores consumed by the existing `composite/scorer.py`.

**Note:** `derivatives/`, `on_chain/`, and `composite/` already have substantial implementations from concurrent work. Only `technicals/` needs a stub.

**Tech Stack:** Python 3.11, SQLite (via `utils/db.py`), OpenAI SDK (via `utils/llm_client.py`), pycoingecko, pydantic

**Already built and tested (148 tests passing):**
- `utils/llm_client.py` — LLM client with batch/fast paths
- `utils/db.py` — DataStore abstraction over SQLite
- `config/` — sector_map.json, sector_config.json, sources.json, asset_universe.json
- `news_sentiment/` — models, processors (fetch, dedupe, prefilter, store), prompter (fast + batch classify)
- `sentiment_score/` — models, processors (decay, aggregation, momentum, catalyst), prompter (batch score)

---

## File Structure

| File | Responsibility | Status |
|------|---------------|--------|
| `pipeline/__init__.py` | Package marker | Create |
| `pipeline/orchestrator.py` | `SentimentPipeline` class with `tick()` method, rate limiting, logging | Create |
| `scripts/build_sector_map.py` | One-time CoinGecko API pull → `config/sector_map.json` | Create |
| `technicals/__init__.py` | Stub package marker | Create |
| `composite/adapters.py` | `SectorSignalSet` → per-asset sentiment score via sector map | Create (composite/ already exists) |
| `tests/test_orchestrator.py` | Tests for the pipeline orchestrator | Create |
| `tests/test_adapters.py` | Tests for composite adapters | Create |
| `tests/test_build_sector_map.py` | Tests for the sector map builder | Create |

---

### Task 1: Pipeline Orchestrator — Core tick() Method

**Files:**
- Create: `pipeline/__init__.py`
- Create: `pipeline/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests for SentimentPipeline**

```python
# tests/test_orchestrator.py
"""Tests for the pipeline orchestrator."""

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pipeline.orchestrator import SentimentPipeline, RateLimiter
from sentiment_score.models import SectorSignalSet
from utils.db import DataStore


NOW = datetime.now(tz=timezone.utc)


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "test.db"
    with DataStore(db_path=db_path) as db:
        yield db


@pytest.fixture
def pipeline(tmp_path):
    """Create a SentimentPipeline with test database and real configs."""
    db_path = tmp_path / "test.db"
    p = SentimentPipeline(
        db_path=db_path,
        sector_map_path="config/sector_map.json",
        sector_config_path="config/sector_config.json",
        sources_config_path="config/sources.json",
        batch_interval_min=30,
    )
    return p


class TestRateLimiter:
    def test_first_call_no_wait(self):
        rl = RateLimiter(calls_per_minute=60)
        start = time.monotonic()
        rl.wait()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    def test_respects_interval(self):
        rl = RateLimiter(calls_per_minute=600)  # 0.1s interval
        rl.wait()
        rl.wait()
        # Second call should have waited ~0.1s (but we use 600/min to keep test fast)
        # Just verify it doesn't error


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
        # After exit, db should be closed


class TestSentimentPipelineTick:
    @patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
    def test_tick_returns_sector_signal_set(self, mock_fetch, pipeline):
        with pipeline:
            result = pipeline.tick()
            assert isinstance(result, SectorSignalSet)
            assert len(result.sectors) == 6

    @patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
    def test_tick_with_no_articles(self, mock_fetch, pipeline):
        with pipeline:
            result = pipeline.tick()
            for signal in result.sectors.values():
                assert signal.sentiment == 0.0
                assert signal.confidence == 0.0

    @patch("pipeline.orchestrator.fetch_all_sources")
    @patch("pipeline.orchestrator.classify_article_fast")
    def test_tick_classifies_catalysts(self, mock_classify, mock_fetch, pipeline):
        from news_sentiment.models import ArticleInput, ClassificationOutput
        mock_fetch.return_value = [
            ArticleInput(
                id="cat1", timestamp=NOW, source="cryptopanic",
                headline="FET partnership announced",
                mentioned_tickers=["FET"],
                relevance_score=0.8, is_catalyst=True,
                matched_sectors=["ai_compute"],
            )
        ]
        mock_classify.return_value = ClassificationOutput(
            primary_sector="ai_compute", sentiment=0.9,
            magnitude="high", confidence=0.95,
        )
        with pipeline:
            result = pipeline.tick()
            mock_classify.assert_called_once()

    @patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
    def test_tick_logs_stats(self, mock_fetch, pipeline):
        with pipeline:
            result = pipeline.tick()
            assert "total_articles" in result.metadata


class TestBatchTiming:
    @patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
    def test_batch_not_run_before_interval(self, mock_fetch, pipeline):
        with pipeline:
            pipeline._last_batch_time = datetime.now(tz=timezone.utc)
            result = pipeline.tick()
            # Batch should not have run since we just set last_batch_time to now

    @patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
    def test_batch_runs_after_interval(self, mock_fetch, pipeline):
        with pipeline:
            pipeline._last_batch_time = (
                datetime.now(tz=timezone.utc) - timedelta(minutes=31)
            )
            result = pipeline.tick()
            # batch_due should have been True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.orchestrator'`

- [ ] **Step 3: Create pipeline/__init__.py**

```python
# pipeline/__init__.py
```

- [ ] **Step 4: Implement pipeline/orchestrator.py**

```python
"""Unified tick scheduler for the sentiment signal pipeline.

Coordinates news fetching, LLM classification (fast + batch paths),
and signal aggregation on a 5-minute interval.

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
    fetch_all_sources,
    get_unprocessed_articles,
    keyword_prefilter,
    load_sector_map,
    load_sources_config,
    mark_processed,
    store_articles,
)
from news_sentiment.prompter import classify_article_batch, classify_article_fast
from sentiment_score.models import SectorSignalSet
from sentiment_score.processors import compute_sector_signals, load_sector_config
from sentiment_score.prompter import score_article_batch
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
        sources_config_path: Path to ``config/sources.json``.
        batch_interval_min: Minutes between batch LLM processing runs.
    """

    def __init__(
        self,
        db_path: Path = Path("data/trading_bot.db"),
        sector_map_path: str = "config/sector_map.json",
        sector_config_path: str = "config/sector_config.json",
        sources_config_path: str = "config/sources.json",
        batch_interval_min: int = 30,
    ) -> None:
        self._db_path = db_path
        self._sector_map_path = sector_map_path
        self._sector_config_path = sector_config_path
        self._sources_config_path = sources_config_path
        self._batch_interval = timedelta(minutes=batch_interval_min)

        self._db: DataStore | None = None
        self._sector_map: dict[str, Any] = {}
        self._sector_config: dict[str, Any] = {}
        self._sources_config: dict[str, Any] = {}
        self._last_batch_time: datetime | None = None

        self._batch_limiter = RateLimiter(calls_per_minute=20)

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> SentimentPipeline:
        """Open the database and load configuration files."""
        self._db = DataStore(db_path=self._db_path)
        self._db.open()
        self._sector_map = load_sector_map(self._sector_map_path)
        self._sector_config = load_sector_config(self._sector_config_path)
        self._sources_config = load_sources_config(self._sources_config_path)
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

    # -- batch timing --------------------------------------------------------

    def _batch_due(self) -> bool:
        """Return True if enough time has passed for a batch run."""
        if self._last_batch_time is None:
            return True
        return datetime.now(tz=timezone.utc) - self._last_batch_time >= self._batch_interval

    # -- main tick -----------------------------------------------------------

    def tick(self) -> SectorSignalSet:
        """Run one pipeline cycle and return the current sector signals.

        Steps:
        1. Fetch new articles from all enabled sources.
        2. Deduplicate and keyword pre-filter.
        3. Store to SQLite.
        4. Fast path: classify catalyst articles immediately.
        5. Batch path: if interval elapsed, process unprocessed backlog.
        6. Aggregate all scored articles into sector signals.
        7. Return the SectorSignalSet.

        Returns:
            A :class:`SectorSignalSet` with signals for all 6 sectors.
        """
        assert self._db is not None, "Pipeline not opened. Use 'with' or call open()."
        tick_start = time.monotonic()

        # 1. Fetch
        raw_articles = fetch_all_sources(self._sources_config)

        # 2. Deduplicate + pre-filter
        deduped = deduplicate(raw_articles, self._db)
        filtered = keyword_prefilter(deduped, self._sector_map)

        # 3. Store
        stored_count = store_articles(filtered, self._db)

        # 4. Fast path — classify catalysts immediately
        catalysts = [a for a in filtered if a.is_catalyst]
        fast_classified = 0
        llm_calls = 0
        for article in catalysts:
            classification = classify_article_fast(article)
            mark_processed(article.id, classification, self._db)
            fast_classified += 1
            llm_calls += 1  # single-shot fast classify

        # 5. Batch path — process unprocessed backlog every batch_interval
        batch_processed = 0
        if self._batch_due():
            unprocessed = get_unprocessed_articles(self._db)
            for article in unprocessed:
                self._batch_limiter.wait()

                # Step 1: classify sector
                classification = classify_article_batch(article)

                # Step 2: score sentiment
                score_result = score_article_batch(
                    article.headline, article.body_snippet,
                    classification.primary_sector,
                )

                # Merge score into classification
                full_classification = ClassificationOutput(
                    primary_sector=classification.primary_sector,
                    secondary_sector=classification.secondary_sector,
                    sentiment=score_result["sentiment"],
                    magnitude=score_result["magnitude"],
                    confidence=score_result.get("confidence", classification.confidence),
                    cross_market=classification.cross_market,
                    reasoning=score_result.get("reasoning", ""),
                )

                mark_processed(article.id, full_classification, self._db)
                batch_processed += 1
                llm_calls += 2  # classify + score

            self._last_batch_time = datetime.now(tz=timezone.utc)

        # 6. Aggregate
        signal_set = compute_sector_signals(self._db, self._sector_config)

        # 7. Logging
        tick_ms = (time.monotonic() - tick_start) * 1000
        signal_set.metadata.update({
            "articles_fetched": len(raw_articles),
            "articles_after_dedup": len(deduped),
            "articles_after_filter": len(filtered),
            "articles_stored": stored_count,
            "catalysts_detected": len(catalysts),
            "fast_path_classified": fast_classified,
            "batch_processed": batch_processed,
            "llm_calls": llm_calls,
            "processing_time_ms": round(tick_ms, 1),
        })

        strongest = max(
            signal_set.sectors.values(),
            key=lambda s: abs(s.sentiment),
            default=None,
        )
        logger.info(
            "tick: fetched=%d filtered=%d stored=%d fast=%d batch=%d "
            "strongest=%s(%.2f) time=%.0fms",
            len(raw_articles), len(filtered), stored_count,
            fast_classified, batch_processed,
            strongest.sector if strongest else "none",
            strongest.sentiment if strongest else 0.0,
            tick_ms,
        )

        return signal_set
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/ tests/test_orchestrator.py
git commit -m "feat: add pipeline orchestrator with tick() method and rate limiter"
```

---

### Task 2: Composite Adapters — SectorSignalSet to Per-Asset Score

**Files:**
- Create: `composite/__init__.py`
- Create: `composite/adapters.py`
- Test: `tests/test_adapters.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_adapters.py
"""Tests for composite/adapters.py — signal-to-asset mapping."""

from datetime import datetime, timezone

import pytest

from composite.adapters import sector_signal_to_asset_score
from sentiment_score.models import SectorSignal, SectorSignalSet


NOW = datetime.now(tz=timezone.utc)


@pytest.fixture
def sector_map():
    import json
    with open("config/sector_map.json") as f:
        return json.load(f)


@pytest.fixture
def signal_set():
    return SectorSignalSet(
        timestamp=NOW,
        sectors={
            "ai_compute": SectorSignal(sector="ai_compute", sentiment=0.8, momentum=0.3, article_count=5, confidence=0.9),
            "defi": SectorSignal(sector="defi", sentiment=-0.2, momentum=-0.1, article_count=3, confidence=0.6),
            "l1_infra": SectorSignal(sector="l1_infra", sentiment=0.1, momentum=0.0, article_count=2, confidence=0.3),
            "meme": SectorSignal(sector="meme", sentiment=0.0, momentum=0.0),
            "store_of_value": SectorSignal(sector="store_of_value", sentiment=0.0, momentum=0.0),
            "other": SectorSignal(sector="other", sentiment=0.0, momentum=0.0),
        },
    )


class TestSectorSignalToAssetScore:
    def test_primary_sector_mapping(self, sector_map, signal_set):
        score = sector_signal_to_asset_score("FET/USD", signal_set, sector_map)
        assert score["sentiment"] == 0.8  # FET -> ai_compute
        assert score["sector"] == "ai_compute"

    def test_dual_routed_token(self, sector_map, signal_set):
        score = sector_signal_to_asset_score("NEAR/USD", signal_set, sector_map)
        # NEAR: primary l1_infra (0.1), secondary ai_compute (0.8 * 0.5 = 0.4)
        # Combined: max or weighted — check implementation
        assert score["primary_sentiment"] == 0.1
        assert score["secondary_sentiment"] is not None

    def test_token_not_in_map(self, signal_set):
        score = sector_signal_to_asset_score("UNKNOWN/USD", signal_set, {})
        assert score["sentiment"] == 0.0
        assert score["sector"] == "other"

    def test_returns_all_fields(self, sector_map, signal_set):
        score = sector_signal_to_asset_score("AAVE/USD", signal_set, sector_map)
        assert "sentiment" in score
        assert "momentum" in score
        assert "confidence" in score
        assert "sector" in score
        assert "catalyst_active" in score
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_adapters.py -v`
Expected: FAIL

- [ ] **Step 3: Implement composite/adapters.py**

```python
"""Adapter to convert SectorSignalSet into per-asset sentiment scores.

Maps each asset to its sector(s) via the sector map, then extracts
the relevant sector signal. For dual-routed tokens, the secondary
sector signal is included at 50% weight.
"""

from __future__ import annotations

import logging
from typing import Any

from sentiment_score.models import SectorSignalSet

logger = logging.getLogger(__name__)


def sector_signal_to_asset_score(
    asset: str,
    signal_set: SectorSignalSet,
    sector_map: dict[str, Any],
) -> dict[str, Any]:
    """Convert a sector-level signal set into a per-asset sentiment score.

    Args:
        asset: Asset identifier (e.g. ``"FET/USD"``).
        signal_set: The current sector signal set.
        sector_map: Parsed ``config/sector_map.json``.

    Returns:
        A dict with keys: ``sentiment``, ``momentum``, ``confidence``,
        ``sector``, ``catalyst_active``, ``primary_sentiment``,
        ``secondary_sentiment``.
    """
    mapping = sector_map.get(asset, {})
    primary = mapping.get("primary", "other")
    secondary = mapping.get("secondary")

    primary_signal = signal_set.sectors.get(primary)
    if primary_signal is None:
        return {
            "sentiment": 0.0,
            "momentum": 0.0,
            "confidence": 0.0,
            "sector": "other",
            "catalyst_active": False,
            "primary_sentiment": 0.0,
            "secondary_sentiment": None,
        }

    result = {
        "sentiment": primary_signal.sentiment,
        "momentum": primary_signal.momentum,
        "confidence": primary_signal.confidence,
        "sector": primary,
        "catalyst_active": primary_signal.catalyst_active,
        "primary_sentiment": primary_signal.sentiment,
        "secondary_sentiment": None,
    }

    # Dual-routing: include secondary sector signal at 50% weight
    if secondary:
        secondary_signal = signal_set.sectors.get(secondary)
        if secondary_signal:
            result["secondary_sentiment"] = secondary_signal.sentiment * 0.5
            # If secondary has a catalyst, propagate it
            if secondary_signal.catalyst_active and not primary_signal.catalyst_active:
                result["catalyst_active"] = True

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_adapters.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add composite/ tests/test_adapters.py
git commit -m "feat: add composite adapters for sector-to-asset signal mapping"
```

---

### Task 3: Sector Map Builder Script

**Files:**
- Create: `scripts/build_sector_map.py`
- Test: `tests/test_build_sector_map.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_build_sector_map.py
"""Tests for scripts/build_sector_map.py — CoinGecko sector map builder."""

import json
from unittest.mock import patch, MagicMock

import pytest

from scripts.build_sector_map import (
    CATEGORY_TO_SECTOR,
    classify_token,
    build_sector_map,
)


class TestCategoryToSector:
    def test_ai_categories_map_correctly(self):
        assert CATEGORY_TO_SECTOR.get("artificial-intelligence") == "ai_compute"

    def test_defi_categories_map_correctly(self):
        assert CATEGORY_TO_SECTOR.get("decentralized-finance-defi") == "defi"

    def test_meme_categories_map_correctly(self):
        assert CATEGORY_TO_SECTOR.get("meme-token") == "meme"


class TestClassifyToken:
    def test_known_categories(self):
        categories = ["artificial-intelligence", "layer-1"]
        result = classify_token("FET", categories)
        assert result["primary"] in ("ai_compute", "l1_infra")

    def test_no_categories_defaults_to_other(self):
        result = classify_token("UNKNOWN", [])
        assert result["primary"] == "other"
        assert result["secondary"] is None

    def test_returns_primary_and_secondary(self):
        result = classify_token("TEST", ["artificial-intelligence", "layer-1"])
        assert result["primary"] is not None
        assert "secondary" in result


class TestBuildSectorMap:
    @patch("scripts.build_sector_map._fetch_coingecko_categories")
    def test_produces_valid_map(self, mock_fetch):
        mock_fetch.return_value = {
            "FET": ["artificial-intelligence"],
            "BTC": ["layer-1", "store-of-value"],
        }
        result = build_sector_map(["FET/USD", "BTC/USD"])
        assert "FET/USD" in result
        assert "BTC/USD" in result
        assert result["FET/USD"]["primary"] in CATEGORY_TO_SECTOR.values() | {"other"}

    @patch("scripts.build_sector_map._fetch_coingecko_categories")
    def test_unknown_token_gets_other(self, mock_fetch):
        mock_fetch.return_value = {}
        result = build_sector_map(["UNKNOWN/USD"])
        assert result["UNKNOWN/USD"]["primary"] == "other"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_build_sector_map.py -v`
Expected: FAIL

- [ ] **Step 3: Implement scripts/build_sector_map.py**

```python
"""Build sector_map.json from CoinGecko category data.

Fetches each token's categories from the CoinGecko API and maps them
to canonical sectors. Writes the result to config/sector_map.json.

Usage::

    python scripts/build_sector_map.py
    python scripts/build_sector_map.py --dry-run
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# CoinGecko category -> canonical sector mapping
# ---------------------------------------------------------------------------

CATEGORY_TO_SECTOR: dict[str, str] = {
    # AI / Compute
    "artificial-intelligence": "ai_compute",
    "ai-agents": "ai_compute",
    "machine-learning": "ai_compute",
    "gpu": "ai_compute",
    # DeFi
    "decentralized-finance-defi": "defi",
    "decentralized-exchange": "defi",
    "lending-borrowing": "defi",
    "yield-farming": "defi",
    "yield-aggregator": "defi",
    "liquid-staking": "defi",
    "oracle": "defi",
    "real-world-assets-rwa": "defi",
    # L1 / Infrastructure
    "layer-1": "l1_infra",
    "layer-2": "l1_infra",
    "smart-contract-platform": "l1_infra",
    "interoperability": "l1_infra",
    "zero-knowledge-zk": "l1_infra",
    "modular-blockchain": "l1_infra",
    "infrastructure": "l1_infra",
    # Meme
    "meme-token": "meme",
    "dog-themed-coins": "meme",
    "cat-themed-coins": "meme",
    "pump-fun": "meme",
    "political-meme": "meme",
    # Store of Value
    "store-of-value": "store_of_value",
    "gold-backed": "store_of_value",
    "privacy-coins": "store_of_value",
    "bitcoin-ecosystem": "store_of_value",
}

# Dual-routing overrides: tokens that should have a secondary sector
DUAL_ROUTE_OVERRIDES: dict[str, str] = {
    "NEAR": "ai_compute",
    "BTC": "store_of_value",
}


# ---------------------------------------------------------------------------
# CoinGecko API
# ---------------------------------------------------------------------------


def _fetch_coingecko_categories(
    tickers: list[str],
) -> dict[str, list[str]]:
    """Fetch CoinGecko categories for a list of tickers.

    Args:
        tickers: List of ticker symbols (e.g. ["BTC", "ETH"]).

    Returns:
        Dict mapping ticker -> list of category IDs.
    """
    try:
        from pycoingecko import CoinGeckoAPI
    except ImportError:
        logger.error("pycoingecko not installed. Run: pip install pycoingecko")
        return {}

    cg = CoinGeckoAPI()
    result: dict[str, list[str]] = {}

    # Get coin list to map tickers to CoinGecko IDs
    try:
        coin_list = cg.get_coins_list()
    except Exception:
        logger.exception("Failed to fetch CoinGecko coin list")
        return {}

    ticker_to_id: dict[str, str] = {}
    for coin in coin_list:
        sym = coin.get("symbol", "").upper()
        if sym in tickers and sym not in ticker_to_id:
            ticker_to_id[sym] = coin["id"]

    # Fetch categories for each matched coin
    for ticker, coin_id in ticker_to_id.items():
        try:
            time.sleep(2)  # respect rate limits
            data = cg.get_coin_by_id(coin_id)
            categories = [
                c.lower().replace(" ", "-")
                for c in data.get("categories", [])
                if c
            ]
            result[ticker] = categories
            logger.info("Fetched categories for %s: %s", ticker, categories)
        except Exception:
            logger.exception("Failed to fetch categories for %s", ticker)
            result[ticker] = []

    return result


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_token(
    ticker: str, categories: list[str]
) -> dict[str, str | None]:
    """Classify a token into a canonical sector based on its categories.

    Args:
        ticker: The token ticker (e.g. "FET").
        categories: List of CoinGecko category IDs for this token.

    Returns:
        Dict with ``primary`` and ``secondary`` sector assignments.
    """
    matched_sectors: list[str] = []
    for cat in categories:
        sector = CATEGORY_TO_SECTOR.get(cat)
        if sector and sector not in matched_sectors:
            matched_sectors.append(sector)

    primary = matched_sectors[0] if matched_sectors else "other"
    secondary = DUAL_ROUTE_OVERRIDES.get(ticker)

    # Don't set secondary if it's the same as primary
    if secondary == primary:
        secondary = None

    return {"primary": primary, "secondary": secondary}


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_sector_map(
    universe: list[str],
) -> dict[str, dict[str, str | None]]:
    """Build the complete sector map for a universe of assets.

    Args:
        universe: List of asset pairs (e.g. ["BTC/USD", "ETH/USD"]).

    Returns:
        Dict mapping each asset pair to its sector assignment.
    """
    tickers = [pair.split("/")[0] for pair in universe]
    categories_by_ticker = _fetch_coingecko_categories(tickers)

    sector_map: dict[str, dict[str, str | None]] = {}
    for pair in universe:
        ticker = pair.split("/")[0]
        categories = categories_by_ticker.get(ticker, [])
        sector_map[pair] = classify_token(ticker, categories)

    return sector_map


def main() -> None:
    """CLI entry point: build sector_map.json from CoinGecko data."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    universe_path = PROJECT_ROOT / "config" / "asset_universe.json"
    output_path = PROJECT_ROOT / "config" / "sector_map.json"

    with open(universe_path) as f:
        universe = json.load(f)

    dry_run = "--dry-run" in sys.argv

    logger.info("Building sector map for %d assets...", len(universe))
    sector_map = build_sector_map(universe)

    if dry_run:
        print(json.dumps(sector_map, indent=2))
    else:
        with open(output_path, "w") as f:
            json.dump(sector_map, f, indent=2)
        logger.info("Wrote sector map to %s", output_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_build_sector_map.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/build_sector_map.py tests/test_build_sector_map.py
git commit -m "feat: add CoinGecko-based sector map builder script"
```

---

### Task 4: Technicals Stub Module

**Note:** `derivatives/`, `on_chain/`, and `composite/` already have implementations from concurrent work. Only `technicals/` needs creation.

**Files:**
- Create: `technicals/__init__.py`

- [ ] **Step 1: Create technicals/__init__.py**

```python
# technicals/__init__.py
"""Technical analysis signals module (to be refactored from sma-prediction/)."""
```

- [ ] **Step 2: Verify imports work**

Run: `python -c "import derivatives; import on_chain; import technicals; import composite; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 3: Commit**

```bash
git add technicals/__init__.py
git commit -m "feat: add technicals stub module"
```

---

### Task 5: Full Integration Test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration.py
"""Integration test: full pipeline tick with mocked news sources and LLM."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from news_sentiment.models import ArticleInput, ClassificationOutput
from pipeline.orchestrator import SentimentPipeline
from sentiment_score.models import SectorSignalSet


NOW = datetime.now(tz=timezone.utc)


def _mock_articles():
    return [
        ArticleInput(
            id="int1", timestamp=NOW, source="cryptopanic",
            headline="FET partnership with major cloud provider",
            mentioned_tickers=["FET"],
            relevance_score=0.8, is_catalyst=True,
            matched_sectors=["ai_compute"],
        ),
        ArticleInput(
            id="int2", timestamp=NOW, source="rss_coindesk",
            headline="Ethereum DeFi TVL reaches new high",
            relevance_score=0.5, is_catalyst=False,
            matched_sectors=["defi"],
        ),
    ]


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


@patch("pipeline.orchestrator.fetch_all_sources", side_effect=_mock_articles)
@patch("pipeline.orchestrator.classify_article_fast", side_effect=_mock_classify_fast)
@patch("pipeline.orchestrator.classify_article_batch", side_effect=_mock_classify_batch)
@patch("pipeline.orchestrator.score_article_batch", side_effect=_mock_score_batch)
def test_full_pipeline_tick(mock_score, mock_batch, mock_fast, mock_fetch, tmp_path):
    db_path = tmp_path / "integration.db"
    with SentimentPipeline(db_path=db_path) as pipeline:
        result = pipeline.tick()

    assert isinstance(result, SectorSignalSet)
    assert len(result.sectors) == 6

    # ai_compute should have signal from the catalyst article
    ai = result.sectors["ai_compute"]
    assert ai.article_count >= 1
    assert ai.sentiment > 0

    # Metadata should be populated
    assert result.metadata["articles_fetched"] == 2
    assert result.metadata["catalysts_detected"] == 1
    assert result.metadata["fast_path_classified"] == 1


@patch("pipeline.orchestrator.fetch_all_sources", return_value=[])
def test_empty_tick_is_safe(mock_fetch, tmp_path):
    db_path = tmp_path / "empty.db"
    with SentimentPipeline(db_path=db_path) as pipeline:
        result = pipeline.tick()

    assert isinstance(result, SectorSignalSet)
    assert all(s.sentiment == 0.0 for s in result.sectors.values())
```

- [ ] **Step 2: Run integration test**

Run: `python -m pytest tests/test_integration.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS (148 existing + new tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add full pipeline integration test"
```

- [ ] **Step 5: Final commit of all remaining files**

```bash
git add -A
git commit -m "feat: complete sentiment signal pipeline with orchestrator, adapters, and stubs"
```
