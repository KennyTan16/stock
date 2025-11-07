"""
Direct test of check_spike function with debug output
"""

import sys
from unittest.mock import patch
from datetime import datetime
import pytz

sys.path.insert(0, '.')
from polygon_websocket import (
    check_spike, momentum_flags, rolling_volume_3min, 
    latest_quotes, send_telegram, minute_aggregates
)

test_alerts = []

def mock_send_telegram(message):
    print(f"\n{'='*60}")
    print("ALERT CAPTURED!")
    print(f"{'='*60}")
    print(message)
    print(f"{'='*60}\n")
    test_alerts.append(message)
    return True

# Setup
symbol = "TEST"
rolling_volume_3min[symbol] = [10000, 10000, 10000]
latest_quotes[symbol] = {'bid': 10.00, 'ask': 10.10}

# Set up minute_aggregates with a high of 10.70
et_tz = pytz.timezone('US/Eastern')
minute_ts = et_tz.localize(datetime(2025, 11, 6, 8, 30, 0))
minute_aggregates[minute_ts][symbol] = {
    'open': 10.00,
    'high': 10.70,  # Set high to 10.70 so 10.80 can break above it
    'low': 10.00,
    'close': 10.70,
    'volume': 0,
    'value': 0,
    'count': 0
}

print("\n" + "="*60)
print("DIRECT CHECK_SPIKE TEST")
print("="*60)

# Patch send_telegram
with patch('polygon_websocket.send_telegram', side_effect=mock_send_telegram):
    
    # STAGE 1: Early Detection
    # At 8:30 AM PREMARKET: need rel_vol>=2.5, pct>=3%, price>0.995*VWAP
    print("\nSTAGE 1: Early Detection")
    print("Params: vol=27K, pct=4%, vwap=10.00, close=10.40")
    print("Expected: Set SETUP flag")
    
    check_spike(
        symbol=symbol,
        current_pct=4.0,        # 4% gain (need >=3%)
        current_vol=27000,      # 27K volume
        minute_ts=minute_ts,
        open_price=10.00,
        close_price=10.40,
        trade_count=100,
        vwap=10.00
    )
    
    print(f"Flag set: {symbol in momentum_flags}")
    if symbol in momentum_flags:
        print(f"Flag data: {momentum_flags[symbol]}")
    
    # STAGE 2: Confirmed Breakout
    # Need: pct>=7%, vol>=30K, price>high, rel_vol>=4
    print("\n" + "="*60)
    print("STAGE 2: Confirmed Breakout")
    print("Params: vol=45K, pct=8%, vwap=10.00, close=10.80, high=10.70")
    print("Expected: BREAKOUT CONFIRMED alert")
    
    check_spike(
        symbol=symbol,
        current_pct=8.0,        # 8% gain (need >=7%)
        current_vol=45000,      # 45K volume (need >=30K)
        minute_ts=minute_ts,
        open_price=10.00,
        close_price=10.80,      # Above high of 10.70
        trade_count=200,
        vwap=10.00
    )
    
    print(f"\nAlerts sent: {len(test_alerts)}")
    if test_alerts:
        print("SUCCESS - Alert triggered!")
    else:
        print("FAILED - No alert")
        print(f"Flag still active: {symbol in momentum_flags}")

print("\n" + "="*60)
print("TEST COMPLETE")
print("="*60 + "\n")
