# scripts/fetch/onchain.py
"""Fetch on-chain data from CoinMetrics Community API.

Usage:
    python -m scripts.fetch.onchain
    python -m scripts.fetch.onchain --assets BTC ETH
    python -m scripts.fetch.onchain --dry-run

Output: data/onchain/<date>_coinmetrics.json
"""
import argparse
import json
from datetime import date, datetime
from pathlib import Path

from on_chain.collectors import CoinMetricsCollector
from utils.db import DataStore

OUTPUT_DIR = Path("data/onchain")
DEFAULT_ASSETS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "UNI", "AAVE", "DOGE", "ADA", "DOT"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch on-chain data from CoinMetrics")
    parser.add_argument("--assets", nargs="+", default=None)
    parser.add_argument("--from-db", action="store_true")
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
        assets = DEFAULT_ASSETS

    print(f"Fetching CoinMetrics data for {len(assets)} assets...")

    collector = CoinMetricsCollector()

    # Coverage check
    print("\n--- Coverage Check ---")
    coverage = collector.check_coverage(assets)
    covered = [a for a in assets if a in coverage]
    uncovered = [a for a in assets if a not in coverage]
    print(f"  Covered: {len(covered)}/{len(assets)} — {covered}")
    if uncovered:
        print(f"  NOT covered: {uncovered}")

    # Fetch data
    print("\n--- Fetching Daily Metrics ---")
    rows = collector.collect(assets)
    print(f"  Got data for {len(rows)} assets")

    # Save snapshot
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    snapshot = {
        "date": today,
        "assets_requested": assets,
        "assets_covered": covered,
        "assets_uncovered": uncovered,
        "data": rows,
    }
    out_path = OUTPUT_DIR / f"{today}_coinmetrics.json"
    out_path.write_text(json.dumps(snapshot, indent=2, default=str))
    print(f"  Saved: {out_path}")

    # Write to DB
    if not args.dry_run and rows:
        with DataStore() as db:
            db.save_on_chain_daily(rows)
        print(f"  Saved to DB: {len(rows)} rows")
    elif not rows:
        print("  No data returned (check CoinMetrics coverage)")
    else:
        print("  (dry-run — DB not updated)")

    # Summary table
    print(f"\n{'Asset':>6s} {'Inflow':>12s} {'Outflow':>12s} {'Netflow':>12s} {'MVRV':>8s} {'NUPL':>8s} {'Active Addr':>12s}")
    print("-" * 74)
    for r in rows:
        print(f"{r['asset']:>6s} {r['exchange_inflow_native']:>12.2f} {r['exchange_outflow_native']:>12.2f} "
              f"{r['exchange_netflow_native']:>12.2f} {r['mvrv']:>8.3f} {r['nupl_computed']:>8.3f} {r['active_addresses']:>12d}")


if __name__ == "__main__":
    main()
