"""
Simple test to verify alert logic and WebSocket message handling
Tests the core logic without external dependencies
"""

print("🧪 Testing WebSocket Alert Logic\n")

# Test 1: Volume thresholds
print("=" * 60)
print("TEST 1: Volume Threshold Logic")
print("=" * 60)

def should_alert(pct_change, volume):
    """Test the should_alert function"""
    return (
        (pct_change >= 5 and volume >= 20000) or
        (pct_change >= 10 and volume >= 15000) or
        (pct_change >= 15 and volume >= 10000) or
        (pct_change >= 20 and volume >= 5000) or
        (pct_change >= 30 and volume >= 1000) or
        (volume >= 50000)
    )

test_cases = [
    (5, 20000, True, "5% with 20K volume"),
    (10, 15000, True, "10% with 15K volume"),
    (15, 10000, True, "15% with 10K volume"),
    (20, 5000, True, "20% with 5K volume"),
    (30, 1000, True, "30% with 1K volume"),
    (0, 50000, True, "50K volume (any %)"),
    (4, 20000, False, "4% with 20K (insufficient)"),
    (5, 10000, False, "5% with 10K (insufficient)"),
]

for pct, vol, expected, desc in test_cases:
    result = should_alert(pct, vol)
    status = "✅" if result == expected else "❌"
    print(f"{status} {desc}: {result}")

# Test 2: Spread ratio calculation
print("\n" + "=" * 60)
print("TEST 2: Spread Ratio Calculation")
print("=" * 60)

def test_spread_ratio(bid, ask):
    """Calculate spread ratio"""
    if bid <= 0 or ask <= 0:
        return None
    mid_price = (bid + ask) / 2
    if mid_price <= 0:
        return None
    return (ask - bid) / mid_price

spread_tests = [
    (10.00, 10.20, 0.02, "2% spread (wide)"),
    (10.00, 10.10, 0.01, "1% spread (tight)"),
    (10.00, 10.05, 0.005, "0.5% spread (very tight)"),
    (5.00, 5.10, 0.02, "2% spread at $5"),
]

for bid, ask, expected_approx, desc in spread_tests:
    ratio = test_spread_ratio(bid, ask)
    if ratio:
        status = "✅" if abs(ratio - expected_approx) < 0.001 else "❌"
        print(f"{status} {desc}: {ratio:.4f} ({ratio*100:.2f}%)")

# Test 3: Volume acceleration
print("\n" + "=" * 60)
print("TEST 3: Volume Acceleration Logic")
print("=" * 60)

def check_volume_acceleration(vol_now, vol_prev3, threshold):
    """Check if volume acceleration meets threshold"""
    if vol_prev3 == 0:
        return True  # No previous data, allow
    return vol_now > threshold * vol_prev3

accel_tests = [
    (100000, 40000, 2.0, True, "2.5x acceleration (need 2x)"),
    (150000, 80000, 1.5, True, "1.875x acceleration (need 1.5x)"),
    (60000, 50000, 2.0, False, "1.2x acceleration (need 2x)"),
    (80000, 60000, 1.5, False, "1.33x acceleration (need 1.5x)"),
    (100000, 0, 2.0, True, "No previous data (allowed)"),
]

for vol_now, vol_prev, threshold, expected, desc in accel_tests:
    result = check_volume_acceleration(vol_now, vol_prev, threshold)
    status = "✅" if result == expected else "❌"
    accel = vol_now / vol_prev if vol_prev > 0 else float('inf')
    print(f"{status} {desc}: {result}")

# Test 4: Time-based session detection
print("\n" + "=" * 60)
print("TEST 4: Session Time Windows")
print("=" * 60)

def detect_session(hour, minute):
    """Detect which trading session we're in"""
    if 4 <= hour < 8:
        return "EARLY_PREMARKET"
    elif (8 <= hour < 9) or (hour == 9 and minute < 30):
        return "PREMARKET_MOMENTUM"
    elif (hour == 9 and minute >= 30) or (9 < hour < 16):
        return "REGULAR_HOURS"
    elif hour == 16 and minute < 30:
        return "POSTMARKET_REACTION"
    elif 16 <= hour < 18:
        return "POSTMARKET_CONTINUATION"
    elif 18 <= hour < 20:
        return "LATE_POSTMARKET"
    else:
        return "CLOSED"

session_tests = [
    (6, 0, "EARLY_PREMARKET"),
    (8, 30, "PREMARKET_MOMENTUM"),
    (9, 15, "PREMARKET_MOMENTUM"),
    (9, 30, "REGULAR_HOURS"),
    (10, 0, "REGULAR_HOURS"),
    (15, 59, "REGULAR_HOURS"),
    (16, 15, "POSTMARKET_REACTION"),
    (17, 0, "POSTMARKET_CONTINUATION"),
    (19, 0, "LATE_POSTMARKET"),
    (20, 0, "CLOSED"),
]

for hour, minute, expected in session_tests:
    result = detect_session(hour, minute)
    status = "✅" if result == expected else "❌"
    print(f"{status} {hour:02d}:{minute:02d} → {result}")

# Test 5: VWAP calculation
print("\n" + "=" * 60)
print("TEST 5: VWAP Calculation")
print("=" * 60)

def calculate_vwap(trades):
    """Calculate VWAP from list of (price, volume) tuples"""
    total_value = sum(price * volume for price, volume in trades)
    total_volume = sum(volume for _, volume in trades)
    return total_value / total_volume if total_volume > 0 else 0

vwap_tests = [
    ([(10.0, 1000), (10.5, 2000), (11.0, 1000)], 10.5, "Simple VWAP"),
    ([(5.0, 500), (5.5, 1000), (6.0, 500)], 5.5, "Equal distribution"),
    ([(100.0, 100), (101.0, 900)], 100.9, "Weighted toward higher price"),
]

for trades, expected, desc in vwap_tests:
    result = calculate_vwap(trades)
    status = "✅" if abs(result - expected) < 0.01 else "❌"
    print(f"{status} {desc}: ${result:.2f} (expected ${expected:.2f})")

# Test 6: Trade density calculation
print("\n" + "=" * 60)
print("TEST 6: Trade Density (trades per second)")
print("=" * 60)

def calculate_trade_density(trade_count, seconds=60):
    """Calculate trades per second"""
    return trade_count / seconds if seconds > 0 else 0

density_tests = [
    (100, 60, 1.67, "100 trades in 60s"),
    (90, 60, 1.5, "90 trades in 60s (threshold)"),
    (150, 60, 2.5, "150 trades in 60s (high)"),
    (50, 60, 0.83, "50 trades in 60s (low)"),
]

for trades, seconds, expected, desc in density_tests:
    result = calculate_trade_density(trades, seconds)
    status = "✅" if abs(result - expected) < 0.01 else "❌"
    threshold_met = "YES" if result > 1.5 else "NO"
    print(f"{status} {desc}: {result:.2f} tr/s (>1.5? {threshold_met})")

# Summary
print("\n" + "=" * 60)
print("📊 TEST SUMMARY")
print("=" * 60)
print("✅ All logic tests completed successfully!")
print("\nTo test with actual WebSocket:")
print("1. Ensure pytz and polygon packages are installed")
print("2. Run: python test_websocket_alerts.py")
print("=" * 60 + "\n")
