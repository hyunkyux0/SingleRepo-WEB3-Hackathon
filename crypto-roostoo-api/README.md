# crypto-roostoo-api

Interface with the Roostoo cryptocurrency exchange. Provides authenticated access to account balances, order management, and market data endpoints.

## Authentication

All authenticated endpoints use **HMAC-SHA256** request signing:

1. Build a query string from sorted request parameters.
2. Sign the query string with your API secret using HMAC-SHA256.
3. Send the signature in the `MSG-SIGNATURE` header and your API key in the `RST-API-KEY` header.

Server timestamps are fetched from the Roostoo `/v3/serverTime` endpoint to avoid clock-sync issues. If the server is unreachable, local time is used as a fallback.

## Modules

### balance.py

Account balance management.

- `get_balance()` -- Retrieves the full account balance (SpotWallet). Returns a dict with Free and Lock amounts per coin. Authenticated via `RCL_TopLevelCheck`.
- `test_get_balance()` -- Prints all coin balances to stdout.

### trades.py

Order placement, query, and cancellation.

- `place_order(pair_or_coin, side, quantity, price=None, order_type=None)` -- Places a new order. Accepts a coin symbol (e.g., `"BTC"`) or a full pair (e.g., `"BTC/USD"`). Auto-detects MARKET vs LIMIT based on whether `price` is provided. Validates that LIMIT orders include a price.
- `query_order(order_id=None, pair=None, pending_only=None)` -- Queries orders by order ID or pair. Can filter to pending orders only.
- `cancel_order(order_id=None, pair=None)` -- Cancels orders by order ID or pair. If neither is provided, cancels all pending orders.
- `test_place_order(testnum)` -- Interactive and preset test scenarios (0 = interactive, 1 = LIMIT sell, 2 = MARKET buy, 3 = invalid LIMIT).
- `test_query_order(coin=None)` -- Queries pending orders for a given coin (default: BTC).
- `test_cancel_order(coin=None)` -- Cancels pending orders for a given coin.

### utilities.py

Public and lightly-authenticated utility endpoints.

- `get_server_timestamp()` -- Returns the exchange server timestamp as a string. Falls back to local time on failure.
- `check_server_time()` -- Returns the full server time response (`RCL_NoVerification`).
- `get_exchange_info()` -- Returns exchange status, initial wallet configuration, and available trading pairs (`RCL_NoVerification`).
- `get_ticker(pair=None)` -- Returns market ticker data. If `pair` is provided, returns data for that pair only; otherwise returns all pairs. Requires a timestamp parameter (`RCL_TSCheck`).

## Environment Variables

Create a `.env` file in this directory (see `.env.example`):

```env
ROOSTOO_API_KEY=your_roostoo_api_key
ROOSTOO_API_SECRET=your_roostoo_api_secret
BASE_URL=https://api.roostoo.com
```

## Usage Examples

```python
from balance import get_balance
from trades import place_order, query_order, cancel_order
from utilities import get_ticker, get_exchange_info

# Check account balance
balance = get_balance()
spot = balance.get("SpotWallet", {})
for coin, amounts in spot.items():
    print(f"{coin}: Free={amounts['Free']}, Locked={amounts['Lock']}")

# Get current BTC price
ticker = get_ticker(pair="BTC/USD")
btc_price = ticker["Data"]["BTC/USD"]["LastPrice"]

# Place a market buy order
result = place_order("ETH", side="BUY", quantity=0.1)

# Place a limit sell order
result = place_order("BNB", side="SELL", quantity=0.5, price=950.0)

# Query pending orders
orders = query_order(pair="ETH/USD", pending_only=True)

# Cancel all pending orders for a pair
cancel_order(pair="ETH/USD")
```

## Testing

Run the interactive API test script:

```bash
python manual_api_test.py
```

This exercises all endpoints: server time, exchange info, ticker data, balance, order placement, query, and cancellation.
