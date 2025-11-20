#!/usr/bin/env python3
"""
Test script for Bid/Ask Pressure Index functionality
Tests pressure calculation, trade flow tracking, and alert generation
"""

import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import after path setup
from polygon_websocket import (
    compute_bid_ask_pressure_index,
    update_trade_flow,
    get_pressure_trend,
    latest_quotes,
    trade_flow_data,
    pressure_index_history,
    get_et_time,
    quote_lock
)

def setup_test_data(symbol):
    """Set up test quote and trade data"""
    # Set up quote data
    with quote_lock:
        latest_quotes[symbol] = {
            'bid': 149.50,
            'ask': 149.52,
            'bid_size': 5000,
            'ask_size': 3000,
            'timestamp': get_et_time()
        }
    
    # Simulate trade flow - more buying pressure
    current_time = get_et_time()
    trades = [
        (current_time - timedelta(seconds=90), 149.52, 2000, 'buy'),
        (current_time - timedelta(seconds=85), 149.51, 1500, 'buy'),
        (current_time - timedelta(seconds=80), 149.50, 800, 'sell'),
        (current_time - timedelta(seconds=75), 149.52, 3000, 'buy'),
        (current_time - timedelta(seconds=70), 149.51, 500, 'sell'),
        (current_time - timedelta(seconds=60), 149.52, 2500, 'buy'),
        (current_time - timedelta(seconds=50), 149.50, 1000, 'sell'),
        (current_time - timedelta(seconds=40), 149.52, 4000, 'buy'),
        (current_time - timedelta(seconds=30), 149.51, 1200, 'buy'),
        (current_time - timedelta(seconds=20), 149.50, 600, 'sell'),
    ]
    
    # Add trades to flow data
    for timestamp, price, size, side in trades:
        update_trade_flow(symbol, timestamp, price, size, side)

def test_pressure_calculation():
    """Test basic pressure index calculation"""
    print("🧪 Testing Bid/Ask Pressure Index Calculation")
    print("=" * 60)
    
    symbol = "AAPL"
    current_price = 149.51
    
    # Set up test data
    setup_test_data(symbol)
    
    # Calculate pressure index
    pressure_data = compute_bid_ask_pressure_index(symbol, current_price, "REGULAR")
    
    print(f"\n📊 Pressure Index Results for {symbol} @ ${current_price:.2f}")
    print(f"  Pressure Index: {pressure_data['pressure_index']:.3f}")
    print(f"  Interpretation: {pressure_data['interpretation']}")
    print(f"  Alert Worthy: {pressure_data['alert_worthy']}")
    print()
    
    print(f"📈 Component Scores:")
    print(f"  Order Book Depth: {pressure_data['depth_score']:.3f}")
    print(f"  Aggressive Trade Flow: {pressure_data['aggressive_score']:.3f}")
    print()
    
    print(f"💹 Order Book Pressure:")
    print(f"  Bid Pressure: {pressure_data['bid_pressure']:.0f} weighted")
    print(f"  Ask Pressure: {pressure_data['ask_pressure']:.0f} weighted")
    print(f"  Bid/Ask Ratio: {(pressure_data['bid_pressure']/(pressure_data['ask_pressure']+1)):.2f}:1")
    print()
    
    print(f"📊 Trade Flow Analysis:")
    print(f"  Buy Volume: {pressure_data['buy_volume']:,} shares")
    print(f"  Sell Volume: {pressure_data['sell_volume']:,} shares")
    print(f"  Total Trades: {pressure_data['total_trades']}")
    print(f"  Large Trades: {pressure_data['large_trades']}")
    print()

def test_pressure_scenarios():
    """Test various pressure scenarios"""
    print("🧪 Testing Various Pressure Scenarios")
    print("=" * 60)
    
    scenarios = [
        ("NVDA", "Strong Buying", {
            'bid': 450.00, 'ask': 450.05, 'bid_size': 8000, 'ask_size': 2000,
            'trades': [
                (450.05, 3000, 'buy'), (450.04, 2500, 'buy'), (450.03, 2000, 'buy'),
                (450.00, 500, 'sell'), (450.01, 800, 'sell')
            ]
        }),
        ("TSLA", "Strong Selling", {
            'bid': 250.00, 'ask': 250.05, 'bid_size': 2000, 'ask_size': 8000,
            'trades': [
                (250.00, 3000, 'sell'), (250.01, 2500, 'sell'), (250.02, 2000, 'sell'),
                (250.05, 500, 'buy'), (250.04, 800, 'buy')
            ]
        }),
        ("SPY", "Neutral/Balanced", {
            'bid': 400.00, 'ask': 400.02, 'bid_size': 5000, 'ask_size': 5000,
            'trades': [
                (400.02, 1500, 'buy'), (400.01, 1200, 'buy'),
                (400.00, 1500, 'sell'), (400.01, 1200, 'sell')
            ]
        })
    ]
    
    for symbol, description, data in scenarios:
        print(f"\n📈 {description}: {symbol}")
        
        # Set up quote
        with quote_lock:
            latest_quotes[symbol] = {
                'bid': data['bid'],
                'ask': data['ask'],
                'bid_size': data['bid_size'],
                'ask_size': data['ask_size'],
                'timestamp': get_et_time()
            }
        
        # Set up trades
        current_time = get_et_time()
        for i, (price, size, side) in enumerate(data['trades']):
            timestamp = current_time - timedelta(seconds=(len(data['trades'])-i) * 10)
            update_trade_flow(symbol, timestamp, price, size, side)
        
        # Calculate pressure
        mid_price = (data['bid'] + data['ask']) / 2
        pressure_data = compute_bid_ask_pressure_index(symbol, mid_price, "REGULAR")
        
        print(f"  Pressure Index: {pressure_data['pressure_index']:.3f} - {pressure_data['interpretation']}")
        print(f"  Depth: {pressure_data['depth_score']:.2f} | Flow: {pressure_data['aggressive_score']:.2f}")
        print(f"  Buy: {pressure_data['buy_volume']:,} | Sell: {pressure_data['sell_volume']:,}")

def test_pressure_trend():
    """Test pressure trend analysis"""
    print("\n🧪 Testing Pressure Trend Analysis")
    print("=" * 60)
    
    symbol = "AAPL"
    current_time = get_et_time()
    
    # Simulate increasing buying pressure over time
    pressure_values = [0.45, 0.50, 0.55, 0.62, 0.68, 0.75, 0.78]
    
    for i, pressure in enumerate(pressure_values):
        timestamp = current_time - timedelta(minutes=(len(pressure_values)-i))
        interpretation = "Increasing Buy Pressure"
        pressure_index_history[symbol].append((timestamp, pressure, interpretation))
    
    # Analyze trend
    trend_data = get_pressure_trend(symbol, lookback_minutes=10)
    
    print(f"\n📊 Trend Analysis for {symbol}:")
    print(f"  Trend: {trend_data['trend'].replace('_', ' ').title()}")
    print(f"  Direction: {trend_data['direction'].title()}")
    print(f"  Strength: {trend_data['strength']:.2f}")
    print(f"  Sample Size: {trend_data['sample_size']} data points")

def test_alert_format():
    """Test alert message formatting"""
    print("\n📱 Testing Alert Message Format")
    print("=" * 60)
    
    symbol = "AAPL"
    current_price = 149.51
    
    # Set up strong buying pressure
    with quote_lock:
        latest_quotes[symbol] = {
            'bid': 149.50,
            'ask': 149.52,
            'bid_size': 8000,
            'ask_size': 2000,
            'timestamp': get_et_time()
        }
    
    # Add buying trades
    current_time = get_et_time()
    for i in range(10):
        update_trade_flow(symbol, current_time - timedelta(seconds=i*10), 149.52, 2000 + i*100, 'buy')
    for i in range(3):
        update_trade_flow(symbol, current_time - timedelta(seconds=i*15), 149.50, 500 + i*50, 'sell')
    
    # Calculate pressure
    pressure_data = compute_bid_ask_pressure_index(symbol, current_price, "REGULAR")
    
    # Get trend
    trend_data = get_pressure_trend(symbol, lookback_minutes=5)
    
    # Format sample alert
    pi = pressure_data['pressure_index']
    interp = pressure_data['interpretation']
    
    trend_emoji = "📈" if trend_data['direction'] == 'bullish' else "📉" if trend_data['direction'] == 'bearish' else "➡️"
    
    sample_alert = f"""⚡ BID/ASK PRESSURE ALERT (REGULAR)
{symbol} @ ${current_price:.2f}

{interp} | Index: {pi:.2f}
{trend_emoji} Trend: {trend_data['trend'].replace('_', ' ').title()}

📊 PRESSURE BREAKDOWN:
Order Book: {pressure_data['depth_score']:.2f} (Bid vs Ask depth)
Trade Flow: {pressure_data['aggressive_score']:.2f} (Buy vs Sell aggression)

💹 VOLUME ANALYSIS:
Buy Volume: {pressure_data['buy_volume']:,} shares
Sell Volume: {pressure_data['sell_volume']:,} shares
Large Trades: {pressure_data['large_trades']} / {pressure_data['total_trades']}

🎯 ORDER BOOK:
Bid Pressure: {pressure_data['bid_pressure']:.0f} weighted
Ask Pressure: {pressure_data['ask_pressure']:.0f} weighted
Bid/Ask Ratio: {(pressure_data['bid_pressure']/(pressure_data['ask_pressure']+1)):.2f}:1

{get_et_time().strftime('%I:%M:%S %p ET')}"""

    print("\n  Sample Alert Message:")
    for line in sample_alert.split('\n'):
        print(f"  {line}")

def test_edge_cases():
    """Test edge cases and error handling"""
    print("\n🧪 Testing Edge Cases")
    print("=" * 60)
    
    # Test with no data
    pressure_data = compute_bid_ask_pressure_index("UNKNOWN", 100.0, "REGULAR")
    print(f"\n  No Data Case:")
    print(f"    Pressure Index: {pressure_data['pressure_index']:.3f} (should be ~0.5)")
    print(f"    Interpretation: {pressure_data['interpretation']}")
    
    # Test with only quote data (no trades)
    with quote_lock:
        latest_quotes["TEST1"] = {
            'bid': 50.00,
            'ask': 50.05,
            'bid_size': 5000,
            'ask_size': 5000,
            'timestamp': get_et_time()
        }
    
    pressure_data = compute_bid_ask_pressure_index("TEST1", 50.02, "REGULAR")
    print(f"\n  Quote Only Case:")
    print(f"    Pressure Index: {pressure_data['pressure_index']:.3f}")
    print(f"    Interpretation: {pressure_data['interpretation']}")

if __name__ == "__main__":
    print("🚀 Testing Bid/Ask Pressure Index System")
    print("=" * 60)
    print()
    
    try:
        test_pressure_calculation()
        test_pressure_scenarios()
        test_pressure_trend()
        test_alert_format()
        test_edge_cases()
        
        print("\n" + "=" * 60)
        print("🎉 All Pressure Index Tests Completed Successfully!")
        print()
        print("✅ Features Tested:")
        print("  - Weighted order book depth scoring")
        print("  - Aggressive trade flow analysis")
        print("  - Pressure index calculation (0-1 scale)")
        print("  - Trend analysis and direction detection")
        print("  - Alert message formatting")
        print("  - Edge case handling")
        print()
        print("📊 Pressure Index Interpretation:")
        print("  0.70 - 1.00: 🟢 Strong to Moderate Buying")
        print("  0.40 - 0.60: ⚪ Neutral/Balanced")
        print("  0.00 - 0.30: 🔴 Moderate to Strong Selling")
        
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        import traceback
        traceback.print_exc()