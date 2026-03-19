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
