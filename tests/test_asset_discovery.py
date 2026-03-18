"""Tests for scripts/discover_assets.py — asset discovery with mocked HTTP."""

import pytest
import json
from unittest.mock import patch, MagicMock

from scripts.discover_assets import discover_active_assets


def _binance_exchange_info(perp_bases):
    """Build a mock Binance exchangeInfo response with given base assets."""
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "symbols": [
            {
                "symbol": f"{base}USDT",
                "status": "TRADING",
                "contractType": "PERPETUAL",
            }
            for base in perp_bases
        ]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _binance_oi(symbol, oi_value):
    """Build a mock Binance openInterest response."""
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "symbol": symbol,
        "openInterest": str(oi_value),
        "time": 1710000000000,
    }
    resp.raise_for_status = MagicMock()
    return resp


# ── Test: assets not in universe are excluded ─────────────────────────────


@patch("scripts.discover_assets.requests.get")
def test_assets_not_in_universe_are_excluded(mock_get):
    """Binance may list perps for tokens not in our universe — those should
    not appear in the result at all (the function iterates over universe,
    not over Binance listings)."""
    universe = ["BTC/USD", "ETH/USD"]

    # Binance returns BTC, ETH, *and* DOGE perps — but DOGE is not in universe
    exchange_info = _binance_exchange_info(["BTC", "ETH", "DOGE"])
    btc_oi = _binance_oi("BTCUSDT", 50000)
    eth_oi = _binance_oi("ETHUSDT", 30000)

    mock_get.side_effect = [exchange_info, btc_oi, eth_oi]

    result = discover_active_assets(universe, max_assets=40)
    result_assets = [r["asset"] for r in result]

    assert "BTC" in result_assets
    assert "ETH" in result_assets
    # DOGE is on Binance but not in our universe — must not appear
    assert "DOGE" not in result_assets


# ── Test: assets without perps get excluded_reason ────────────────────────


@patch("scripts.discover_assets.requests.get")
def test_assets_without_perps_get_excluded_reason(mock_get):
    """Assets in the universe that have no Binance perpetual contract
    should appear in results with has_perps=False and a non-null
    excluded_reason."""
    universe = ["BTC/USD", "ETH/USD", "SOMI/USD"]

    # Binance only lists BTC and ETH perps — SOMI has none
    exchange_info = _binance_exchange_info(["BTC", "ETH"])
    btc_oi = _binance_oi("BTCUSDT", 50000)
    eth_oi = _binance_oi("ETHUSDT", 30000)

    mock_get.side_effect = [exchange_info, btc_oi, eth_oi]

    result = discover_active_assets(universe, max_assets=40)

    somi = [r for r in result if r["asset"] == "SOMI"]
    assert len(somi) == 1
    assert somi[0]["has_perps"] is False
    assert somi[0]["excluded_reason"] is not None
    assert "SOMI" in somi[0]["excluded_reason"]

    # BTC and ETH should have perps and no exclusion
    btc = [r for r in result if r["asset"] == "BTC"][0]
    assert btc["has_perps"] is True
    assert btc["excluded_reason"] is None


# ── Test: OI ranking works ────────────────────────────────────────────────


@patch("scripts.discover_assets.requests.get")
def test_oi_ranking(mock_get):
    """Assets with perps should be ranked by open interest descending:
    highest OI gets rank 1."""
    universe = ["BTC/USD", "ETH/USD", "SOL/USD"]

    exchange_info = _binance_exchange_info(["BTC", "ETH", "SOL"])
    # OI: SOL=80000 > BTC=50000 > ETH=30000
    btc_oi = _binance_oi("BTCUSDT", 50000)
    eth_oi = _binance_oi("ETHUSDT", 30000)
    sol_oi = _binance_oi("SOLUSDT", 80000)

    mock_get.side_effect = [exchange_info, btc_oi, eth_oi, sol_oi]

    result = discover_active_assets(universe, max_assets=40)

    active = {r["asset"]: r for r in result if r["has_perps"]}
    assert active["SOL"]["oi_rank"] == 1
    assert active["BTC"]["oi_rank"] == 2
    assert active["ETH"]["oi_rank"] == 3


# ── Test: max_assets cutoff ───────────────────────────────────────────────


@patch("scripts.discover_assets.requests.get")
def test_max_assets_cutoff(mock_get):
    """Assets with perps beyond the max_assets cutoff should have
    excluded_reason set. Assets within the cutoff should not."""
    universe = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD"]

    exchange_info = _binance_exchange_info(["BTC", "ETH", "SOL", "DOGE"])
    btc_oi = _binance_oi("BTCUSDT", 40000)
    eth_oi = _binance_oi("ETHUSDT", 30000)
    sol_oi = _binance_oi("SOLUSDT", 20000)
    doge_oi = _binance_oi("DOGEUSDT", 10000)

    mock_get.side_effect = [exchange_info, btc_oi, eth_oi, sol_oi, doge_oi]

    # Only allow top 2 assets
    result = discover_active_assets(universe, max_assets=2)

    active = {r["asset"]: r for r in result if r["has_perps"]}

    # Top 2 by OI (BTC=40k, ETH=30k) should have no exclusion
    assert active["BTC"]["excluded_reason"] is None
    assert active["BTC"]["oi_rank"] == 1
    assert active["ETH"]["excluded_reason"] is None
    assert active["ETH"]["oi_rank"] == 2

    # Rank 3 and 4 exceed max_assets=2 -> excluded
    assert active["SOL"]["excluded_reason"] is not None
    assert "max_assets" in active["SOL"]["excluded_reason"]
    assert active["SOL"]["oi_rank"] == 3

    assert active["DOGE"]["excluded_reason"] is not None
    assert "max_assets" in active["DOGE"]["excluded_reason"]
    assert active["DOGE"]["oi_rank"] == 4
