# Pipeline CLI Tools Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build CLI entry points for each pipeline stage so every step (fetch → store → score → decide) can be run independently from the terminal, with outputs written to `data/<stage>/` as inspectable JSON files.

**Architecture:** Each pipeline stage gets a standalone CLI script in `scripts/<group>/`. Groups: `scripts/fetch/` (data collection), `scripts/score/` (signal scoring), `scripts/inspect/` (DB + snapshot inspection). Each script: (1) runs one stage, (2) writes results to both SQLite and a JSON snapshot in `data/<stage>/`, (3) prints a summary to stdout.

**Tech Stack:** Python 3.8+, argparse (stdlib), existing modules (derivatives, on_chain, composite, utils.db)

**Spec:** `docs/superpowers/specs/2026-03-18-derivatives-onchain-signal-module-design.md`

---

## File Map

### New Files (create)

| File | Responsibility |
|------|---------------|
| `scripts/fetch/__init__.py` | Package init |
| `scripts/fetch/derivatives.py` | CLI: fetch funding rates + OI from Binance/Bybit, save to DB + `data/derivatives/` |
| `scripts/fetch/onchain.py` | CLI: fetch CoinMetrics daily data, save to DB + `data/onchain/` |
| `scripts/fetch/discover.py` | CLI: run asset discovery, save to DB + `data/asset_registry/` |
| `scripts/score/__init__.py` | Package init |
| `scripts/score/derivatives.py` | CLI: read derivatives data from DB, compute scores, save to `data/derivatives_scores/` |
| `scripts/score/onchain.py` | CLI: read on-chain data from DB, compute scores, save to `data/onchain_scores/` |
| `scripts/score/composite.py` | CLI: read all scores, run composite scorer + overrides, save to `data/composite/` |
| `scripts/inspect/__init__.py` | Package init |
| `scripts/inspect/show_db.py` | CLI: dump any DB table to stdout as formatted JSON |
| `tests/test_cli_tools.py` | Tests for CLI snapshot writing |

### Existing Files (no changes)

| File | Status |
|------|--------|
| `derivatives/collectors.py` | Used as-is by fetch scripts |
| `derivatives/processors.py` | Used as-is by score scripts |
| `on_chain/collectors.py` | Used as-is by fetch scripts |
| `on_chain/processors.py` | Used as-is by score scripts |
| `composite/scorer.py` | Used as-is by composite score script |
| `utils/db.py` | Used as-is for storage |
| `scripts/discover_assets.py` | Used as-is by fetch/discover |

---

## Output Directory Layout

After running all stages:

```
data/
  trading_bot.db                          # SQLite (all tables)
  asset_registry/
    2026-03-19T12-00-00_active.json       # discovered assets
  derivatives/
    2026-03-19T12-05-00_binance.json      # raw Binance funding + OI
    2026-03-19T12-05-00_bybit.json        # raw Bybit funding + OI
  onchain/
    2026-03-19_coinmetrics.json           # daily CoinMetrics data
  derivatives_scores/
    2026-03-19T12-05-00_scores.json       # per-asset derivatives scores
  onchain_scores/
    2026-03-19T12-05-00_scores.json       # per-asset on-chain scores
  composite/
    2026-03-19T12-05-00_decisions.json    # final BUY/SELL/HOLD per asset
```

Each JSON file is a complete snapshot — human-readable, `jq`-friendly.

---

## Chunk 1: CLI Fetch Tools (real API calls → DB + JSON snapshots)

### Task 1: Asset discovery CLI

**Files:**
- Create: `scripts/fetch/__init__.py`
- Create: `scripts/fetch/discover.py`

- [ ] **Step 1: Create scripts/fetch/__init__.py**

```python
# scripts/fetch/__init__.py
```

- [ ] **Step 2: Create scripts/fetch/discover.py**

```python
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
```

- [ ] **Step 3: Test it**

```bash
python -m scripts.fetch.discover --max-assets 5
cat data/asset_registry/*.json | python -m json.tool | head -30
```

- [ ] **Step 4: Commit**

```bash
git add scripts/fetch/
git commit -m "feat: add asset discovery CLI with JSON snapshots"
```

---

### Task 2: Fetch derivatives CLI (Binance + Bybit)

**Files:**
- Create: `scripts/fetch/derivatives.py`

- [ ] **Step 1: Create scripts/fetch/derivatives.py**

```python
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
```

- [ ] **Step 2: Test it**

```bash
python -m scripts.fetch.derivatives --assets BTC ETH SOL
cat data/derivatives/*_binance.json | python -m json.tool | head -30
```

- [ ] **Step 3: Commit**

```bash
git add scripts/fetch/derivatives.py
git commit -m "feat: add derivatives fetch CLI (Binance + Bybit)"
```

---

### Task 3: Fetch on-chain CLI (CoinMetrics)

**Files:**
- Create: `scripts/fetch/onchain.py`

- [ ] **Step 1: Create scripts/fetch/onchain.py**

```python
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
```

- [ ] **Step 2: Test it**

```bash
python -m scripts.fetch.onchain --assets BTC ETH
cat data/onchain/*.json | python -m json.tool | head -40
```

- [ ] **Step 3: Commit**

```bash
git add scripts/fetch/onchain.py
git commit -m "feat: add on-chain fetch CLI (CoinMetrics)"
```

---

## Chunk 2: CLI Scoring Tools (read DB → compute scores → JSON snapshots)

### Task 4: Score derivatives CLI

**Files:**
- Create: `scripts/score/__init__.py`
- Create: `scripts/score/derivatives.py`

- [ ] **Step 1: Create scripts/score/__init__.py and scripts/score/derivatives.py**

```python
# scripts/score/derivatives.py
"""Compute derivatives signal scores from data already in DB.

Prerequisites: run fetch_derivatives first.

Usage:
    python -m scripts.score.derivatives
    python -m scripts.score.derivatives --assets BTC ETH SOL

Output: data/derivatives_scores/<timestamp>_scores.json
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

from derivatives.processors import (
    aggregate_funding_rate_oi_weighted,
    generate_derivatives_signal,
)
from utils.db import DataStore

OUTPUT_DIR = Path("data/derivatives_scores")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score derivatives signals from DB data")
    parser.add_argument("--assets", nargs="+", default=None)
    args = parser.parse_args(argv)

    config = json.load(open("config/derivatives_config.json"))

    with DataStore() as db:
        if args.assets:
            assets = args.assets
        else:
            assets = db.get_active_assets()
            if not assets:
                print("No active assets. Run 'python -m scripts.fetch.discover' first.")
                return

        print(f"Scoring derivatives for {len(assets)} assets...")
        results = []

        for asset in assets:
            # Get latest funding rates from all exchanges
            funding_rows = db.get_latest_funding(asset)
            oi_rows = db.get_oi_history(asset, lookback_hours=1)

            if not funding_rows:
                print(f"  {asset}: no funding data — skipping")
                continue

            # Aggregate funding rate (OI-weighted if possible)
            agg_rate = aggregate_funding_rate_oi_weighted(
                [{"exchange": r["exchange"], "rate": r["rate"],
                  "oi_usd": next((o["oi_usd"] for o in oi_rows if o["exchange"] == r["exchange"]), 0)}
                 for r in funding_rows]
            )

            # Compute OI change (need at least 2 data points)
            oi_history = db.get_oi_history(asset, lookback_hours=24)
            if len(oi_history) >= 2:
                old_oi = oi_history[0]["oi_value"]
                new_oi = oi_history[-1]["oi_value"]
                oi_change_pct = (new_oi - old_oi) / old_oi if old_oi > 0 else 0
            else:
                oi_change_pct = 0

            # Price change (placeholder — would come from OHLC)
            price_change_pct = 0  # TODO: read from ohlc_data table

            # Long/short ratio (placeholder)
            ls_ratio = 1.0  # TODO: read from long_short_ratio table

            signal = generate_derivatives_signal(
                asset=asset,
                funding_rate=agg_rate,
                oi_change_pct=oi_change_pct,
                price_change_pct=price_change_pct,
                long_short_ratio=ls_ratio,
                config=config,
            )

            entry = {
                "asset": asset,
                "funding_rate_aggregated": agg_rate,
                "oi_change_pct": oi_change_pct,
                "funding_score": signal.funding_score,
                "oi_divergence_score": signal.oi_divergence_score,
                "long_short_score": signal.long_short_score,
                "combined_score": signal.combined_score,
                "funding_sources": len(funding_rows),
            }
            results.append(entry)
            print(f"  {asset:>6s}: combined={signal.combined_score:+.4f} (fund={signal.funding_score:+.3f} oi={signal.oi_divergence_score:+.3f} ls={signal.long_short_score:+.3f})")

    # Save snapshot
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    snapshot = {"timestamp": ts, "scores": results}
    out_path = OUTPUT_DIR / f"{ts}_scores.json"
    out_path.write_text(json.dumps(snapshot, indent=2, default=str))
    print(f"\nSnapshot saved: {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test it** (requires fetch_derivatives to have run first)

```bash
python -m scripts.score.derivatives --assets BTC ETH SOL
cat data/derivatives_scores/*.json | python -m json.tool
```

- [ ] **Step 3: Commit**

```bash
git add scripts/score/
git commit -m "feat: add derivatives scoring CLI"
```

---

### Task 5: Score on-chain CLI

**Files:**
- Create: `scripts/score/onchain.py`

- [ ] **Step 1: Create scripts/score/onchain.py**

```python
# scripts/score/onchain.py
"""Compute on-chain signal scores from data already in DB.

Prerequisites: run fetch_onchain first.

Usage:
    python -m scripts.score.onchain
    python -m scripts.score.onchain --assets BTC ETH

Output: data/onchain_scores/<timestamp>_scores.json
"""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from on_chain.processors import generate_on_chain_signal
from utils.db import DataStore

OUTPUT_DIR = Path("data/onchain_scores")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score on-chain signals from DB data")
    parser.add_argument("--assets", nargs="+", default=None)
    args = parser.parse_args(argv)

    config = json.load(open("config/onchain_config.json"))

    with DataStore() as db:
        if args.assets:
            assets = args.assets
        else:
            assets = db.get_active_assets()
            if not assets:
                assets = ["BTC", "ETH"]

        print(f"Scoring on-chain for {len(assets)} assets...")
        results = []

        for asset in assets:
            on_chain = db.get_on_chain(asset, lookback_days=30)
            if not on_chain:
                print(f"  {asset}: no on-chain data — skipping")
                continue

            latest = on_chain[-1]
            netflow = latest["exchange_netflow_native"]
            nupl = latest["nupl_computed"]

            # Compute 30-day average and std for flow normalization
            flows = [r["exchange_netflow_native"] for r in on_chain]
            avg_flow = sum(flows) / len(flows) if flows else 0
            std_flow = (sum((f - avg_flow) ** 2 for f in flows) / len(flows)) ** 0.5 if len(flows) > 1 else 1.0

            # Active address growth
            if len(on_chain) >= 2:
                old_addr = on_chain[0]["active_addresses"]
                new_addr = on_chain[-1]["active_addresses"]
                addr_growth = (new_addr - old_addr) / old_addr if old_addr > 0 else 0
            else:
                addr_growth = 0

            # Whale data (only for ETH-ecosystem — check DB)
            whale_window = datetime.utcnow() - timedelta(hours=config["whale_rolling_window_hours"])
            whale_rows = db.get_recent_whale_transfers(asset, since=whale_window)
            if whale_rows:
                to_ex = sum(r["value_usd"] for r in whale_rows if r["direction"] == "to_exchange")
                from_ex = sum(r["value_usd"] for r in whale_rows if r["direction"] == "from_exchange")
            else:
                to_ex = None
                from_ex = None

            signal = generate_on_chain_signal(
                asset=asset,
                netflow=netflow, avg_30d_netflow=avg_flow, std_30d=std_flow,
                nupl=nupl, active_addr_growth=addr_growth,
                whale_to_exchange_usd=to_ex, whale_from_exchange_usd=from_ex,
                config=config,
            )

            entry = {
                "asset": asset,
                "netflow": netflow,
                "nupl": nupl,
                "active_addr_growth": addr_growth,
                "whale_to_exchange_usd": to_ex,
                "whale_from_exchange_usd": from_ex,
                "exchange_flow_score": signal.exchange_flow_score,
                "nupl_score": signal.nupl_score,
                "active_addr_score": signal.active_addr_score,
                "whale_score": signal.whale_score,
                "combined_score": signal.combined_score,
                "confidence": signal.confidence,
            }
            results.append(entry)
            print(f"  {asset:>6s}: combined={signal.combined_score:+.4f} (flow={signal.exchange_flow_score:+.3f} nupl={signal.nupl_score:+.3f} addr={signal.active_addr_score:+.3f} whale={signal.whale_score:+.3f}) conf={signal.confidence:.2f}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    snapshot = {"timestamp": ts, "scores": results}
    out_path = OUTPUT_DIR / f"{ts}_scores.json"
    out_path.write_text(json.dumps(snapshot, indent=2, default=str))
    print(f"\nSnapshot saved: {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test it**

```bash
python -m scripts.score.onchain --assets BTC ETH
cat data/onchain_scores/*.json | python -m json.tool
```

- [ ] **Step 3: Commit**

```bash
git add scripts/score/onchain.py
git commit -m "feat: add on-chain scoring CLI"
```

---

### Task 6: Composite scorer CLI

**Files:**
- Create: `scripts/score/composite.py`

- [ ] **Step 1: Create scripts/score/composite.py**

```python
# scripts/score/composite.py
"""Run composite scorer: combine all signals → BUY/SELL/HOLD decisions.

Prerequisites: run score_derivatives and score_onchain first (or provide scores manually).

Usage:
    python -m scripts.score.composite
    python -m scripts.score.composite --assets BTC ETH SOL
    python -m scripts.score.composite --deriv-file data/derivatives_scores/latest.json --onchain-file data/onchain_scores/latest.json

Output: data/composite/<timestamp>_decisions.json
"""
import argparse
import glob
import json
from datetime import datetime
from pathlib import Path

from composite.scorer import make_optimized_trading_decision
from utils.db import DataStore

OUTPUT_DIR = Path("data/composite")


def _load_latest_json(directory: str) -> dict | None:
    files = sorted(glob.glob(f"{directory}/*_scores.json"))
    if not files:
        return None
    with open(files[-1]) as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run composite scoring pipeline")
    parser.add_argument("--assets", nargs="+", default=None)
    parser.add_argument("--deriv-file", default=None, help="Path to derivatives scores JSON")
    parser.add_argument("--onchain-file", default=None, help="Path to on-chain scores JSON")
    parser.add_argument("--technical-score", type=float, default=0.0, help="Mock technical score (default 0)")
    parser.add_argument("--sentiment-score", type=float, default=0.0, help="Mock sentiment score (default 0)")
    parser.add_argument("--mtf-score", type=float, default=0.0, help="Mock multi-timeframe score (default 0)")
    args = parser.parse_args(argv)

    config = json.load(open("config/composite_config.json"))

    # Load derivatives scores
    if args.deriv_file:
        deriv_data = json.load(open(args.deriv_file))
    else:
        deriv_data = _load_latest_json("data/derivatives_scores")
    if not deriv_data:
        print("No derivatives scores found. Run 'python -m scripts.score.derivatives' first.")
        return

    # Load on-chain scores
    if args.onchain_file:
        onchain_data = json.load(open(args.onchain_file))
    else:
        onchain_data = _load_latest_json("data/onchain_scores")

    # Build score lookup
    deriv_scores = {s["asset"]: s["combined_score"] for s in deriv_data.get("scores", [])}
    onchain_scores = {s["asset"]: s for s in (onchain_data or {}).get("scores", [])}

    if args.assets:
        assets = args.assets
    else:
        assets = list(deriv_scores.keys())

    print(f"Composite scoring for {len(assets)} assets...")
    print(f"  Technical={args.technical_score:+.2f} Sentiment={args.sentiment_score:+.2f} MTF={args.mtf_score:+.2f} (mocked)")
    print()

    results = []
    for asset in assets:
        d_score = deriv_scores.get(asset, 0.0)
        oc = onchain_scores.get(asset, {})
        oc_score = oc.get("combined_score", 0.0)
        nupl = oc.get("nupl", 0.5)
        funding_rate = next(
            (s["funding_rate_aggregated"] for s in deriv_data.get("scores", []) if s["asset"] == asset),
            0.0
        )

        decision = make_optimized_trading_decision(
            asset=asset,
            scores={
                "technical": args.technical_score,
                "derivatives": d_score,
                "on_chain": oc_score,
                "multi_timeframe": args.mtf_score,
                "sentiment": args.sentiment_score,
            },
            weights=config["weights"],
            thresholds=config["thresholds"],
            override_inputs={
                "funding_rate": funding_rate,
                "nupl": nupl,
                "tf_opposition": False,
                "catalyst_sentiment": 0.0,
            },
            override_config=config["overrides"],
        )

        entry = {
            "asset": asset,
            "decision": decision.decision,
            "final_score": decision.final_score,
            "raw_composite": decision.raw_composite,
            "sub_scores": {
                "technical": decision.technical_score,
                "derivatives": decision.derivatives_score,
                "on_chain": decision.on_chain_score,
                "multi_timeframe": decision.mtf_score,
                "sentiment": decision.sentiment_score,
            },
            "overrides_fired": [o.rule_id for o in decision.overrides_fired],
            "override_details": [
                {"rule": o.rule_id, "tier": o.tier, "before": o.score_before, "after": o.score_after}
                for o in decision.overrides_fired
            ],
        }
        results.append(entry)

        overrides_str = f" overrides={[o.rule_id for o in decision.overrides_fired]}" if decision.overrides_fired else ""
        print(f"  {asset:>6s}: {decision.decision:4s} score={decision.final_score:+.4f} (raw={decision.raw_composite:+.4f}){overrides_str}")

    # Save snapshot
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    snapshot = {
        "timestamp": ts,
        "config_weights": config["weights"],
        "config_thresholds": config["thresholds"],
        "mocked_scores": {
            "technical": args.technical_score,
            "sentiment": args.sentiment_score,
            "multi_timeframe": args.mtf_score,
        },
        "decisions": results,
        "summary": {
            "buy": sum(1 for r in results if r["decision"] == "BUY"),
            "sell": sum(1 for r in results if r["decision"] == "SELL"),
            "hold": sum(1 for r in results if r["decision"] == "HOLD"),
        },
    }
    out_path = OUTPUT_DIR / f"{ts}_decisions.json"
    out_path.write_text(json.dumps(snapshot, indent=2, default=str))
    print(f"\nSnapshot saved: {out_path}")

    # Log to DB
    with DataStore() as db:
        for r in results:
            db.log_signal({
                "asset": r["asset"],
                "timestamp": datetime.utcnow(),
                **r["sub_scores"],
                "raw_composite": r["raw_composite"],
                "final_score": r["final_score"],
                "overrides_fired": json.dumps(r["overrides_fired"]),
                "decision": r["decision"],
                "metadata": json.dumps(r["override_details"]),
            })
    print(f"Logged {len(results)} decisions to signal_log")

    print(f"\n{'='*50}")
    print(f"BUY: {snapshot['summary']['buy']} | SELL: {snapshot['summary']['sell']} | HOLD: {snapshot['summary']['hold']}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test it**

```bash
python -m scripts.score.composite --assets BTC ETH SOL
cat data/composite/*.json | python -m json.tool
```

- [ ] **Step 3: Commit**

```bash
git add scripts/score/composite.py
git commit -m "feat: add composite scoring CLI with override tracing"
```

---

### Task 7: DB inspection CLI

**Files:**
- Create: `scripts/inspect/__init__.py`
- Create: `scripts/inspect/show_db.py`

- [ ] **Step 1: Create scripts/inspect/__init__.py and scripts/inspect/show_db.py**

```python
# scripts/inspect/show_db.py
"""Inspect any table in the trading bot database.

Usage:
    python -m scripts.inspect.show_db --tables                     # list all tables
    python -m scripts.inspect.show_db --table funding_rates         # dump table
    python -m scripts.inspect.show_db --table signal_log --limit 5  # last 5 rows
    python -m scripts.inspect.show_db --table asset_registry --where "has_perps = 1"
"""
import argparse
import json

from utils.db import DataStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inspect trading bot database")
    parser.add_argument("--tables", action="store_true", help="List all tables")
    parser.add_argument("--table", type=str, help="Table name to dump")
    parser.add_argument("--limit", type=int, default=20, help="Max rows (default 20)")
    parser.add_argument("--where", type=str, default=None, help="SQL WHERE clause")
    parser.add_argument("--count", action="store_true", help="Show row count only")
    args = parser.parse_args(argv)

    with DataStore() as db:
        if args.tables:
            tables = db.list_tables()
            print("Tables in trading_bot.db:")
            for t in tables:
                count = db.fetchone(f"SELECT COUNT(*) as cnt FROM [{t}]")
                print(f"  {t:25s} {count['cnt']:>8d} rows")
            return

        if not args.table:
            parser.print_help()
            return

        table = args.table
        where = f" WHERE {args.where}" if args.where else ""

        if args.count:
            count = db.fetchone(f"SELECT COUNT(*) as cnt FROM [{table}]{where}")
            print(f"{table}: {count['cnt']} rows")
            return

        rows = db.fetchall(
            f"SELECT * FROM [{table}]{where} ORDER BY rowid DESC LIMIT ?",
            (args.limit,),
        )
        data = [dict(row) for row in rows]
        data.reverse()  # oldest first
        print(json.dumps(data, indent=2, default=str))
        print(f"\n({len(data)} rows shown, limit={args.limit})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test it**

```bash
python -m scripts.inspect.show_db --tables
python -m scripts.inspect.show_db --table funding_rates --limit 5
python -m scripts.inspect.show_db --table signal_log
```

- [ ] **Step 3: Commit**

```bash
git add scripts/inspect/
git commit -m "feat: add DB inspection CLI"
```

---

## Chunk 3: Full Pipeline Run Guide

### Task 8: Update manual testing guide

**Files:**
- Modify: `docs/manual-testing.md`

- [ ] **Step 1: Append the full pipeline walkthrough to docs/manual-testing.md**

Add a new section at the end of the file:

```markdown
---

## Full Pipeline Walkthrough (real API data)

Run each step sequentially. Inspect JSON output after each step before continuing.

### Step 1: Discover active assets

```bash
python -m scripts.fetch.discover --max-assets 5
cat data/asset_registry/*.json | python -m json.tool | head -20
```

### Step 2: Fetch derivatives data (Binance + Bybit)

```bash
python -m scripts.fetch.derivatives --assets BTC ETH SOL
ls -la data/derivatives/
cat data/derivatives/*_binance.json | python -m json.tool | head -30
cat data/derivatives/*_bybit.json | python -m json.tool | head -30
```

### Step 3: Fetch on-chain data (CoinMetrics)

```bash
python -m scripts.fetch.onchain --assets BTC ETH
ls -la data/onchain/
cat data/onchain/*.json | python -m json.tool
```

### Step 4: Score derivatives signals

```bash
python -m scripts.score.derivatives --assets BTC ETH SOL
cat data/derivatives_scores/*.json | python -m json.tool
```

### Step 5: Score on-chain signals

```bash
python -m scripts.score.onchain --assets BTC ETH
cat data/onchain_scores/*.json | python -m json.tool
```

### Step 6: Run composite scorer

```bash
python -m scripts.score.composite --assets BTC ETH SOL
cat data/composite/*.json | python -m json.tool
```

### Step 7: Inspect the database

```bash
python -m scripts.inspect.show_db --tables
python -m scripts.inspect.show_db --table funding_rates --limit 5
python -m scripts.inspect.show_db --table on_chain_daily
python -m scripts.inspect.show_db --table signal_log
```

### Step 8: Re-run with different mock scores

```bash
# Simulate bullish technicals + sentiment
python -m scripts.score.composite --assets BTC ETH SOL --technical-score 0.8 --sentiment-score 0.6

# Compare with bearish technicals
python -m scripts.score.composite --assets BTC ETH SOL --technical-score -0.8 --sentiment-score -0.6

# Check all snapshots
ls data/composite/
```

### Cleanup

```bash
# Remove all snapshots (DB remains)
rm -rf data/derivatives/ data/onchain/ data/derivatives_scores/ data/onchain_scores/ data/composite/ data/asset_registry/

# Remove DB too
rm -f data/trading_bot.db
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/manual-testing.md
git commit -m "docs: add full pipeline walkthrough to manual testing guide"
```

---

## Summary

| Task | What it builds | Command |
|------|---------------|---------|
| 1 | Asset discovery CLI | `python -m scripts.fetch.discover` |
| 2 | Derivatives fetch CLI | `python -m scripts.fetch.derivatives` |
| 3 | On-chain fetch CLI | `python -m scripts.fetch.onchain` |
| 4 | Derivatives scoring CLI | `python -m scripts.score.derivatives` |
| 5 | On-chain scoring CLI | `python -m scripts.score.onchain` |
| 6 | Composite scoring CLI | `python -m scripts.score.composite` |
| 7 | DB inspection CLI | `python -m scripts.inspect.show_db` |
| 8 | Manual testing guide update | `docs/manual-testing.md` |

**Scripts directory layout:**

```
scripts/
  __init__.py                  # existing
  discover_assets.py           # existing (core discovery logic)
  build_sector_map.py          # existing (sentiment)
  fetch/
    __init__.py
    discover.py                # asset discovery CLI
    derivatives.py             # Binance/Bybit fetch CLI
    onchain.py                 # CoinMetrics fetch CLI
  score/
    __init__.py
    derivatives.py             # derivatives scoring CLI
    onchain.py                 # on-chain scoring CLI
    composite.py               # composite scoring CLI
  inspect/
    __init__.py
    show_db.py                 # DB table inspector CLI
```

**Pipeline execution order:**

```
fetch.discover → fetch.derivatives → fetch.onchain → score.derivatives → score.onchain → score.composite → inspect.show_db
```

Each step is independent after its prerequisites run. Every step writes to both `data/trading_bot.db` (structured) and `data/<stage>/*.json` (human-inspectable snapshots).
