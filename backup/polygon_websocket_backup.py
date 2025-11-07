"""
Polygon.io WebSocket Client for Real-Time Pre-Market Data

Simple WebSocket client to receive real-time stock data for pre-market analysis.
Subscribes to minute aggregates for specified tickers and displays live price updates.
"""

from polygon import WebSocketClient
from polygon.websocket.models import Feed, Market
from datetime import datetime, timedelta, time
import sys
import logging
import csv
from collections import defaultdict
from typing import List
import requests
import pytz
import time as time_module
import json
from datetime import datetime
import threading
import queue

# Global dictionary to store latest prices
ticker_prices = {}

# Global dictionary to store minute aggregates
# Structure: {minute_timestamp: {symbol: {total_volume: int, total_value: float, trade_count: int, avg_price: float, open_price: float, close_price: float, high_price: float, low_price: float, open_close_change_pct: float}}}
minute_aggregates = defaultdict(lambda: defaultdict(lambda: {
    'total_volume': 0, 
    'total_value': 0, 
    'trade_count': 0, 
    'avg_price': 0,
    'open_price': None,
    'close_price': 0,
    'high_price': None,
    'low_price': None,
    'open_close_change_pct': 0
}))

# Global dictionary to store previous minute data for comparison
# Structure: {symbol: {'prev_change_pct': float, 'prev_volume': int, 'prev_minute': datetime, 'checked_for_spike': bool}}
previous_minute_data = {}

# Global dictionary to track symbols that have already been alerted to prevent spam
# Structure: {symbol: {'last_alert_minute': datetime, 'alert_type': str, 'cooldown_minutes': int}}
alerted_symbols = {}

# Global variable to store target tickers for filtering
target_tickers = set()

# Telegram configuration
TELEGRAM_BOT_TOKEN = "8230689629:AAHtpdsVb8znDZ_DyKMzcOgee-aczA9acOE"
TELEGRAM_CHAT_ID = "8258742558"

# Global Telegram message queue for truly async sending
telegram_queue = queue.Queue(maxsize=100)  # Limit queue size to prevent memory issues
telegram_worker_running = False
telegram_worker_thread = None

# Pre-market session configuration (Eastern Time)
PRE_MARKET_START = "03:59"  # 4:00 AM ET
PRE_MARKET_END = "09:30"    # 9:30 AM ET

# Timezone configuration
ET_TIMEZONE = pytz.timezone('US/Eastern')

def get_et_time():
    """Get current Eastern Time"""
    return datetime.now(ET_TIMEZONE)

def create_et_datetime(date, time_str):
    """Create Eastern Time datetime from date and time string"""
    time_obj = datetime.strptime(time_str, "%H:%M").time()
    naive_dt = datetime.combine(date, time_obj)
    return ET_TIMEZONE.localize(naive_dt)

def is_premarket_session(dt=None):
    """Check if we're currently in pre-market session (4:00 AM - 9:30 AM ET)"""
    if dt is None:
        dt = get_et_time()
    
    # Check if it's a weekday (Monday=0, Sunday=6)
    if dt.weekday() >= 5:
        return False
    
    # Convert to time for comparison
    current_time = dt.time()
    start_time = datetime.strptime(PRE_MARKET_START, "%H:%M").time()
    end_time = datetime.strptime(PRE_MARKET_END, "%H:%M").time()
    
    return start_time <= current_time < end_time

def get_next_premarket_time(current_time):
    """Calculate the next pre-market session start time"""
    today = current_time.date()
    premarket_start_today = create_et_datetime(today, PRE_MARKET_START)
    
    # If we haven't reached today's pre-market yet and it's a weekday
    if current_time < premarket_start_today and today.weekday() < 5:
        return premarket_start_today
    
    # Otherwise, find next weekday
    next_day = today + timedelta(days=1)
    while next_day.weekday() >= 5:  # Skip weekends
        next_day += timedelta(days=1)
    
    return create_et_datetime(next_day, PRE_MARKET_START)

def telegram_worker():
    """Background worker to process Telegram messages from queue"""
    global telegram_worker_running
    
    message_count = 0
    
    while telegram_worker_running:
        try:
            # Wait for a message from the queue (with timeout)
            message = telegram_queue.get(timeout=1.0)
            message_count += 1
                        
            # Send the message
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            
            payload = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'HTML'
            }
            
            try:
                response = requests.post(url, data=payload, timeout=5)
                
                if response.status_code == 200:
                    print(f"✅ Telegram message #{message_count} sent successfully")
                else:
                    print(f"❌ Failed to send Telegram message #{message_count}: {response.status_code}")
                    print(f"📋 Response: {response.text[:200]}")
            except requests.RequestException as e:
                print(f"❌ Network error sending Telegram message #{message_count}: {e}")
            
            # Mark task as done
            telegram_queue.task_done()
                
        except queue.Empty:
            # No message in queue, continue loop (this is normal)
            continue
        except Exception as e:
            print(f"❌ Telegram worker critical error: {e}")
            continue
    
    print(f"📱 Telegram worker stopped (processed {message_count} messages")

def start_telegram_worker():
    """Start the Telegram worker thread"""
    global telegram_worker_running, telegram_worker_thread
    
    # Always stop existing worker first
    if telegram_worker_running:
        stop_telegram_worker()
        time_module.sleep(1)  # Give it time to stop
    
    telegram_worker_running = True
    telegram_worker_thread = threading.Thread(target=telegram_worker, daemon=True)
    telegram_worker_thread.name = "TelegramWorker"
    telegram_worker_thread.start()
    
    # Verify the thread actually started
    time_module.sleep(0.2)  # Give it a moment to start
    if telegram_worker_thread.is_alive():
        print(f"📱 Telegram worker thread started successfully")
    else:
        print(f"❌ Telegram worker thread failed to start!")
        
    return telegram_worker_thread

def check_telegram_worker_health():
    """Check if Telegram worker thread is still alive and restart if needed"""
    global telegram_worker_thread, telegram_worker_running
    
    try:
        if not telegram_worker_running:
            print(f"❌ Telegram worker not supposed to be running")
            return False
            
        # Check if we have a thread reference and if it's alive
        if telegram_worker_thread is not None and hasattr(telegram_worker_thread, 'is_alive'):
            is_alive = telegram_worker_thread.is_alive()
            if not is_alive:
                print(f"❌ Telegram worker thread is dead (reference check) - FORCING RESTART")
                start_telegram_worker()
                return False
            return is_alive
        
        # No thread reference - this is bad, force restart
        print(f"❌ No Telegram worker thread reference - FORCING RESTART")
        start_telegram_worker()
        return False
    except Exception as e:
        print(f"❌ Error checking worker health: {e}")
        # Try to restart worker
        try:
            start_telegram_worker()
        except:
            pass
        return False

def stop_telegram_worker():
    """Stop the Telegram worker thread"""
    global telegram_worker_running, telegram_worker_thread
    telegram_worker_running = False
    telegram_worker_thread = None
    print(f"📱 Telegram worker stop requested")

def queue_telegram_message(message):
    """Add a message to the Telegram queue for async sending"""
    try:
        # Try to add to queue (non-blocking)
        telegram_queue.put_nowait(message)
        queue_size = telegram_queue.qsize()
        print(f"📬 Message queued (Queue: {queue_size}/100)")
        
        # Warn if queue is getting full
        if queue_size > 80:
            print(f"⚠️ WARNING: Telegram queue is {queue_size}% full!")
        
        return True
    except queue.Full:
        print(f"❌ CRITICAL: Telegram queue is FULL! Message dropped!")
        print(f"📋 Dropped message preview: {message[:100]}...")
        
        # Try to remove oldest message and add new one
        try:
            telegram_queue.get_nowait()  # Remove oldest
            telegram_queue.put_nowait(message)  # Add new
            print(f"♻️ Removed oldest message to make room")
            return True
        except:
            return False
    except Exception as e:
        print(f"❌ Error queuing Telegram message: {e}")
        import traceback
        traceback.print_exc()
        return False

def read_tickers_from_csv(filepath: str) -> List[str]:
    """
    Read ticker symbols from a CSV file.
    
    Args:
        filepath (str): Path to the CSV file containing ticker symbols
        
    Returns:
        List[str]: List of ticker symbols
    """
    tickers = []
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            csv_reader = csv.reader(file)
            for row in csv_reader:
                if row:  # Check if row is not empty
                    # Take the first column and clean it
                    ticker = row[0].strip().upper()
                    if ticker and ticker != "SYMBOL":  # Skip header if it exists
                        tickers.append(ticker)
        return tickers
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return []
    
def convert_timestamp_to_datetime(timestamp):
    """Convert various timestamp formats to datetime object"""
    if timestamp:
        if isinstance(timestamp, int):
            # Handle both millisecond and nanosecond timestamps
            if timestamp > 1000000000000000:  # Nanoseconds
                return datetime.fromtimestamp(timestamp / 1000000000)
            elif timestamp > 1000000000000:  # Milliseconds
                return datetime.fromtimestamp(timestamp / 1000)
            else:  # Seconds
                return datetime.fromtimestamp(timestamp)
        else:
            return timestamp
    else:
        return datetime.now()
    
def get_minute_timestamp(timestamp):
    """Convert timestamp to minute-level timestamp (remove seconds)"""
    if isinstance(timestamp, int):
        # Handle both millisecond and nanosecond timestamps
        if timestamp > 1000000000000000:  # Nanoseconds
            dt = datetime.fromtimestamp(timestamp / 1000000000)
        elif timestamp > 1000000000000:  # Milliseconds
            dt = datetime.fromtimestamp(timestamp / 1000)
        else:  # Seconds
            dt = datetime.fromtimestamp(timestamp)
    else:
        dt = timestamp
    
    # Round down to the minute (set seconds and microseconds to 0)
    minute_dt = dt.replace(second=0, microsecond=0)
    return minute_dt


def handle_msg(msg):
    """Handle incoming WebSocket messages"""
    global ticker_prices
    
    if isinstance(msg, list):
        # Handle multiple messages
        for message in msg:
            process_message(message)
    else:
        # Handle single message
        process_message(msg)

def update_minute_aggregates(symbol, trade_price, trade_size, dt):
    """Update minute-level trade aggregates with OHLC data and percentage change"""
    global minute_aggregates
    
    minute_ts = get_minute_timestamp(dt)
    trade_value = trade_price * trade_size
    
    agg = minute_aggregates[minute_ts][symbol]
    
    # Update volume and value aggregates
    agg['total_volume'] += trade_size
    agg['total_value'] += trade_value
    agg['trade_count'] += 1
    
    # Set opening price (first trade of the minute)
    if agg['open_price'] is None:
        agg['open_price'] = trade_price
    
    # Always update closing price (last trade becomes close)
    agg['close_price'] = trade_price
    
    # Update high and low prices
    if agg['high_price'] is None or trade_price > agg['high_price']:
        agg['high_price'] = trade_price
    if agg['low_price'] is None or trade_price < agg['low_price']:
        agg['low_price'] = trade_price
    
    # Calculate average price
    if agg['total_volume'] > 0:
        agg['avg_price'] = agg['total_value'] / agg['total_volume']
    
    # Calculate open-to-close percentage change for the minute
    if agg['open_price'] and agg['open_price'] > 0:
        price_change = agg['close_price'] - agg['open_price']
        agg['open_close_change_pct'] = (price_change / agg['open_price']) * 100
    
    return minute_ts, agg

def update_latest_prices(symbol, price, size, timestamp, dt, **kwargs):
    """Update the latest price dictionary"""
    global ticker_prices
    
    time_str = dt.strftime('%H:%M:%S.%f')[:-3]
    ticker_prices[symbol] = {
        'price': price,
        'size': size,
        'time': time_str,
        'timestamp': timestamp,
        **kwargs
    }


def get_minute_stats(symbol, minute_timestamp=None):
    """Get minute statistics for a specific symbol and minute"""
    global minute_aggregates
    
    if minute_timestamp is None:
        # Get the latest minute for this symbol
        symbol_minutes = []
        for minute_ts, symbols in minute_aggregates.items():
            if symbol in symbols:
                symbol_minutes.append(minute_ts)
        
        if not symbol_minutes:
            return None
        
        minute_timestamp = max(symbol_minutes)
    
    if minute_timestamp in minute_aggregates and symbol in minute_aggregates[minute_timestamp]:
        agg = minute_aggregates[minute_timestamp][symbol]
        return {
            'symbol': symbol,
            'minute': minute_timestamp,
            'open_price': agg['open_price'],
            'close_price': agg['close_price'],
            'high_price': agg['high_price'],
            'low_price': agg['low_price'],
            'volume': agg['total_volume'],
            'avg_price': agg['avg_price'],
            'trade_count': agg['trade_count'],
            'open_close_change_pct': agg['open_close_change_pct'],
            'open_close_change_dollar': agg['close_price'] - agg['open_price'] if agg['open_price'] else 0
        }
    
    return None

def evaluate_spike_conditions(pct_change, volume):
    """
    Evaluate if percentage change and volume meet spike detection criteria
    
    Args:
        pct_change (float): Percentage change to evaluate
        volume (int): Trading volume to evaluate
        
    Returns:
        bool: True if spike conditions are met, False otherwise
    """    
    return ((pct_change >= 5 and volume >= 20000) 
            or (pct_change >= 10 and volume >= 15000) 
            or (pct_change >= 15 and volume >= 10000)
            or (pct_change >= 20 and volume >= 5000)
            or (pct_change >= 30)
            or (volume >= 50000))

def should_send_alert(symbol, minute_ts, cooldown_minutes=5):
    """
    Check if we should send an alert for this symbol to prevent spam
    
    Args:
        symbol (str): Stock symbol
        minute_ts (datetime): Current minute timestamp
        cooldown_minutes (int): Minutes to wait before allowing another alert
        
    Returns:
        bool: True if alert should be sent, False if in cooldown period
    """
    global alerted_symbols
    
    if symbol not in alerted_symbols:
        return True
    
    last_alert_time = alerted_symbols[symbol]['last_alert_minute']
    time_diff = (minute_ts - last_alert_time).total_seconds() / 60
    
    return time_diff >= cooldown_minutes

def mark_symbol_alerted(symbol, minute_ts):
    """
    Mark a symbol as alerted to track cooldown period
    
    Args:
        symbol (str): Stock symbol
        minute_ts (datetime): Current minute timestamp
    """
    global alerted_symbols
    
    alerted_symbols[symbol] = {
        'last_alert_minute': minute_ts,
        'cooldown_minutes': 5
    }

def check_percentage_and_volume_spike(symbol, current_change_pct, current_volume, minute_ts):
    """Check if current percentage change vs previous minute meets spike conditions"""
    global previous_minute_data
    
    spike_detected = False
    telegram_message = ""
    
    # Check if we have previous data for this symbol
    if symbol in previous_minute_data:
        prev_data = previous_minute_data[symbol]
        prev_change_pct = prev_data['prev_change_pct']
        prev_volume = prev_data['prev_volume']
        prev_minute = prev_data['prev_minute']
        
        # Only check for spike if this is a NEW minute AND we haven't checked it yet
        if prev_minute != minute_ts:
            # This is a new minute, check for spike
            pct_change_diff = current_change_pct - prev_change_pct
            
            if evaluate_spike_conditions(pct_change_diff, current_volume):
                spike_detected = True
                telegram_message = (
                    f"🚨🚨 SPIKE ALERT for {symbol}! 🚨🚨\n"
                    f"📊 Previous minute: {prev_change_pct:+.2f}% (Vol: {prev_volume:,})\n"
                    f"📊 Current minute: {current_change_pct:+.2f}% (Vol: {current_volume:,})\n"
                    f"📈 Percentage difference: {pct_change_diff:+.2f}%"
                )
            
            # Update for the new minute
            previous_minute_data[symbol] = {
                'prev_change_pct': current_change_pct,
                'prev_volume': current_volume,
                'prev_minute': minute_ts,
                'spike_checked': True  # Mark that we've checked this minute
            }
        else:
            # Same minute - just update the data, don't check for spike again
            previous_minute_data[symbol]['prev_change_pct'] = current_change_pct
            previous_minute_data[symbol]['prev_volume'] = current_volume
            return  # Exit early, no need to check spike again
    else:
        # First time seeing this symbol
        if evaluate_spike_conditions(abs(current_change_pct), current_volume):
            spike_detected = True
            telegram_message = (
                f"🚨🚨 FIRST MINUTE SPIKE ALERT for {symbol}! 🚨🚨\n"
                f"📊 First minute data: {current_change_pct:+.2f}% (Vol: {current_volume:,})\n"
                f"📈 Significant activity detected on first observation!"
            )
        
        # Initialize tracking for this symbol
        previous_minute_data[symbol] = {
            'prev_change_pct': current_change_pct,
            'prev_volume': current_volume,
            'prev_minute': minute_ts,
            'spike_checked': True
        }
    
    # Send Telegram message if spike detected and not in cooldown
    if spike_detected:
        if should_send_alert(symbol, minute_ts):
            success = queue_telegram_message(telegram_message)
            if success:
                mark_symbol_alerted(symbol, minute_ts)
                print(f"🚨 SPIKE ALERT queued for {symbol}")
            else:
                print(f"❌ Failed to queue spike alert for {symbol}")
        else:
            print(f"⏳ Spike detected for {symbol} but in cooldown period")
    
def process_trade_message(msg):
    """Process trade message"""
    symbol = getattr(msg, 'symbol', 'Unknown')
    
    # Filter: Only process trades for tickers in our list
    if symbol not in target_tickers:
        return
        
    trade_price = getattr(msg, 'price', 0)
    trade_size = getattr(msg, 'size', 0)
    timestamp = getattr(msg, 'timestamp', None)
    exchange = getattr(msg, 'exchange', None)
    conditions = getattr(msg, 'conditions', [])
    tape = getattr(msg, 'tape', None)
    
    # Convert timestamp
    dt = convert_timestamp_to_datetime(timestamp)
    
    # Update aggregates
    minute_ts, agg = update_minute_aggregates(symbol, trade_price, trade_size, dt)
    
    # Update latest prices
    update_latest_prices(symbol, trade_price, trade_size, timestamp, dt, 
                        exchange=exchange, conditions=conditions, tape=tape)
    
    # Check for percentage and volume spike conditions
    check_percentage_and_volume_spike(
        symbol, 
        agg['open_close_change_pct'], 
        agg['total_volume'], 
        minute_ts
    )
        

def process_aggregate_message(msg):
    """Process aggregate message (fallback)"""
    symbol = getattr(msg, 'symbol', 'Unknown')
    
    # Filter: Only process aggregates for tickers in our list
    if symbol not in target_tickers:
        return
        
    close_price = getattr(msg, 'close', 0)
    volume = getattr(msg, 'volume', 0)
    timestamp = getattr(msg, 'timestamp', None)
    
    # Convert timestamp
    dt = convert_timestamp_to_datetime(timestamp)
    
    # Update latest prices
    update_latest_prices(symbol, close_price, volume, timestamp, dt)
    
    # Simple aggregate notification
    print(f"📊 {symbol}: ${close_price:.2f} (Vol: {volume:,})")

def process_message(msg):
    """Process individual WebSocket message for trade data"""
    global target_tickers
    
    try:
        if hasattr(msg, 'symbol') and hasattr(msg, 'price'):
            # Handle Trade object
            process_trade_message(msg)
        elif hasattr(msg, 'symbol') and hasattr(msg, 'close'):
            # Handle EquityAgg object (fallback)
            process_aggregate_message(msg)
        else:
            # Unknown message type - minimal logging
            print(f"🔍 Unknown message type: {type(msg)}")
                        
    except Exception as e:
        print(f"❌ Error processing message: {e}")
        # Reduced error logging
        if hasattr(msg, 'symbol'):
            print(f"   Symbol: {getattr(msg, 'symbol', 'Unknown')}")

def save_minute_data_to_json(filename=None):
    """Save minute aggregates data to JSON file"""
    global minute_aggregates
    
    if filename is None:
        # Create filename with current date
        current_time = get_et_time()
        filename = f"minute_data_{current_time.strftime('%Y%m%d')}.json"
    
    try:
        # Convert the nested defaultdict to regular dict for JSON serialization
        json_data = {}
        
        for minute_ts, symbols in minute_aggregates.items():
            # Convert datetime to string for JSON
            minute_str = minute_ts.strftime('%Y-%m-%d %H:%M:%S')
            json_data[minute_str] = {}
            
            for symbol, agg_data in symbols.items():
                json_data[minute_str][symbol] = dict(agg_data)  # Convert to regular dict
        
        # Save to JSON file
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Minute data saved to {filename} ({len(json_data)} minutes, {sum(len(symbols) for symbols in json_data.values())} symbol entries)")
        return True
        
    except Exception as e:
        print(f"❌ Error saving minute data to JSON: {e}")
        return False

def load_minute_data_from_json(filename=None):
    """Load minute aggregates data from JSON file"""
    global minute_aggregates
    
    if filename is None:
        # Use today's filename
        current_time = get_et_time()
        filename = f"minute_data_{current_time.strftime('%Y%m%d')}.json"
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        # Convert back to the nested defaultdict structure
        minute_aggregates.clear()
        
        for minute_str, symbols in json_data.items():
            # Convert string back to datetime
            minute_dt = datetime.strptime(minute_str, '%Y-%m-%d %H:%M:%S')
            
            for symbol, agg_data in symbols.items():
                minute_aggregates[minute_dt][symbol] = agg_data
        
        print(f"📂 Minute data loaded from {filename} ({len(json_data)} minutes)")
        return True
        
    except FileNotFoundError:
        print(f"📂 No existing data file found: {filename}")
        return False
    except Exception as e:
        print(f"❌ Error loading minute data from JSON: {e}")
        return False

def handle_error(error):
    """Handle WebSocket errors"""
    print(f"\n❌ WebSocket Error: {error}")

def run_websocket_session():
    """Run WebSocket client during pre-market session"""
    global target_tickers
    
    # Your API key
    API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"
    
    print(f"🎯 Monitoring {len(target_tickers)} tickers during pre-market session")
    
    # Load existing data for today if available
    load_minute_data_from_json()
    
    try:
        # Create WebSocket client
        client = WebSocketClient(
            api_key=API_KEY,
            feed=Feed.RealTime,
            market=Market.Stocks
        )
        
        client.subscribe('T.*')
                
        # Use threading to run WebSocket in background
        import threading
        websocket_running = True
        websocket_error = None
        
        def websocket_runner():
            nonlocal websocket_running, websocket_error
            try:
                while websocket_running:
                    client.run(handle_msg)
            except Exception as e:
                websocket_error = e
                websocket_running = False
        
        # Start WebSocket in background thread
        websocket_thread = threading.Thread(target=websocket_runner, daemon=True)
        websocket_thread.start()
        
        print("✅ WebSocket running in background, starting periodic tasks...")
        
        # Start Telegram worker thread
        start_telegram_worker()
        
        # Monitor session and handle periodic saves in main thread
        last_health_check = time_module.time()
        health_check_interval = 10  # Check every 10 seconds (more frequent)
        
        while is_premarket_session() and websocket_running:
            try:
                # Check for WebSocket errors
                if websocket_error:
                    print(f"\n⚠️  WebSocket error: {websocket_error}")
                    print("Restarting WebSocket in 5 seconds...")
                    time_module.sleep(5)
                    
                    # Restart WebSocket
                    websocket_error = None
                    websocket_running = True
                    websocket_thread = threading.Thread(target=websocket_runner, daemon=True)
                    websocket_thread.start()
                
                # Check Telegram worker health every 10 seconds
                current_time = time_module.time()
                if current_time - last_health_check >= health_check_interval:
                    is_healthy = check_telegram_worker_health()
                    if is_healthy:
                        queue_size = telegram_queue.qsize()
                        if queue_size > 0:
                            print(f"💚 Telegram worker healthy - Processing {queue_size} queued messages")
                    
                    last_health_check = current_time
                
                # Also do a quick health check if there are queued messages
                queue_size = telegram_queue.qsize()
                if queue_size > 0:
                    if not check_telegram_worker_health():
                        print(f"⚠️ Found {queue_size} queued messages but worker is dead!")
                
                # Sleep briefly before next check
                time_module.sleep(2)  # Check every 2 seconds (more frequent)
                
            except KeyboardInterrupt:
                print(f"\n🛑 Interrupted by user")
                websocket_running = False
                break
        
        # Stop WebSocket
        websocket_running = False
        
        # Stop Telegram worker
        stop_telegram_worker()
        
        # Final save when session ends
        print(f"\n⏰ Pre-market session ended at {get_et_time().strftime('%H:%M:%S ET')}")
        save_minute_data_to_json()
        
    except Exception as e:
        print(f"\n❌ Failed to start WebSocket client: {e}")
        # Save data even if there's an error
        save_minute_data_to_json()

def main():
    """Main function with simple pre-market scheduling"""
    global target_tickers
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Set global target tickers for filtering
    target_tickers = set(read_tickers_from_csv("tickers.csv"))
    
    print(f"\n🚀 Pre-Market Stock Monitoring System")
    print(f"📈 Tracking OHLC data and spike detection during pre-market hours")
    print(f"🎯 Monitoring {len(target_tickers)} tickers from tickers.csv")
    print(f"⏰ Active during: {PRE_MARKET_START} - {PRE_MARKET_END} ET")
    print(f"🔄 Running continuously - Press Ctrl+C to stop\n")
    
    try:
        while True:
            current_et_time = get_et_time()
            
            # Check if we're currently in pre-market session
            if is_premarket_session(current_et_time):
                print(f"✅ PRE-MARKET SESSION ACTIVE - {current_et_time.strftime('%Y-%m-%d %H:%M:%S ET')}")
                
                # Clear previous session data
                global previous_minute_data, alerted_symbols
                previous_minute_data.clear()
                alerted_symbols.clear()
                
                # Run the WebSocket session
                run_websocket_session()
                
                print(f"💤 Pre-market session ended. Waiting for next session...")
            else:
                # Not in pre-market - sleep until next session
                next_session_time = get_next_premarket_time(current_et_time)
                time_until_session = (next_session_time - current_et_time).total_seconds()
                
                # Convert to hours:minutes:seconds for display
                hours = int(time_until_session // 3600)
                minutes = int((time_until_session % 3600) // 60)
                seconds = int(time_until_session % 60)
                
                print(f"💤 Waiting for pre-market | Next session: {next_session_time.strftime('%Y-%m-%d %H:%M ET')} | Time remaining: {hours:02d}:{minutes:02d}:{seconds:02d}")
                
                # Sleep until next session (minus 5 seconds to be ready)
                sleep_time = max(1, time_until_session - 5)
                time_module.sleep(sleep_time)
                
    except KeyboardInterrupt:
        print(f"\n🛑 Shutting down monitoring system...")
        # Final save before exit
        print("💾 Saving final data...")
        save_minute_data_to_json()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ System error: {e}")
        # Save data before restart
        save_minute_data_to_json()
        print("Restarting in 10 seconds...")
        time_module.sleep(10)

if __name__ == "__main__":
    main()