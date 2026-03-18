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
