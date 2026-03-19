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
