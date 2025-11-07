"""
Test different WebSocket feeds to find which one supports quotes
"""
from polygon import WebSocketClient
from polygon.websocket.models import Feed, Market
import time
import threading

API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"

def test_feed(feed_name, feed_type):
    print(f"\n{'='*60}")
    print(f"Testing Feed: {feed_name}")
    print('='*60)
    
    quote_count = [0]
    trade_count = [0]
    
    def handle_msg(msgs):
        if not isinstance(msgs, list):
            msgs = [msgs]
        
        for msg in msgs:
            if hasattr(msg, 'ev'):
                if msg.ev == 'Q':
                    quote_count[0] += 1
                    if quote_count[0] <= 3:
                        print(f"[QUOTE {quote_count[0]}] {msg.sym}: bid=${msg.bp:.2f} ask=${msg.ap:.2f}")
                elif msg.ev == 'T':
                    trade_count[0] += 1
                    if trade_count[0] <= 3:
                        print(f"[TRADE {trade_count[0]}] {msg.symbol}: ${msg.price:.2f}")
    
    try:
        client = WebSocketClient(
            api_key=API_KEY,
            feed=feed_type,
            market=Market.Stocks
        )
        
        # Subscribe to both
        client.subscribe('T.AAPL')
        client.subscribe('Q.AAPL')
        
        running = [True]
        def runner():
            try:
                client.run(handle_msg)
            except Exception as e:
                print(f"Error: {e}")
                running[0] = False
        
        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        
        print("Waiting 8 seconds...")
        time.sleep(8)
        
        print(f"\nResults: {quote_count[0]} quotes, {trade_count[0]} trades")
        running[0] = False
        
        return quote_count[0] > 0
        
    except Exception as e:
        print(f"Failed to connect: {e}")
        return False

print("=== Testing All Available Polygon.io WebSocket Feeds ===\n")
print("Testing different feed types to find quote support...\n")

# Test different feeds
feeds_to_test = [
    ("RealTime", Feed.RealTime),
    ("Delayed", Feed.Delayed),
]

results = {}
for name, feed in feeds_to_test:
    try:
        results[name] = test_feed(name, feed)
        time.sleep(2)  # Cool down between tests
    except Exception as e:
        print(f"Could not test {name}: {e}")
        results[name] = False

print("\n" + "="*60)
print("SUMMARY")
print("="*60)
for feed_name, has_quotes in results.items():
    status = "✓ HAS QUOTES" if has_quotes else "✗ NO QUOTES"
    print(f"{feed_name:15} : {status}")

print("\n" + "="*60)
print("CONCLUSION")
print("="*60)
if any(results.values()):
    working_feeds = [k for k, v in results.items() if v]
    print(f"✓ Quote streaming works with: {', '.join(working_feeds)}")
else:
    print("✗ No WebSocket feed provided quote data")
    print("\nLikely reasons:")
    print("1. WebSocket quote streaming not included in your plan")
    print("2. Requires 'Starter' tier or above ($99+/month)")
    print("3. REST API quotes work, but real-time streaming is separate")
    print("\nYour fallback spread estimator will be used instead.")
