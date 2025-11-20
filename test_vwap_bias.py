"""
Test VWAP bias calculation to verify it's working correctly
"""
import sys
from datetime import datetime, timedelta
from collections import defaultdict
import pytz

# Import from main file
sys.path.insert(0, '.')
import polygon_websocket

# Set up test data
ET_TIMEZONE = pytz.timezone('America/New_York')

def test_vwap_bias():
    """Test VWAP bias calculation with sample data"""
    print("=" * 80)
    print("TESTING VWAP BIAS CALCULATION")
    print("=" * 80)
    
    test_symbol = "TEST"
    
    # Clear any existing data
    polygon_websocket.minute_aggregates.clear()
    
    # Create test data for 5 minutes
    base_time = datetime.now(ET_TIMEZONE).replace(second=0, microsecond=0)
    
    print("\nTest Case 1: Bullish (all prices > VWAP)")
    print("-" * 80)
    
    # Bullish scenario: prices consistently above VWAP
    test_data_bullish = [
        {'time': base_time - timedelta(minutes=4), 'price': 100.0, 'vwap': 99.5},
        {'time': base_time - timedelta(minutes=3), 'price': 101.0, 'vwap': 100.0},
        {'time': base_time - timedelta(minutes=2), 'price': 102.0, 'vwap': 100.5},
        {'time': base_time - timedelta(minutes=1), 'price': 103.0, 'vwap': 101.0},
        {'time': base_time, 'price': 104.0, 'vwap': 102.0},
    ]
    
    for data in test_data_bullish:
        polygon_websocket.minute_aggregates[data['time']][test_symbol] = {
            'open': data['price'] - 0.5,
            'close': data['price'],
            'high': data['price'] + 0.2,
            'low': data['price'] - 0.5,
            'volume': 1000,
            'value': data['vwap'] * 1000,
            'count': 10,
            'vwap': data['vwap']
        }
        print(f"  {data['time'].strftime('%H:%M')}: Price={data['price']:.2f}, VWAP={data['vwap']:.2f}, Above={data['price'] > data['vwap']}")
    
    bias = polygon_websocket.vwap_bias(test_symbol, n=3)
    print(f"\n  Result: {bias}")
    print(f"  Expected: bullish")
    print(f"  ✓ PASS" if bias == "bullish" else f"  ✗ FAIL")
    
    # Test Case 2: Bearish
    print("\n\nTest Case 2: Bearish (all prices < VWAP)")
    print("-" * 80)
    
    polygon_websocket.minute_aggregates.clear()
    test_symbol = "TEST2"
    
    test_data_bearish = [
        {'time': base_time - timedelta(minutes=4), 'price': 100.0, 'vwap': 101.0},
        {'time': base_time - timedelta(minutes=3), 'price': 99.0, 'vwap': 100.5},
        {'time': base_time - timedelta(minutes=2), 'price': 98.0, 'vwap': 100.0},
        {'time': base_time - timedelta(minutes=1), 'price': 97.0, 'vwap': 99.5},
        {'time': base_time, 'price': 96.0, 'vwap': 99.0},
    ]
    
    for data in test_data_bearish:
        polygon_websocket.minute_aggregates[data['time']][test_symbol] = {
            'open': data['price'] + 0.5,
            'close': data['price'],
            'high': data['price'] + 0.5,
            'low': data['price'] - 0.2,
            'volume': 1000,
            'value': data['vwap'] * 1000,
            'count': 10,
            'vwap': data['vwap']
        }
        print(f"  {data['time'].strftime('%H:%M')}: Price={data['price']:.2f}, VWAP={data['vwap']:.2f}, Below={data['price'] < data['vwap']}")
    
    bias = polygon_websocket.vwap_bias(test_symbol, n=3)
    print(f"\n  Result: {bias}")
    print(f"  Expected: bearish")
    print(f"  ✓ PASS" if bias == "bearish" else f"  ✗ FAIL")
    
    # Test Case 3: Neutral (mixed)
    print("\n\nTest Case 3: Neutral (mixed above/below)")
    print("-" * 80)
    
    polygon_websocket.minute_aggregates.clear()
    test_symbol = "TEST3"
    
    test_data_neutral = [
        {'time': base_time - timedelta(minutes=4), 'price': 100.0, 'vwap': 101.0},
        {'time': base_time - timedelta(minutes=3), 'price': 102.0, 'vwap': 100.5},
        {'time': base_time - timedelta(minutes=2), 'price': 99.0, 'vwap': 100.0},
        {'time': base_time - timedelta(minutes=1), 'price': 101.0, 'vwap': 99.5},
        {'time': base_time, 'price': 98.0, 'vwap': 100.0},
    ]
    
    for data in test_data_neutral:
        polygon_websocket.minute_aggregates[data['time']][test_symbol] = {
            'open': 100.0,
            'close': data['price'],
            'high': max(100.0, data['price']),
            'low': min(100.0, data['price']),
            'volume': 1000,
            'value': data['vwap'] * 1000,
            'count': 10,
            'vwap': data['vwap']
        }
        relation = "Above" if data['price'] > data['vwap'] else "Below"
        print(f"  {data['time'].strftime('%H:%M')}: Price={data['price']:.2f}, VWAP={data['vwap']:.2f}, {relation}")
    
    bias = polygon_websocket.vwap_bias(test_symbol, n=3)
    print(f"\n  Result: {bias}")
    print(f"  Expected: neutral")
    print(f"  ✓ PASS" if bias == "neutral" else f"  ✗ FAIL")
    
    # Test get_recent_prices and get_recent_vwaps
    print("\n\nTest Case 4: get_recent_prices and get_recent_vwaps")
    print("-" * 80)
    
    prices = polygon_websocket.get_recent_prices(test_symbol, n=3)
    vwaps = polygon_websocket.get_recent_vwaps(test_symbol, n=3)
    
    print(f"  Recent prices (n=3): {prices}")
    print(f"  Recent VWAPs (n=3): {vwaps}")
    print(f"  Expected prices: [99.0, 101.0, 98.0] (last 3 in chronological order)")
    print(f"  Expected VWAPs: [100.0, 99.5, 100.0]")
    
    expected_prices = [99.0, 101.0, 98.0]
    expected_vwaps = [100.0, 99.5, 100.0]
    
    prices_match = len(prices) == 3 and all(abs(p - e) < 0.01 for p, e in zip(prices, expected_prices))
    vwaps_match = len(vwaps) == 3 and all(abs(v - e) < 0.01 for v, e in zip(vwaps, expected_vwaps))
    
    print(f"  ✓ PASS" if prices_match and vwaps_match else f"  ✗ FAIL")
    
    print("\n" + "=" * 80)
    print("VWAP BIAS TESTS COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    test_vwap_bias()
