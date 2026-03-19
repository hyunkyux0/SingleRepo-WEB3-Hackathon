# scripts/score/simulate_derivatives.py
"""Simulate derivatives scores across different market regimes.

Saves results to data/derivatives_scores/simulated_regimes.csv

Usage:
    python -m scripts.score.simulate_derivatives
"""
import csv
import json
from pathlib import Path

from derivatives.processors import generate_derivatives_signal

OUTPUT_DIR = Path("data/derivatives_scores")

SCENARIOS = [
    # (name, funding_rate, oi_change_pct, price_change_pct, long_short_ratio)
    ("Calm market (current)",     0.000004,  0.0004,  0.00004, 1.0),
    ("Slight bull",               0.0001,    0.03,    0.02,    1.2),
    ("Moderate bull",             0.0003,    0.10,    0.05,    1.5),
    ("Strong bull",               0.0005,    0.20,    0.08,    2.0),
    ("Overcrowded longs",         0.0008,    0.30,    0.08,    3.0),
    ("Extreme euphoria",          0.0015,    0.50,    0.15,    5.0),
    ("Slight bear",              -0.0001,    0.02,   -0.02,    0.8),
    ("Moderate bear",            -0.0003,    0.10,   -0.05,    0.6),
    ("Strong bear",              -0.0005,    0.20,   -0.08,    0.4),
    ("Crash / cascade",          -0.0012,    0.40,   -0.10,    0.3),
    ("Extreme panic",            -0.0020,    0.60,   -0.20,    0.2),
    ("Capitulation (deleverage)",-0.0005,   -0.30,   -0.08,    0.5),
    ("Short squeeze",            -0.0010,    0.20,    0.12,    0.4),
    ("Choppy range",              0.00005,   0.001,  -0.002,   1.05),
    ("Dead market",               0.0,       0.0,     0.0,     1.0),
]


def main() -> None:
    config = json.load(open("config/derivatives_config.json"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "simulated_regimes.csv"

    rows = []
    for name, fr, oi, pr, ls in SCENARIOS:
        signal = generate_derivatives_signal("BTC", fr, oi, pr, ls, config)
        rows.append({
            "scenario": name,
            "funding_rate": fr,
            "oi_change_pct": oi,
            "price_change_pct": pr,
            "long_short_ratio": ls,
            "funding_score": round(signal.funding_score, 4),
            "oi_divergence_score": round(signal.oi_divergence_score, 4),
            "long_short_score": round(signal.long_short_score, 4),
            "combined_score": round(signal.combined_score, 4),
        })

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved: {out_path}")
    print()
    print(f"{'Scenario':<28s} {'Combined':>9s} {'Funding':>9s} {'OI Div':>9s} {'L/S':>9s}")
    print("-" * 66)
    for r in rows:
        print(f"{r['scenario']:<28s} {r['combined_score']:>+9.4f} {r['funding_score']:>+9.4f} {r['oi_divergence_score']:>+9.4f} {r['long_short_score']:>+9.4f}")


if __name__ == "__main__":
    main()
