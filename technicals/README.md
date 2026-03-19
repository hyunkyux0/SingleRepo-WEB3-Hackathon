# technicals

Stub module for technical analysis signals. Not yet implemented.

## Current Status

This module contains only an `__init__.py` with a placeholder docstring. No functional code exists here yet.

## Planned Functionality

The technical analysis logic currently lives in `sma-prediction/trading_strategy.py` and needs to be refactored into this module. Planned components:

- **SMA (Simple Moving Average):** Trend detection using short/long moving average crossovers
- **Bollinger Bands:** Volatility-based overbought/oversold detection
- **Regime detection:** Market regime classification (trending, ranging, volatile) extracted from the existing trading strategy

The output should conform to the same [-1, +1] scoring convention used by the `derivatives` and `on_chain` modules, producing a normalized technical score for consumption by the `composite` scorer.

## Related Code

- `sma-prediction/trading_strategy.py` -- Current technical analysis implementation
- `sma-prediction/backtest_sma.py` -- Backtesting framework
- `sma-prediction/multi_cryptocurrency_optimizer.py` -- Multi-asset portfolio optimization
- `sma-prediction/prices.py` -- Price data fetching
