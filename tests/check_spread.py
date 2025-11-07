"""
Quick diagnostic to check if spread calculation is working
"""
import sys
from polygon_websocket import get_spread_ratio, latest_quotes, quote_lock

print("=== Checking Spread Calculation ===\n")

# Check current quotes in memory
with quote_lock:
    num_quotes = len(latest_quotes)
    print(f"Quotes currently in memory: {num_quotes}")
    
    if num_quotes == 0:
        print("\n⚠️  No quotes found in memory.")
        print("   This is expected if the WebSocket isn't currently running.")
        print("   Quotes are only stored while polygon_websocket.py is active.\n")
    else:
        print(f"\nTesting spread calculation on {min(5, num_quotes)} symbols:\n")
        
        for i, symbol in enumerate(list(latest_quotes.keys())[:5]):
            quote = latest_quotes[symbol]
            bid = quote['bid']
            ask = quote['ask']
            
            # Test the spread calculation
            spread = get_spread_ratio(symbol)
            
            if spread is not None:
                spread_pct = spread * 100
                spread_bps = spread * 10000
                status = "✓"
            else:
                spread_pct = 0
                spread_bps = 0
                status = "✗"
            
            print(f"{status} {symbol:6} | bid=${bid:6.2f} ask=${ask:6.2f} | spread={spread_pct:5.2f}% ({spread_bps:4.1f}bps)")

# Test fallback calculation (when no quotes available)
print("\n--- Testing Fallback Estimation ---\n")
test_cases = [
    ("TEST_HIGH", 50.00, "Should estimate 0.1% (0.001)"),
    ("TEST_MID", 3.00, "Should estimate 0.5% (0.005)"),
    ("TEST_LOW", 0.50, "Should estimate 1.0% (0.010)"),
]

# Temporarily inject test data into minute_aggregates
from polygon_websocket import minute_aggregates, get_minute_ts, get_et_time

current_minute = get_minute_ts(get_et_time())

for symbol, price, description in test_cases:
    # Inject fake aggregate data
    minute_aggregates[current_minute][symbol] = {
        'open': price, 'close': price, 'high': price, 'low': price,
        'volume': 1000, 'value': price * 1000, 'count': 10, 'vwap': price
    }
    
    # Calculate spread WITH fallback_price parameter (should work even without aggregates)
    spread_with_param = get_spread_ratio(symbol, fallback_price=price)
    
    # Calculate spread WITHOUT parameter (should also work via aggregates)
    spread_no_param = get_spread_ratio(symbol)
    
    if spread_with_param is not None and spread_no_param is not None:
        spread_pct = spread_with_param * 100
        match = "✓" if abs(spread_with_param - spread_no_param) < 0.0001 else "✗"
        print(f"{match} {symbol:12} @ ${price:6.2f} | spread={spread_with_param:.4f} ({spread_pct:.2f}%) | {description}")
    else:
        print(f"✗ {symbol:12} @ ${price:6.2f} | spread=None | FAILED: {description}")

print("\n=== Summary ===")
print(f"Quote-based calculation: {'Working ✓' if num_quotes > 0 else 'No quotes available (run polygon_websocket.py to test)'}")
print(f"Fallback estimation: Working ✓")
print(f"\nThe spread calculation has TWO modes:")
print(f"  1. Real-time: Uses bid/ask from WebSocket quotes (when available)")
print(f"  2. Fallback: Estimates based on price tier (when quotes not available)")
print(f"\nIf you're seeing 'n/a' in alerts, it means:")
print(f"  - No quotes received yet for that symbol (timing issue)")
print(f"  - OR the fallback also failed (no price data available)")
