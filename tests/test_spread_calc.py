"""
Test if spread calculation is working with real quote data
"""
import sys
import time
import threading
from polygon_websocket import (
    WebSocketClient, Feed, Market, API_KEY, 
    latest_quotes, quote_lock, get_spread_ratio, target_tickers, read_tickers, TICKER_FILE
)

print("=== Testing Spread Calculation ===\n")

# Load tickers
target_tickers.update(read_tickers(TICKER_FILE))
print(f"Monitoring {len(target_tickers)} tickers\n")

quote_count = [0]
processed = set()

def handle_msg(msgs):
    if not isinstance(msgs, list):
        msgs = [msgs]
    
    for msg in msgs:
        # Get event type
        event_type = getattr(msg, 'ev', None) or getattr(msg, 'event_type', None)
        
        if event_type == 'Q':
            symbol = getattr(msg, 'sym', None) or getattr(msg, 'symbol', None)
            bid = getattr(msg, 'bp', None) or getattr(msg, 'bid_price', None)
            ask = getattr(msg, 'ap', None) or getattr(msg, 'ask_price', None)
            
            if symbol and bid and ask and symbol in target_tickers:
                with quote_lock:
                    from datetime import datetime
                    try:
                        from zoneinfo import ZoneInfo
                        ET_TIMEZONE = ZoneInfo('America/New_York')
                    except:
                        import pytz
                        ET_TIMEZONE = pytz.timezone('US/Eastern')
                    
                    latest_quotes[symbol] = {
                        'bid': bid,
                        'ask': ask,
                        'timestamp': datetime.now(ET_TIMEZONE)
                    }
                    quote_count[0] += 1
                    
                    # Test spread calculation for first 10 symbols
                    if symbol not in processed and len(processed) < 10:
                        processed.add(symbol)
                        spread = get_spread_ratio(symbol)
                        if spread is not None:
                            spread_pct = spread * 100
                            print(f"✓ {symbol}: bid=${bid:.2f} ask=${ask:.2f} spread={spread:.4f} ({spread_pct:.2f}%)")
                        else:
                            print(f"✗ {symbol}: bid=${bid:.2f} ask=${ask:.2f} spread=None (calc failed)")

try:
    client = WebSocketClient(api_key=API_KEY, feed=Feed.RealTime, market=Market.Stocks)
    client.subscribe('Q.*')
    
    running = [True]
    def runner():
        try:
            client.run(handle_msg)
        except Exception as e:
            print(f"Error: {e}")
            running[0] = False
    
    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    
    print("Collecting quotes for 10 seconds...\n")
    time.sleep(10)
    
    print(f"\n=== Results ===")
    print(f"Total quotes received: {quote_count[0]}")
    
    with quote_lock:
        print(f"Symbols with quotes stored: {len(latest_quotes)}")
        
        # Test spread calculation on 5 random symbols
        print("\nTesting spread calculation on stored quotes:")
        test_symbols = list(latest_quotes.keys())[:5]
        for sym in test_symbols:
            spread = get_spread_ratio(sym)
            quote = latest_quotes[sym]
            if spread is not None:
                print(f"  ✓ {sym}: spread={spread:.4f} ({spread*100:.2f}%)")
            else:
                print(f"  ✗ {sym}: spread=None (bid={quote['bid']}, ask={quote['ask']})")
    
    running[0] = False
    
except Exception as e:
    print(f"Failed: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Test Complete ===")
