"""
Command-line tool to verify alerts using the ACTUAL check_spike logic from polygon_websocket.py

Usage:
    python verify_alerts_advanced.py SYMBOL DATE START_TIME END_TIME
    
Examples:
    python verify_alerts_advanced.py BKYI 2025-11-07 09:30 09:45
    python verify_alerts_advanced.py RUBI 2025-11-07 08:00 08:15
    python verify_alerts_advanced.py VSME 2025-11-07 08:00 08:30
"""

import sys
import os

# CRITICAL: Set this BEFORE importing polygon_websocket
# so it reads the env var at module load time
os.environ["DISABLE_NOTIFICATIONS"] = "1"

import requests
import csv
from datetime import datetime, timedelta
import pytz
from collections import defaultdict

# Import the actual detection logic from polygon_websocket.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import polygon_websocket

# Configuration
API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"

def load_historical_stats(symbol):
    """Load historical statistics for symbol"""
    try:
        with open('historical_data/stats_cache.csv', 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['symbol'] == symbol:
                    return {
                        'avg_volume': float(row['avg_volume_20d']) if row['avg_volume_20d'] else None,
                        'avg_range': float(row['avg_range_20d']) if row['avg_range_20d'] else None
                    }
    except Exception as e:
        print(f"⚠️ Warning: Could not load historical stats: {e}")
    return {'avg_volume': None, 'avg_range': None}

def fetch_data(symbol, date, start_time, end_time):
    """Fetch minute data from Polygon API"""
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/minute/{date}/{date}"
    params = {
        'apiKey': API_KEY,
        'adjusted': 'true',
        'sort': 'asc',
        'limit': 50000
    }
    
    print(f"📡 Fetching {symbol} data from Polygon API...")
    
    response = requests.get(url, params=params, timeout=30)
    
    if response.status_code != 200:
        print(f"❌ API Error: {response.status_code}")
        return None
    
    data = response.json()
    
    if data.get('status') != 'OK':
        print(f"❌ API returned status: {data.get('status')}")
        return None
    
    results = data.get('results', [])
    print(f"✓ Received {len(results)} total bars for {date}")
    
    # Filter for time range and convert
    et_tz = pytz.timezone('America/New_York')
    target_start = et_tz.localize(datetime.strptime(f"{date} {start_time}:00", "%Y-%m-%d %H:%M:%S"))
    target_end = et_tz.localize(datetime.strptime(f"{date} {end_time}:00", "%Y-%m-%d %H:%M:%S"))
    
    print(f"Target range: {target_start.strftime('%Y-%m-%d %H:%M:%S ET')} to {target_end.strftime('%Y-%m-%d %H:%M:%S ET')}")
    
    all_bars = []
    for bar in results:
        bar_time = datetime.fromtimestamp(bar['t'] / 1000, tz=pytz.UTC).astimezone(et_tz)
        pct = ((bar['c'] - bar['o']) / bar['o']) * 100 if bar['o'] > 0 else 0
        
        all_bars.append({
            'time': bar_time.strftime('%H:%M'),
            'datetime': bar_time,
            'open': bar['o'],
            'high': bar['h'],
            'low': bar['l'],
            'close': bar['c'],
            'volume': bar['v'],
            'trades': bar['n'],
            'vwap': bar['vw'],
            'pct': pct,
            'in_range': target_start <= bar_time <= target_end
        })
    
    return all_bars

def simulate_detection(symbol, all_bars, target_range_only=False):
    """Simulate the actual detection logic with proper state management"""
    
    # Reset global state to simulate fresh session
    polygon_websocket.minute_aggregates.clear()
    polygon_websocket.rolling_volume_3min.clear()
    polygon_websocket.momentum_counter.clear()
    polygon_websocket.alert_tracker.clear()
    polygon_websocket.price_history.clear()
    
    # Load historical stats into cache
    stats = load_historical_stats(symbol)
    if stats['avg_volume']:
        polygon_websocket.historical_stats_cache[symbol] = {
            'avg_volume': stats['avg_volume'],
            'avg_range': stats['avg_range'],
            'last_updated': ''
        }
    
    print(f"\n{'='*80}")
    print(f"SIMULATING REAL-TIME DETECTION FOR {symbol}")
    print(f"{'='*80}")
    
    if stats['avg_volume']:
        print(f"\nHistorical Stats:")
        print(f"  Avg 20-day volume: {stats['avg_volume']:,.0f}")
        print(f"  Avg 20-day range: ${stats['avg_range']:.2f}")
    
    alerts = []
    
    # Process bars chronologically to build up state
    for i, bar in enumerate(all_bars):
        dt = bar['datetime']
        
        # Update minute_aggregates (simulate the aggregate building)
        minute_ts = dt.replace(second=0, microsecond=0)
        polygon_websocket.minute_aggregates[minute_ts][symbol] = {
            'open': bar['open'],
            'close': bar['close'],
            'high': bar['high'],
            'low': bar['low'],
            'volume': bar['volume'],
            'value': bar['vwap'] * bar['volume'],
            'count': bar['trades'],
            'vwap': bar['vwap']
        }
        
        # Update rolling volume (shift window)
        if i >= 1:
            prev_vol = all_bars[i-1]['volume']
            polygon_websocket.update_rolling_volume(symbol, prev_vol)
        
        # Update price history
        polygon_websocket.update_price_history(symbol, dt, bar['close'], bar['volume'])
        
        # Build momentum state for ALL bars (needed for context)
        # but only run full check_spike (which prints/alerts) for target range
        if not bar['in_range']:
            # Just update momentum counter without alerting
            vols = polygon_websocket.rolling_volume_3min.get(symbol, [0, 0, 0])
            vol_prev5 = sum(vols) / max(len(vols), 1)
            rel_vol = bar['volume'] / max(vol_prev5, 1)
            
            # Get dynamic thresholds
            avg_vol_20d = polygon_websocket.get_average_volume(symbol)
            avg_range_20d = polygon_websocket.get_average_price_range(symbol)
            
            if avg_range_20d and bar['open'] > 0:
                pct_thresh = max(3.8, (avg_range_20d / bar['open']) * 1.2)
            else:
                pct_thresh = 3.8
            
            relvol_ok = rel_vol >= 2.0
            pct_ok = bar['pct'] >= pct_thresh
            
            if relvol_ok and pct_ok:
                polygon_websocket.momentum_counter[symbol] = polygon_websocket.momentum_counter.get(symbol, 0) + 1
            else:
                polygon_websocket.momentum_counter[symbol] = max(0, polygon_websocket.momentum_counter.get(symbol, 0) - 1)
            
            continue  # Skip to next bar
        
        # Only call check_spike for bars in target range
        alert = polygon_websocket.check_spike(
            symbol=symbol,
            current_pct=bar['pct'],
            current_vol=bar['volume'],
            minute_ts=dt,
            open_price=bar['open'],
            close_price=bar['close'],
            trade_count=bar['trades'],
            vwap=bar['vwap']
        )
        
        status = "✅ ALERTED" if alert else "❌ NO ALERT"
        print(f"\n{bar['time']} {status}")
        print(f"  ${bar['open']:.2f} → ${bar['close']:.2f} ({bar['pct']:+.2f}%)")
        print(f"  Volume: {bar['volume']:,} | Trades: {bar['trades']:,}")
        print(f"  Momentum persistence: {polygon_websocket.momentum_counter.get(symbol, 0)} bars")
        
        if alert:
            print(f"  🔥 Stage: {alert['stage']}")
            print(f"  🔥 Quality: {alert['quality_score']:.1f}/100")
            print(f"  🔥 RelVol: {alert['rel_vol']:.2f}x")
            alerts.append({**bar, 'alert_data': alert})
    
    return alerts

def main():
    if len(sys.argv) != 5:
        print("Usage: python verify_alerts_advanced.py SYMBOL DATE START_TIME END_TIME")
        print("\nExamples:")
        print("  python verify_alerts_advanced.py BKYI 2025-11-07 09:30 09:45")
        print("  python verify_alerts_advanced.py RUBI 2025-11-07 08:00 08:15")
        print("  python verify_alerts_advanced.py VSME 2025-11-07 08:00 08:30")
        print("\nNote:")
        print("  - Uses ACTUAL check_spike logic from polygon_websocket.py")
        print("  - Simulates full state (persistence, VWAP, momentum)")
        print("  - Times are in ET (Eastern Time)")
        print("  - Use 24-hour format (e.g., 09:30, 14:45)")
        sys.exit(1)
    
    symbol = sys.argv[1].upper()
    date = sys.argv[2]
    start_time = sys.argv[3]
    end_time = sys.argv[4]
    
    print(f"{'='*80}")
    print(f"ADVANCED ALERT VERIFICATION (Using Real check_spike Logic)")
    print(f"{'='*80}")
    print(f"Symbol: {symbol}")
    print(f"Date: {date}")
    print(f"Time: {start_time} - {end_time} ET")
    
    # Note: DISABLE_NOTIFICATIONS already set at module import time
    
    # Fetch ALL bars for the day (need context before target range)
    # We pass the user's requested start/end times - fetch_data will get all bars
    # but only mark the requested range as in_range=True
    all_bars = fetch_data(symbol, date, start_time, end_time)
    
    if all_bars is None:
        print("\n❌ Failed to fetch data from API")
        sys.exit(1)
    
    # Simulate detection
    alerts = simulate_detection(symbol, all_bars)
    
    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    
    if alerts:
        print(f"\n✅ {len(alerts)} alert(s) triggered in time range:")
        for alert in alerts:
            alert_data = alert['alert_data']
            print(f"\n  {alert['time']} - {alert_data['stage']}")
            print(f"    Move: {alert['pct']:+.2f}% | Volume: {alert['volume']:,}")
            print(f"    Quality: {alert_data['quality_score']:.1f}/100")
            print(f"    RelVol: {alert_data['rel_vol']:.2f}x")
            print(f"    VWAP Trend: {alert_data['vwap_trend']}")
            print(f"    Momentum Bars: {alert_data['momentum_bars']}")
    else:
        print(f"\n❌ NO alerts would be triggered")
        print("\nPossible reasons:")
        print("  • Multi-bar persistence not met (need 1-3 consecutive bars)")
        print("  • VWAP trend bearish on multiple lookback periods")
        print("  • Quality score below Stage 1 threshold (45)")
        print("  • Volume/percentage below dynamic thresholds")
        print("  • Within 5-minute cooldown from previous alert")
    
    print(f"\n{'='*80}")
    print("✓ Simulation complete")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
