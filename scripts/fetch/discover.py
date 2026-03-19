# scripts/fetch/discover.py
"""Discover which assets have perpetual futures and rank by OI.

Usage:
    python -m scripts.fetch.discover
    python -m scripts.fetch.discover --max-assets 10
    python -m scripts.fetch.discover --dry-run  # don't write to DB

Output: data/asset_registry/<timestamp>_active.json
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from scripts.discover_assets import discover_active_assets
from utils.db import DataStore

OUTPUT_DIR = Path("data/asset_registry")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Discover assets with perpetual futures")
    parser.add_argument("--max-assets", type=int, default=40)
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = parser.parse_args(argv)

    print(f"Discovering assets (max={args.max_assets})...")
    results = discover_active_assets(max_assets=args.max_assets)

    active = [r for r in results if r["has_perps"] and not r.get("excluded_reason")]
    excluded = [r for r in results if r.get("excluded_reason")]

    # Save snapshot
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    snapshot = {
        "timestamp": ts,
        "max_assets": args.max_assets,
        "active_count": len(active),
        "excluded_count": len(excluded),
        "active": active,
        "excluded": excluded,
    }
    out_path = OUTPUT_DIR / f"{ts}_active.json"
    out_path.write_text(json.dumps(snapshot, indent=2, default=str))
    print(f"Snapshot saved: {out_path}")

    # Write to DB
    if not args.dry_run:
        with DataStore() as db:
            db.save_asset_registry(results)
        print(f"Saved to DB: {len(results)} entries")
    else:
        print("(dry-run — DB not updated)")

    # Summary
    print(f"\n{'='*50}")
    print(f"Active: {len(active)} | Excluded: {len(excluded)}")
    print(f"{'='*50}")
    for r in active[:10]:
        print(f"  {r['asset']:8s} rank={r['oi_rank']}")
    if len(active) > 10:
        print(f"  ... and {len(active) - 10} more")
    if excluded[:3]:
        print(f"\nExcluded (first 3):")
        for r in excluded[:3]:
            print(f"  {r['asset']:8s} {r['excluded_reason'][:60]}")


if __name__ == "__main__":
    main()
