# sma-prediction

Technical analysis strategy module with dual-mode adaptive trading. Detects market regime (TREND vs RANGE) and applies the appropriate strategy: SMA crossover for trending markets, Bollinger Band mean reversion for range-bound markets.

This module is the original technical analysis engine. Parts of its functionality are being refactored into the `technicals/` module for integration with the composite scoring pipeline.

## Modules

### trading_strategy.py

Core trading logic with three layers:

**Regime Detection** (`detect_market_regime`):
- Computes 50-period MA slope normalized by price. Slope above `slope_threshold` indicates a trend.
- Computes 20-period Bollinger Band width normalized by price. Width above `bb_width_threshold` indicates trending volatility.
- Returns `"trend"` if either indicator fires, `"range"` otherwise.

**SMA Crossover** (`sma_trading_decision`):
- Calculates short and long simple moving averages.
- BUY on golden cross (short SMA crosses above long SMA).
- SELL on death cross (short SMA crosses below long SMA).
- Momentum confirmation: BUY/SELL when SMA difference exceeds 2% even without crossover.

**Bollinger Band Mean Reversion** (`mean_reversion_decision`):
- BUY when price drops below the lower Bollinger Band.
- SELL when price reaches the exit target (entry price + exit_ratio * band width).
- Configurable entry threshold and exit ratio per asset.

**Unified Entry Point** (`make_optimized_trading_decision`):
- Loads per-crypto optimized parameters from `output/optimized_strategy_parameters.json`.
- Detects regime, then delegates to the appropriate strategy.
- Falls back to default parameters if no optimized config exists for the asset.

### multi_cryptocurrency_optimizer.py

Grid search optimizer for SMA strategy parameters across multiple cryptocurrencies.

- Fetches OHLC data from Kraken API for 30+ crypto pairs.
- Tests parameter combinations: SMA short/long windows, slope thresholds, BB width thresholds, entry thresholds, exit ratios.
- Evaluates each combination via backtesting with commission costs.
- Scores using multi-objective criteria: return percentage, Sharpe ratio, Sortino ratio, Calmar ratio, win rate.
- Outputs optimized parameters to `output/optimized_strategy_parameters.json`.
- Generates portfolio allocation recommendations to `output/force_currency_allocation.json`.
- Organizes cryptocurrencies into priority tiers by market cap and liquidity.

### backtest_sma.py

Backtesting framework for evaluating SMA trading strategies against historical data.

- `SMABacktester` class: Runs a strategy over a price series with configurable initial capital and commission (default 0.1%).
- Tracks position entry/exit, portfolio value over time, and trade log.
- Computes performance metrics:
  - Return percentage
  - Sharpe ratio (annualized, risk-free rate adjustable)
  - Sortino ratio (downside deviation only)
  - Calmar ratio (return / max drawdown)
  - Maximum drawdown
  - Number of trades, win rate
- Supports visualization of equity curve, drawdowns, and trade markers.

### prices.py

Price data fetching from Kraken public API.

- `fetch_kraken_ohlc(pair, interval)` -- Fetches full OHLC history for a pair. Returns list of `[timestamp, open, high, low, close, vwap, volume, count]`.
- `fetch_kraken_ohlc_recent(pair, interval, count)` -- Fetches recent OHLC data limited to a count of periods.
- `save_prices_to_csv(data, filename)` -- Saves OHLC data to CSV for local caching.
- `load_prices_from_csv(filename)` -- Loads previously saved OHLC data.
- Supports all Kraken intervals: 1, 5, 15, 30, 60, 240, 1440, 10080, 21600 minutes.

## Usage

```bash
# Run the full optimizer across all supported cryptos
python multi_cryptocurrency_optimizer.py

# Results are written to:
#   ../output/optimized_strategy_parameters.json
#   ../output/force_currency_allocation.json
```

## Output

Optimized parameters are stored in `output/optimized_strategy_parameters.json` with per-crypto entries containing:

- `short_window`, `long_window` -- SMA periods
- `slope_threshold`, `bb_width_threshold` -- Regime detection thresholds
- `bb_window`, `bb_std` -- Bollinger Band parameters
- `entry_threshold`, `exit_ratio` -- Mean reversion entry/exit configuration
- `return_pct`, `sharpe_ratio`, `sortino_ratio`, `calmar_ratio` -- Performance metrics
- `num_trades`, `win_rate`, `max_drawdown` -- Trade statistics
