#!/usr/bin/env python3
"""
Simple WebSocket connection diagnostic
"""
import time
from polygon import WebSocketClient
from polygon.websocket.models import Feed, Market

API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"

message_count = 0
last_message_time = time.time()

def handle_msg(msgs):
    global message_count, last_message_time
    if not isinstance(msgs, list):
        msgs = [msgs]
    
    for msg in msgs:
        message_count += 1
        last_message_time = time.time()
        
        event_type = getattr(msg, 'ev', None) or getattr(msg, 'event_type', None)
        symbol = getattr(msg, 'sym', None) or getattr(msg, 'symbol', None)
        
        if message_count <= 10:  # Print first 10 messages
            print(f"Message #{message_count}: Type={event_type}, Symbol={symbol}")

print("🧪 Simple WebSocket Test")
print("Connecting...")

client = WebSocketClient(api_key=API_KEY, feed=Feed.RealTime, market=Market.Stocks)
client.subscribe('T.AAPL', 'T.MSFT', 'Q.AAPL', 'Q.MSFT')

print("✅ Subscribed to AAPL and MSFT trades + quotes")
print("Listening for 60 seconds...\n")

start = time.time()

try:
    import threading
    
    def run():
        try:
            client.run(handle_msg)
        except Exception as e:
            print(f"❌ Error: {e}")
    
    t = threading.Thread(target=run, daemon=True)
    t.start()
    
    while time.time() - start < 60:
        time.sleep(5)
        elapsed = time.time() - start
        since_last = time.time() - last_message_time
        print(f"⏱️  {elapsed:.0f}s | Messages: {message_count} | Last message: {since_last:.1f}s ago")
    
    print(f"\n✅ Test complete! Received {message_count} messages in 60 seconds")
    
except KeyboardInterrupt:
    print(f"\n⚠️ Interrupted. Received {message_count} messages")
