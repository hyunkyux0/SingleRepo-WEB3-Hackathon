# Flags — Known Issues & Future Work

Items that need attention but are not blocking current development.

---

## Data Sources

### CryptoPanic free tier has 24-hour delay
- **Status:** Workaround in place (age filter set to 48h)
- **Impact:** CryptoPanic articles arrive 24-25h delayed. Usable for trend sentiment, not breaking news detection. RSS feeds (CoinDesk, CoinTelegraph, Decrypt) provide real-time articles.
- **Fix options:**
  - Pay for CryptoPanic Pro ($49/mo) for real-time access
  - Replace with a different real-time news aggregator
  - Accept delay — sentiment trends don't need minute-level freshness

### Whale tracking (Etherscan) not wired up
- **Status:** `EtherscanCollector` code exists but `scripts/fetch/onchain.py` doesn't call it
- **Impact:** `whale_score` is always null, whale sub-weight gets renormalized out
- **Fix:** Need Etherscan API key (free registration) + exchange address labels from `brianleect/etherscan-labels` repo + add Etherscan fetch step to onchain CLI

### Coinalyze long/short ratio not fetched
- **Status:** `CoinalyzeCollector` code exists but not called by fetch scripts
- **Impact:** `long_short_score` is always 0 (25% of derivatives signal weight is dead)
- **Fix:** Need free Coinalyze API key (registration) + add to `scripts/fetch/derivatives.py`

### CoinMetrics limited coverage
- **Status:** Only BTC/ETH have exchange flow data. ~15 assets have MVRV + active addresses. ~45 assets have no on-chain data.
- **Impact:** On-chain signal only works for a fraction of the universe. Tiered approach in place (auto-renormalize weights for missing data).
- **Fix options:**
  - Add Santiment free tier (22 assets with real-time active addresses, 30 with lagged MVRV)
  - Add DeFiLlama TVL as activity proxy for 24 DeFi/L1 assets
  - Accept — on-chain is a slow-moving cycle indicator, not critical for 5-min trading

---

## Scoring & Weights

### Composite weights need backtesting optimization
- **Status:** Using default starting weights (`tech=0.35, deriv=0.25, onchain=0.15, mtf=0.10, sentiment=0.15`)
- **Impact:** Weights are educated guesses, not optimized for risk-adjusted returns
- **Fix:** Run grid search backtesting across historical data once all signal generators are producing real data

### Derivatives scores are small in calm markets
- **Status:** Combined scores typically 0.01-0.04 during calm conditions
- **Impact:** Derivatives signal is quiet most of the time (~52% of days), loud during extremes (~2% of days). This is by design — it's a risk management signal, not a trade initiator.
- **Evidence:** Real historical data scored in `data/derivatives_scores/real_historical_scored.csv`. Peak: TRUMP +0.44 (March 14, funding -0.17% + OI +67%).
- **Fix options:**
  - Rescale scoring functions (reduce normalization caps) to amplify signal
  - Upweight derivatives in composite for assets where it's the primary signal
  - Accept — wait for backtesting to determine optimal scaling

### Scoring functions may need rescaling
- **Status:** `score_funding_rate` caps at `rate / 0.002`. Typical funding (0.01%) produces score of 0.05. Extreme funding (0.20%) produces 1.0.
- **Impact:** The 0.002 cap was chosen to make 0.20% = extreme = score of 1.0. But if typical market conditions rarely exceed 0.05%, the signal is always in the low range.
- **Fix:** After collecting more historical data, adjust the cap based on actual funding rate distribution percentiles (e.g., set cap = 95th percentile of absolute funding rates).

---

## Infrastructure

### technicals/ module is a stub
- **Status:** Only `__init__.py` exists. SMA/BB regime detection still lives in `sma-prediction/trading_strategy.py`
- **Impact:** Technical signal is mocked (hardcoded 0.0) in composite scoring
- **Fix:** Extract `make_optimized_trading_decision` from `sma-prediction/trading_strategy.py`, wrap to output -1 to +1 score

### Pipeline orchestrator only handles sentiment
- **Status:** `pipeline/orchestrator.py` runs the sentiment pipeline (news fetch → classify → aggregate). Does not orchestrate derivatives/on-chain/composite.
- **Impact:** Full pipeline requires manual CLI steps. No automated 5-min loop for all signals.
- **Fix:** Extend orchestrator to call all collectors → signal generators → composite scorer in a unified tick.

### No automated scheduling
- **Status:** All scripts are manual CLI invocations
- **Impact:** Need to manually run fetch/score scripts
- **Fix:** Add cron job or persistent daemon that runs the full pipeline every 5 minutes
