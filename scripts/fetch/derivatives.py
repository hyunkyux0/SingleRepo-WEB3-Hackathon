# scripts/fetch/derivatives.py
"""Fetch derivatives data (funding rates, OI) from Binance and Bybit.

Usage:
    python -m scripts.fetch.derivatives
    python -m scripts.fetch.derivatives --assets BTC ETH SOL
    python -m scripts.fetch.derivatives --from-db  # use active assets from DB
    python -m scripts.fetch.derivatives --dry-run

Output: data/derivatives/<timestamp>_<exchange>.json
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

from derivatives.collectors import BinanceCollector, BybitCollector
from utils.db import DataStore

OUTPUT_DIR = Path("data/derivatives")
DEFAULT_ASSETS = ["BTC", "ETH", "SOL"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch derivatives data")
    parser.add_argument("--assets", nargs="+", default=None, help="Assets to fetch (e.g. BTC ETH SOL)")
    parser.add_argument("--from-db", action="store_true", help="Use active assets from DB registry")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = parser.parse_args(argv)

    # Determine asset list
    if args.from_db:
        with DataStore() as db:
            assets = db.get_active_assets()
        if not assets:
            print("No active assets in DB. Run 'python -m scripts.fetch.discover' first.")
            return
    elif args.assets:
        assets = args.assets
    else:
        assets = DEFAULT_ASSETS

    print(f"Fetching derivatives for {len(assets)} assets: {assets[:5]}{'...' if len(assets) > 5 else ''}")

    ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Binance
    print("\n--- Binance ---")
    binance = BinanceCollector()
    binance_funding = binance.collect_funding_rates(assets)
    binance_oi = binance.collect_open_interest(assets)
    print(f"  Funding rates: {len(binance_funding)} rows")
    print(f"  Open interest: {len(binance_oi)} rows")

    binance_snapshot = {
        "timestamp": ts, "exchange": "binance", "assets": assets,
        "funding_rates": binance_funding, "open_interest": binance_oi,
    }
    binance_path = OUTPUT_DIR / f"{ts}_binance.json"
    binance_path.write_text(json.dumps(binance_snapshot, indent=2, default=str))
    print(f"  Saved: {binance_path}")

    # Bybit
    print("\n--- Bybit ---")
    bybit = BybitCollector()
    bybit_funding = bybit.collect_funding_rates(assets)
    bybit_oi = bybit.collect_open_interest(assets)
    print(f"  Funding rates: {len(bybit_funding)} rows")
    print(f"  Open interest: {len(bybit_oi)} rows")

    bybit_snapshot = {
        "timestamp": ts, "exchange": "bybit", "assets": assets,
        "funding_rates": bybit_funding, "open_interest": bybit_oi,
    }
    bybit_path = OUTPUT_DIR / f"{ts}_bybit.json"
    bybit_path.write_text(json.dumps(bybit_snapshot, indent=2, default=str))
    print(f"  Saved: {bybit_path}")

    # Write to DB
    if not args.dry_run:
        with DataStore() as db:
            db.save_funding_rates(binance_funding + bybit_funding)
            db.save_open_interest(binance_oi + bybit_oi)
        print(f"\nSaved to DB: {len(binance_funding) + len(bybit_funding)} funding, {len(binance_oi) + len(bybit_oi)} OI")
    else:
        print("\n(dry-run — DB not updated)")

    # Summary table
    print(f"\n{'Asset':>8s} {'Bin Fund':>10s} {'Byb Fund':>10s} {'Bin OI':>14s} {'Byb OI':>14s}")
    print("-" * 60)
    for asset in assets:
        bf = next((r["rate"] for r in binance_funding if r["asset"] == asset), None)
        yf = next((r["rate"] for r in bybit_funding if r["asset"] == asset), None)
        bo = next((r["oi_value"] for r in binance_oi if r["asset"] == asset), None)
        yo = next((r["oi_value"] for r in bybit_oi if r["asset"] == asset), None)
        print(f"{asset:>8s} {bf if bf is not None else 'N/A':>10} {yf if yf is not None else 'N/A':>10} {bo if bo is not None else 'N/A':>14} {yo if yo is not None else 'N/A':>14}")


if __name__ == "__main__":
    main()
