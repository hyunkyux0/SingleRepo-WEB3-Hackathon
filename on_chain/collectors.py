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

    REQUIRED_METRICS = {"FlowInExNtv", "FlowOutExNtv", "AdrActCnt", "CapMVRVCur"}
    # Subset of metrics for assets that lack exchange flow data
    FALLBACK_METRICS = {"AdrActCnt", "CapMVRVCur"}

    def __init__(self) -> None:
        self._coverage_cache: dict[str, dict] = {}  # asset -> {"cm_id": str, "has_flows": bool}

    def check_coverage(self, assets: list[str]) -> dict[str, dict]:
        """Runtime coverage check: query CoinMetrics catalog to discover
        which assets are available and which metrics they support.

        Returns dict mapping asset -> {"cm_id": str, "has_flows": bool, "metrics": set}.
        Assets not in CoinMetrics at all are excluded.
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
                if upper not in assets:
                    continue
                available = {m["metric"] for m in entry.get("metrics", [])}
                has_flows = "FlowInExNtv" in available and "FlowOutExNtv" in available
                has_mvrv = "CapMVRVCur" in available
                has_addr = "AdrActCnt" in available
                if not has_mvrv and not has_addr:
                    logger.info(f"CoinMetrics: {upper} has no usable metrics, skipping")
                    continue
                self._coverage_cache[upper] = {
                    "cm_id": cm_id,
                    "has_flows": has_flows,
                    "has_mvrv": has_mvrv,
                    "has_addr": has_addr,
                    "metrics": available,
                }
        except Exception as e:
            logger.warning(f"CoinMetrics coverage check failed: {e}")
        full = sum(1 for v in self._coverage_cache.values() if v["has_flows"])
        partial = len(self._coverage_cache) - full
        logger.info(f"CoinMetrics coverage: {full} full (with flows), {partial} partial, {len(assets) - len(self._coverage_cache)} unavailable")
        return self._coverage_cache

    def poll_interval_seconds(self) -> int:
        return 86400  # once daily

    def collect(self, assets: list[str]) -> list[dict]:
        rows = []
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        coverage = self.check_coverage(assets)
        for asset in assets:
            info = coverage.get(asset)
            if not info:
                logger.debug(f"CoinMetrics: no coverage for {asset}, skipping")
                continue

            cm_asset = info["cm_id"]
            # Only request metrics this asset actually has
            request_metrics = []
            if info["has_flows"]:
                request_metrics.extend(["FlowInExNtv", "FlowOutExNtv"])
            if info["has_mvrv"]:
                request_metrics.append("CapMVRVCur")
            if info["has_addr"]:
                request_metrics.append("AdrActCnt")

            if not request_metrics:
                continue

            try:
                resp = requests.get(
                    f"{self.BASE_URL}/timeseries/asset-metrics",
                    params={
                        "assets": cm_asset,
                        "metrics": ",".join(request_metrics),
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
    do not get whale tracking data -- see spec Section 11."""

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
        seen_hashes: set[str] = set()

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
