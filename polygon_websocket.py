"""
Polygon.io WebSocket Client for Real-Time Pre-Market Data

Simple WebSocket client to receive real-time stock data for pre-market analysis.
Subscribes to minute aggregates for specified tickers and displays live price updates.
"""

from polygon import WebSocketClient
from polygon.websocket.models import Feed, Market
from datetime import datetime
import sys
import logging
import csv
from typing import List

# Global dictionary to store latest prices
ticker_prices = {}

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

def process_message(msg):
    """Process individual WebSocket message for trade data"""
    global tickers
    
    try:
        # Check if it's a Trade object (polygon library object)
        if hasattr(msg, 'symbol') and hasattr(msg, 'price'):
            # Handle Trade object
            symbol = getattr(msg, 'symbol', 'Unknown')
            
            # Filter: Only process trades for tickers in our list
            if symbol not in tickers:
                return  # Skip this trade if it's not in our ticker list
                
            trade_price = getattr(msg, 'price', 0)
            trade_size = getattr(msg, 'size', 0)
            timestamp = getattr(msg, 'timestamp', None)
            
            # Additional trade attributes
            exchange = getattr(msg, 'exchange', None)
            conditions = getattr(msg, 'conditions', [])
            tape = getattr(msg, 'tape', None)
            
            print(f"\n📊 Raw trade object: {msg}")
            print(f"   Type: {type(msg)}")
            print(f"   Symbol: {symbol}")
            print(f"   Price: ${trade_price}")
            print(f"   Size: {trade_size}")
            print(f"   Exchange: {exchange}")
            print(f"   Conditions: {conditions}")
            print(f"   Tape: {tape}")
            
            # Convert timestamp to readable format
            if timestamp:
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
                time_str = dt.strftime('%H:%M:%S.%f')[:-3]  # Include milliseconds
            else:
                time_str = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            
            # Update our price dictionary
            ticker_prices[symbol] = {
                'price': trade_price,
                'size': trade_size,
                'time': time_str,
                'timestamp': timestamp,
                'exchange': exchange,
                'conditions': conditions
            }
            
            # Print the trade update
            print(f"\n💰 LIVE TRADE [{time_str}]")
            print(f"   {symbol}: ${trade_price:.2f} x {trade_size:,} shares")
            if exchange:
                print(f"   Exchange: {exchange}")
            if conditions:
                print(f"   Conditions: {conditions}")
        
        elif hasattr(msg, 'symbol') and hasattr(msg, 'close'):
            # Fallback: Handle EquityAgg object (in case mixed data comes through)
            symbol = getattr(msg, 'symbol', 'Unknown')
            
            # Filter: Only process aggregates for tickers in our list
            if symbol not in tickers:
                return  # Skip this aggregate if it's not in our ticker list
                
            close_price = getattr(msg, 'close', 0)
            volume = getattr(msg, 'volume', 0)
            timestamp = getattr(msg, 'timestamp', None)
            
            print(f"\n📊 Raw aggregate object: {msg}")
            print(f"   Type: {type(msg)}")
            print(f"   Symbol: {symbol}")
            print(f"   Close: {close_price}")
            print(f"   Volume: {volume}")
            
            # Convert timestamp to readable format
            if timestamp:
                if isinstance(timestamp, int):
                    dt = datetime.fromtimestamp(timestamp / 1000 if timestamp > 1000000000000 else timestamp)
                else:
                    dt = timestamp
                time_str = dt.strftime('%H:%M:%S')
            else:
                time_str = datetime.now().strftime('%H:%M:%S')
            
            # Update our price dictionary
            ticker_prices[symbol] = {
                'price': close_price,
                'volume': volume,
                'time': time_str,
                'timestamp': timestamp
            }
            
            # Print the update
            print(f"\n🔴 AGGREGATE UPDATE [{time_str}]")
            print(f"   {symbol}: ${close_price:.2f} (Vol: {volume:,})")
        
        else:
            # Debug unknown message types
            print(f"\n🔍 Unknown message type: {type(msg)}")
            print(f"   Content: {msg}")
            print(f"   Available attributes: {dir(msg) if hasattr(msg, '__dict__') else 'No attributes'}")
                        
    except Exception as e:
        print(f"Error processing message: {e}")
        print(f"Message: {msg}")
        print(f"Message type: {type(msg)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")

def handle_error(error):
    """Handle WebSocket errors"""
    print(f"\n❌ WebSocket Error: {error}")

def main():
    """Main function to start WebSocket connection"""
    global tickers
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Your API key
    API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"
    
    # Load tickers from CSV
    tickers = read_tickers_from_csv("tickers.csv")
    
    print(f"\n🚀 Starting WebSocket for Real-Time Trade Data")
    
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
        print(f"Final prices at {datetime.now().strftime('%H:%M:%S')}:")
        for ticker, data in ticker_prices.items():
            print(f"   {ticker}: ${data['price']:.2f}")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Connection error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()