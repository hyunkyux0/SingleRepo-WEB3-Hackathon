# scripts/fetch/market_data.py
"""Fetch OHLCV market data from Binance for all universe assets.

Usage:
    python -m scripts.fetch.market_data
    python -m scripts.fetch.market_data --assets BTC ETH SOL
    python -m scripts.fetch.market_data --interval 1h --limit 100
    python -m scripts.fetch.market_data --from-db

Output: data/market_data/<asset>_<interval>.json (per-asset snapshots)
        data/market_data/<timestamp>_summary.json (all assets)
"""
import argparse
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import requests

from utils.db import DataStore

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("data/market_data")

# Map our asset symbols to Binance spot symbols
def _to_binance_spot(asset: str) -> str:
    return f"{asset}USDT"


def fetch_klines(asset: str, interval: str = "5m", limit: int = 100) -> list[dict]:
    """Fetch OHLCV candles from Binance spot API.
    Free, no auth, 1200 weight/min rate limit.
    """
    symbol = _to_binance_spot(asset)
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
        rows = []
        for candle in raw:
            rows.append({
                "asset": asset,
                "timestamp": datetime.utcfromtimestamp(candle[0] / 1000).isoformat(),
                "interval": interval,
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
                "vwap": None,
            })
        return rows
    except Exception as e:
        logger.warning(f"Binance klines failed for {asset}: {e}")
        return []


def load_universe(path: str = "config/asset_universe.json") -> list[str]:
    with open(path) as f:
        pairs = json.load(f)
    return [p.split("/")[0] for p in pairs]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch OHLCV market data from Binance")
    parser.add_argument("--assets", nargs="+", default=None)
    parser.add_argument("--from-db", action="store_true", help="Use active assets from DB")
    parser.add_argument("--interval", default="5m", help="Candle interval (default: 5m)")
    parser.add_argument("--limit", type=int, default=100, help="Number of candles (default: 100)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.from_db:
        with DataStore() as db:
            assets = db.get_active_assets()
        if not assets:
            print("No active assets in DB. Run 'python -m scripts.fetch.discover' first.")
            return
    elif args.assets:
        assets = args.assets
    else:
        assets = load_universe()

    print(f"Fetching {args.interval} OHLCV for {len(assets)} assets ({args.limit} candles each)...")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")

    all_data = {}
    success = 0
    failed = []

    for i, asset in enumerate(assets):
        rows = fetch_klines(asset, interval=args.interval, limit=args.limit)
        if rows:
            all_data[asset] = rows
            success += 1
            # Save per-asset file
            asset_path = OUTPUT_DIR / f"{asset}_{args.interval}.json"
            asset_path.write_text(json.dumps(rows, indent=2))

            latest = rows[-1]
            prev = rows[-2] if len(rows) >= 2 else rows[-1]
            pct = (latest["close"] - prev["close"]) / prev["close"] * 100 if prev["close"] else 0
            print(f"  {asset:>8s}: {len(rows)} candles, close=${latest['close']:.4f}, chg={pct:+.2f}%")
        else:
            failed.append(asset)
            print(f"  {asset:>8s}: FAILED")

        # Rate limit: ~10 req/sec to stay safe
        if (i + 1) % 10 == 0:
            time.sleep(1)

    # Save summary
    summary = {
        "timestamp": ts,
        "interval": args.interval,
        "limit": args.limit,
        "success": success,
        "failed": failed,
        "assets": list(all_data.keys()),
    }
    summary_path = OUTPUT_DIR / f"{ts}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary saved: {summary_path}")

    # Write to DB
    if not args.dry_run:
        all_rows = []
        for rows in all_data.values():
            all_rows.extend(rows)
        if all_rows:
            with DataStore() as db:
                db.save_ohlc(all_rows)
            print(f"Saved to DB: {len(all_rows)} candles")
    else:
        print("(dry-run — DB not updated)")

    print(f"\n{'='*50}")
    print(f"Success: {success}/{len(assets)} | Failed: {len(failed)}")
    if failed:
        print(f"Failed: {failed}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
