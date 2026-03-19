# tests

Comprehensive test suite covering all pipeline modules. 263 tests total.

## Test File to Module Mapping

| Test File | Module Tested | Test Count |
|-----------|---------------|------------|
| `test_db.py` | `utils/db.py` | Connection lifecycle, table creation, CRUD, WAL mode, row factory |
| `test_news_sentiment.py` | `news_sentiment/` | Article models, processors (fetch, dedupe, prefilter, store), prompter (fast/batch classify) |
| `test_sentiment_score.py` | `sentiment_score/` | Scored article models, decay/weight computation, sector aggregation, batch scoring prompter |
| `test_orchestrator.py` | `pipeline/orchestrator.py` | Pipeline tick flow, batch timing, rate limiter, signal set output |
| `test_adapters.py` | `composite/adapters.py` | Sector-to-asset mapping, dual routing (NEAR, BTC), catalyst propagation |
| `test_composite_scorer.py` | `composite/scorer.py` | Weighted sum normalization, mixed signals |
| `test_composite_overrides.py` | `composite/scorer.py` | Soft penalties (funding, NUPL), hard clamps, catalyst boost, TF opposition, full decision flow |
| `test_derivatives_collectors.py` | `derivatives/collectors.py` | Binance, Bybit, Coinalyze collectors with mocked HTTP responses |
| `test_derivatives_models.py` | `derivatives/models.py` | Model validation, score clamping, from_sub_scores |
| `test_derivatives_processors.py` | `derivatives/processors.py` | Funding score, OI divergence, long/short ratio scoring |
| `test_onchain_collectors.py` | `on_chain/collectors.py` | CoinMetrics and Etherscan collectors with mocked HTTP responses |
| `test_onchain_models.py` | `on_chain/models.py` | Model validation, computed netflow, from_sub_scores |
| `test_onchain_processors.py` | `on_chain/processors.py` | Exchange flow, NUPL, active address, whale activity scoring |
| `test_build_sector_map.py` | `scripts/build_sector_map.py` | Category-to-sector mapping, classify_token, dual routing, full map build |
| `test_asset_discovery.py` | `scripts/discover_assets.py` | Universe filtering, perp detection, OI ranking, max_assets cutoff |
| `test_integration.py` | Cross-module | End-to-end pipeline integration with mocked sources |

## How to Run

```bash
# Run all tests
pytest tests/

# Run all tests with verbose output
pytest tests/ -v

# Run a specific test file
pytest tests/test_db.py

# Run a specific test class
pytest tests/test_composite_overrides.py::TestSoftOverrides

# Run a specific test
pytest tests/test_adapters.py::TestSectorSignalToAssetScore::test_dual_routed_near

# Run with coverage
pytest tests/ --cov=. --cov-report=term-missing
```

## Test Patterns

**Unit tests:** Each module is tested in isolation. External dependencies (LLM calls, HTTP APIs, database) are mocked.

**Mocked LLM:** Tests for the prompter modules mock `call_llm()` to return predictable JSON responses, testing parsing, validation, and fallback behavior without making real API calls.

**Mocked HTTP sources:** Collector tests (derivatives, on-chain) use `unittest.mock.patch` on `requests.get` to simulate exchange API responses.

**Integration tests:** `test_integration.py` tests the full pipeline flow with mocked news sources, verifying that articles flow through fetch, dedupe, classify, score, and aggregate stages correctly.
