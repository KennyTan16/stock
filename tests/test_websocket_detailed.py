"""
Enhanced test with better logging to diagnose why no trades
"""
from polygon import WebSocketClient
from polygon.websocket.models import Feed, Market
import time
import threading

API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"

print("=== Detailed WebSocket Diagnostic ===\n")

message_count = [0]
quote_count = [0]
trade_count = [0]
other_count = [0]

def handle_msg(msgs):
    global message_count, quote_count, trade_count, other_count
    
    if not isinstance(msgs, list):
        msgs = [msgs]
    
    for msg in msgs:
        message_count[0] += 1
        
        # Log first 10 messages completely
        if message_count[0] <= 10:
            print(f"\n[MSG {message_count[0]}] Raw message:")
            print(f"  Type: {type(msg)}")
            print(f"  Dir: {[attr for attr in dir(msg) if not attr.startswith('_')]}")
            if hasattr(msg, '__dict__'):
                print(f"  Dict: {msg.__dict__}")
        
        # Check message type
        if hasattr(msg, 'ev'):
            if msg.ev == 'Q':
                quote_count[0] += 1
                if quote_count[0] <= 3:
                    print(f"\n✓ [QUOTE] {msg.sym}: bid=${msg.bp} ask=${msg.ap}")
            elif msg.ev == 'T':
                trade_count[0] += 1
                if trade_count[0] <= 3:
                    print(f"\n✓ [TRADE] {msg.symbol}: ${msg.price} size={msg.size}")
            else:
                other_count[0] += 1
                if other_count[0] <= 3:
                    print(f"\n[OTHER] Event type: {msg.ev}")
        else:
            print(f"\n[UNKNOWN] No 'ev' attribute: {msg}")

try:
    client = WebSocketClient(
        api_key=API_KEY,
        feed=Feed.RealTime,
        market=Market.Stocks
    )
    
    print("Subscribing to T.* (all trades)...")
    client.subscribe('T.*')
    
    print("Subscribing to Q.* (all quotes)...")
    client.subscribe('Q.*')
    
    print("\nStarting WebSocket connection...")
    
    running = [True]
    error_msg = [None]
    
    def runner():
        try:
            print("[Thread] Calling client.run()...")
            client.run(handle_msg)
            print("[Thread] client.run() returned normally")
        except Exception as e:
            print(f"[Thread] Exception: {e}")
            import traceback
            traceback.print_exc()
            error_msg[0] = str(e)
            running[0] = False
    
    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    
    print("\nWaiting 15 seconds for data...")
    for i in range(15):
        time.sleep(1)
        if i % 5 == 4:
            print(f"  {i+1}s - Messages: {message_count[0]}, Trades: {trade_count[0]}, Quotes: {quote_count[0]}, Other: {other_count[0]}")
    
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    print(f"Total messages:  {message_count[0]}")
    print(f"Trade messages:  {trade_count[0]}")
    print(f"Quote messages:  {quote_count[0]}")
    print(f"Other messages:  {other_count[0]}")
    
    if error_msg[0]:
        print(f"\nError occurred: {error_msg[0]}")
    
    if message_count[0] == 0:
        print("\n⚠️ NO MESSAGES RECEIVED AT ALL!")
        print("\nPossible causes:")
        print("1. WebSocket connection failed silently")
        print("2. Subscription format incorrect")
        print("3. Market is closed (after hours)")
        print("4. API key lacks WebSocket permissions")
        print("\nChecking market status...")
        
        import requests
        try:
            resp = requests.get(f"https://api.polygon.io/v1/marketstatus/now?apiKey={API_KEY}", timeout=5)
            if resp.status_code == 200:
                status = resp.json()
                print(f"Market status: {status.get('market', 'unknown')}")
                print(f"Server time: {status.get('serverTime', 'unknown')}")
        except:
            pass
    
    running[0] = False
    
except Exception as e:
    print(f"\n✗ Failed to create client: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Test Complete ===")
