"""Aggregation and scoring functions for the sentiment signal pipeline.

Handles temporal decay computation, source/magnitude weighting,
per-sector signal aggregation, momentum calculation, catalyst detection,
and full sector signal set generation.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from sentiment_score.models import ScoredArticle, SectorSignal, SectorSignalSet
from utils.db import DataStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source weight mapping
# ---------------------------------------------------------------------------

_SOURCE_WEIGHTS: dict[str, float] = {
    "cryptopanic": 1.0,
    "rss_coindesk": 0.8,
    "rss_cointelegraph": 0.8,
    "rss_decrypt": 0.8,
    "rss_theblock": 0.8,
    "twitter": 0.6,
    "reddit": 0.4,
}

_DEFAULT_SOURCE_WEIGHT: float = 0.5

# ---------------------------------------------------------------------------
# Magnitude weight mapping
# ---------------------------------------------------------------------------

_MAGNITUDE_WEIGHTS: dict[str, float] = {
    "high": 3.0,
    "medium": 1.0,
    "low": 0.3,
}

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_sector_config(path: str) -> dict[str, Any]:
    """Load the per-sector configuration from *path*.

    Args:
        path: Filesystem path to ``config/sector_config.json``.

    Returns:
        Parsed JSON object mapping sector IDs to their parameter dicts.
    """
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Weight helpers
# ---------------------------------------------------------------------------


def get_source_weight(source: str) -> float:
    """Return the credibility weight for a news source.

    Known weights: cryptopanic=1.0, rss_*=0.8, twitter=0.6, reddit=0.4.
    Unknown sources receive a default weight of 0.5.

    Args:
        source: The source identifier (e.g. ``"cryptopanic"``, ``"twitter"``).

    Returns:
        A float weight in the range (0, 1].
    """
    # Check exact match first, then prefix match for rss sources
    if source in _SOURCE_WEIGHTS:
        return _SOURCE_WEIGHTS[source]
    if source.startswith("rss_"):
        return 0.8
    return _DEFAULT_SOURCE_WEIGHT


def get_magnitude_weight(magnitude: str) -> float:
    """Return the multiplier weight for a sentiment magnitude level.

    Weights: high=3.0, medium=1.0, low=0.3.

    Args:
        magnitude: One of ``"low"``, ``"medium"``, ``"high"``.

    Returns:
        A float multiplier.
    """
    return _MAGNITUDE_WEIGHTS.get(magnitude.lower(), 1.0)


def compute_decay(hours_elapsed: float, decay_lambda: float) -> float:
    """Compute temporal decay weight using exponential decay.

    Formula: ``exp(-decay_lambda * hours_elapsed)``

    Args:
        hours_elapsed: Number of hours since article publication.
        decay_lambda: Decay rate parameter (higher = faster decay).

    Returns:
        A float in (0, 1] representing the decay weight.
    """
    return math.exp(-decay_lambda * hours_elapsed)


# ---------------------------------------------------------------------------
# Article query & scoring
# ---------------------------------------------------------------------------


def build_scored_articles(
    db: DataStore, sector: str, lookback_hours: float
) -> list[ScoredArticle]:
    """Query processed articles for a sector and compute their weights.

    Retrieves all articles from the SQLite ``articles`` table that:
    - have ``processed = 1``
    - have ``llm_sector`` matching *sector*
    - have a ``timestamp`` within the last *lookback_hours*

    For each article, ``source_weight`` and ``decay_weight`` are computed
    based on the article's source and age.

    Args:
        db: An open :class:`DataStore`.
        sector: The sector ID to filter on (e.g. ``"defi"``).
        lookback_hours: How far back in time to look (in hours).

    Returns:
        A list of :class:`ScoredArticle` objects with weights populated.
    """
    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=lookback_hours)
    cutoff_iso = cutoff.isoformat()

    rows = db.fetchall(
        """
        SELECT id, timestamp, source, headline, llm_sector,
               llm_sentiment, llm_magnitude, llm_confidence
        FROM articles
        WHERE processed = 1
          AND llm_sector = ?
          AND timestamp >= ?
        ORDER BY timestamp DESC
        """,
        (sector, cutoff_iso),
    )

    scored: list[ScoredArticle] = []
    for row in rows:
        try:
            ts = datetime.fromisoformat(row["timestamp"])
            # Ensure timezone-aware for consistent subtraction
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            hours_elapsed = max(0.0, (now - ts).total_seconds() / 3600.0)

            sentiment = float(row["llm_sentiment"]) if row["llm_sentiment"] is not None else 0.0
            magnitude = str(row["llm_magnitude"] or "low").lower()
            if magnitude not in ("low", "medium", "high"):
                magnitude = "low"

            source = row["source"] or ""

            scored.append(
                ScoredArticle(
                    article_id=row["id"],
                    timestamp=ts,
                    primary_sector=sector,
                    sentiment=sentiment,
                    magnitude=magnitude,
                    source=source,
                    source_weight=get_source_weight(source),
                    decay_weight=compute_decay(hours_elapsed, _get_decay_lambda(sector)),
                )
            )
        except Exception:
            logger.exception("Failed to build ScoredArticle from row id=%s", row["id"])
            continue

    logger.debug(
        "build_scored_articles: sector=%s lookback=%.1fh -> %d articles",
        sector,
        lookback_hours,
        len(scored),
    )
    return scored


def _get_decay_lambda(sector: str) -> float:
    """Return a default decay lambda for a sector.

    These defaults match ``config/sector_config.json`` initial values and
    are used when the sector config is not passed to
    :func:`build_scored_articles`.

    Args:
        sector: The sector ID.

    Returns:
        The decay lambda value.
    """
    defaults: dict[str, float] = {
        "l1_infra": 0.1,
        "defi": 0.3,
        "ai_compute": 0.5,
        "meme": 2.0,
        "store_of_value": 0.1,
        "other": 0.5,
    }
    return defaults.get(sector, 0.5)


# ---------------------------------------------------------------------------
# Weighted sentiment computation (shared helper)
# ---------------------------------------------------------------------------


def _compute_weighted_sentiment(scored_articles: list[ScoredArticle]) -> float:
    """Compute the weighted average sentiment for a list of scored articles.

    Formula::

        weighted_sum = sum(sentiment_i * decay_weight_i * source_weight_i * magnitude_weight_i)
        total_weight = sum(decay_weight_i * source_weight_i * magnitude_weight_i)
        result = weighted_sum / total_weight

    Args:
        scored_articles: Articles with weights already computed.

    Returns:
        The weighted average sentiment, or 0.0 if no articles / zero weight.
    """
    if not scored_articles:
        return 0.0

    weighted_sum = 0.0
    total_weight = 0.0

    for art in scored_articles:
        mag_weight = get_magnitude_weight(art.magnitude)
        w = art.decay_weight * art.source_weight * mag_weight
        weighted_sum += art.sentiment * w
        total_weight += w

    if total_weight == 0.0:
        return 0.0

    return weighted_sum / total_weight


# ---------------------------------------------------------------------------
# Sector signal aggregation
# ---------------------------------------------------------------------------


def aggregate_sector_signal(
    scored_articles: list[ScoredArticle],
    sector: str,
    sector_config: dict[str, Any],
    db: DataStore,
) -> SectorSignal:
    """Compute the aggregated signal for one sector.

    Performs the following computations:

    1. **Weighted sentiment** — weighted average of article sentiments
       using decay, source, and magnitude weights.
    2. **Momentum** — difference between current window sentiment and
       the previous window sentiment (each window = ``lookback_hours``).
    3. **Confidence** — ``min(1.0, article_count / 10) * mean(llm_confidence)``.
    4. **Catalyst detection** — any article with ``magnitude=high`` AND
       ``|sentiment| > catalyst_threshold`` AND within last 30 minutes.

    Args:
        scored_articles: Pre-built scored articles for the current window.
        sector: The sector ID.
        sector_config: The full sector config dict (all sectors).
        db: An open :class:`DataStore` for querying the previous window.

    Returns:
        A :class:`SectorSignal` with all fields populated.
    """
    cfg = sector_config.get(sector, {})
    lookback_hours = float(cfg.get("lookback_hours", 24))
    catalyst_threshold = float(cfg.get("catalyst_threshold", 0.7))

    # -- Weighted sentiment (current window) --------------------------------
    sector_sentiment = _compute_weighted_sentiment(scored_articles)

    # -- Momentum -----------------------------------------------------------
    # Query previous window: [now - 2*lookback, now - lookback]
    now = datetime.now(tz=timezone.utc)
    prev_start = now - timedelta(hours=2 * lookback_hours)
    prev_end = now - timedelta(hours=lookback_hours)
    prev_start_iso = prev_start.isoformat()
    prev_end_iso = prev_end.isoformat()

    prev_rows = db.fetchall(
        """
        SELECT id, timestamp, source, llm_sentiment, llm_magnitude
        FROM articles
        WHERE processed = 1
          AND llm_sector = ?
          AND timestamp >= ?
          AND timestamp < ?
        ORDER BY timestamp DESC
        """,
        (sector, prev_start_iso, prev_end_iso),
    )

    prev_scored: list[ScoredArticle] = []
    for row in prev_rows:
        try:
            ts = datetime.fromisoformat(row["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            hours_elapsed = max(0.0, (now - ts).total_seconds() / 3600.0)
            sentiment = float(row["llm_sentiment"]) if row["llm_sentiment"] is not None else 0.0
            magnitude = str(row["llm_magnitude"] or "low").lower()
            if magnitude not in ("low", "medium", "high"):
                magnitude = "low"
            source = row["source"] or ""

            prev_scored.append(
                ScoredArticle(
                    article_id=row["id"],
                    timestamp=ts,
                    primary_sector=sector,
                    sentiment=sentiment,
                    magnitude=magnitude,
                    source=source,
                    source_weight=get_source_weight(source),
                    decay_weight=compute_decay(hours_elapsed, _get_decay_lambda(sector)),
                )
            )
        except Exception:
            logger.exception("Failed to parse previous-window article row id=%s", row["id"])
            continue

    prev_sentiment = _compute_weighted_sentiment(prev_scored)

    # Momentum = current sentiment - previous sentiment
    # If only one window has articles, treat the other as 0
    momentum = sector_sentiment - prev_sentiment

    # -- Confidence ---------------------------------------------------------
    article_count = len(scored_articles)
    if article_count > 0:
        # Fetch llm_confidence values for the current-window articles
        article_ids = [art.article_id for art in scored_articles]
        placeholders = ", ".join("?" for _ in article_ids)
        conf_rows = db.fetchall(
            f"SELECT llm_confidence FROM articles WHERE id IN ({placeholders})",
            tuple(article_ids),
        )
        confidences = [
            float(r["llm_confidence"])
            for r in conf_rows
            if r["llm_confidence"] is not None
        ]
        mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        sector_confidence = min(1.0, article_count / 10.0) * mean_confidence
    else:
        sector_confidence = 0.0

    # -- Catalyst detection -------------------------------------------------
    catalyst_active = False
    catalyst_details: dict[str, Any] | None = None
    catalyst_cutoff = now - timedelta(minutes=30)

    for art in scored_articles:
        ts = art.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if (
            art.magnitude == "high"
            and abs(art.sentiment) > catalyst_threshold
            and ts >= catalyst_cutoff
        ):
            catalyst_active = True
            catalyst_details = {
                "article_id": art.article_id,
                "sentiment": art.sentiment,
                "magnitude": art.magnitude,
                "source": art.source,
                "timestamp": ts.isoformat(),
            }
            break  # one catalyst is enough to activate

    signal = SectorSignal(
        sector=sector,
        sentiment=sector_sentiment,
        momentum=momentum,
        catalyst_active=catalyst_active,
        catalyst_details=catalyst_details,
        article_count=article_count,
        confidence=sector_confidence,
    )

    logger.info(
        "aggregate_sector_signal: sector=%s sentiment=%.3f momentum=%.3f "
        "catalyst=%s articles=%d confidence=%.3f",
        sector,
        sector_sentiment,
        momentum,
        catalyst_active,
        article_count,
        sector_confidence,
    )

    return signal


# ---------------------------------------------------------------------------
# Full signal set computation
# ---------------------------------------------------------------------------


def compute_sector_signals(
    db: DataStore, sector_config: dict[str, Any]
) -> SectorSignalSet:
    """Compute signals for all sectors and return a complete signal set.

    Iterates over all 6 canonical sectors defined in *sector_config*,
    builds scored articles for each, and aggregates them into per-sector
    signals.

    Args:
        db: An open :class:`DataStore`.
        sector_config: Parsed ``config/sector_config.json``.

    Returns:
        A :class:`SectorSignalSet` with the current timestamp and a
        signal for every sector.
    """
    now = datetime.now(tz=timezone.utc)
    sectors: dict[str, SectorSignal] = {}

    for sector, cfg in sector_config.items():
        lookback_hours = float(cfg.get("lookback_hours", 24))

        scored_articles = build_scored_articles(db, sector, lookback_hours)
        signal = aggregate_sector_signal(scored_articles, sector, sector_config, db)
        sectors[sector] = signal

    signal_set = SectorSignalSet(
        timestamp=now,
        sectors=sectors,
        metadata={
            "sector_count": len(sectors),
            "total_articles": sum(s.article_count for s in sectors.values()),
        },
    )

    logger.info(
        "compute_sector_signals: %d sectors, %d total articles",
        len(sectors),
        signal_set.metadata["total_articles"],
    )

    return signal_set


# ---------------------------------------------------------------------------
# v2: Sector summary (deterministic)
# ---------------------------------------------------------------------------


def build_sector_summary(
    db: DataStore, sector: str, lookback_hours: float
) -> dict[str, Any]:
    """Build a deterministic summary of articles for one sector.

    Queries the DB for classified articles in the given sector within
    the lookback window. Returns headline list, article velocity,
    ticker frequency, and catalyst count.

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

    # Current window: top 10 by relevance
    current_rows = db.fetchall(
        """SELECT headline, body_snippet, source, mentioned_tickers,
                  relevance_score, is_catalyst, timestamp
           FROM articles
           WHERE processed = 1 AND llm_sector = ? AND timestamp >= ?
           ORDER BY relevance_score DESC LIMIT 10""",
        (sector, cutoff),
    )

    # Counts for velocity
    current_count_row = db.fetchone(
        "SELECT COUNT(*) as cnt FROM articles "
        "WHERE processed=1 AND llm_sector=? AND timestamp>=?",
        (sector, cutoff),
    )
    current_count = current_count_row["cnt"] if current_count_row else 0

    prev_count_row = db.fetchone(
        "SELECT COUNT(*) as cnt FROM articles "
        "WHERE processed=1 AND llm_sector=? AND timestamp>=? AND timestamp<?",
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

    # Build headlines + aggregate tickers
    top_headlines: list[dict[str, Any]] = []
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


# ---------------------------------------------------------------------------
# v2: Price fetching
# ---------------------------------------------------------------------------

# Map common tickers to Kraken pair format
_KRAKEN_PAIRS: dict[str, str] = {
    "BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD",
    "XRP": "XRPUSD", "ADA": "ADAUSD", "DOT": "DOTUSD",
    "AVAX": "AVAXUSD", "LINK": "LINKUSD", "UNI": "UNIUSD",
    "AAVE": "AAVEUSD", "DOGE": "DOGEUSD", "SHIB": "SHIBUSD",
    "FET": "FETUSD", "NEAR": "NEARUSD", "SUI": "SUIUSD",
    "APT": "APTUSD", "FIL": "FILUSD", "LTC": "LTCUSD",
}


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

    pairs = []
    ticker_for_pair: dict[str, str] = {}
    for t in tickers[:5]:
        pair = _KRAKEN_PAIRS.get(t, f"{t}USD")
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

    results: list[dict[str, Any]] = []
    for pair_key, ticker in ticker_for_pair.items():
        pair_data = None
        for key in data.get("result", {}):
            if pair_key in key or ticker in key:
                pair_data = data["result"][key]
                break
        if pair_data is None:
            continue

        try:
            price = float(pair_data["c"][0])
            open_price = float(pair_data["o"])
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


# ---------------------------------------------------------------------------
# v2: Evidence gathering
# ---------------------------------------------------------------------------


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

    token_prices = fetch_current_prices(sector_tickers)

    prev_sent = 0.0
    if previous_signals and sector in previous_signals:
        prev_sent = previous_signals[sector]

    return {
        "token_prices": token_prices,
        "previous_sentiment": prev_sent,
        "funding_rate": None,       # populated by derivatives module when available
        "nupl": None,               # populated by on_chain module when available
        "exchange_net_flow": None,   # populated by on_chain module when available
    }
