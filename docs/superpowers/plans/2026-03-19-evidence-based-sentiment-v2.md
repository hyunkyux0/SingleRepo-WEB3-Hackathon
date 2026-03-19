# Evidence-Based Sentiment Pipeline v2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-article LLM sentiment scoring with per-sector evidence-based scoring that includes market context (prices, funding rates, article velocity).

**Architecture:** Classification stays per-article (unchanged). Scoring moves to per-sector: a deterministic summary of articles + quantitative evidence is fed into ONE LLM call per sector. The orchestrator's tick() flow is restructured to classify first, then score sectors. Per-article `score_article_batch()` is deprecated.

**Tech Stack:** Python 3.11, OpenAI API (via `utils/llm_client.py`), Kraken REST API, SQLite, pydantic

**Spec:** `docs/superpowers/specs/2026-03-19-evidence-based-sentiment-v2-design.md`

**Existing tests:** 263 passing. All must continue passing after each task.

**Deprecation note:** `compute_sector_signals()`, `aggregate_sector_signal()`, `build_scored_articles()`, and `score_article_batch()` are deprecated — kept in code for backward compatibility (their existing tests still pass) but no longer called by the orchestrator. The orchestrator builds SectorSignal objects directly using `build_sector_summary()` + `gather_evidence()` + `score_sector()`.

**Momentum note:** Momentum changes from window-based (compare current vs previous lookback window articles) to tick-based (compare current tick score vs previous tick score). Tick-based is more appropriate for the evidence-based approach since the score already incorporates the full article window. Previous window sentiment was a proxy for "what was the trend?" — now we have the actual previous score.

---

---

## File Structure

| File | Change | Responsibility |
|------|--------|---------------|
| `scripts/fetch_news.py:67` | Modify | Remove `filter=hot`, add 24h age cutoff |
| `news_sentiment/processors.py:141-154` | Modify | Extend Jaccard dedup to check last 200 DB articles |
| `sentiment_score/models.py:28-37` | Modify | Add `key_driver` and `reasoning` fields to `SectorSignal` |
| `sentiment_score/processors.py` | Modify | Add `build_sector_summary()`, `gather_evidence()`, `fetch_current_prices()`. Refactor `compute_sector_signals()` to use `score_sector()`. |
| `sentiment_score/prompter.py` | Modify | Add `score_sector()`. Keep `score_article_batch()` for backward compat. |
| `pipeline/orchestrator.py` | Modify | Restructure tick(): remove per-article scoring loop, add sector scoring loop. Add `_previous_signals`, `_last_rss_fetch`. |
| `tests/test_sentiment_v2.py` | Create | Tests for new functions |
| `tests/test_orchestrator.py` | Modify | Update mocks for new tick() flow |
| `tests/test_integration.py` | Modify | Update mocks for new tick() flow |

---

### Task 1: Fix CryptoPanic Fetching + Age Cutoff

**Files:**
- Modify: `scripts/fetch_news.py:67` (remove filter=hot)
- Modify: `scripts/fetch_news.py:56-78` (add age cutoff)
- Test: `tests/test_fetch_news.py` (create)

- [ ] **Step 1: Write tests for fetch changes**

```python
# tests/test_fetch_news.py
"""Tests for scripts/fetch_news.py — fetching and age cutoff."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from scripts.fetch_news import deduplicate, _jaccard_similarity


class TestAgeFilter:
    def test_old_articles_filtered(self):
        from scripts.fetch_news import _filter_by_age
        now = datetime.now(tz=timezone.utc)
        articles = [
            {"timestamp": (now - timedelta(hours=2)).isoformat(), "headline": "Recent"},
            {"timestamp": (now - timedelta(hours=30)).isoformat(), "headline": "Old"},
        ]
        result = _filter_by_age(articles, max_age_hours=24)
        assert len(result) == 1
        assert result[0]["headline"] == "Recent"

    def test_no_timestamp_kept(self):
        from scripts.fetch_news import _filter_by_age
        articles = [{"headline": "No timestamp"}]
        result = _filter_by_age(articles, max_age_hours=24)
        assert len(result) == 1  # kept by default

    def test_all_recent_kept(self):
        from scripts.fetch_news import _filter_by_age
        now = datetime.now(tz=timezone.utc)
        articles = [
            {"timestamp": (now - timedelta(hours=i)).isoformat(), "headline": f"Art {i}"}
            for i in range(5)
        ]
        result = _filter_by_age(articles, max_age_hours=24)
        assert len(result) == 5


class TestDeduplication:
    def test_removes_duplicate_urls(self):
        articles = [
            {"url": "https://x.com/1", "headline": "First"},
            {"url": "https://x.com/1", "headline": "Duplicate"},
        ]
        result = deduplicate(articles)
        assert len(result) == 1

    def test_removes_similar_headlines(self):
        articles = [
            {"url": "", "headline": "Bitcoin price surges to new record high today"},
            {"url": "", "headline": "Bitcoin price surges to new record high"},
        ]
        result = deduplicate(articles)
        assert len(result) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_fetch_news.py -v`
Expected: FAIL — `_filter_by_age` not found

- [ ] **Step 3: Implement changes in fetch_news.py**

In `scripts/fetch_news.py`:

1. Remove `&filter=hot` from the CryptoPanic URL (line 67):
```python
# Change:
url = f"https://cryptopanic.com/api/developer/v2/posts/?auth_token={api_key}&filter=hot&public=true"
# To:
url = f"https://cryptopanic.com/api/developer/v2/posts/?auth_token={api_key}&public=true"
```

2. Add `_filter_by_age()` function after the `deduplicate()` function:
```python
def _filter_by_age(articles: list[dict], max_age_hours: float = 24) -> list[dict]:
    """Discard articles older than max_age_hours."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    result = []
    for art in articles:
        ts_str = art.get("timestamp", "")
        if not ts_str:
            result.append(art)  # keep if no timestamp
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                result.append(art)
        except (ValueError, TypeError):
            result.append(art)  # keep if unparseable
    removed = len(articles) - len(result)
    if removed > 0:
        logger.info("Age filter: removed %d articles older than %dh", removed, max_age_hours)
    return result
```

3. Call `_filter_by_age` in `fetch_all()` before returning:
```python
def fetch_all(sources=None):
    ...
    all_articles = ...  # existing fetch logic
    all_articles = _filter_by_age(all_articles)  # ADD THIS
    logger.info(...)
    return all_articles
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_fetch_news.py tests/ -v --tb=short`
Expected: All PASS (new + existing 263)

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_news.py tests/test_fetch_news.py
git commit -m "feat: remove CryptoPanic hot filter, add 24h age cutoff to fetch_news"
```

---

### Task 2: Improve Deduplication — Jaccard Against DB

**Files:**
- Modify: `news_sentiment/processors.py:141-154`
- Test: `tests/test_news_sentiment.py` (add tests)

- [ ] **Step 1: Write test for DB-backed Jaccard dedup**

Add to `tests/test_news_sentiment.py` class `TestDeduplicate`:

```python
def test_jaccard_dedup_against_db(self, tmp_db):
    """Headlines similar to recent DB articles should be deduped."""
    # Store an article with a similar headline
    from news_sentiment.processors import store_articles, deduplicate
    from news_sentiment.models import ArticleInput
    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc)
    existing = ArticleInput(
        id="db1", timestamp=now, source="rss",
        headline="Bitcoin surges past 100K on massive ETF inflows",
        url="https://old.com/1",
    )
    store_articles([existing], tmp_db)

    # Try to add a very similar headline from a different source
    new_article = ArticleInput(
        id="new1", timestamp=now, source="rss_coindesk",
        headline="Bitcoin surges past 100K on massive ETF inflows today",
        url="https://new.com/1",  # different URL
    )
    result = deduplicate([new_article], tmp_db)
    assert len(result) == 0  # should be deduped by Jaccard against DB
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_news_sentiment.py::TestDeduplicate::test_jaccard_dedup_against_db -v`
Expected: FAIL — current dedup only checks Jaccard within batch, not against DB

- [ ] **Step 3: Update deduplicate() in news_sentiment/processors.py**

Replace the dedup function to also check Jaccard against the last 200 DB headlines:

```python
def deduplicate(
    articles: list[ArticleInput], db: DataStore
) -> list[ArticleInput]:
    if not articles:
        return []

    # 1. Remove articles whose URL already exists in DB
    existing_urls: set[str] = set()
    rows = db.fetchall("SELECT url FROM articles WHERE url != ''")
    for row in rows:
        existing_urls.add(row["url"])

    unique: list[ArticleInput] = []
    for art in articles:
        if art.url and art.url in existing_urls:
            continue
        unique.append(art)

    # 2. Fetch recent DB headlines for Jaccard comparison
    db_headlines: list[str] = []
    recent_rows = db.fetchall(
        "SELECT headline FROM articles ORDER BY timestamp DESC LIMIT 200"
    )
    for row in recent_rows:
        if row["headline"]:
            db_headlines.append(row["headline"])

    # 3. Remove near-duplicates against DB + within batch (Jaccard > 0.7)
    deduped: list[ArticleInput] = []
    for art in unique:
        is_dup = False
        # Check against DB headlines
        for db_hl in db_headlines:
            if _jaccard_similarity(art.headline, db_hl) > 0.7:
                is_dup = True
                break
        # Check against already-kept batch articles
        if not is_dup:
            for kept in deduped:
                if _jaccard_similarity(art.headline, kept.headline) > 0.7:
                    is_dup = True
                    break
        if not is_dup:
            deduped.append(art)

    removed = len(articles) - len(deduped)
    if removed > 0:
        logger.info("Deduplication removed %d articles (%d -> %d)", removed, len(articles), len(deduped))

    return deduped
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_news_sentiment.py tests/ -q --tb=short`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add news_sentiment/processors.py tests/test_news_sentiment.py
git commit -m "feat: extend dedup to check Jaccard against last 200 DB articles"
```

---

### Task 3: Add key_driver and reasoning to SectorSignal

**Files:**
- Modify: `sentiment_score/models.py:28-37`
- Test: `tests/test_sentiment_score.py` (add tests)

- [ ] **Step 1: Write tests**

Add to `tests/test_sentiment_score.py` class `TestSectorSignal`:

```python
def test_new_fields_defaults(self):
    sig = SectorSignal(sector="defi", sentiment=0.3, momentum=0.1)
    assert sig.key_driver == ""
    assert sig.reasoning == ""

def test_new_fields_populated(self):
    sig = SectorSignal(
        sector="ai_compute", sentiment=0.5, momentum=0.2,
        key_driver="NVIDIA partnership",
        reasoning="Strong bullish signal from NVIDIA. FET already up 5%.",
    )
    assert sig.key_driver == "NVIDIA partnership"
    assert "NVIDIA" in sig.reasoning
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sentiment_score.py::TestSectorSignal -v`
Expected: FAIL — `key_driver` field not recognized

- [ ] **Step 3: Add fields to SectorSignal**

In `sentiment_score/models.py`, add to `SectorSignal`:

```python
class SectorSignal(BaseModel):
    """Aggregated signal for a single sector."""

    sector: str
    sentiment: float
    momentum: float
    catalyst_active: bool = False
    catalyst_details: Optional[dict] = None
    article_count: int = 0
    confidence: float = 0.0
    key_driver: str = ""      # NEW: primary factor driving the score
    reasoning: str = ""       # NEW: LLM explanation referencing evidence
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ -q --tb=short`
Expected: All PASS (additive fields with defaults don't break anything)

- [ ] **Step 5: Commit**

```bash
git add sentiment_score/models.py tests/test_sentiment_score.py
git commit -m "feat: add key_driver and reasoning fields to SectorSignal"
```

---

### Task 4: Build Sector Summary + Evidence Gathering

**Files:**
- Modify: `sentiment_score/processors.py`
- Create: `tests/test_sentiment_v2.py`

- [ ] **Step 1: Write tests for build_sector_summary**

```python
# tests/test_sentiment_v2.py
"""Tests for evidence-based sentiment v2 functions."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from sentiment_score.processors import (
    build_sector_summary,
    gather_evidence,
    fetch_current_prices,
)
from utils.db import DataStore


NOW = datetime.now(tz=timezone.utc)


def _insert(db, id, sector, headline, source="rss_coindesk",
            snippet="", tickers="[]", relevance=0.5, hours_ago=0,
            sentiment=0.0, magnitude="low", confidence=0.7):
    ts = (NOW - timedelta(hours=hours_ago)).isoformat()
    db.execute(
        """INSERT OR IGNORE INTO articles
           (id, timestamp, source, headline, body_snippet, mentioned_tickers,
            relevance_score, is_catalyst, processed, llm_sector,
            llm_sentiment, llm_magnitude, llm_confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?, ?)""",
        (id, ts, source, headline, snippet, tickers, relevance,
         sector, sentiment, magnitude, confidence),
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
            _insert(tmp_db, f"lim{i}", "defi", f"Article {i}", hours_ago=i*0.5)
        result = build_sector_summary(tmp_db, "defi", lookback_hours=24)
        assert len(result["top_headlines"]) <= 10

    def test_velocity_accelerating(self, tmp_db):
        # 5 articles in current window (0-12h), 1 in previous (12-24h)
        for i in range(5):
            _insert(tmp_db, f"acc{i}", "ai_compute", f"AI news {i}", hours_ago=i)
        _insert(tmp_db, "acc_old", "ai_compute", "Old AI news", hours_ago=18)
        result = build_sector_summary(tmp_db, "ai_compute", lookback_hours=12)
        assert result["velocity"] == "accelerating"

    def test_velocity_decelerating(self, tmp_db):
        # 1 article in current window, 5 in previous
        _insert(tmp_db, "dec0", "defi", "Recent", hours_ago=1)
        for i in range(5):
            _insert(tmp_db, f"dec{i+1}", "defi", f"Old {i}", hours_ago=15+i)
        result = build_sector_summary(tmp_db, "defi", lookback_hours=12)
        assert result["velocity"] == "decelerating"

    def test_includes_snippet_when_available(self, tmp_db):
        _insert(tmp_db, "snip1", "defi", "Headline", snippet="Body text here")
        result = build_sector_summary(tmp_db, "defi", lookback_hours=24)
        assert result["top_headlines"][0]["snippet"] == "Body text here"

    def test_mentioned_tickers_aggregated(self, tmp_db):
        _insert(tmp_db, "tk1", "defi", "UNI surges", tickers='["UNI"]')
        _insert(tmp_db, "tk2", "defi", "UNI and AAVE rally", tickers='["UNI", "AAVE"]')
        result = build_sector_summary(tmp_db, "defi", lookback_hours=24)
        assert result["mentioned_tickers"]["UNI"] == 2
        assert result["mentioned_tickers"]["AAVE"] == 1


class TestFetchCurrentPrices:
    @patch("sentiment_score.processors.requests.get")
    def test_returns_prices(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "result": {
                "FETUSD": {
                    "c": ["1.42", "0.01"],   # last trade [price, volume]
                    "o": "1.35",              # opening price
                }
            }
        }
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
        mock_get.return_value.json.return_value = {
            "result": {
                "BTCUSD": {
                    "c": ["84000", "0.5"],
                    "o": "86000",
                }
            }
        }
        result = fetch_current_prices(["BTC"])
        assert result[0]["change_24h_pct"] == pytest.approx(-2.326, abs=0.01)


class TestGatherEvidence:
    @patch("sentiment_score.processors.fetch_current_prices")
    def test_returns_evidence_dict(self, mock_prices, tmp_db, sector_map):
        mock_prices.return_value = [
            {"ticker": "FET", "price": 1.42, "change_24h_pct": 5.1},
        ]
        summary = {"mentioned_tickers": {"FET": 3}}
        prev_signals = {"ai_compute": 0.2}
        result = gather_evidence("ai_compute", sector_map, summary, prev_signals)
        assert "token_prices" in result
        assert "previous_sentiment" in result
        assert result["previous_sentiment"] == 0.2

    @patch("sentiment_score.processors.fetch_current_prices")
    def test_no_previous_signals(self, mock_prices, tmp_db, sector_map):
        mock_prices.return_value = []
        summary = {"mentioned_tickers": {}}
        result = gather_evidence("defi", sector_map, summary, None)
        assert result["previous_sentiment"] == 0.0

    @patch("sentiment_score.processors.fetch_current_prices")
    def test_selects_sector_tokens(self, mock_prices, tmp_db, sector_map):
        mock_prices.return_value = []
        summary = {"mentioned_tickers": {}}
        gather_evidence("ai_compute", sector_map, summary, None)
        # Should have called fetch_current_prices with ai_compute tokens
        called_tickers = mock_prices.call_args[0][0]
        assert "FET" in called_tickers
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sentiment_v2.py -v`
Expected: FAIL — functions not found

- [ ] **Step 3: Implement build_sector_summary()**

Add to `sentiment_score/processors.py`:

```python
import requests  # add to imports at top

def build_sector_summary(
    db: DataStore, sector: str, lookback_hours: float
) -> dict[str, Any]:
    """Build a deterministic summary of articles for one sector.

    Args:
        db: Open DataStore.
        sector: Sector ID (e.g. "defi").
        lookback_hours: How far back to look.

    Returns:
        Dict with sector, article_count, velocity, top_headlines,
        mentioned_tickers, catalyst_count.
    """
    now = datetime.now(tz=timezone.utc)
    cutoff = (now - timedelta(hours=lookback_hours)).isoformat()
    prev_cutoff = (now - timedelta(hours=2 * lookback_hours)).isoformat()

    # Current window articles
    current_rows = db.fetchall(
        """SELECT headline, body_snippet, source, mentioned_tickers,
                  relevance_score, is_catalyst, timestamp
           FROM articles
           WHERE processed = 1 AND llm_sector = ? AND timestamp >= ?
           ORDER BY relevance_score DESC LIMIT 10""",
        (sector, cutoff),
    )

    # Count for current and previous windows (for velocity)
    current_count_row = db.fetchone(
        "SELECT COUNT(*) as cnt FROM articles WHERE processed=1 AND llm_sector=? AND timestamp>=?",
        (sector, cutoff),
    )
    current_count = current_count_row["cnt"] if current_count_row else 0

    prev_count_row = db.fetchone(
        "SELECT COUNT(*) as cnt FROM articles WHERE processed=1 AND llm_sector=? AND timestamp>=? AND timestamp<?",
        (sector, prev_cutoff, cutoff),
    )
    prev_count = prev_count_row["cnt"] if prev_count_row else 0

    # Velocity
    if prev_count == 0:
        velocity = "accelerating" if current_count > 0 else "steady"
    elif current_count > prev_count * 1.5:
        velocity = "accelerating"
    elif current_count < prev_count * 0.5:
        velocity = "decelerating"
    else:
        velocity = "steady"

    # Build headlines list + aggregate tickers
    top_headlines = []
    mentioned_tickers: dict[str, int] = {}
    catalyst_count = 0

    for row in current_rows:
        ts = datetime.fromisoformat(row["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_hours = round((now - ts).total_seconds() / 3600, 1)

        tickers = json.loads(row["mentioned_tickers"]) if row["mentioned_tickers"] else []
        for t in tickers:
            mentioned_tickers[t] = mentioned_tickers.get(t, 0) + 1

        if row["is_catalyst"]:
            catalyst_count += 1

        top_headlines.append({
            "headline": row["headline"],
            "snippet": row["body_snippet"] or "",
            "source": row["source"],
            "tickers": tickers,
            "age_hours": age_hours,
            "is_catalyst": bool(row["is_catalyst"]),
        })

    return {
        "sector": sector,
        "article_count": current_count,
        "velocity": velocity,
        "top_headlines": top_headlines,
        "mentioned_tickers": mentioned_tickers,
        "catalyst_count": catalyst_count,
    }
```

- [ ] **Step 4: Implement fetch_current_prices()**

Add to `sentiment_score/processors.py`:

```python
def fetch_current_prices(tickers: list[str]) -> list[dict[str, Any]]:
    """Fetch current prices from Kraken REST API.

    Args:
        tickers: List of ticker symbols (e.g. ["BTC", "ETH"]).

    Returns:
        List of dicts with ticker, price, change_24h_pct.
        Returns empty list on failure.
    """
    if not tickers:
        return []

    # Map common tickers to Kraken pair format
    pair_map = {
        "BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD",
        "XRP": "XRPUSD", "ADA": "ADAUSD", "DOT": "DOTUSD",
        "AVAX": "AVAXUSD", "LINK": "LINKUSD", "UNI": "UNIUSD",
        "AAVE": "AAVEUSD", "DOGE": "DOGEUSD", "SHIB": "SHIBUSD",
        "FET": "FETUSD", "NEAR": "NEARUSD", "SUI": "SUIUSD",
        "APT": "APTUSD", "FIL": "FILUSD", "LTC": "LTCUSD",
    }

    pairs = []
    ticker_for_pair = {}
    for t in tickers[:5]:  # max 5 tokens
        pair = pair_map.get(t, f"{t}USD")
        pairs.append(pair)
        ticker_for_pair[pair] = t

    try:
        url = f"https://api.kraken.com/0/public/Ticker?pair={','.join(pairs)}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("Kraken price fetch failed")
        return []

    results = []
    for pair_key, ticker in ticker_for_pair.items():
        # Kraken returns keys with various prefixes
        pair_data = None
        for key in data.get("result", {}):
            if pair_key in key or ticker in key:
                pair_data = data["result"][key]
                break
        if pair_data is None:
            continue

        try:
            price = float(pair_data["c"][0])     # last trade price
            open_price = float(pair_data["o"])    # 24h opening price
            change_pct = ((price - open_price) / open_price) * 100 if open_price else 0.0
            results.append({
                "ticker": ticker,
                "price": price,
                "change_24h_pct": round(change_pct, 3),
            })
        except (KeyError, ValueError, IndexError):
            logger.warning("Failed to parse price for %s", ticker)
            continue

    return results
```

- [ ] **Step 5: Implement gather_evidence()**

Add to `sentiment_score/processors.py`:

```python
def gather_evidence(
    sector: str,
    sector_map: dict[str, Any],
    sector_summary: dict[str, Any],
    previous_signals: dict[str, float] | None,
) -> dict[str, Any]:
    """Gather quantitative market context for sector scoring.

    Args:
        sector: Sector ID.
        sector_map: Parsed sector_map.json.
        sector_summary: Output of build_sector_summary().
        previous_signals: Dict mapping sector -> previous sentiment. None on first tick.

    Returns:
        Dict with token_prices, previous_sentiment, and optional signals.
    """
    # Find tokens in this sector
    sector_tickers = [
        pair.split("/")[0]
        for pair, info in sector_map.items()
        if info.get("primary") == sector
    ][:5]

    # Fetch prices
    token_prices = fetch_current_prices(sector_tickers)

    # Previous sentiment
    prev_sent = 0.0
    if previous_signals and sector in previous_signals:
        prev_sent = previous_signals[sector]

    evidence: dict[str, Any] = {
        "token_prices": token_prices,
        "previous_sentiment": prev_sent,
        "funding_rate": None,
        "nupl": None,
        "exchange_net_flow": None,
    }

    # TODO: populate funding_rate, nupl, exchange_net_flow from
    # derivatives/on_chain modules when available

    return evidence
```

- [ ] **Step 6: Run all tests**

Run: `python -m pytest tests/ -q --tb=short`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add sentiment_score/processors.py tests/test_sentiment_v2.py
git commit -m "feat: add build_sector_summary, fetch_current_prices, gather_evidence"
```

---

### Task 5: score_sector() Prompt + Function

**Files:**
- Modify: `sentiment_score/prompter.py`
- Add tests to: `tests/test_sentiment_v2.py`

- [ ] **Step 1: Write tests for score_sector**

Add to `tests/test_sentiment_v2.py`:

```python
from sentiment_score.prompter import score_sector, build_sector_score_prompt


class TestBuildSectorScorePrompt:
    def test_includes_sector(self):
        summary = {
            "sector": "ai_compute", "article_count": 3, "velocity": "accelerating",
            "top_headlines": [
                {"headline": "NVIDIA AI chip", "snippet": "Details...", "source": "rss_coindesk",
                 "tickers": ["FET"], "age_hours": 2.0, "is_catalyst": False},
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
            "token_prices": [],
            "previous_sentiment": 0.0,
            "funding_rate": None, "nupl": None, "exchange_net_flow": None,
        }
        prompt = build_sector_score_prompt(summary, evidence)
        assert "Funding rate" not in prompt
        assert "NUPL" not in prompt


class TestScoreSector:
    def test_valid_response(self):
        response = {
            "sentiment": 0.45, "magnitude": "medium", "confidence": 0.8,
            "key_driver": "NVIDIA partnership",
            "reasoning": "Strong signal from NVIDIA. FET up 5%.",
        }
        with patch("sentiment_score.prompter.call_llm",
                   return_value=(json.dumps(response), {}, "openai/gpt-5.4-nano")):
            result = score_sector(
                {"sector": "ai_compute", "article_count": 3, "velocity": "steady",
                 "top_headlines": [], "mentioned_tickers": {}, "catalyst_count": 0},
                {"token_prices": [], "previous_sentiment": 0.0,
                 "funding_rate": None, "nupl": None, "exchange_net_flow": None},
            )
            assert result["sentiment"] == 0.45
            assert result["key_driver"] == "NVIDIA partnership"

    def test_clamps_sentiment(self):
        response = {"sentiment": 5.0, "magnitude": "high", "confidence": 0.5,
                    "key_driver": "x", "reasoning": "y"}
        with patch("sentiment_score.prompter.call_llm",
                   return_value=(json.dumps(response), {}, "test")):
            result = score_sector(
                {"sector": "defi", "article_count": 1, "velocity": "steady",
                 "top_headlines": [], "mentioned_tickers": {}, "catalyst_count": 0},
                {"token_prices": [], "previous_sentiment": 0.0,
                 "funding_rate": None, "nupl": None, "exchange_net_flow": None},
            )
            assert result["sentiment"] == 1.0

    def test_llm_failure_returns_default(self):
        with patch("sentiment_score.prompter.call_llm",
                   side_effect=RuntimeError("API down")):
            result = score_sector(
                {"sector": "meme", "article_count": 0, "velocity": "steady",
                 "top_headlines": [], "mentioned_tickers": {}, "catalyst_count": 0},
                {"token_prices": [], "previous_sentiment": 0.0,
                 "funding_rate": None, "nupl": None, "exchange_net_flow": None},
            )
            assert result["sentiment"] == 0.0
            assert result["confidence"] == 0.0

    def test_empty_sector_skips_llm(self):
        """Sectors with 0 articles should not call the LLM."""
        with patch("sentiment_score.prompter.call_llm") as mock_llm:
            result = score_sector(
                {"sector": "meme", "article_count": 0, "velocity": "steady",
                 "top_headlines": [], "mentioned_tickers": {}, "catalyst_count": 0},
                {"token_prices": [], "previous_sentiment": 0.0,
                 "funding_rate": None, "nupl": None, "exchange_net_flow": None},
            )
            mock_llm.assert_not_called()
            assert result["sentiment"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sentiment_v2.py::TestScoreSector -v`
Expected: FAIL

- [ ] **Step 3: Implement score_sector() and build_sector_score_prompt()**

Add to `sentiment_score/prompter.py`:

```python
SECTOR_SCORE_SYSTEM = """You are scoring the net sentiment for a crypto sector.
Your score will be used as ONE input to a quantitative trading system.
Score conservatively — only strong, clear signals should produce extreme values.

Scoring rules:
- Score from -1.0 (extremely bearish) to +1.0 (extremely bullish)
- Score reflects expected NET price impact on this sector over the next 1-7 days
- Consider how news interacts with current market state:
  * Bullish news + already overleveraged long (high funding) = weaker signal
  * Bearish news + market already down significantly = potential reversal
  * High article velocity on same topic = stronger signal
  * Multiple independent bullish/bearish stories = stronger than a single story
- magnitude: low (<2% expected move), medium (2-8%), high (>8%)
- Your reasoning MUST reference at least one piece of market context evidence

Output JSON only:
{
  "sentiment": <float -1.0 to 1.0>,
  "magnitude": "<low|medium|high>",
  "confidence": <float 0 to 1>,
  "key_driver": "<the single most important factor driving the score>",
  "reasoning": "<2-3 sentences explaining score, referencing market context>"
}"""


def build_sector_score_prompt(summary: dict, evidence: dict) -> str:
    """Build the user prompt for sector-level scoring."""
    parts = [f"Sector: {summary['sector']}", "", "=== Market Context ==="]

    # Token prices
    prices = evidence.get("token_prices", [])
    if prices:
        price_strs = [f"{p['ticker']} ${p['price']:.2f} ({p['change_24h_pct']:+.1f}% 24h)" for p in prices]
        parts.append(f"Sector tokens: {', '.join(price_strs)}")

    parts.append(f"Article velocity: {summary['article_count']} articles in lookback window ({summary['velocity']})")
    parts.append(f"Previous sentiment score: {evidence.get('previous_sentiment', 0.0)}")

    # Optional signals
    if evidence.get("funding_rate") is not None:
        fr = evidence["funding_rate"]
        interp = "longs paying shorts" if fr > 0 else "shorts paying longs"
        parts.append(f"Funding rate: {fr:.4f}% ({interp})")
    if evidence.get("nupl") is not None:
        parts.append(f"NUPL: {evidence['nupl']:.3f}")
    if evidence.get("exchange_net_flow") is not None:
        parts.append(f"Exchange net flow: {evidence['exchange_net_flow']}")

    # Headlines
    headlines = summary.get("top_headlines", [])
    if headlines:
        parts.append(f"\n=== News Events ({summary['article_count']} articles) ===")
        for i, hl in enumerate(headlines, 1):
            catalyst_tag = " [CATALYST]" if hl.get("is_catalyst") else ""
            parts.append(f"{i}. [{hl['source']}, {hl['age_hours']:.0f}h ago]{catalyst_tag} {hl['headline']}")
            if hl.get("snippet"):
                parts.append(f"   -> {hl['snippet'][:200]}")

    parts.append(f"\nScore the net sentiment impact on the {summary['sector']} sector.")
    return "\n".join(parts)


def score_sector(summary: dict, evidence: dict) -> dict:
    """Score a sector's sentiment using ONE LLM call with evidence.

    Args:
        summary: Output of build_sector_summary().
        evidence: Output of gather_evidence().

    Returns:
        Dict with sentiment, magnitude, confidence, key_driver, reasoning.
    """
    # Skip LLM for empty sectors
    if summary.get("article_count", 0) == 0:
        return {
            "sentiment": 0.0, "magnitude": "low", "confidence": 0.0,
            "key_driver": "", "reasoning": "No articles in window.",
        }

    user_prompt = build_sector_score_prompt(summary, evidence)

    for attempt in range(2):
        try:
            content, usage, llm_label = call_llm(
                system_prompt=SECTOR_SCORE_SYSTEM,
                user_prompt=user_prompt,
                temperature=0.2,
                max_completion_tokens=500,
                fast=False,
            )

            cleaned = _strip_code_fences(content)
            data = json.loads(cleaned)

            sentiment = max(-1.0, min(1.0, float(data.get("sentiment", 0.0))))
            magnitude = str(data.get("magnitude", "low")).lower()
            if magnitude not in ("low", "medium", "high"):
                magnitude = "low"
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))

            logger.info(
                "score_sector [%s]: sentiment=%.2f magnitude=%s confidence=%.2f (via %s)",
                summary["sector"], sentiment, magnitude, confidence, llm_label,
            )

            return {
                "sentiment": sentiment,
                "magnitude": magnitude,
                "confidence": confidence,
                "key_driver": str(data.get("key_driver", "")),
                "reasoning": str(data.get("reasoning", "")),
            }

        except json.JSONDecodeError:
            if attempt == 0:
                logger.warning("score_sector JSON parse failed, retrying")
                continue
            logger.error("score_sector JSON parse failed after retry")
        except Exception:
            logger.exception("score_sector failed (attempt %d)", attempt + 1)
            if attempt == 0:
                continue

    return {
        "sentiment": 0.0, "magnitude": "low", "confidence": 0.0,
        "key_driver": "", "reasoning": "LLM scoring failed.",
    }
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ -q --tb=short`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add sentiment_score/prompter.py tests/test_sentiment_v2.py
git commit -m "feat: add score_sector() with evidence-based prompt"
```

---

### Task 6: Restructure Orchestrator tick()

**Files:**
- Modify: `pipeline/orchestrator.py`
- Modify: `tests/test_orchestrator.py`
- Modify: `tests/test_integration.py`

- [ ] **Step 1: Update orchestrator imports and state**

In `pipeline/orchestrator.py`:

Remove `score_article_batch` import. Add/update imports:
```python
from sentiment_score.models import SectorSignal, SectorSignalSet
from sentiment_score.processors import (
    build_sector_summary,
    gather_evidence,
    load_sector_config,
)
from sentiment_score.prompter import score_sector
```

Remove these imports (no longer used by orchestrator):
```python
# REMOVE: from sentiment_score.processors import compute_sector_signals
# REMOVE: from sentiment_score.prompter import score_article_batch
```

Add to `__init__`:
```python
self._previous_signals: dict[str, float] = {}
self._last_rss_fetch: datetime | None = None
```

- [ ] **Step 2: Rewrite tick() method**

Replace the tick body (lines 152-236) with the new v2 flow:

```python
def tick(self) -> SectorSignalSet:
    assert self._db is not None, "Pipeline not opened. Use 'with' or call open()."
    tick_start = time.monotonic()

    # 1. Fetch (scripts/fetch_news — sole fetching layer)
    # CryptoPanic every tick, RSS every 15 min
    rss_due = (
        self._last_rss_fetch is None
        or (datetime.now(tz=timezone.utc) - self._last_rss_fetch).total_seconds() >= 900
    )
    if rss_due:
        raw_dicts = fetch_all_sources()  # all sources
        self._last_rss_fetch = datetime.now(tz=timezone.utc)
    else:
        raw_dicts = fetch_all_sources(sources=["cryptopanic"])  # CryptoPanic only
    raw_dicts = raw_dedup(raw_dicts)
    raw_articles = [dict_to_article(d) for d in raw_dicts]

    # 2. Deduplicate against DB + pre-filter
    deduped = deduplicate(raw_articles, self._db)
    filtered = keyword_prefilter(deduped, self._sector_map)

    # 3. Store
    stored_count = store_articles(filtered, self._db)

    # 4. Classify all articles into sectors
    catalysts = [a for a in filtered if a.is_catalyst]
    fast_classified = 0
    llm_calls = 0

    # Fast path: catalysts get immediate classification
    for article in catalysts:
        classification = classify_article_fast(article)
        mark_processed(article.id, classification, self._db)
        fast_classified += 1
        llm_calls += 1

    # Batch path: classify remaining (sector only, no scoring)
    batch_classified = 0
    if self._batch_due():
        unprocessed = get_unprocessed_articles(self._db)
        for article in unprocessed:
            self._batch_limiter.wait()
            classification = classify_article_batch(article)
            mark_processed(article.id, classification, self._db)
            batch_classified += 1
            llm_calls += 1
        self._last_batch_time = datetime.now(tz=timezone.utc)

    # 5. Score each sector (ONE LLM call per sector with evidence)
    now = datetime.now(tz=timezone.utc)
    sectors: dict[str, Any] = {}

    for sector, cfg in self._sector_config.items():
        lookback_hours = float(cfg.get("lookback_hours", 24))

        # Build summary + gather evidence
        summary = build_sector_summary(self._db, sector, lookback_hours)
        evidence = gather_evidence(
            sector, self._sector_map, summary, self._previous_signals
        )

        # Score sector (skips LLM if 0 articles)
        score_result = score_sector(summary, evidence)
        if summary["article_count"] > 0:
            llm_calls += 1

        # Detect catalyst from fast-path articles
        catalyst_active = False
        catalyst_details = None
        catalyst_threshold = float(cfg.get("catalyst_threshold", 0.7))
        catalyst_cutoff = now - timedelta(minutes=30)

        # Check DB for recent high-magnitude articles
        catalyst_rows = self._db.fetchall(
            """SELECT id, llm_sentiment, llm_magnitude, timestamp
               FROM articles WHERE processed=1 AND llm_sector=?
               AND llm_magnitude='high' AND timestamp>=?""",
            (sector, catalyst_cutoff.isoformat()),
        )
        for row in catalyst_rows:
            if row["llm_sentiment"] is not None and abs(row["llm_sentiment"]) > catalyst_threshold:
                catalyst_active = True
                catalyst_details = {
                    "article_id": row["id"],
                    "sentiment": row["llm_sentiment"],
                    "timestamp": row["timestamp"],
                }
                break

        # Compute momentum
        prev_sent = self._previous_signals.get(sector, 0.0)
        momentum = score_result["sentiment"] - prev_sent

        sectors[sector] = SectorSignal(
            sector=sector,
            sentiment=score_result["sentiment"],
            momentum=momentum,
            catalyst_active=catalyst_active,
            catalyst_details=catalyst_details,
            article_count=summary["article_count"],
            confidence=score_result["confidence"],
            key_driver=score_result.get("key_driver", ""),
            reasoning=score_result.get("reasoning", ""),
        )

    signal_set = SectorSignalSet(
        timestamp=now,
        sectors=sectors,
        metadata={
            "sector_count": len(sectors),
            "total_articles": sum(s.article_count for s in sectors.values()),
        },
    )

    # Store previous signals for next tick
    self._previous_signals = {s: sig.sentiment for s, sig in sectors.items()}

    # Logging metadata
    tick_ms = (time.monotonic() - tick_start) * 1000
    signal_set.metadata.update({
        "articles_fetched": len(raw_articles),
        "articles_after_dedup": len(deduped),
        "articles_after_filter": len(filtered),
        "articles_stored": stored_count,
        "catalysts_detected": len(catalysts),
        "fast_path_classified": fast_classified,
        "batch_classified": batch_classified,
        "llm_calls": llm_calls,
        "processing_time_ms": round(tick_ms, 1),
    })

    strongest = max(sectors.values(), key=lambda s: abs(s.sentiment), default=None)
    logger.info(
        "tick: fetched=%d filtered=%d fast=%d batch=%d sector_scores=%d "
        "llm_calls=%d strongest=%s(%.2f) time=%.0fms",
        len(raw_articles), len(filtered), fast_classified, batch_classified,
        len([s for s in sectors.values() if s.article_count > 0]),
        llm_calls,
        strongest.sector if strongest else "none",
        strongest.sentiment if strongest else 0.0,
        tick_ms,
    )

    return signal_set
```

- [ ] **Step 3: Update orchestrator tests**

In `tests/test_orchestrator.py`, update all mocks. The key changes:
- Replace `score_article_batch` mocks with `score_sector` mocks
- Add mocks for `build_sector_summary` and `gather_evidence`
- Change metadata assertion from `batch_processed` to `batch_classified`
- Remove `score_article_batch` from mock imports

For every test that mocks `fetch_all_sources`, also mock:
```python
@patch("pipeline.orchestrator.score_sector", return_value={
    "sentiment": 0.0, "magnitude": "low", "confidence": 0.0,
    "key_driver": "", "reasoning": "",
})
@patch("pipeline.orchestrator.gather_evidence", return_value={
    "token_prices": [], "previous_sentiment": 0.0,
    "funding_rate": None, "nupl": None, "exchange_net_flow": None,
})
@patch("pipeline.orchestrator.build_sector_summary", return_value={
    "sector": "other", "article_count": 0, "velocity": "steady",
    "top_headlines": [], "mentioned_tickers": {}, "catalyst_count": 0,
})
```

For the batch test (`test_tick_batch_processes_non_catalysts`), remove the `score_article_batch` mock and instead check that `batch_classified` appears in metadata (not `batch_processed`).

For the catalyst test, update `score_sector` mock to return non-zero sentiment for the ai_compute sector.

- [ ] **Step 4: Update integration tests**

Same mock pattern in `tests/test_integration.py`:
- Remove all `score_article_batch` patches
- Add `score_sector`, `gather_evidence`, `build_sector_summary` patches
- For `test_full_pipeline_tick`: mock `score_sector` to return `{"sentiment": 0.85, ...}` for the ai_compute sector call
- Update metadata assertions: `batch_processed` -> `batch_classified`

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/ -q --tb=short`
Expected: All PASS (263 existing + new)

- [ ] **Step 6: Commit**

```bash
git add pipeline/orchestrator.py tests/test_orchestrator.py tests/test_integration.py
git commit -m "feat: restructure orchestrator to use per-sector evidence-based scoring"
```

---

### Task 7: Update run_pipeline.py Output + End-to-End Test

**Files:**
- Modify: `scripts/run_pipeline.py`
- No new tests (manual E2E verification)

- [ ] **Step 1: Update run_pipeline output to include new fields**

In `scripts/run_pipeline.py`, update the sector_signals output to include `key_driver` and `reasoning`:

```python
"sector_signals": {
    sector: {
        "sentiment": sig.sentiment,
        "momentum": sig.momentum,
        "catalyst_active": sig.catalyst_active,
        "catalyst_details": sig.catalyst_details,
        "article_count": sig.article_count,
        "confidence": sig.confidence,
        "key_driver": sig.key_driver,       # NEW
        "reasoning": sig.reasoning,          # NEW
    }
    for sector, sig in signal_set.sectors.items()
},
```

- [ ] **Step 2: Run all tests one final time**

Run: `python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 3: Run the pipeline E2E**

Run: `python -m scripts.run_pipeline`
Expected: Pipeline runs, shows sector scores with key_driver and reasoning in output.

- [ ] **Step 4: Commit everything**

```bash
git add scripts/run_pipeline.py
git commit -m "feat: add key_driver and reasoning to pipeline output"
```
