"""
Check Polygon.io account details and entitlements
"""
import requests

API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"

print("=== Checking Polygon.io Account ===\n")

# Check account status
try:
    response = requests.get(
        f"https://api.polygon.io/v1/marketstatus/now?apiKey={API_KEY}",
        timeout=10
    )
    if response.status_code == 200:
        print("✓ API Key is valid and working")
    else:
        print(f"✗ API returned status: {response.status_code}")
except Exception as e:
    print(f"✗ Error checking API: {e}")

# Try to get a quote via REST API (different from WebSocket)
print("\nTesting REST API quote endpoint...")
try:
    # Try last quote for AAPL
    response = requests.get(
        f"https://api.polygon.io/v2/last/nbbo/AAPL?apiKey={API_KEY}",
        timeout=10
    )
    print(f"Quote endpoint status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Response: {data}")
        if 'status' in data and data['status'] == 'OK':
            print("✓ REST API quotes working!")
        elif 'status' in data and data['status'] == 'ERROR':
            print(f"✗ Error: {data.get('error', 'Unknown')}")
    elif response.status_code == 403:
        print("✗ 403 Forbidden: Quote data not included in your plan")
    else:
        print(f"Response: {response.text}")
except Exception as e:
    print(f"✗ Error: {e}")

# Check if trades work via REST
print("\nTesting REST API trades endpoint...")
try:
    response = requests.get(
        f"https://api.polygon.io/v2/last/trade/AAPL?apiKey={API_KEY}",
        timeout=10
    )
    print(f"Trade endpoint status: {response.status_code}")
    if response.status_code == 200:
        print("✓ REST API trades working!")
except Exception as e:
    print(f"✗ Error: {e}")

print("\n=== Check Complete ===")
print("\nRecommendation:")
print("1. Log into https://polygon.io/dashboard")
print("2. Check your subscription tier")
print("3. Look for 'Quotes' or 'Level 1 Data' in your entitlements")
print("4. If not included, quotes must be enabled or plan upgraded")
