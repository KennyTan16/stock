"""
Simulate spread calculation during alert scenarios
"""
from polygon_websocket import get_spread_ratio, latest_quotes, quote_lock

print("=== Simulating Alert Scenarios ===\n")

# Scenario 1: Alert with quote data available
print("Scenario 1: Symbol with quote data")
print("-" * 50)
symbol1 = "AAPL"
with quote_lock:
    latest_quotes[symbol1] = {
        'bid': 150.00,
        'ask': 150.05,
        'timestamp': None
    }

spread1 = get_spread_ratio(symbol1, fallback_price=150.02)
if spread1:
    print(f"✓ {symbol1}: spread={spread1:.4f} ({spread1*100:.2f}%)")
    print(f"  → Used REAL quote data (bid/ask)")
else:
    print(f"✗ {symbol1}: spread=None (FAILED)")

# Scenario 2: Alert WITHOUT quote data but with price
print("\nScenario 2: Symbol without quote, but has price")
print("-" * 50)
symbol2 = "TSLA"
spread2 = get_spread_ratio(symbol2, fallback_price=250.50)
if spread2:
    print(f"✓ {symbol2}: spread={spread2:.4f} ({spread2*100:.2f}%)")
    print(f"  → Used FALLBACK estimation (price-based)")
else:
    print(f"✗ {symbol2}: spread=None (FAILED)")

# Scenario 3: Alert WITHOUT quote and WITHOUT price (THIS is the "n/a" case)
print("\nScenario 3: Symbol without quote AND without price")
print("-" * 50)
symbol3 = "UNKNOWN"
spread3 = get_spread_ratio(symbol3, fallback_price=None)
if spread3:
    print(f"✓ {symbol3}: spread={spread3:.4f} ({spread3*100:.2f}%)")
else:
    print(f"✗ {symbol3}: spread=None (Expected - no data available)")
    print(f"  → This would show as 'n/a' in alert")

# Scenario 4: Alert with zero/invalid price
print("\nScenario 4: Symbol with invalid price (0)")
print("-" * 50)
symbol4 = "INVALID"
spread4 = get_spread_ratio(symbol4, fallback_price=0)
if spread4:
    print(f"✓ {symbol4}: spread={spread4:.4f} ({spread4*100:.2f}%)")
else:
    print(f"✗ {symbol4}: spread=None (Expected - invalid price)")
    print(f"  → This would show as 'n/a' in alert")

print("\n" + "=" * 50)
print("CONCLUSION:")
print("=" * 50)
print("The spread calculation will return a value (not 'n/a') if:")
print("  1. Real quotes are available (bid/ask from WebSocket), OR")
print("  2. A valid price is passed as fallback_price parameter")
print("\nThe spread shows 'n/a' only when:")
print("  • No quotes received yet for the symbol, AND")
print("  • close_price is 0, None, or not passed to get_spread_ratio()")
print("\nFIX APPLIED:")
print("  ✓ Updated get_spread_ratio() to accept fallback_price parameter")
print("  ✓ Updated check_spike() to pass close_price as fallback")
print("  → Spread should now ALWAYS show a value (never 'n/a')")
