import requests
from datetime import datetime, timedelta

API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"
symbol = "AAPL"

end = datetime.now()
start = end - timedelta(days=30)

url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
params = {
    'adjusted': 'true',
    'sort': 'desc',
    'limit': 20,
    'apiKey': API_KEY
}

print(f"Testing Polygon API with {symbol}...")
r = requests.get(url, params=params, timeout=10)
print(f"Status: {r.status_code}")

data = r.json()
results = data.get('results', [])
print(f"Results: {len(results)} bars")

if results:
    volumes = [b['v'] for b in results]
    ranges = [b['h'] - b['l'] for b in results]
    
    avg_vol = sum(volumes) / len(volumes)
    avg_range = sum(ranges) / len(ranges)
    
    print(f"\n20-Day Statistics:")
    print(f"  Avg Volume: {avg_vol:,.0f}")
    print(f"  Avg Range: ${avg_range:.2f}")
    print(f"\nSample bars:")
    for b in results[:3]:
        print(f"  Vol: {b['v']:,}, Range: ${b['h']-b['l']:.2f}")
