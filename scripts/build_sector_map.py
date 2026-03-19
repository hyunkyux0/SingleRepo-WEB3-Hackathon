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
