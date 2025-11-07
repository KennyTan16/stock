"""
Simple ASCII-only test for dual-stage detection
"""

import sys
from datetime import datetime
import pytz
from collections import defaultdict
from unittest.mock import Mock, patch

# Import from main file  
sys.path.insert(0, '.')
from polygon_websocket import (
    check_spike, update_aggregates, handle_msg,
    minute_aggregates, latest_quotes, momentum_flags, rolling_volume_3min,
    target_tickers, get_et_time
)

test_alerts = []

def mock_send_telegram(message):
    """Capture alerts"""
    print(f"\n{'='*60}")
    print("ALERT SENT!")
    print(f"{'='*60}")
    print(message)
    print(f"{'='*60}\n")
    test_alerts.append(message)
    return True

def create_trade_msg(symbol, price, size, timestamp):
    msg = Mock()
    msg.symbol = symbol
    msg.price = price
    msg.size = size
    msg.timestamp = timestamp
    msg.ev = 'T'
    return msg

def create_quote_msg(symbol, bid, ask):
    msg = Mock()
    msg.sym = symbol
    msg.bp = bid
    msg.ap = ask
    msg.ev = 'Q'
    return msg

def get_ts(hour, minute):
    et_tz = pytz.timezone('US/Eastern')
    dt = et_tz.localize(datetime(2025, 11, 6, hour, minute, 0))
    return int(dt.timestamp() * 1000)

def clear_data():
    minute_aggregates.clear()
    latest_quotes.clear()
    momentum_flags.clear()
    rolling_volume_3min.clear()
    test_alerts.clear()

def test():
    print("\nTEST: PREMARKET Dual-Stage Detection")
    print("="*60)
    
    clear_data()
    symbol = "TEST"
    target_tickers.add(symbol)
    
    # Set previous volume: 10K avg
    rolling_volume_3min[symbol] = [10000, 10000, 10000]
    print(f"Previous volume: 10K avg")
    
    # Set quote (1% spread, well under 3% limit)
    quote_msg = create_quote_msg(symbol, 10.00, 10.10)
    handle_msg([quote_msg])
    print(f"Quote: Bid $10.00 / Ask $10.10 (1% spread)")
    
    # Build to 40K volume with 8% gain at 8:30 AM
    base_ts = get_ts(8, 30)
    open_price = 10.00
    
    print(f"\nBuilding volume to 40K with 8% gain...")
    # 200 trades x 200 size = 40K volume
    for i in range(200):
        trade_price = open_price * (1 + 0.08 * (i / 200))
        trade_msg = create_trade_msg(symbol, trade_price, 200, base_ts + i * 100)
        handle_msg([trade_msg])
    
    print(f"\nExpected: 1 BREAKOUT CONFIRMED alert")
    print(f"Actual alerts sent: {len(test_alerts)}")
    
    if test_alerts:
        print("\nSUCCESS!")
    else:
        print("\nFAILED - no alert sent")
        print(f"Flag active: {symbol in momentum_flags}")
        if symbol in momentum_flags:
            print(f"Flag: {momentum_flags[symbol]}")
    
    target_tickers.discard(symbol)

if __name__ == "__main__":
    print("\nDUAL-STAGE DETECTION TEST")
    print("="*60)
    
    with patch('polygon_websocket.send_telegram', side_effect=mock_send_telegram):
        test()
    
    print("\nTEST COMPLETE")
    print("="*60 + "\n")
