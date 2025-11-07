"""
Quick test script to verify Polygon.io quote entitlement
Tests if quotes can be received independently
"""
from polygon import WebSocketClient
from polygon.websocket.models import Feed, Market
import time

API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"

quote_count = 0
trade_count = 0

def handle_msg(msgs):
    global quote_count, trade_count
    if not isinstance(msgs, list):
        msgs = [msgs]
    
    for msg in msgs:
        if hasattr(msg, 'ev'):
            if msg.ev == 'Q':
                quote_count += 1
                if quote_count <= 5:
                    print(f"[QUOTE] {msg.sym}: bid={msg.bp} ask={msg.ap}")
            elif msg.ev == 'T':
                trade_count += 1
                if trade_count <= 5:
                    print(f"[TRADE] {msg.symbol}: price={msg.price}")

print("=== Testing Polygon.io Quote Subscription ===\n")

# Test 1: Quotes only
print("Test 1: Subscribing to QUOTES ONLY (Q.AAPL)")
client = WebSocketClient(api_key=API_KEY, feed=Feed.RealTime, market=Market.Stocks)
client.subscribe('Q.AAPL')  # Just Apple quotes

import threading
running = [True]

def runner():
    try:
        client.run(handle_msg)
    except Exception as e:
        print(f"Error: {e}")
        running[0] = False

thread = threading.Thread(target=runner, daemon=True)
thread.start()

print("Waiting 10 seconds for quotes...")
time.sleep(10)

print(f"\nResult: Received {quote_count} quotes, {trade_count} trades")

if quote_count > 0:
    print("✓ SUCCESS: Quote data is working!")
else:
    print("✗ FAILED: No quotes received")
    print("\nPossible reasons:")
    print("1. Your Polygon.io plan doesn't include real-time quotes")
    print("2. Quote entitlement not enabled in dashboard")
    print("3. Need to use different feed (e.g., Feed.Delayed instead of Feed.RealTime)")

running[0] = False
print("\n=== Test Complete ===")
