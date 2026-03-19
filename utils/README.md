# utils

Shared utilities for LLM access and database persistence. All modules in the project import from this package rather than configuring providers or database connections directly.

## Files

### llm_client.py

Universal LLM client with a two-provider hierarchy:

1. **Primary: OpenRouter** -- uses the OpenAI-compatible API at `https://openrouter.ai/api/v1`
2. **Fallback: OpenAI** -- activated when the primary fails after retries

Two model paths are supported:

| Path | Environment Variable | Use Case |
|------|---------------------|----------|
| Standard (batch) | `OPENROUTER_MODEL` | Bulk article classification and scoring |
| Fast (real-time) | `OPENROUTER_MODEL_FAST` | Catalyst classification with low latency |

**Key function: `call_llm()`**

```python
from utils.llm_client import call_llm

content, usage_dict, llm_label = call_llm(
    system_prompt="You are a classifier.",
    user_prompt="Classify this article...",
    temperature=0.2,
    max_completion_tokens=500,
    fast=True,  # use OPENROUTER_MODEL_FAST
)
```

Returns a tuple of `(response_text, usage_dict, "provider/model")`.

Retry behavior:
- Primary provider: 2 attempts (initial + 1 retry)
- Fallback provider: 1 attempt
- Raises `RuntimeError` if all providers fail

Other public functions:
- `get_llm_client()` -- returns `(OpenAI_client, model, provider)` for the batch model
- `get_llm_client_fast()` -- returns the fast-path client, falling back to batch
- `get_llm_label()` -- returns a human-readable `"provider/model"` string

### db.py

Thread-safe SQLite wrapper using WAL journal mode. All database access goes through the `DataStore` class so that a future migration (e.g., to RDS or DynamoDB) requires changes in only one place.

**Usage:**

```python
from utils.db import DataStore

with DataStore() as db:
    db.execute("INSERT INTO signal_log (timestamp, asset) VALUES (?, ?)", (ts, "BTC/USD"))
    rows = db.fetchall("SELECT * FROM signal_log WHERE asset = ?", ("BTC/USD",))
```

**Tables created on init:**

| Table | Purpose |
|-------|---------|
| `articles` | News articles with LLM classification fields |
| `signal_log` | Composite scoring results per asset per tick |
| `asset_registry` | Active assets with perpetual contract availability |
| `funding_rates` | Funding rate snapshots from derivatives exchanges |
| `open_interest` | Open interest snapshots |
| `long_short_ratio` | Long/short ratio data from aggregators |
| `on_chain_daily` | Daily on-chain metrics (exchange flows, MVRV, NUPL, active addresses) |
| `whale_transfers` | Large transfers to/from exchange addresses |
| `ohlc_data` | Price candle data (multi-interval) |

**Key features:**
- Context manager support (`with DataStore() as db:`)
- `sqlite3.Row` row factory for dict-style access
- WAL journal mode for concurrent read performance
- Domain-specific helpers: `save_funding_rates()`, `save_on_chain_daily()`, `log_signal()`, `get_active_assets()`, `prune_old_data()`, etc.
- Default database path: `data/trading_bot.db` relative to project root
- Auto-creates parent directories

**Data retention (via `prune_old_data()`):**
- funding_rates, open_interest, long_short_ratio: 30 days
- whale_transfers: 90 days
- ohlc_data, on_chain_daily: 365 days

## Environment Variables

Set these in a `.env` file at the project root:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes (primary) | API key for OpenRouter |
| `OPENROUTER_MODEL` | Yes (primary) | Batch model name (e.g., `hunter-alpha`) |
| `OPENROUTER_MODEL_FAST` | No | Fast model name (e.g., `gpt-5.4-nano`); falls back to batch model |
| `OPENAI_API_KEY` | No (fallback) | OpenAI API key used when OpenRouter fails |
| `OPENAI_MODEL` | No | OpenAI model name; defaults to `gpt-5.4-nano` |
