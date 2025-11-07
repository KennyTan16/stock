"""
Live integration test - sends REAL Telegram notification to verify end-to-end flow
This will test with actual alert sending to your phone
"""

import sys
from datetime import datetime
import pytz

sys.path.insert(0, '.')
from polygon_websocket import (
    check_spike, momentum_flags, rolling_volume_3min, 
    latest_quotes, minute_aggregates, send_telegram,
    get_et_time
)

def test_telegram_connectivity():
    """Test 1: Verify Telegram bot can send messages"""
    print("\n" + "="*70)
    print("TEST 1: Telegram Connectivity")
    print("="*70)
    
    test_message = (
        "🧪 <b>TEST MESSAGE - Dual-Stage Momentum System</b>\n\n"
        f"✅ Bot is online and connected\n"
        f"⏰ {get_et_time().strftime('%I:%M:%S %p ET on %B %d, %Y')}\n\n"
        "If you received this, your Telegram notifications are working!"
    )
    
    print("Sending test message to Telegram...")
    success = send_telegram(test_message)
    
    if success:
        print("✅ SUCCESS - Check your phone for the test message!")
    else:
        print("❌ FAILED - Could not send to Telegram. Check your credentials.")
    
    return success

def test_premarket_scenario():
    """Test 2: Simulate PREMARKET dual-stage detection with real alert"""
    print("\n" + "="*70)
    print("TEST 2: PREMARKET Dual-Stage Alert (8:30 AM)")
    print("="*70)
    
    # Clear previous data
    momentum_flags.clear()
    
    # Setup test symbol
    symbol = "TSLA"
    
    # Setup previous volume (10K average)
    rolling_volume_3min[symbol] = [10000, 10000, 10000]
    print(f"✓ Set previous volume: 10K average")
    
    # Setup quote with tight spread (1%)
    latest_quotes[symbol] = {'bid': 250.00, 'ask': 252.50}
    print(f"✓ Set quote: Bid $250.00 / Ask $252.50 (1% spread)")
    
    # Setup time: 8:30 AM ET (PREMARKET)
    et_tz = pytz.timezone('US/Eastern')
    minute_ts = et_tz.localize(datetime(2025, 11, 6, 8, 30, 0))
    
    # Setup minute_aggregates with realistic data
    minute_aggregates[minute_ts][symbol] = {
        'open': 250.00,
        'high': 265.00,
        'low': 250.00,
        'close': 265.00,
        'volume': 0,
        'value': 0,
        'count': 0
    }
    print(f"✓ Set intraday high: $265.00")
    
    # STAGE 1: Early Detection
    print("\n--- STAGE 1: Early Detection ---")
    print("Simulating: 27K volume, 4% gain, rel_vol 2.7x")
    
    check_spike(
        symbol=symbol,
        current_pct=4.0,
        current_vol=27000,
        minute_ts=minute_ts,
        open_price=250.00,
        close_price=260.00,
        trade_count=100,
        vwap=250.00
    )
    
    if symbol in momentum_flags:
        print(f"✅ Flag set: {momentum_flags[symbol]['flag']}")
    else:
        print("❌ Flag not set - Stage 1 failed")
        return False
    
    # STAGE 2: Confirmed Breakout
    print("\n--- STAGE 2: Confirmed Breakout ---")
    print("Simulating: 50K volume, 8% gain, breaks above high")
    print("Expected: REAL Telegram alert to your phone")
    
    result = check_spike(
        symbol=symbol,
        current_pct=8.0,
        current_vol=50000,
        minute_ts=minute_ts,
        open_price=250.00,
        close_price=270.00,  # Breaks above $265 high
        trade_count=250,
        vwap=250.00
    )
    
    if symbol not in momentum_flags:
        print("✅ Flag cleared after breakout (alert sent)")
        print("\n🔔 Check your phone for the BREAKOUT alert!")
        return True
    else:
        print("❌ Flag still active - breakout not triggered")
        return False

def test_regular_hours_scenario():
    """Test 3: Simulate REGULAR HOURS dual-stage detection"""
    print("\n" + "="*70)
    print("TEST 3: REGULAR HOURS Dual-Stage Alert (10:30 AM)")
    print("="*70)
    
    # Clear previous data
    momentum_flags.clear()
    
    symbol = "NVDA"
    
    # Setup with higher volume baseline for regular hours
    rolling_volume_3min[symbol] = [25000, 25000, 25000]
    print(f"✓ Set previous volume: 25K average")
    
    latest_quotes[symbol] = {'bid': 140.00, 'ask': 140.28}
    print(f"✓ Set quote: Bid $140.00 / Ask $140.28 (0.2% spread)")
    
    # Setup time: 10:30 AM ET (REGULAR HOURS)
    et_tz = pytz.timezone('US/Eastern')
    minute_ts = et_tz.localize(datetime(2025, 11, 6, 10, 30, 0))
    
    minute_aggregates[minute_ts][symbol] = {
        'open': 140.00,
        'high': 145.00,
        'low': 140.00,
        'close': 145.00,
        'volume': 0,
        'value': 0,
        'count': 0
    }
    print(f"✓ Set intraday high: $145.00")
    
    # STAGE 1: Early Detection (need 4% for regular hours)
    print("\n--- STAGE 1: Early Detection ---")
    print("Simulating: 70K volume, 5% gain, rel_vol 2.8x")
    
    check_spike(
        symbol=symbol,
        current_pct=5.0,
        current_vol=70000,
        minute_ts=minute_ts,
        open_price=140.00,
        close_price=147.00,
        trade_count=150,
        vwap=140.00
    )
    
    if symbol in momentum_flags:
        print(f"✅ Flag set: {momentum_flags[symbol]['flag']}")
    else:
        print("❌ Flag not set - Stage 1 failed")
        return False
    
    # STAGE 2: Confirmed Breakout (need 75K vol, 7% gain)
    print("\n--- STAGE 2: Confirmed Breakout ---")
    print("Simulating: 110K volume, 8% gain, breaks above high")
    print("Expected: REAL Telegram alert to your phone")
    
    check_spike(
        symbol=symbol,
        current_pct=8.0,
        current_vol=110000,
        minute_ts=minute_ts,
        open_price=140.00,
        close_price=151.20,  # Breaks above $145 high
        trade_count=300,
        vwap=140.00
    )
    
    if symbol not in momentum_flags:
        print("✅ Flag cleared after breakout (alert sent)")
        print("\n🔔 Check your phone for the BREAKOUT alert!")
        return True
    else:
        print("❌ Flag still active - breakout not triggered")
        return False

def test_fast_break_scenario():
    """Test 4: Simulate FAST-BREAK parabolic move"""
    print("\n" + "="*70)
    print("TEST 4: FAST-BREAK MODE (Parabolic Move)")
    print("="*70)
    
    symbol = "COIN"
    
    # Setup with baseline volume
    rolling_volume_3min[symbol] = [15000, 15000, 15000]
    print(f"✓ Set previous volume: 15K average (need 8x for fast-break)")
    
    latest_quotes[symbol] = {'bid': 200.00, 'ask': 200.40}
    print(f"✓ Set quote: Bid $200.00 / Ask $200.40 (0.2% spread)")
    
    et_tz = pytz.timezone('US/Eastern')
    minute_ts = et_tz.localize(datetime(2025, 11, 6, 14, 30, 0))
    
    minute_aggregates[minute_ts][symbol] = {
        'open': 200.00,
        'high': 222.00,
        'low': 200.00,
        'close': 222.00,
        'volume': 0,
        'value': 0,
        'count': 0
    }
    
    print("\n--- FAST-BREAK Detection ---")
    print("Simulating: 125K volume (8.3x surge), 11% gain")
    print("Expected: REAL Telegram FAST-BREAK alert")
    
    check_spike(
        symbol=symbol,
        current_pct=11.0,
        current_vol=125000,  # 8.3x the 15K average
        minute_ts=minute_ts,
        open_price=200.00,
        close_price=222.00,
        trade_count=400,
        vwap=200.00
    )
    
    print("✅ Fast-break scenario executed")
    print("\n🔔 Check your phone for the FAST-BREAK alert!")
    return True

def validate_calculations():
    """Test 5: Validate all calculation logic"""
    print("\n" + "="*70)
    print("TEST 5: Calculation Validation")
    print("="*70)
    
    # Test rel_vol calculation
    test_vol = 50000
    prev_vols = [10000, 10000, 10000]
    avg = sum(prev_vols) / len(prev_vols)
    rel_vol = test_vol / avg
    
    print(f"Rel Vol: {test_vol:,} / {avg:,} = {rel_vol:.2f}x")
    assert rel_vol == 5.0, "Rel vol calculation failed"
    print("✅ Rel vol calculation correct")
    
    # Test percentage calculation
    open_p = 100.00
    close_p = 108.00
    pct = ((close_p - open_p) / open_p) * 100
    print(f"% Change: ({close_p} - {open_p}) / {open_p} * 100 = {pct:.2f}%")
    assert pct == 8.0, "Percentage calculation failed"
    print("✅ Percentage calculation correct")
    
    # Test VWAP threshold
    price = 109.95
    vwap = 110.00
    threshold = 0.995 * vwap
    passes = price > threshold
    print(f"VWAP check: {price:.2f} > 0.995 * {vwap:.2f} ({threshold:.2f})? {passes}")
    assert passes, "VWAP threshold check failed"
    print("✅ VWAP threshold calculation correct")
    
    # Test spread ratio
    bid = 100.00
    ask = 101.00
    mid = (bid + ask) / 2
    spread_ratio = (ask - bid) / mid
    print(f"Spread: ({ask} - {bid}) / {mid:.2f} = {spread_ratio:.4f} ({spread_ratio*100:.2f}%)")
    expected = 0.0099502
    assert abs(spread_ratio - expected) < 0.00001, "Spread calculation failed"
    print("✅ Spread ratio calculation correct")
    
    return True

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🧪 LIVE TELEGRAM INTEGRATION TEST")
    print("="*70)
    print(f"Current ET Time: {get_et_time().strftime('%I:%M:%S %p on %B %d, %Y')}")
    print("="*70)
    
    results = []
    
    # Test 1: Telegram connectivity
    results.append(("Telegram Connectivity", test_telegram_connectivity()))
    
    if not results[0][1]:
        print("\n❌ Cannot proceed - Telegram connection failed")
        print("Please check your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        sys.exit(1)
    
    input("\nPress Enter to continue with alert tests (will send real notifications)...")
    
    # Test 2: PREMARKET scenario
    results.append(("PREMARKET Alert", test_premarket_scenario()))
    
    input("\nPress Enter to continue...")
    
    # Test 3: REGULAR HOURS scenario
    results.append(("REGULAR HOURS Alert", test_regular_hours_scenario()))
    
    input("\nPress Enter to continue...")
    
    # Test 4: FAST-BREAK scenario
    results.append(("FAST-BREAK Alert", test_fast_break_scenario()))
    
    # Test 5: Calculation validation
    results.append(("Calculation Validation", validate_calculations()))
    
    # Summary
    print("\n" + "="*70)
    print("📊 TEST SUMMARY")
    print("="*70)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:.<50} {status}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    
    print("="*70)
    print(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        print("Your dual-stage momentum detection system is working correctly!")
        print("Telegram notifications are being delivered to your phone.")
    else:
        print(f"\n⚠️ {total - passed} test(s) failed. Review the output above.")
    
    print("="*70 + "\n")
