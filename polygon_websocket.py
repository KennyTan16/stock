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
    """Save minute aggregates to JSON file"""
    try:
        filename = f"minute_data_{get_et_time().strftime('%Y%m%d')}.json"
        
        with data_lock:
            # Convert to serializable format
            save_data = {}
            for minute_ts, symbols in minute_aggregates.items():
                minute_key = minute_ts.strftime('%Y-%m-%d %H:%M:%S')
                save_data[minute_key] = {}
                for symbol, agg in symbols.items():
                    save_data[minute_key][symbol] = dict(agg)
        
        with open(filename, 'w') as f:
            json.dump(save_data, f, indent=2)
        
        print(f"✓ Saved {len(save_data)} minutes of data")
        return True
    except Exception as e:
        print(f"Save error: {e}")
        return False

def load_previous_minute():
    """Load minute aggregates from JSON file"""
    filename = f"minute_data_{get_et_time().strftime('%Y%m%d')}.json"
    
    if not os.path.exists(filename):
        print("📂 No previous data found")
        return False
    
    try:
        with open(filename, 'r') as f:
            save_data = json.load(f)
        
        with data_lock:
            minute_aggregates.clear()
            for minute_key, symbols in save_data.items():
                minute_ts = datetime.strptime(minute_key, '%Y-%m-%d %H:%M:%S')
                for symbol, agg in symbols.items():
                    minute_aggregates[minute_ts][symbol] = agg
        
        print(f"✓ Loaded {len(save_data)} minutes of data")
        return True
    except Exception as e:
        print(f"Load error: {e}")
        return False

def should_alert(pct_change, volume):
    """Check if conditions meet alert criteria - based on current minute only"""
    return (
        (pct_change >= 5 and volume >= 20000) or
        (pct_change >= 10 and volume >= 15000) or
        (pct_change >= 15 and volume >= 10000) or
        (pct_change >= 20 and volume >= 5000) or
        (pct_change >= 30 and volume >= 1000) or
        (volume >= 50000)
    )

def check_spike(symbol, current_pct, current_vol, minute_ts, open_price, close_price):
    """Check for spike and send alert if conditions met - current minute only"""
    
    # Check if current minute meets alert criteria
    if should_alert(current_pct, current_vol):
        message = (
            f"🚨 SPIKE: {symbol} @ {minute_ts.strftime('%H:%M')}\n"
            f"Open: ${open_price:.2f} → Close: ${close_price:.2f}\n"
            f"Change: {current_pct:+.2f}%\n"
            f"Volume: {current_vol:,}"
        )
        
        # Send alert if not in cooldown
        if can_send_alert(symbol, minute_ts):
            if send_telegram(message):
                mark_alerted(symbol, minute_ts)
                print(f"✓ Alert sent: {symbol} ({current_pct:+.2f}%, {current_vol:,})")

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
        
        # Calculate percentage change within the current minute (open to close)
        pct_change = 0
        if agg['open'] and agg['open'] > 0:
            pct_change = ((agg['close'] - agg['open']) / agg['open']) * 100
        
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