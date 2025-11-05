"""
Simplified Polygon.io WebSocket Client for Pre-Market Data
Tracks OHLC data and sends Telegram alerts for significant price movements
"""

from polygon import WebSocketClient
from polygon.websocket.models import Feed, Market
from datetime import datetime, timedelta
import sys
import csv
import requests
import pytz
import time
import threading
import json
import os
from collections import defaultdict

# Configuration
API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"
TELEGRAM_BOT_TOKEN = "8230689629:AAHtpdsVb8znDZ_DyKMzcOgee-aczA9acOE"
TELEGRAM_CHAT_ID = "8258742558"
PRE_MARKET_START = "03:59"
PRE_MARKET_END = "09:30"
ALERT_COOLDOWN_MINUTES = 5
DATA_FILE = "symbol_tracking_data.json"

# Timezone
ET_TIMEZONE = pytz.timezone('US/Eastern')

# Global data structures
target_tickers = set()
minute_aggregates = defaultdict(lambda: defaultdict(lambda: {
    'open': None, 'close': 0, 'high': None, 'low': None,
    'volume': 0, 'value': 0, 'count': 0
}))
# Track both first occurrence (baseline) and previous minute for each symbol
symbol_data = {}  # {symbol: {'first': {'pct': float, 'vol': int, 'open': float, 'close': float, 'time': datetime}, 'prev': {'pct': float, 'vol': int, 'open': float, 'close': float, 'time': datetime}}}
alert_tracker = {}  # {symbol: datetime} - last alert time
data_lock = threading.Lock()
telegram_lock = threading.Lock()

def get_et_time():
    """Get current Eastern Time"""
    return datetime.now(ET_TIMEZONE)

def is_premarket_session():
    """Check if currently in pre-market (4:00 AM - 9:30 AM ET, weekdays)"""
    dt = get_et_time()
    if dt.weekday() >= 5:
        return False
    
    current_time = dt.time()
    start = datetime.strptime(PRE_MARKET_START, "%H:%M").time()
    end = datetime.strptime(PRE_MARKET_END, "%H:%M").time()
    return start <= current_time < end

def get_next_premarket():
    """Get next pre-market start time"""
    now = get_et_time()
    today_start = ET_TIMEZONE.localize(
        datetime.combine(now.date(), datetime.strptime(PRE_MARKET_START, "%H:%M").time())
    )
    
    if now < today_start and now.weekday() < 5:
        return today_start
    
    # Find next weekday
    next_day = now.date() + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    
    return ET_TIMEZONE.localize(
        datetime.combine(next_day, datetime.strptime(PRE_MARKET_START, "%H:%M").time())
    )

def read_tickers(filepath):
    """Read ticker symbols from CSV"""
    tickers = []
    try:
        with open(filepath, 'r') as f:
            for row in csv.reader(f):
                if row:
                    ticker = row[0].strip().upper()
                    if ticker and ticker != "SYMBOL":
                        tickers.append(ticker)
    except Exception as e:
        print(f"Error reading tickers: {e}")
    return tickers

def get_minute_ts(timestamp):
    """Convert timestamp to minute-level datetime"""
    if isinstance(timestamp, int):
        if timestamp > 1000000000000000:  # Nanoseconds
            dt = datetime.fromtimestamp(timestamp / 1e9)
        elif timestamp > 1000000000000:  # Milliseconds
            dt = datetime.fromtimestamp(timestamp / 1000)
        else:
            dt = datetime.fromtimestamp(timestamp)
    else:
        dt = timestamp
    return dt.replace(second=0, microsecond=0)

def send_telegram(message):
    """Send Telegram message with rate limiting"""
    with telegram_lock:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            response = requests.post(
                url,
                data={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'},
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Telegram error: {e}")
            return False

def can_send_alert(symbol, minute_ts):
    """Check if alert can be sent (respects cooldown)"""
    if symbol not in alert_tracker:
        return True
    
    last_alert = alert_tracker[symbol]
    minutes_since = (minute_ts - last_alert).total_seconds() / 60
    return minutes_since >= ALERT_COOLDOWN_MINUTES

def mark_alerted(symbol, minute_ts):
    """Mark symbol as alerted"""
    alert_tracker[symbol] = minute_ts

def save_previous_minute():
    """Save symbol tracking data to JSON file (first occurrence + previous minute)"""
    try:
        with data_lock:
            # Convert datetime objects to ISO format strings
            save_data = {}
            for symbol, data in symbol_data.items():
                save_data[symbol] = {}
                
                # Save first occurrence (baseline)
                if 'first' in data:
                    save_data[symbol]['first'] = {
                        'pct': data['first']['pct'],
                        'vol': data['first']['vol'],
                        'open': data['first']['open'],
                        'close': data['first']['close'],
                        'time': data['first']['time'].isoformat()
                    }
                
                # Save previous minute
                if 'prev' in data:
                    save_data[symbol]['prev'] = {
                        'pct': data['prev']['pct'],
                        'vol': data['prev']['vol'],
                        'open': data['prev']['open'],
                        'close': data['prev']['close'],
                        'time': data['prev']['time'].isoformat()
                    }
        
        with open(DATA_FILE, 'w') as f:
            json.dump(save_data, f, indent=2)
        
        print(f"✓ Saved data for {len(save_data)} symbols")
        return True
    except Exception as e:
        print(f"Save error: {e}")
        return False

def load_previous_minute():
    """Load symbol tracking data from JSON file (first occurrence + previous minute)"""
    if not os.path.exists(DATA_FILE):
        print("📂 No previous data found")
        return False
    
    try:
        with open(DATA_FILE, 'r') as f:
            save_data = json.load(f)
        
        with data_lock:
            symbol_data.clear()
            for symbol, data in save_data.items():
                symbol_data[symbol] = {}
                
                # Load first occurrence (baseline)
                if 'first' in data:
                    symbol_data[symbol]['first'] = {
                        'pct': data['first']['pct'],
                        'vol': data['first']['vol'],
                        'open': data['first']['open'],
                        'close': data['first']['close'],
                        'time': datetime.fromisoformat(data['first']['time'])
                    }
                
                # Load previous minute
                if 'prev' in data:
                    symbol_data[symbol]['prev'] = {
                        'pct': data['prev']['pct'],
                        'vol': data['prev']['vol'],
                        'open': data['prev']['open'],
                        'close': data['prev']['close'],
                        'time': datetime.fromisoformat(data['prev']['time'])
                    }
        
        print(f"✓ Loaded data for {len(save_data)} symbols")
        return True
    except Exception as e:
        print(f"Load error: {e}")
        return False

def should_alert(pct_change, volume, prev_volume=None):
    """Check if conditions meet alert criteria"""
    if prev_volume is not None:
        volume_ratio = volume / prev_volume
        return (
            (volume_ratio >= 100 and volume >= 1000)
        )
    else:
        # If prev_volume is None or 0 (gap in data), use stricter criteria
        return (
            (pct_change >= 0 and volume >= 50000) or
            (pct_change >= 10 and volume >= 20000) or
            (pct_change >= 20 and volume >= 10000) or
            (pct_change >= 30 and volume >= 5000)
        )

def check_spike(symbol, current_pct, current_vol, minute_ts, open_price, close_price):
    """Check for spike and send alert if conditions met"""
    spike = False
    message = ""
    
    with data_lock:
        if symbol in symbol_data:
            # Symbol has been seen before
            data = symbol_data[symbol]
            
            # Check if we have previous minute data
            if 'prev' in data:
                prev = data['prev']
                
                # Only check if new minute
                if prev['time'] != minute_ts:
                    expected_prev_time = minute_ts - timedelta(minutes=1)
                    is_consecutive = (prev['time'] == expected_prev_time)
                    
                    pct_diff = current_pct - prev['pct']
                    
                    prev_vol = prev['vol'] if is_consecutive else 1
                    
                    if should_alert(pct_diff, current_vol, prev_vol):
                        spike = True
                        first = data.get('first', prev)
                        
                        # Show different message based on whether prev is consecutive
                        if is_consecutive:
                            message = (
                                f"🚨 SPIKE: {symbol}\n"
                                f"Base: ${first['open']:.2f} @ {first['time'].strftime('%H:%M')} (0.00%)\n"
                                f"Prev: {prev['pct']:+.2f}% ({prev['vol']:,}) @ {prev['time'].strftime('%H:%M')}\n"
                                f"Now: {current_pct:+.2f}% ({current_vol:,}) @ {minute_ts.strftime('%H:%M')}\n"
                                f"Δ Change: {pct_diff:+.2f}%\n"
                                f"Current Price: ${close_price:.2f}"
                            )
                        else:
                            message = (
                                f"🚨 SPIKE: {symbol}\n"
                                f"Base: ${first['open']:.2f} @ {first['time'].strftime('%H:%M')} (0.00%)\n"
                                f"Last: {prev['pct']:+.2f}% @ {prev['time'].strftime('%H:%M')} (gap)\n"
                                f"Now: {current_pct:+.2f}% ({current_vol:,}) @ {minute_ts.strftime('%H:%M')}\n"
                                f"Δ Change: {pct_diff:+.2f}%\n"
                                f"Current Price: ${close_price:.2f}"
                            )
                    
                    # Update previous minute
                    symbol_data[symbol]['prev'] = {
                        'pct': current_pct,
                        'vol': current_vol,
                        'open': open_price,
                        'close': close_price,
                        'time': minute_ts
                    }
                else:
                    # Same minute - just update the values
                    symbol_data[symbol]['prev'] = {
                        'pct': current_pct,
                        'vol': current_vol,
                        'open': open_price,
                        'close': close_price,
                        'time': minute_ts
                    }
            else:
                # Have first occurrence but no prev minute yet (shouldn't happen, but handle it)
                symbol_data[symbol]['prev'] = {
                    'pct': current_pct,
                    'vol': current_vol,
                    'open': open_price,
                    'close': close_price,
                    'time': minute_ts
                }
        else:
            # First observation for this symbol - store as both first and prev
            if should_alert(current_pct, current_vol):
                spike = True
                message = (
                    f"🚨 FIRST SPIKE: {symbol}\n"
                    f"Data: {current_pct:+.2f}% ({current_vol:,})\n"
                    f"Open: ${open_price:.2f} → Close: ${close_price:.2f}"
                )
            
            # Store first occurrence (baseline) with prices and current as prev
            symbol_data[symbol] = {
                'first': {
                    'pct': current_pct,
                    'vol': current_vol,
                    'open': open_price,
                    'close': close_price,
                    'time': minute_ts
                },
                'prev': {
                    'pct': current_pct,
                    'vol': current_vol,
                    'open': open_price,
                    'close': close_price,
                    'time': minute_ts
                }
            }
    
    # Send alert if spike detected and not in cooldown
    if spike and can_send_alert(symbol, minute_ts):
        if send_telegram(message):
            mark_alerted(symbol, minute_ts)
            print(f"✓ Alert sent: {symbol}")

def update_aggregates(symbol, price, size, timestamp):
    """Update minute-level aggregates"""
    minute_ts = get_minute_ts(timestamp)
    
    with data_lock:
        agg = minute_aggregates[minute_ts][symbol]
        
        # Update OHLC
        if agg['open'] is None:
            agg['open'] = price
        agg['close'] = price
        
        if agg['high'] is None or price > agg['high']:
            agg['high'] = price
        if agg['low'] is None or price < agg['low']:
            agg['low'] = price
        
        # Update volume
        agg['volume'] += size
        agg['value'] += price * size
        agg['count'] += 1
        
        # Calculate percentage change from baseline (first occurrence open price)
        # If no baseline yet, use minute's own open price
        base_price = None
        if symbol in symbol_data and 'first' in symbol_data[symbol]:
            base_price = symbol_data[symbol]['first']['open']
        else:
            base_price = agg['open']
        
        pct_change = 0
        if base_price and base_price > 0:
            pct_change = ((agg['close'] - base_price) / base_price) * 100
        
        return minute_ts, agg['volume'], pct_change, agg['open'], agg['close']

def handle_msg(msgs):
    """Handle incoming WebSocket messages"""
    if not isinstance(msgs, list):
        msgs = [msgs]
    
    for msg in msgs:
        try:
            # Only process trade messages for target tickers
            if not hasattr(msg, 'symbol') or not hasattr(msg, 'price'):
                continue
            
            symbol = msg.symbol
            if symbol not in target_tickers:
                continue
            
            price = msg.price
            size = msg.size
            timestamp = msg.timestamp
            
            # Update aggregates and check for spike
            minute_ts, volume, pct_change, open_price, close_price = update_aggregates(symbol, price, size, timestamp)
            check_spike(symbol, pct_change, volume, minute_ts, open_price, close_price)
            
        except Exception as e:
            print(f"Error processing message: {e}")

def run_session():
    """Run WebSocket session during pre-market"""
    print(f"✓ Session started: {get_et_time().strftime('%H:%M:%S ET')}")
    
    # Load previous data if available
    load_previous_minute()
    
    # Clear alert tracker for new session
    with data_lock:
        alert_tracker.clear()
    
    try:
        client = WebSocketClient(
            api_key=API_KEY,
            feed=Feed.RealTime,
            market=Market.Stocks
        )
        
        # Subscribe to all trades
        client.subscribe('T.*')
        
        # Run in background thread
        ws_running = [True]
        
        def ws_runner():
            try:
                client.run(handle_msg)
            except Exception as e:
                print(f"WebSocket error: {e}")
                ws_running[0] = False
        
        ws_thread = threading.Thread(target=ws_runner, daemon=True)
        ws_thread.start()
        
        # Monitor session
        while is_premarket_session() and ws_running[0]:
            time.sleep(5)
        
        ws_running[0] = False
        print(f"✓ Session ended: {get_et_time().strftime('%H:%M:%S ET')}")
        
        # Save data at end of session
        save_previous_minute()
        
    except Exception as e:
        print(f"Session error: {e}")

def main():
    """Main function"""
    global target_tickers
    
    print("🚀 Pre-Market Monitor")
    print(f"⏰ Active: {PRE_MARKET_START} - {PRE_MARKET_END} ET")
    
    # Load tickers
    target_tickers = set(read_tickers("tickers.csv"))
    print(f"📊 Monitoring {len(target_tickers)} tickers")
    
    try:
        while True:
            if is_premarket_session():
                run_session()
            else:
                next_session = get_next_premarket()
                wait_time = (next_session - get_et_time()).total_seconds()
                
                hours = int(wait_time // 3600)
                minutes = int((wait_time % 3600) // 60)
                
                print(f"💤 Next session: {next_session.strftime('%Y-%m-%d %H:%M ET')} ({hours}h {minutes}m)")
                time.sleep(min(300, max(1, wait_time - 10)))  # Check every 5 min or sooner
                
    except KeyboardInterrupt:
        print("\n💾 Saving data before exit...")
        save_previous_minute()
        print("✓ Shutdown complete")
        sys.exit(0)

if __name__ == "__main__":
    main()