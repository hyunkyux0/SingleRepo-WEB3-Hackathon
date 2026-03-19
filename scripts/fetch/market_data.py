# scripts/fetch/market_data.py
"""Fetch OHLCV market data from Binance for all universe assets.

Builds incrementally: per-asset JSON files are appended (deduplicated by
timestamp), and the DB uses INSERT OR REPLACE so re-runs are safe.

Usage:
    python -m scripts.fetch.market_data                          # latest 100 candles, all assets
    python -m scripts.fetch.market_data --assets BTC ETH SOL
    python -m scripts.fetch.market_data --interval 1h --limit 500
    python -m scripts.fetch.market_data --full-history            # paginate back as far as Binance allows
    python -m scripts.fetch.market_data --full-history --interval 1d  # daily history (~1000 days)
    python -m scripts.fetch.market_data --from-db

Output: data/market_data/<asset>_<interval>.json (per-asset, incremental)
        data/market_data/<timestamp>_summary.json
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


def _to_binance_spot(asset: str) -> str:
    return f"{asset}USDT"


def _parse_candles(asset: str, raw: list, interval: str) -> list[dict]:
    """Convert Binance kline response to our dict format."""
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


def fetch_klines(asset: str, interval: str = "5m", limit: int = 100,
                 start_time: int | None = None) -> list[dict]:
    """Fetch OHLCV candles from Binance spot API.
    Free, no auth, 1200 weight/min rate limit.
    """
    symbol = _to_binance_spot(asset)
    params = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
    if start_time is not None:
        params["startTime"] = start_time
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return _parse_candles(asset, resp.json(), interval)
    except Exception as e:
        logger.warning(f"Binance klines failed for {asset}: {e}")
        return []


def fetch_full_history(asset: str, interval: str = "5m") -> list[dict]:
    """Paginate backwards to fetch all available history for an asset.
    Binance returns max 1000 candles per request.
    """
    all_rows = []
    end_time = None  # start from most recent

    while True:
        params = {"symbol": _to_binance_spot(asset), "interval": interval, "limit": 1000}
        if end_time is not None:
            params["endTime"] = end_time

        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            logger.warning(f"Binance history failed for {asset}: {e}")
            break

        if not raw:
            break

        rows = _parse_candles(asset, raw, interval)
        all_rows = rows + all_rows  # prepend older data

        # Next page: go before the earliest candle we got
        earliest_ts = raw[0][0]
        end_time = earliest_ts - 1

        if len(raw) < 1000:
            break  # no more data available

        time.sleep(0.2)  # rate limit courtesy

    return all_rows


def _load_existing(path: Path) -> list[dict]:
    """Load existing per-asset JSON file if it exists."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return []


def _merge_incremental(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge new candles into existing data, deduplicated by timestamp."""
    seen = {r["timestamp"] for r in existing}
    merged = list(existing)
    added = 0
    for row in new:
        if row["timestamp"] not in seen:
            merged.append(row)
            seen.add(row["timestamp"])
            added += 1
    merged.sort(key=lambda r: r["timestamp"])
    return merged, added


def load_universe(path: str = "config/asset_universe.json") -> list[str]:
    with open(path) as f:
        pairs = json.load(f)
    return [p.split("/")[0] for p in pairs]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch OHLCV market data from Binance")
    parser.add_argument("--assets", nargs="+", default=None)
    parser.add_argument("--from-db", action="store_true", help="Use active assets from DB")
    parser.add_argument("--interval", default="5m", help="Candle interval (default: 5m)")
    parser.add_argument("--limit", type=int, default=100, help="Number of candles per request (default: 100)")
    parser.add_argument("--full-history", action="store_true", help="Paginate to fetch all available history")
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

    mode = "full history" if args.full_history else f"latest {args.limit}"
    print(f"Fetching {args.interval} OHLCV for {len(assets)} assets ({mode})...")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")

    all_new_rows = []
    success = 0
    failed = []
    total_added = 0

    for i, asset in enumerate(assets):
        if args.full_history:
            rows = fetch_full_history(asset, interval=args.interval)
        else:
            rows = fetch_klines(asset, interval=args.interval, limit=args.limit)

        if rows:
            # Incremental merge with existing file
            asset_path = OUTPUT_DIR / f"{asset}_{args.interval}.json"
            existing = _load_existing(asset_path)
            merged, added = _merge_incremental(existing, rows)
            asset_path.write_text(json.dumps(merged, indent=2))

            all_new_rows.extend(rows)
            success += 1
            total_added += added

            first_ts = merged[0]["timestamp"][:10]
            last_ts = merged[-1]["timestamp"][:10]
            print(f"  {asset:>8s}: {len(merged)} total candles ({added} new), {first_ts} to {last_ts}, close=${rows[-1]['close']:.4f}")
        else:
            failed.append(asset)
            print(f"  {asset:>8s}: FAILED")

        # Rate limit: ~10 req/sec for normal, slower for full history (handled inside fetch_full_history)
        if not args.full_history and (i + 1) % 10 == 0:
            time.sleep(1)

    # Save summary
    summary = {
        "timestamp": ts,
        "interval": args.interval,
        "mode": "full_history" if args.full_history else f"latest_{args.limit}",
        "success": success,
        "failed": failed,
        "total_new_candles": total_added,
        "assets": [a for a in assets if a not in failed],
    }
    summary_path = OUTPUT_DIR / f"{ts}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary saved: {summary_path}")

    # Write to DB (INSERT OR REPLACE handles dedup)
    if not args.dry_run and all_new_rows:
        with DataStore() as db:
            db.save_ohlc(all_new_rows)
        print(f"Saved to DB: {len(all_new_rows)} candles ({total_added} new)")
    elif not all_new_rows:
        print("No new data to save")
    else:
        print("(dry-run — DB not updated)")

    print(f"\n{'='*50}")
    print(f"Success: {success}/{len(assets)} | Failed: {len(failed)} | New candles: {total_added}")
    if failed:
        print(f"Failed: {failed}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
