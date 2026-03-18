"""Data collectors for derivatives exchanges.

Each collector implements BaseCollector contract (spec Section 5):
  collect(assets) -> list[dict]
  poll_interval_seconds() -> int

Collectors never write to DB directly -- the orchestrator
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
