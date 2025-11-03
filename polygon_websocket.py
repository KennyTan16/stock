"""
Polygon.io WebSocket Client for Real-Time Pre-Market Data

Simple WebSocket client to receive real-time stock data for pre-market analysis.
Subscribes to minute aggregates for specified tickers and displays live price updates.
"""

from polygon import WebSocketClient
from polygon.websocket.models import Feed, Market
from datetime import datetime, timedelta
import sys
import logging
import csv
from collections import defaultdict
from typing import List
import requests
import urllib.parse

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
# Structure: {symbol: {'prev_change_pct': float, 'prev_volume': int, 'prev_minute': datetime}}
previous_minute_data = {}

# Global variable to store target tickers for filtering
target_tickers = set()

# Telegram configuration
TELEGRAM_BOT_TOKEN = "8230689629:AAHtpdsVb8znDZ_DyKMzcOgee-aczA9acOE"
TELEGRAM_CHAT_ID = "8258742558"

def send_telegram_message(message):
    """Send message to Telegram chat"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        }
        
        response = requests.post(url, data=payload, timeout=10)
        
        if response.status_code == 200:
            print("✅ Telegram message sent successfully")
            return True
        else:
            print(f"❌ Failed to send Telegram message: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error sending Telegram message: {e}")
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

def check_percentage_and_volume_spike(symbol, current_change_pct, current_volume, minute_ts):
    """Check if current percentage change vs previous minute meets spike conditions"""
    global previous_minute_data
    
    # Check if we have previous minute data for this symbol
    if symbol in previous_minute_data:
        prev_data = previous_minute_data[symbol]
        prev_change_pct = prev_data['prev_change_pct']
        prev_volume = prev_data['prev_volume']
        prev_minute = prev_data['prev_minute']
        
        # Only check if we have data from a different minute
        if prev_minute != minute_ts:
            # Calculate the difference in percentage change
            pct_change_diff = current_change_pct - prev_change_pct
            # Check conditions: percentage difference > 0.1% AND current volume > 10 (adjusted for testing)
            if ((pct_change_diff >= 5 and current_volume >= 20000) 
            or (pct_change_diff >= 10 and current_volume >= 15000) 
            or (pct_change_diff >= 15 and current_volume >= 10000)
            or (pct_change_diff >= 20 and current_volume >= 5000)
            or (pct_change_diff >= 30 and current_volume >= 2000)
            or (pct_change_diff >= 35) or (current_volume >= 100000)):
                # Format the Telegram message
                telegram_message = (
                    f"🚨🚨 SPIKE ALERT for {symbol}! 🚨🚨\n"
                    f"📊 Previous minute: {prev_change_pct:+.2f}% (Vol: {prev_volume:,})\n"
                    f"📊 Current minute: {current_change_pct:+.2f}% (Vol: {current_volume:,})\n"
                    f"📈 Percentage difference: {pct_change_diff:+.2f}%"
                )
                
                # Send to Telegram
                send_telegram_message(telegram_message)
    
    # Update previous minute data for next comparison
    previous_minute_data[symbol] = {
        'prev_change_pct': current_change_pct,
        'prev_volume': current_volume,
        'prev_minute': minute_ts
    }
    
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

def handle_error(error):
    """Handle WebSocket errors"""
    print(f"\n❌ WebSocket Error: {error}")

def main():
    """Main function to start WebSocket connection"""
    global target_tickers
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Your API key
    API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"
    
    # Set global target tickers for filtering
    target_tickers = set(read_tickers_from_csv("tickers.csv"))
    
    print(f"\n🚀 Starting WebSocket for Real-Time Trade Data")
    print(f"📈 Tracking OHLC data and open-to-close percentage changes per minute")
    print(f"🎯 Monitoring {len(target_tickers)} tickers from tickers.csv")
    print("\nPress Ctrl+C to stop\n")
    
    # Create WebSocket client
    try:
        client = WebSocketClient(
            api_key=API_KEY,
            feed=Feed.RealTime,
            market=Market.Stocks
        )
        
        client.subscribe('T.*')
        
        # Start the connection
        client.run(handle_msg)
        
    except KeyboardInterrupt:
        print(f"\n🛑 Shutting down WebSocket connection...")
        sys.exit(0)

    except Exception as e:
        print(f"\n❌ Connection error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()