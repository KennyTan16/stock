"""
Test file to verify WebSocket alert logic without connecting to Polygon
Simulates trade/quote messages and checks if alerts are triggered correctly
"""

import sys
from datetime import datetime
import pytz
from collections import defaultdict
from unittest.mock import Mock, patch

# Import functions from main file
sys.path.insert(0, '.')
from polygon_websocket import (
    check_spike, update_aggregates, handle_msg, get_spread_ratio,
    minute_aggregates, latest_quotes, momentum_flags, rolling_volume_3min,
    alert_tracker, get_et_time, data_lock, quote_lock
)

# Test data structures
test_alerts = []

def mock_send_telegram(message):
    """Mock Telegram send to capture alerts instead of sending"""
    print(f"\n{'='*60}")
    print("📨 ALERT CAPTURED:")
    print(f"{'='*60}")
    print(message)
    print(f"{'='*60}\n")
    test_alerts.append(message)
    return True

def create_trade_msg(symbol, price, size, timestamp):
    """Create mock trade message"""
    msg = Mock()
    msg.symbol = symbol
    msg.price = price
    msg.size = size
    msg.timestamp = timestamp
    msg.ev = 'T'
    return msg

def create_quote_msg(symbol, bid, ask):
    """Create mock quote message"""
    msg = Mock()
    msg.sym = symbol
    msg.bp = bid
    msg.ap = ask
    msg.ev = 'Q'
    return msg

def get_test_timestamp(hour, minute):
    """Get timestamp for specific time"""
    et_tz = pytz.timezone('US/Eastern')
    dt = et_tz.localize(datetime(2025, 11, 6, hour, minute, 0))
    return int(dt.timestamp() * 1000)  # milliseconds

def clear_test_data():
    """Clear all test data structures"""
    minute_aggregates.clear()
    latest_quotes.clear()
    momentum_flags.clear()
    rolling_volume_3min.clear()
    alert_tracker.clear()
    test_alerts.clear()

def test_early_premarket_watchlist():
    """Test 4-8 AM early pre-market watchlist logic"""
    print("\n" + "="*60)
    print("TEST 1: Early Pre-Market Watchlist (4-8 AM)")
    print("="*60)
    
    clear_test_data()
    symbol = "TEST"
    
    # Set up initial volume for 3-min comparison
    rolling_volume_3min[symbol] = [50000, 50000, 50000]
    
    # Create quote for spread calculation
    quote_msg = create_quote_msg(symbol, 5.00, 5.10)  # 2% spread
    handle_msg([quote_msg])
    
    # Simulate high volume spike at 6:00 AM
    base_ts = get_test_timestamp(6, 0)
    open_price = 5.00
    
    # Build up volume and trades over 1 minute
    for i in range(1500):  # 1500 trades to reach 1000+ count
        trade_price = open_price * (1 + 0.15 * (i / 1500))  # 15% gain
        trade_msg = create_trade_msg(symbol, trade_price, 120, base_ts + i * 40)
        handle_msg([trade_msg])
    
    print(f"\n✓ Simulated {rolling_volume_3min[symbol][-1]:,} volume")
    print(f"✓ Price moved from ${open_price:.2f} to ${trade_price:.2f} ({((trade_price/open_price - 1)*100):.1f}%)")
    print(f"\n📊 Expected: EARLY_PREMARKET_WATCHLIST alert")
    print(f"📊 Actual alerts sent: {len(test_alerts)}")

def test_premarket_momentum_confirmation():
    """Test 8-9:30 AM pre-market momentum confirmation"""
    print("\n" + "="*60)
    print("TEST 2: Pre-Market Momentum Confirmation (8-9:30 AM)")
    print("="*60)
    
    clear_test_data()
    symbol = "TEST"
    
    # Set up initial volume for 3-min comparison
    rolling_volume_3min[symbol] = [30000, 30000, 30000]
    
    # Create tight quote
    quote_msg = create_quote_msg(symbol, 10.00, 10.10)  # 1% spread
    handle_msg([quote_msg])
    
    # Simulate momentum at 8:30 AM
    base_ts = get_test_timestamp(8, 30)
    open_price = 10.00
    
    # Build volume to 80K with 350 trades
    for i in range(350):
        trade_price = open_price * (1 + 0.10 * (i / 350))  # 10% gain
        trade_msg = create_trade_msg(symbol, trade_price, 230, base_ts + i * 170)
        handle_msg([trade_msg])
    
    print(f"\n✓ Simulated volume and momentum")
    print(f"✓ Price: ${open_price:.2f} → ${trade_price:.2f} ({((trade_price/open_price - 1)*100):.1f}%)")
    print(f"\n📊 Expected: MOMENTUM CONFIRMED alert")
    print(f"📊 Actual alerts sent: {len(test_alerts)}")

def test_regular_hours_momentum():
    """Test 9:30 AM - 4:00 PM regular hours momentum"""
    print("\n" + "="*60)
    print("TEST 3: Regular Hours Momentum (9:30 AM - 4:00 PM)")
    print("="*60)
    
    clear_test_data()
    symbol = "TEST"
    
    # Set up initial volume
    rolling_volume_3min[symbol] = [35000, 35000, 35000]
    
    # Create tight quote
    quote_msg = create_quote_msg(symbol, 15.00, 15.25)  # 1.67% spread
    handle_msg([quote_msg])
    
    # Simulate spike at 10:00 AM
    base_ts = get_test_timestamp(10, 0)
    open_price = 15.00
    
    # Need 75K volume, 300+ trades, 10% gain, 1.5 trades/sec = 90+ trades
    for i in range(350):
        trade_price = open_price * (1 + 0.12 * (i / 350))  # 12% gain
        trade_msg = create_trade_msg(symbol, trade_price, 220, base_ts + i * 170)
        handle_msg([trade_msg])
    
    print(f"\n✓ Simulated regular hours momentum")
    print(f"✓ Price: ${open_price:.2f} → ${trade_price:.2f} ({((trade_price/open_price - 1)*100):.1f}%)")
    print(f"✓ Trade density: {350/60:.1f} trades/sec")
    print(f"\n📊 Expected: REGULAR HOURS MOMENTUM alert")
    print(f"📊 Actual alerts sent: {len(test_alerts)}")

def test_postmarket_reaction():
    """Test 4:00-4:30 PM post-market reaction"""
    print("\n" + "="*60)
    print("TEST 4: Post-Market Reaction (4:00-4:30 PM)")
    print("="*60)
    
    clear_test_data()
    symbol = "TEST"
    
    # Set up initial volume
    rolling_volume_3min[symbol] = [80000, 80000, 80000]
    
    # Create quote
    quote_msg = create_quote_msg(symbol, 8.00, 8.12)  # 1.5% spread
    handle_msg([quote_msg])
    
    # Simulate reaction at 4:10 PM
    base_ts = get_test_timestamp(16, 10)
    open_price = 8.00
    
    # Need 200K volume, 10% gain, 2x volume acceleration
    for i in range(800):
        trade_price = open_price * (1 + 0.12 * (i / 800))  # 12% gain
        trade_msg = create_trade_msg(symbol, trade_price, 260, base_ts + i * 75)
        handle_msg([trade_msg])
    
    print(f"\n✓ Simulated post-market reaction")
    print(f"✓ Price: ${open_price:.2f} → ${trade_price:.2f} ({((trade_price/open_price - 1)*100):.1f}%)")
    print(f"\n📊 Expected: POST-MARKET REACTION alert")
    print(f"📊 Actual alerts sent: {len(test_alerts)}")

def test_postmarket_continuation():
    """Test 4:30-6:00 PM post-market continuation"""
    print("\n" + "="*60)
    print("TEST 5: Post-Market Continuation (4:30-6:00 PM)")
    print("="*60)
    
    clear_test_data()
    symbol = "TEST"
    
    # Set up initial volume
    rolling_volume_3min[symbol] = [50000, 50000, 50000]
    
    # Create tight quote
    quote_msg = create_quote_msg(symbol, 12.00, 12.15)  # 1.25% spread
    handle_msg([quote_msg])
    
    # Simulate continuation at 5:00 PM
    base_ts = get_test_timestamp(17, 0)
    open_price = 12.00
    
    # Need 100K volume, price > vwap, 1.5x volume acceleration
    for i in range(500):
        trade_price = open_price * (1 + 0.08 * (i / 500))  # 8% gain
        trade_msg = create_trade_msg(symbol, trade_price, 210, base_ts + i * 120)
        handle_msg([trade_msg])
    
    print(f"\n✓ Simulated post-market continuation")
    print(f"✓ Price: ${open_price:.2f} → ${trade_price:.2f} ({((trade_price/open_price - 1)*100):.1f}%)")
    print(f"\n📊 Expected: POST-MARKET CONTINUATION alert")
    print(f"📊 Actual alerts sent: {len(test_alerts)}")

def test_late_postmarket_watch():
    """Test 6:00-8:00 PM late post-market watch"""
    print("\n" + "="*60)
    print("TEST 6: Late Post-Market Watch (6:00-8:00 PM)")
    print("="*60)
    
    clear_test_data()
    symbol = "TEST"
    
    # Simulate high volume spike at 7:00 PM
    base_ts = get_test_timestamp(19, 0)
    open_price = 6.00
    
    # Need 300K volume, 15% gain
    for i in range(1200):
        trade_price = open_price * (1 + 0.16 * (i / 1200))  # 16% gain
        trade_msg = create_trade_msg(symbol, trade_price, 260, base_ts + i * 50)
        handle_msg([trade_msg])
    
    print(f"\n✓ Simulated late post-market activity")
    print(f"✓ Price: ${open_price:.2f} → ${trade_price:.2f} ({((trade_price/open_price - 1)*100):.1f}%)")
    print(f"\n📊 Expected: LATE POST-MARKET WATCH alert (observation only)")
    print(f"📊 Actual alerts sent: {len(test_alerts)}")

def test_no_alert_insufficient_criteria():
    """Test that no alert is sent when criteria are not met"""
    print("\n" + "="*60)
    print("TEST 7: No Alert - Insufficient Criteria")
    print("="*60)
    
    clear_test_data()
    symbol = "TEST"
    
    # Simulate weak volume at 8:00 AM (should NOT alert)
    base_ts = get_test_timestamp(8, 0)
    open_price = 10.00
    
    # Only 50K volume, 200 trades, 5% gain - not enough
    for i in range(200):
        trade_price = open_price * (1 + 0.05 * (i / 200))
        trade_msg = create_trade_msg(symbol, trade_price, 250, base_ts + i * 300)
        handle_msg([trade_msg])
    
    print(f"\n✓ Simulated weak momentum")
    print(f"✓ Volume: ~50K (need 75K)")
    print(f"✓ Gain: ~5% (need 8%)")
    print(f"\n📊 Expected: NO alert")
    print(f"📊 Actual alerts sent: {len(test_alerts)}")

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🧪 WEBSOCKET ALERT LOGIC TEST SUITE")
    print("="*60)
    
    # Patch send_telegram to capture alerts
    with patch('polygon_websocket.send_telegram', side_effect=mock_send_telegram):
        # Run all tests
        test_early_premarket_watchlist()
        test_premarket_momentum_confirmation()
        test_regular_hours_momentum()
        test_postmarket_reaction()
        test_postmarket_continuation()
        test_late_postmarket_watch()
        test_no_alert_insufficient_criteria()
    
    # Summary
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60)
    print(f"Total alerts captured: {len(test_alerts)}")
    print(f"\n✅ All tests completed!")
    print("="*60 + "\n")
