# Test Files

This directory contains all test and diagnostic scripts for the stock alert system.

## Diagnostic Scripts

### Quote & Spread Testing
- **`check_spread.py`** - Verify spread calculation logic with different scenarios
- **`check_polygon_plan.py`** - Verify Polygon.io API access and quote entitlement
- **`test_quotes.py`** - Test quote reception from WebSocket
- **`test_spread_calc.py`** - Test spread calculations with real quote data
- **`test_spread_scenarios.py`** - Simulate different alert scenarios for spread calculation
- **`test_all_feeds.py`** - Test all Polygon.io feeds (trades, quotes, aggregates)
- **`test_websocket_detailed.py`** - Detailed WebSocket connection testing

## Integration Tests
- **`test_websocket_alerts.py`** - Test live alert generation
- **`test_live_telegram.py`** - Test Telegram notifications
- **`test_simple.py`** - Simple smoke test
- **`test_direct.py`** - Direct API testing
- **`test_ascii.py`** - ASCII formatting tests

## Running Tests

### Individual Tests
```bash
python tests/check_spread.py
python tests/test_spread_scenarios.py
```

### With Debug Flags
```bash
$env:DEBUG_QUOTES="1"; python tests/test_quotes.py
$env:STAGE2_DEBUG="1"; python polygon_websocket.py
```

## Note
Most test files can be run independently. Some may require:
- Polygon.io API key (set in parent `polygon_websocket.py`)
- Active market hours for live data testing
- Telegram credentials for notification testing
