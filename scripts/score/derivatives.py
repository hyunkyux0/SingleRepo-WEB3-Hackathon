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

            # Price change from OHLC data
            ohlc = db.get_ohlc(asset, "5m", lookback=20)
            if len(ohlc) >= 2:
                old_close = ohlc[0]["close"]
                new_close = ohlc[-1]["close"]
                price_change_pct = (new_close - old_close) / old_close if old_close > 0 else 0
            else:
                price_change_pct = 0

            # Long/short ratio from DB (Coinalyze)
            ls_rows = db.fetchall(
                "SELECT ratio FROM long_short_ratio WHERE asset = ? ORDER BY timestamp DESC LIMIT 1",
                (asset,),
            )
            ls_ratio = dict(ls_rows[0])["ratio"] if ls_rows else 1.0

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
                "inputs": {
                    "funding_rate_aggregated": agg_rate,
                    "oi_change_pct": oi_change_pct,
                    "price_change_pct": price_change_pct,
                    "long_short_ratio": ls_ratio,
                    "funding_sources": len(funding_rows),
                    "ohlc_candles": len(ohlc),
                },
                "funding_score": signal.funding_score,
                "oi_divergence_score": signal.oi_divergence_score,
                "long_short_score": signal.long_short_score,
                "combined_score": signal.combined_score,
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
