# scripts

Utility scripts for data preparation and asset discovery. These are run manually or as part of initial setup, not during live pipeline operation.

## Files

### build_sector_map.py

Builds `config/sector_map.json` from CoinGecko category data. Fetches each token's categories from the CoinGecko API and maps them to one of 6 canonical sectors.

**CoinGecko category-to-sector mapping (`CATEGORY_TO_SECTOR`):**
- AI/Compute: artificial-intelligence, ai-agents, machine-learning, gpu
- DeFi: decentralized-finance-defi, decentralized-exchange, lending-borrowing, yield-farming, yield-aggregator, liquid-staking, oracle, real-world-assets-rwa
- L1/Infrastructure: layer-1, layer-2, smart-contract-platform, interoperability, zero-knowledge-zk, modular-blockchain, infrastructure
- Meme: meme-token, dog-themed-coins, cat-themed-coins, pump-fun, political-meme
- Store of Value: store-of-value, gold-backed, privacy-coins, bitcoin-ecosystem

**Dual-route overrides (`DUAL_ROUTE_OVERRIDES`):**
- NEAR: secondary sector = ai_compute
- BTC: secondary sector = store_of_value

If a token's secondary sector would be the same as its primary, the secondary is set to null.

**Key functions:**
- `_fetch_coingecko_categories(tickers)` -- Queries CoinGecko API with 2-second rate limiting
- `classify_token(ticker, categories)` -- Maps categories to primary/secondary sectors
- `build_sector_map(universe)` -- Full pipeline: universe list to sector map dict

**Usage:**

```bash
# Build and write to config/sector_map.json
python scripts/build_sector_map.py

# Preview output without writing
python scripts/build_sector_map.py --dry-run
```

### discover_assets.py

Discovers which assets in the universe have perpetual futures contracts on Binance, ranks them by open interest, and produces `asset_registry` rows.

**Process:**
1. Loads the asset universe from `config/asset_universe.json`
2. Queries Binance Futures `exchangeInfo` for available PERPETUAL contracts
3. For each matched asset, fetches current open interest
4. Ranks by OI and applies a `max_assets` cutoff (default: 40)
5. Returns a list of dicts ready for `DataStore.save_asset_registry()`

Assets without perpetual contracts receive an `excluded_reason`. Assets beyond the OI rank cutoff are also excluded.

**Usage:**

```bash
python scripts/discover_assets.py
```

Output prints the number of active vs excluded assets and shows the top 10 by OI rank.
