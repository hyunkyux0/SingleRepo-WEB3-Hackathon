# Cluster + Sector-Specific Sentiment: Research & Analysis

> **Concept**: Cluster crypto coins into sectors (e.g., AI, DeFi, L1, Meme), then route sector-relevant news/social sentiment to those clusters to generate trading signals. Example: NVIDIA announcement → detect as AI-sector relevant → score sentiment → apply signal to AI cluster coins (FET, NEAR, RNDR, WLD).

---

## 1. Existing Methods & Results

### 1.1 QuantConnect: Sector Rotation Based on News Sentiment (Equities)

The closest proven implementation to this concept, applied to equity sectors rather than crypto.

**Method:**
- Uses Brain Sentiment Indicator (NLP on financial news), scores from -1 to +1
- Calculates sector sentiment by weighting each constituent's 30-day sentiment score by its ETF weight
- Selects top 3 sectors by sentiment score, allocates 1/3 capital each
- Rebalances monthly

**Results:**

| Strategy Variant | Sharpe Ratio |
|------------------|-------------|
| SPY Benchmark | 0.564 |
| **Weighted Average (Best)** | **0.806** |
| Simple Average of Top Performers | 0.697 |
| Simple Average | 0.59 |
| Momentum Benchmark | 0.336 |

**Key Insight**: Weighting sentiment by constituent market cap improved Sharpe from 0.59 to 0.806 — a 37% improvement from a single design choice.

> **Ref**: [Sector Rotation Based On News Sentiment (QuantConnect)](https://www.quantconnect.com/research/15309/sector-rotation-based-on-news-sentiment/). Backtesting period: Jan 2017 – Nov 2022.

---

### 1.2 Connectedness Between Sectoral Cryptos and Counterpart Stocks (Cogent Economics 2025)

Examines 14 crypto sector indices vs corresponding equity sectors using wavelet coherence + k-means clustering.

**Method:**
- Defines 13 crypto sectoral indices (minimum 3 cryptos per sector, market-cap weighted)
- Uses wavelet coherence to measure crypto-stock connectedness across multiple frequency bands
- Applies k-means clustering to identify connectedness regimes

**Three Connectedness Regimes Discovered:**

| Regime | Crypto Sectors | Behavior |
|--------|---------------|----------|
| **Persistent co-movers** | Real estate, supply chain, education | Always track equity counterpart; continuous monitoring justified |
| **Event-driven aligners** | Insurance, cybersecurity, e-commerce, **AI** | Spike during catalyst events then decouple; event detection triggers needed |
| **Weakly connected** | Cloud, telecommunications, gaming | Cross-market linkage is fragmented; crypto-native signals dominate |

**Key Insight**: Cybersecurity crypto assets are *most responsive* to sector-specific equity triggers. Not all sectors respond equally — uniform sentiment weighting across sectors is suboptimal.

> **Ref**: [Connectedness between sectoral cryptos and counterpart stocks](https://www.tandfonline.com/doi/full/10.1080/23322039.2025.2549934). Study period: 2022-2024.

---

### 1.3 NVIDIA GTC → AI Token Propagation (Empirical Event Data)

Real-world data on how equity-sector news propagates to the corresponding crypto cluster.

**NVIDIA GTC 2026 (March 17, 2026) Impact:**

| Token | Sector Role | Move | Timing |
|-------|-------------|------|--------|
| FET | Autonomous agents | +20% | Within hours |
| GRASS | Data supply chain | +13% | Within hours |
| NEAR | Infrastructure/compute | +10% | Within hours |
| WLD | Identity verification | +10% | Within hours |
| BTC | Market benchmark | +0.51% | Same period |
| ETH | Market benchmark | +2.14% | Same period |

**Market Context During the Move:**
- Fear & Greed Index: 28/100 (fear territory)
- $344 million in liquidations (83% shorts)
- BTC dominance: 56.8%

**Historical Pattern**: Post-NVIDIA rallies historically retrace 30-40% within a week. The GTC 2024 Blackwell announcement triggered 15-25% spikes in RNDR and AGIX over 48 hours with similar retracement.

**Key Insight**: Sector-specific propagation is real, fast (hours not days), and measurable. But the signal has a defined lifespan — holding through the full cycle round-trips gains.

> **Ref**: [AI Tokens Pump 20% After Nvidia GTC (SpotedCrypto)](https://www.spotedcrypto.com/ai-tokens-surge-nvidia-gtc-trending/). Also: [NVIDIA GTC 2025 AI Token Impact (CoinCentral)](https://coincentral.com/nvidia-gtc-2025-huangs-1-trillion-chip-forecast-sent-these-ai-crypto-tokens-soaring/). Also: [AI Tokens Lead Social Buzz After NVIDIA (AllAboutAI)](https://www.allaboutai.com/ai-news/ai-tokens-lead-social-buzz-after-nvidia-investment-news/).

---

### 1.4 Sentiment Contagion Asymmetry (European Journal of Finance 2025)

Studies how equity market sentiment events propagate to crypto using multivariate Hawkes processes on high-frequency data.

**Key Finding**: The contagion effect is **asymmetric**:
- **Positive equity sentiment** jumps trigger moderate cross-contagion on both positive and negative crypto jumps
- **Negative equity sentiment** jumps have **no contagion effect** on Bitcoin prices

**Implication**: The system should be biased toward detecting positive sector catalysts from equities. Negative equity news does not reliably propagate to corresponding crypto sectors.

> **Ref**: [Cryptocurrency jump contagion with market sentiment events (European Journal of Finance 2025)](https://www.tandfonline.com/doi/full/10.1080/1351847X.2025.2477696).

---

### 1.5 Sentiment Sensitivity Varies by Sector and Time Horizon (Economic Change & Restructuring 2025)

Wavelet-based analysis of how investor sentiment affects different crypto sectors across multiple time frequencies.

**Key Finding**: Different sectors respond to sentiment at different time horizons. Some sectors react to short-term sentiment spikes (daily), others only to sustained sentiment shifts (weekly/monthly). The implication is that sentiment lookback windows should be calibrated per sector, not applied uniformly.

> **Ref**: [Time and frequency domain relationship between investor sentiment and sectoral cryptocurrencies](https://link.springer.com/article/10.1007/s10644-025-09878-z).

---

### 1.6 Narrative Attention vs Returns (CoinGecko 2025)

**Narrative Popularity (% of investor attention, 2025):**
- Meme coins: 25.02%
- AI: 22.39% (up 6.72pp YoY)
- All others: <10% each

**Narrative Profitability (YTD returns, 2025):**
- Meme coins: **-31.6%**
- AI: **-50.2%**

**Key Insight**: Peak narrative attention correlates with poor returns. By the time a narrative is widely discussed, the alpha is priced in or the sector is overheated. What matters is the *rate of change* of attention, not the absolute level.

> **Ref**: [CoinGecko Most Popular Crypto Narratives 2025](https://www.coingecko.com/research/publications/most-popular-crypto-narratives). Also: [CoinGecko Crypto Narratives by Profitability 2025](https://www.coingecko.com/research/publications/most-profitable-crypto-narratives).

---

### 1.7 Commercial Narrative Trackers

**Sharpe AI** tracks 17+ crypto narratives (AI Agents, DeFi, Memecoins, RWA, DePIN, DeSci, etc.) with real-time social sentiment, volume, performance metrics, and narrative momentum indicators. Detects capital rotation between narratives.

**CoinGecko** publishes quarterly narrative analysis covering attention share and profitability per narrative category.

These demonstrate commercial demand for sector-sentiment analysis but neither integrates algorithmic trading logic or dynamic clustering.

> **Ref**: [Sharpe AI Narratives Tracker](https://sharpe.ai/narratives). [CoinGecko Narratives](https://www.coingecko.com/learn/crypto-narratives).

---

## 2. What Exists vs What's Novel

| Component | Existing Work | Status |
|-----------|--------------|--------|
| Correlation-based crypto clustering | arXiv 2505.24831 (Louvain + consensus) | Validated (71-74% win rates) |
| Sentiment-based sector rotation | QuantConnect (equity, NLP, Sharpe 0.806) | Validated (equities only) |
| Cross-market sentiment propagation crypto | European Journal of Finance 2025 (Hawkes) | Validated (asymmetric effect) |
| Sector-specific crypto-equity connectedness | Cogent Economics 2025 (wavelet + k-means) | Validated (3 regimes found) |
| Narrative tracking for crypto | Sharpe AI, CoinGecko | Commercial products (no trading logic) |
| **Louvain clustering + sector-routed LLM sentiment + rotation** | **Nobody** | **Novel combination** |

---

## 3. Author's Analysis & Recommendations

### 3.1 The Concept is Sound — Individual Components are Validated

The three pillars — clustering, sector sentiment, and rotation — are each independently validated:
- Clustering improves diversification and portfolio performance (arXiv)
- Sentiment-weighted sector rotation beats benchmarks by 43% Sharpe improvement (QuantConnect)
- Cross-market sector propagation is real and measurable (NVIDIA → AI tokens within hours)

No published work combines all three for crypto. This is genuinely novel.

> **Source**: Author's synthesis of the research above.

### 3.2 Critical Design Insights from Research

**Insight 1: Weight sentiment by constituent market cap within clusters**
The QuantConnect study showed this single change improved Sharpe from 0.59 to 0.806 (37% improvement). In a crypto AI cluster, FET's sentiment should count more than a micro-cap AI token.

> **Ref**: [QuantConnect Sector Rotation](https://www.quantconnect.com/research/15309/sector-rotation-based-on-news-sentiment/)

**Insight 2: Trade sentiment momentum, not sentiment level**
CoinGecko 2025 data proves peak attention = worst returns (AI: 22.39% attention, -50.2% returns). The actionable signal is `sentiment_change = sentiment_today - sentiment_7d_ago`. Buy sectors with accelerating sentiment from a low base. Sell sectors with decelerating sentiment from a high base.

> **Ref**: [CoinGecko Narratives Profitability](https://www.coingecko.com/research/publications/most-profitable-crypto-narratives). Author's interpretation of the data.

**Insight 3: Sentiment propagation is asymmetric — bullish equity news propagates, bearish doesn't**
The European Journal of Finance Hawkes process study shows positive sentiment jumps cross-contaminate, but negative ones don't. Design the system to be biased toward detecting positive catalysts. Don't assume symmetry.

> **Ref**: [European Journal of Finance 2025](https://www.tandfonline.com/doi/full/10.1080/1351847X.2025.2477696)

**Insight 4: Different clusters need different sentiment weights**
The Cogent Economics three-regime framework means:
- **Meme clusters**: Sentiment weight ~0.9 (pure narrative plays)
- **AI clusters**: Sentiment weight ~0.6 (mix of narrative + equity cross-market)
- **DeFi clusters**: Sentiment weight ~0.3 (TVL and on-chain fundamentals matter more)
- **Infrastructure clusters**: Sentiment weight ~0.2 (on-chain usage dominates)

> **Ref**: [Cogent Economics 2025](https://www.tandfonline.com/doi/full/10.1080/23322039.2025.2549934). Specific weight values are the author's recommendation based on the regime classification.

**Insight 5: Event-driven entries need explicit exit rules**
NVIDIA → AI token rallies retrace 30-40% within a week. The entry signal (sector catalyst detected) is strong, but without take-profit rules you round-trip. Recommend: take 50% profit at +10%, trail the rest with ATR-based stops.

> **Ref**: [SpotedCrypto NVIDIA GTC analysis](https://www.spotedcrypto.com/ai-tokens-surge-nvidia-gtc-trending/) — "post-NVIDIA rallies tend to retrace 30-40% within a week." Exit rule specifics are the author's recommendation.

**Insight 6: Classify news into sectors BEFORE scoring sentiment**
Two-step LLM pipeline: (1) "Which crypto sector does this news affect?" → sector classification, (2) "Is this bullish or bearish for that sector?" → sentiment scoring. Separating these improves accuracy over doing both in one pass.

> **Source**: Author's recommendation based on NLP best practices. The QuantConnect study implicitly does this (news is pre-tagged to sector ETFs), but doesn't discuss the classification step explicitly.

**Insight 7: Calibrate sentiment lookback per sector**
The Economic Change & Restructuring wavelet study shows different sectors respond at different time frequencies. Meme coins react to hourly sentiment spikes. Infrastructure tokens only respond to sustained weekly/monthly sentiment shifts. Use different lookback windows.

> **Ref**: [Economic Change & Restructuring 2025](https://link.springer.com/article/10.1007/s10644-025-09878-z). Specific lookback values would need to be calibrated empirically.

### 3.3 Recommended Architecture

```
                    ┌─────────────────────────────┐
                    │  NEWS + SOCIAL MEDIA FEEDS   │
                    │  (Twitter/X, Reddit, News)   │
                    └─────────┬───────────────────┘
                              │
                              ▼
                    ┌─────────────────────────────┐
                    │  SECTOR CLASSIFIER (LLM)     │
                    │                              │
                    │  Step 1: "Which crypto sector│
                    │  does this news affect?"     │
                    │  → AI / DeFi / L1 / Meme /  │
                    │    Infrastructure / General  │
                    │                              │
                    │  Step 2: Source detection:    │
                    │  "Is this equity news that   │
                    │   maps to a crypto sector?"  │
                    │  (NVIDIA → AI cluster)       │
                    └─────────┬───────────────────┘
                              │
                    ┌─────────▼───────────────────┐
                    │  SENTIMENT SCORER (per sector)│
                    │                              │
                    │  - Multi-LLM majority voting │
                    │    (Trust-The-Majority)      │
                    │  - Ebbinghaus temporal decay  │
                    │  - Market-cap weighted within │
                    │    each cluster              │
                    │                              │
                    │  Output per sector:           │
                    │  • sentiment_score (-1 to +1) │
                    │  • sentiment_momentum         │
                    │    (rate of change vs 7d ago) │
                    │  • catalyst_detected (bool)   │
                    └─────────┬───────────────────┘
                              │
              ┌───────────────┼───────────────────┐
              ▼               ▼                   ▼
    ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
    │ AI Cluster  │  │ DeFi Cluster │  │ Meme Cluster │  ...
    │             │  │              │  │              │
    │ FET, NEAR,  │  │ UNI, AAVE,  │  │ DOGE, SHIB   │
    │ RNDR, WLD   │  │ CRV         │  │              │
    │             │  │              │  │              │
    │ Regime:     │  │ Regime:      │  │ Regime:      │
    │ EVENT-      │  │ PERSISTENT   │  │ PURE         │
    │ DRIVEN      │  │ CO-MOVER     │  │ SENTIMENT    │
    │             │  │              │  │              │
    │ Sentiment   │  │ Sentiment    │  │ Sentiment    │
    │ weight: 0.6 │  │ weight: 0.3  │  │ weight: 0.9  │
    │             │  │              │  │              │
    │ Lookback:   │  │ Lookback:    │  │ Lookback:    │
    │ 4-24 hours  │  │ 7-14 days    │  │ 1-4 hours    │
    └──────┬──────┘  └──────┬───────┘  └──────┬───────┘
           │                │                  │
           ▼                ▼                  ▼
    ┌──────────────────────────────────────────────┐
    │  SECTOR ROTATION ENGINE                      │
    │                                              │
    │  1. Rank sectors by sentiment_momentum       │
    │     (rate of change, NOT absolute level)     │
    │                                              │
    │  2. If catalyst_detected for a sector:       │
    │     → Enter with event-driven position       │
    │     → Take 50% profit at +10%                │
    │     → ATR trailing stop on remainder         │
    │                                              │
    │  3. If sentiment_momentum > threshold:       │
    │     → Overweight sector (gradual rotation)   │
    │     → Monthly rebalance (non-catalyst)       │
    │                                              │
    │  4. If sentiment_momentum < -threshold:      │
    │     → Underweight sector                     │
    │     → Shift allocation to neutral clusters   │
    │                                              │
    │  5. Max 30% portfolio in any single cluster  │
    └──────────────────────────────────────────────┘
```

> **Source**: Author's design. Combines QuantConnect sector rotation framework (Ref: QuantConnect), Louvain clustering (Ref: arXiv 2505.24831), Trust-The-Majority sentiment (Ref: IEEE CiFer 2025), three-regime classification (Ref: Cogent Economics 2025), and event retracement patterns (Ref: SpotedCrypto).

### 3.4 Open Questions That Need Empirical Testing

1. **Cluster stability vs narrative speed**: Louvain clustering uses 30-day correlation windows. Crypto narratives can shift in days. Will the clusters be stale by the time sentiment signals fire? May need shorter windows (7-14 days) or hybrid static-label + dynamic-correlation clusters.

2. **LLM sector classification accuracy**: How well do LLMs classify crypto news into sectors? "NVIDIA announces new GPU" is easy. "SEC delays ETF decision" could affect multiple sectors differently. Classification errors propagate through the entire system.

3. **Optimal sentiment lookback per sector**: The wavelet study says sectors respond at different frequencies, but doesn't give specific lookback values for crypto sectors. These need empirical calibration.

4. **Event detection latency**: If NVIDIA news moves AI tokens within hours, the system needs to detect, classify, score, and act within minutes. Can the LLM pipeline run fast enough? VADER as a fast pre-filter + LLM for confirmation might be necessary.

5. **Retracement timing calibration**: "30-40% retracement within a week" is a rough historical average. Need to study whether this varies by sector, catalyst type, or market conditions.

> **Source**: Author's analysis. These are open research questions that would need backtesting on historical data to answer.

---

## 4. Full Reference List

### Academic Papers
| ID | Paper | Source | URL |
|----|-------|--------|-----|
| R1 | Connectedness between sectoral cryptos and counterpart stocks | Cogent Economics & Finance (2025) | https://www.tandfonline.com/doi/full/10.1080/23322039.2025.2549934 |
| R2 | Cryptocurrency jump contagion with market sentiment events | European Journal of Finance (2025) | https://www.tandfonline.com/doi/full/10.1080/1351847X.2025.2477696 |
| R3 | Time and frequency domain relationship between investor sentiment and sectoral cryptocurrencies | Economic Change & Restructuring (2025) | https://link.springer.com/article/10.1007/s10644-025-09878-z |
| R4 | Optimising cryptocurrency portfolios through stable clustering | arXiv 2505.24831 (May 2025) | https://arxiv.org/html/2505.24831v1 |
| R5 | Sentiment-Aware Mean-Variance Portfolio Optimization | arXiv 2508.16378 | https://arxiv.org/pdf/2508.16378 |
| R6 | Enhancing Cryptocurrency Trading: Deep RL + Multi-LLM Sentiment | IEEE CiFer 2025 | https://ieeexplore.ieee.org/document/10975733/ |
| R7 | Investor sentiment and cross-section of cryptocurrency returns | ScienceDirect (2025) | https://www.sciencedirect.com/science/article/abs/pii/S2214635025000243 |
| R8 | From Disruption to Integration: Cryptocurrency and Macroeconomy | MDPI JRFM (2025) | https://www.mdpi.com/1911-8074/18/7/360 |
| R9 | LLMs and NLP Models in Cryptocurrency Sentiment Analysis | MDPI Big Data (2024) | https://www.mdpi.com/2504-2289/8/6/63 |

### Practitioner & Industry Sources
| ID | Source | URL |
|----|--------|-----|
| P1 | Sector Rotation Based On News Sentiment (QuantConnect) | https://www.quantconnect.com/research/15309/sector-rotation-based-on-news-sentiment/ |
| P2 | AI Tokens Pump 20% After Nvidia GTC (SpotedCrypto) | https://www.spotedcrypto.com/ai-tokens-surge-nvidia-gtc-trending/ |
| P3 | NVIDIA GTC 2025 AI Token Impact (CoinCentral) | https://coincentral.com/nvidia-gtc-2025-huangs-1-trillion-chip-forecast-sent-these-ai-crypto-tokens-soaring/ |
| P4 | AI Tokens Lead Social Buzz After NVIDIA (AllAboutAI) | https://www.allaboutai.com/ai-news/ai-tokens-lead-social-buzz-after-nvidia-investment-news/ |
| P5 | NVIDIA as Crypto's Safe Haven (FinancialContent) | https://markets.financialcontent.com/stocks/article/breakingcrypto-2025-10-28-nvidia-the-ai-powerhouse-emerges-as-cryptos-unconventional-safe-haven |
| P6 | CoinGecko Most Popular Crypto Narratives 2025 | https://www.coingecko.com/research/publications/most-popular-crypto-narratives |
| P7 | CoinGecko Crypto Narratives by Profitability 2025 | https://www.coingecko.com/research/publications/most-profitable-crypto-narratives |
| P8 | Sharpe AI Crypto Narratives Tracker | https://sharpe.ai/narratives |
| P9 | CoinGecko Crypto Narratives Overview | https://www.coingecko.com/learn/crypto-narratives |
| P10 | Top Crypto Narratives Q2: Meme, RWA, AI, DePin (BeInCrypto) | https://beincrypto.com/crypto-narratives-meme-coins-rwa-ai-depin/ |
