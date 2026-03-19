#!/usr/bin/env python3
"""Run the sentiment pipeline once and save outputs.

Calls the pipeline orchestrator's tick() method, which:
1. Fetches news via scripts/fetch_news.py
2. Pre-filters and deduplicates via news_sentiment/processors.py
3. Classifies sectors and scores sentiment via news_sentiment/prompter.py + sentiment_score/
4. Aggregates into per-sector signals

Saves all outputs to data/ for inspection:
- data/pipeline_runs/run_{timestamp}.json — full signal set + metadata

Usage:
    python -m scripts.run_pipeline
    python -m scripts.fetch_news          # fetch only, no classification
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_pipeline")

OUTPUT_DIR = PROJECT_ROOT / "data" / "pipeline_runs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the sentiment pipeline once")
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR))
    args = parser.parse_args()

    from pipeline.orchestrator import SentimentPipeline
    from composite.adapters import sector_signal_to_asset_score

    # Load sector map for per-asset scoring
    with open(PROJECT_ROOT / "config" / "sector_map.json") as f:
        sector_map = json.load(f)

    logger.info("Starting pipeline tick...")
    with SentimentPipeline() as pipeline:
        signal_set = pipeline.tick()

    # Compute per-asset scores
    asset_scores = {}
    for asset in sector_map:
        asset_scores[asset] = sector_signal_to_asset_score(asset, signal_set, sector_map)

    # Save output
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"run_{ts}.json"

    output = {
        "timestamp": signal_set.timestamp.isoformat(),
        "metadata": signal_set.metadata,
        "sector_signals": {
            sector: {
                "sentiment": sig.sentiment,
                "momentum": sig.momentum,
                "catalyst_active": sig.catalyst_active,
                "catalyst_details": sig.catalyst_details,
                "article_count": sig.article_count,
                "confidence": sig.confidence,
                "key_driver": sig.key_driver,
                "reasoning": sig.reasoning,
            }
            for sector, sig in signal_set.sectors.items()
        },
        "asset_scores": asset_scores,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    logger.info("Saved pipeline output to %s", output_path)

    # Print summary
    print(f"\n{'='*60}")
    print(f"Sentiment Pipeline Run")
    print(f"{'='*60}")
    meta = signal_set.metadata
    print(f"Articles fetched:    {meta.get('articles_fetched', 0)}")
    print(f"After filter:        {meta.get('articles_after_filter', 0)}")
    print(f"Catalysts detected:  {meta.get('catalysts_detected', 0)}")
    print(f"Fast classified:     {meta.get('fast_path_classified', 0)}")
    print(f"Batch classified:    {meta.get('batch_classified', 0)}")
    print(f"LLM calls:           {meta.get('llm_calls', 0)}")
    print(f"Processing time:     {meta.get('processing_time_ms', 0):.0f}ms")

    print(f"\n{'Sector':<16} {'Sent':>8} {'Mom':>8} {'Conf':>6} {'Arts':>5} {'Cat':>4} Key Driver")
    print(f"{'-'*16} {'-'*8} {'-'*8} {'-'*6} {'-'*5} {'-'*4} {'-'*30}")
    for sector, sig in sorted(signal_set.sectors.items()):
        catalyst = "Y" if sig.catalyst_active else ""
        driver = sig.key_driver[:30] if sig.key_driver else ""
        print(
            f"{sector:<16} {sig.sentiment:>+8.4f} {sig.momentum:>+8.4f} "
            f"{sig.confidence:>6.3f} {sig.article_count:>5d} {catalyst:>4} {driver}"
        )

    # Print reasoning for sectors with signal
    has_reasoning = [(s, sig) for s, sig in signal_set.sectors.items() if sig.reasoning and sig.reasoning != "No articles in window."]
    if has_reasoning:
        print(f"\nSector Reasoning:")
        for sector, sig in has_reasoning:
            print(f"  [{sector}] {sig.reasoning}")

    # Print top movers
    non_zero = {k: v for k, v in asset_scores.items() if v["sentiment"] != 0.0}
    if non_zero:
        print(f"\nTop Asset Signals (non-zero):")
        sorted_assets = sorted(non_zero.items(), key=lambda x: abs(x[1]["sentiment"]), reverse=True)
        for asset, score in sorted_assets[:10]:
            ticker = asset.split("/")[0]
            catalyst = " [CATALYST]" if score["catalyst_active"] else ""
            print(f"  {ticker:<10} {score['sector']:<14} sent={score['sentiment']:+.4f}{catalyst}")

    print(f"\nOutput: {output_path}")


if __name__ == "__main__":
    main()
