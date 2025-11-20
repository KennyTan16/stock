#!/usr/bin/env python3
"""
Test WebSocket Data Reception
Verifies that we're receiving both trade and quote data from Polygon WebSocket
"""

import sys
import os
import time
from datetime import datetime
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from polygon import WebSocketClient
    from polygon.websocket.models import Feed, Market
except ImportError:
    print("❌ Error: polygon package not installed")
    print("   Install with: pip install polygon-api-client")
    sys.exit(1)

# Configuration
API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"
TEST_SYMBOLS = ['AAPL', 'MSFT', 'TSLA', 'NVDA', 'AMD']  # Popular symbols for testing
TEST_DURATION = 30  # seconds

# Tracking
trade_counts = defaultdict(int)
quote_counts = defaultdict(int)
last_trade = {}
last_quote = {}
total_trades = 0
total_quotes = 0
start_time = None

def handle_msg(msgs):
    """Handle incoming WebSocket messages"""
    global total_trades, total_quotes
    
    if not isinstance(msgs, list):
        msgs = [msgs]
    
    for msg in msgs:
        try:
            # Get event type
            event_type = None
            if hasattr(msg, 'ev'):
                event_type = msg.ev
            elif hasattr(msg, 'event_type'):
                event_type = msg.event_type
            
            # Handle quotes
            if event_type == 'Q':
                symbol = getattr(msg, 'sym', None) or getattr(msg, 'symbol', None)
                bid = getattr(msg, 'bp', None) or getattr(msg, 'bid_price', None)
                ask = getattr(msg, 'ap', None) or getattr(msg, 'ask_price', None)
                bid_size = getattr(msg, 'bs', None) or getattr(msg, 'bid_size', 0)
                ask_size = getattr(msg, 'as', None) or getattr(msg, 'ask_size', 0)
                
                if symbol and bid and ask:
                    quote_counts[symbol] += 1
                    total_quotes += 1
                    last_quote[symbol] = {
                        'bid': bid,
                        'ask': ask,
                        'bid_size': bid_size,
                        'ask_size': ask_size,
                        'time': datetime.now()
                    }
                    
                    # Print first quote for each symbol
                    if quote_counts[symbol] == 1:
                        print(f"📊 First QUOTE: {symbol} - Bid: ${bid:.2f} ({bid_size}) / Ask: ${ask:.2f} ({ask_size})")
            
            # Handle trades
            elif event_type == 'T':
                symbol = getattr(msg, 'sym', None) or getattr(msg, 'symbol', None)
                price = getattr(msg, 'p', None) or getattr(msg, 'price', None)
                size = getattr(msg, 's', None) or getattr(msg, 'size', None)
                
                if symbol and price and size:
                    trade_counts[symbol] += 1
                    total_trades += 1
                    last_trade[symbol] = {
                        'price': price,
                        'size': size,
                        'time': datetime.now()
                    }
                    
                    # Print first trade for each symbol
                    if trade_counts[symbol] == 1:
                        print(f"💹 First TRADE: {symbol} - Price: ${price:.2f}, Size: {size:,}")
        
        except Exception as e:
            print(f"⚠️ Error processing message: {e}")

def print_status():
    """Print current status"""
    elapsed = time.time() - start_time
    print(f"\n{'='*70}")
    print(f"⏱️  Elapsed Time: {elapsed:.1f}s / {TEST_DURATION}s")
    print(f"{'='*70}")
    
    print(f"\n📈 TRADES RECEIVED: {total_trades:,}")
    if trade_counts:
        print("   Symbol breakdown:")
        for symbol in sorted(trade_counts.keys(), key=lambda x: trade_counts[x], reverse=True)[:10]:
            last = last_trade.get(symbol, {})
            price = last.get('price', 0)
            size = last.get('size', 0)
            print(f"   {symbol:6} - {trade_counts[symbol]:4} trades | Last: ${price:8.2f} x {size:,}")
    else:
        print("   ⚠️ No trades received yet")
    
    print(f"\n📊 QUOTES RECEIVED: {total_quotes:,}")
    if quote_counts:
        print("   Symbol breakdown:")
        for symbol in sorted(quote_counts.keys(), key=lambda x: quote_counts[x], reverse=True)[:10]:
            last = last_quote.get(symbol, {})
            bid = last.get('bid', 0)
            ask = last.get('ask', 0)
            print(f"   {symbol:6} - {quote_counts[symbol]:4} quotes | Last: ${bid:.2f} / ${ask:.2f}")
    else:
        print("   ⚠️ No quotes received yet")
    
    print(f"\n{'='*70}")

def main():
    """Main test function"""
    global start_time
    
    print("🧪 WEBSOCKET DATA RECEPTION TEST")
    print("=" * 70)
    print(f"Testing with symbols: {', '.join(TEST_SYMBOLS)}")
    print(f"Duration: {TEST_DURATION} seconds")
    print(f"Feed: RealTime")
    print("=" * 70)
    print("\n🔌 Connecting to Polygon WebSocket...")
    
    try:
        client = WebSocketClient(
            api_key=API_KEY,
            feed=Feed.RealTime,
            market=Market.Stocks
        )
        
        # Subscribe to trades and quotes for test symbols
        for symbol in TEST_SYMBOLS:
            client.subscribe(f'T.{symbol}')  # Trades
            client.subscribe(f'Q.{symbol}')  # Quotes
        
        print("✅ Connected and subscribed")
        print(f"   Subscribed to trades: {', '.join(TEST_SYMBOLS)}")
        print(f"   Subscribed to quotes: {', '.join(TEST_SYMBOLS)}")
        print("\n⏳ Listening for data...\n")
        
        start_time = time.time()
        
        # Run client in background
        import threading
        
        def run_client():
            try:
                client.run(handle_msg)
            except Exception as e:
                print(f"❌ WebSocket error: {e}")
        
        ws_thread = threading.Thread(target=run_client, daemon=True)
        ws_thread.start()
        
        # Monitor for TEST_DURATION seconds with status updates every 5 seconds
        last_print = 0
        while time.time() - start_time < TEST_DURATION:
            time.sleep(1)
            elapsed = time.time() - start_time
            
            # Print status every 5 seconds
            if int(elapsed) % 5 == 0 and int(elapsed) != last_print:
                print_status()
                last_print = int(elapsed)
        
        # Final status
        print("\n✅ Test completed!")
        print_status()
        
        # Summary
        print("\n📋 SUMMARY:")
        if total_trades > 0 and total_quotes > 0:
            print("   ✅ Receiving BOTH trades and quotes")
            print(f"   ✅ Trade reception rate: {total_trades/TEST_DURATION:.1f} trades/sec")
            print(f"   ✅ Quote reception rate: {total_quotes/TEST_DURATION:.1f} quotes/sec")
            print(f"   ✅ Symbols with trades: {len(trade_counts)}")
            print(f"   ✅ Symbols with quotes: {len(quote_counts)}")
        elif total_trades > 0:
            print("   ⚠️ Receiving trades but NO quotes")
            print("   Check quote subscription pattern")
        elif total_quotes > 0:
            print("   ⚠️ Receiving quotes but NO trades")
            print("   Check trade subscription pattern")
        else:
            print("   ❌ NOT receiving any data!")
            print("   Possible issues:")
            print("      - API key invalid or rate limited")
            print("      - Market is closed")
            print("      - Network connectivity issues")
            print("      - Subscription patterns incorrect")
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Test interrupted by user")
        print_status()
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
