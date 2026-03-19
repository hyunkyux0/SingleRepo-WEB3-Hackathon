# Manual Testing Guide — Derivatives & On-Chain Signals

Interactive terminal commands to explore each module. Run from project root.

---

## Setup

```bash
cd /workspace/SingleRepo-WEB3-Hackathon
python -m pytest tests/ -v --tb=short   # verify 213 pass
```

---

## 1. Derivatives Scoring (offline, no API)

```bash
python
```

```python
from derivatives.processors import score_funding_rate, score_oi_divergence, score_long_short_ratio, generate_derivatives_signal
import json

# Load config
config = json.load(open("config/derivatives_config.json"))
config
```

### Funding Rate Scoring

```python
# Positive funding = overcrowded longs = bearish = negative score
score_funding_rate(0.0005)    # 0.05% funding
score_funding_rate(-0.0005)   # -0.05% funding
score_funding_rate(0.0)       # neutral
score_funding_rate(0.002)     # extreme positive -> capped at -1.0
```

### OI Divergence Scoring

```python
# Rising OI + rising price = trend confirmation
score_oi_divergence(oi_change_pct=0.05, price_change_pct=0.03)

# Rising OI + falling price = bearish continuation
score_oi_divergence(oi_change_pct=0.05, price_change_pct=-0.03)

# Falling OI = deleveraging, toward zero
score_oi_divergence(oi_change_pct=-0.05, price_change_pct=0.03)
```

### Long/Short Ratio (contrarian)

```python
score_long_short_ratio(3.0)   # too many longs -> negative
score_long_short_ratio(0.4)   # too many shorts -> positive
score_long_short_ratio(1.0)   # balanced -> near zero
```

### OI-Weighted Funding Aggregation

```python
from derivatives.processors import aggregate_funding_rate_oi_weighted

# Binance has 3x the OI of Bybit, so its rate dominates
rates = [
    {"exchange": "binance", "rate": 0.0003, "oi_usd": 300_000_000},
    {"exchange": "bybit",   "rate": 0.0001, "oi_usd": 100_000_000},
]
aggregate_funding_rate_oi_weighted(rates)
```

### Full Derivatives Signal

```python
signal = generate_derivatives_signal(
    asset="BTC",
    funding_rate=0.0003,
    oi_change_pct=0.02,
    price_change_pct=0.01,
    long_short_ratio=1.5,
    config=config,
)
signal.combined_score
signal.funding_score
signal.oi_divergence_score
signal.long_short_score
```

```python
exit()
```

---

## 2. On-Chain Scoring (offline, no API)

```bash
python
```

```python
from on_chain.processors import score_exchange_flow, score_nupl, score_active_addresses, score_whale_activity, generate_on_chain_signal
import json

config = json.load(open("config/onchain_config.json"))
config
```

### Exchange Flow

```python
# Net inflow = selling pressure = negative
score_exchange_flow(netflow=200, avg_30d_netflow=0, std_30d=100)

# Net outflow = accumulation = positive
score_exchange_flow(netflow=-200, avg_30d_netflow=0, std_30d=100)
```

### NUPL (cycle indicator)

```python
score_nupl(0.80)    # euphoria -> negative
score_nupl(-0.10)   # capitulation -> positive
score_nupl(0.40)    # mid-cycle -> near zero
score_nupl(0.0)     # boundary
score_nupl(0.75)    # spec threshold
```

### Active Address Growth

```python
score_active_addresses(growth_rate_30d=0.10)    # 10% growth -> positive
score_active_addresses(growth_rate_30d=-0.10)   # 10% decline -> negative
score_active_addresses(growth_rate_30d=0.0)     # flat
```

### Whale Activity

```python
# $5M to exchange, $1M from exchange -> net sell pressure
score_whale_activity(to_exchange_usd=5_000_000, from_exchange_usd=1_000_000)

# $1M to, $5M from -> net accumulation
score_whale_activity(to_exchange_usd=1_000_000, from_exchange_usd=5_000_000)

# No activity
score_whale_activity(to_exchange_usd=0, from_exchange_usd=0)
```

### Full On-Chain Signal (with whale data — ETH)

```python
signal = generate_on_chain_signal(
    asset="ETH",
    netflow=200, avg_30d_netflow=50, std_30d=80,
    nupl=0.5, active_addr_growth=0.05,
    whale_to_exchange_usd=2_000_000,
    whale_from_exchange_usd=1_000_000,
    config=config,
)
signal.combined_score
signal.exchange_flow_score
signal.nupl_score
signal.active_addr_score
signal.whale_score
signal.confidence
```

### Full On-Chain Signal (without whale data — BTC, weights renormalized)

```python
signal = generate_on_chain_signal(
    asset="BTC",
    netflow=-100, avg_30d_netflow=50, std_30d=80,
    nupl=0.3, active_addr_growth=0.08,
    whale_to_exchange_usd=None,
    whale_from_exchange_usd=None,
    config=config,
)
signal.combined_score
signal.whale_score   # 0.0 — no data
signal.confidence
```

```python
exit()
```

---

## 3. Composite Scorer + Override Rules

```bash
python
```

```python
from composite.scorer import compute_weighted_sum, apply_overrides, make_optimized_trading_decision
import json

config = json.load(open("config/composite_config.json"))
weights = config["weights"]
thresholds = config["thresholds"]
overrides = config["overrides"]
```

### Weighted Sum

```python
# All bullish
compute_weighted_sum(1.0, 1.0, 1.0, 1.0, 1.0, weights)

# Mixed signals
compute_weighted_sum(0.8, -0.5, 0.2, 0.5, 0.0, weights)

# All bearish
compute_weighted_sum(-1.0, -1.0, -1.0, -1.0, -1.0, weights)
```

### Overrides — No Triggers

```python
r = apply_overrides(0.5, funding_rate=0.0, nupl=0.4, tf_opposition=False, catalyst_sentiment=0.0, config=overrides)
r["final_score"]
[o.rule_id for o in r["overrides_fired"]]
```

### Overrides — Soft Penalty (funding > 0.10%)

```python
r = apply_overrides(0.5, funding_rate=0.0012, nupl=0.4, tf_opposition=False, catalyst_sentiment=0.0, config=overrides)
r["final_score"]   # 0.5 * 0.2 = 0.1
[o.rule_id for o in r["overrides_fired"]]
```

### Overrides — Stacked Soft (funding + NUPL euphoria)

```python
r = apply_overrides(0.5, funding_rate=0.0012, nupl=0.80, tf_opposition=False, catalyst_sentiment=0.0, config=overrides)
r["final_score"]   # 0.5 * 0.2 * 0.2 = 0.02
[o.rule_id for o in r["overrides_fired"]]
```

### Overrides — Hard Block (funding > 0.20%)

```python
r = apply_overrides(0.5, funding_rate=0.003, nupl=0.4, tf_opposition=False, catalyst_sentiment=0.0, config=overrides)
r["final_score"]   # clamped to 0.0
[o.rule_id for o in r["overrides_fired"]]
```

### Overrides — Catalyst Boost then Penalty

```python
r = apply_overrides(0.4, funding_rate=0.0012, nupl=0.4, tf_opposition=False, catalyst_sentiment=0.8, config=overrides)
r["final_score"]   # 0.4 * 1.5 * 0.2 = 0.12
[o.rule_id for o in r["overrides_fired"]]
```

### Full Trading Decision

```python
d = make_optimized_trading_decision(
    asset="BTC",
    scores={"technical": 0.8, "derivatives": 0.5, "on_chain": 0.3, "multi_timeframe": 0.7, "sentiment": 0.4},
    weights=weights,
    thresholds=thresholds,
    override_inputs={"funding_rate": 0.0, "nupl": 0.5, "tf_opposition": False, "catalyst_sentiment": 0.0},
    override_config=overrides,
)
d.decision
d.final_score
d.raw_composite
[o.rule_id for o in d.overrides_fired]
```

### Bearish Decision

```python
d = make_optimized_trading_decision(
    asset="ETH",
    scores={"technical": -0.8, "derivatives": -0.5, "on_chain": -0.3, "multi_timeframe": -0.7, "sentiment": -0.4},
    weights=weights,
    thresholds=thresholds,
    override_inputs={"funding_rate": 0.0, "nupl": 0.5, "tf_opposition": False, "catalyst_sentiment": 0.0},
    override_config=overrides,
)
d.decision
d.final_score
```

```python
exit()
```

---

## 4. DataStore (creates data/trading_bot.db)

```bash
python
```

```python
from utils.db import DataStore
from datetime import datetime, timedelta

db = DataStore()
db.open()
db.list_tables()
```

### Asset Registry

```python
db.save_asset_registry([
    {"asset": "BTC", "has_perps": True, "exchange_sources": '["binance","bybit"]', "oi_rank": 1, "excluded_reason": None},
    {"asset": "ETH", "has_perps": True, "exchange_sources": '["binance","bybit"]', "oi_rank": 2, "excluded_reason": None},
    {"asset": "SOMI", "has_perps": False, "exchange_sources": '[]', "oi_rank": None, "excluded_reason": "No perps on Binance"},
])
db.get_active_assets()
```

### Funding Rates

```python
now = datetime.utcnow()
db.save_funding_rates([
    {"asset": "BTC", "timestamp": now, "exchange": "binance", "rate": 0.00015},
    {"asset": "BTC", "timestamp": now, "exchange": "bybit",   "rate": 0.00012},
])
db.get_latest_funding("BTC")
```

### On-Chain Daily

```python
from datetime import date
db.save_on_chain_daily([{
    "asset": "BTC", "date": date.today(),
    "exchange_inflow_native": 500.0, "exchange_outflow_native": 300.0,
    "exchange_netflow_native": 200.0, "mvrv": 2.5,
    "nupl_computed": 0.6, "active_addresses": 900000,
}])
db.get_on_chain("BTC", lookback_days=7)
```

### Signal Log

```python
db.log_signal({
    "asset": "BTC", "timestamp": now,
    "technical_score": 0.7, "derivatives_score": 0.3,
    "on_chain_score": 0.1, "mtf_score": 0.5, "sentiment_score": 0.2,
    "raw_composite": 0.42, "final_score": 0.42,
    "overrides_fired": "[]", "decision": "BUY", "metadata": "{}",
})
db.fetchall("SELECT asset, decision, final_score FROM signal_log")
```

### Cleanup

```python
db.close()
exit()
```

```bash
# Verify DB was created
ls -la data/trading_bot.db
```

---

## 5. Asset Discovery (LIVE — calls Binance API)

```bash
python
```

```python
from scripts.discover_assets import discover_active_assets

results = discover_active_assets(max_assets=10)
active = [r for r in results if r["has_perps"] and not r["excluded_reason"]]
excluded = [r for r in results if r["excluded_reason"]]
len(active)
len(excluded)
```

```python
# Top 5 by OI
for r in active[:5]:
    print(f"{r['asset']:8s} rank={r['oi_rank']}")
```

```python
# First 5 excluded
for r in excluded[:5]:
    print(f"{r['asset']:8s} reason={r['excluded_reason'][:60]}")
```

```python
exit()
```

---

## 6. End-to-End: Combine All Signals for One Asset

```bash
python
```

```python
from derivatives.processors import generate_derivatives_signal
from on_chain.processors import generate_on_chain_signal
from composite.scorer import make_optimized_trading_decision
import json

deriv_cfg = json.load(open("config/derivatives_config.json"))
chain_cfg = json.load(open("config/onchain_config.json"))
comp_cfg  = json.load(open("config/composite_config.json"))

# Simulate BTC market state
deriv = generate_derivatives_signal("BTC", funding_rate=0.0003, oi_change_pct=0.04, price_change_pct=0.02, long_short_ratio=1.8, config=deriv_cfg)
chain = generate_on_chain_signal("BTC", netflow=-150, avg_30d_netflow=50, std_30d=80, nupl=0.45, active_addr_growth=0.06, whale_to_exchange_usd=None, whale_from_exchange_usd=None, config=chain_cfg)

print(f"Derivatives: {deriv.combined_score:.4f}")
print(f"On-chain:    {chain.combined_score:.4f}")
```

```python
# Feed into composite scorer (mock technical + sentiment + mtf)
decision = make_optimized_trading_decision(
    asset="BTC",
    scores={
        "technical": 0.6,
        "derivatives": deriv.combined_score,
        "on_chain": chain.combined_score,
        "multi_timeframe": 0.5,
        "sentiment": 0.3,
    },
    weights=comp_cfg["weights"],
    thresholds=comp_cfg["thresholds"],
    override_inputs={
        "funding_rate": 0.0003,
        "nupl": 0.45,
        "tf_opposition": False,
        "catalyst_sentiment": 0.0,
    },
    override_config=comp_cfg["overrides"],
)

print(f"\nDecision:    {decision.decision}")
print(f"Final score: {decision.final_score:.4f}")
print(f"Raw score:   {decision.raw_composite:.4f}")
print(f"Overrides:   {[o.rule_id for o in decision.overrides_fired]}")
```

```python
exit()
```
