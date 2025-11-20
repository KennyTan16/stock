"""
Download and cache minute-level bars from Polygon.io for grid search backtesting.
Fetches aggregated minute bars for a date range and symbol list, saves as gzipped JSON.

Usage:
  python download_minute_data.py --days 9

Output:
  data/minute_bars/minute_bars_YYYYMMDD.json.gz per day
"""

import os
import sys
import gzip
import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from polygon import RESTClient
from polygon_websocket import read_tickers, TICKER_FILE, ET_TIMEZONE

API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"
OUTPUT_DIR = Path("data/minute_bars")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def download_minute_bars(client, symbol, date_str):
    """Download minute bars for symbol on given date (YYYYMMDD format).
    Returns: list of {timestamp, open, close, high, low, volume, trades, vwap}
    """
    try:
        aggs = client.get_aggs(
            ticker=symbol,
            multiplier=1,
            timespan='minute',
            from_=date_str,
            to=date_str,
            limit=50000
        )
        bars = []
        for agg in aggs:
            ts = datetime.fromtimestamp(agg.timestamp / 1000, tz=ET_TIMEZONE)
            bars.append({
                'timestamp': ts.isoformat(),
                'open': agg.open,
                'close': agg.close,
                'high': agg.high,
                'low': agg.low,
                'volume': agg.volume,
                'trades': agg.transactions if hasattr(agg, 'transactions') else 0,
                'vwap': agg.vwap if hasattr(agg, 'vwap') else agg.close
            })
        return bars
    except Exception as e:
        print(f"  ⚠️ {symbol}: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(description="Download minute bars from Polygon.io")
    parser.add_argument('--days', type=int, default=9, help="Number of days to download (default: 9)")
    args = parser.parse_args()

    print("=== Polygon Minute Data Download ===")
    
    # Load tickers
    symbols = read_tickers(TICKER_FILE)
    if not symbols:
        print("⚠️ No tickers loaded. Ensure data/tickers.csv exists.")
        sys.exit(1)
    print(f"✓ Loaded {len(symbols)} symbols")

    # Initialize Polygon client
    client = RESTClient(API_KEY)
    
    # Date range
    end_date = datetime.now()
    dates = [(end_date - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(args.days)]
    print(f"✓ Downloading {len(dates)} days: {dates[-1]} to {dates[0]}")

    for date_str in reversed(dates):  # oldest first
        date_file = date_str.replace('-', '')
        output_file = OUTPUT_DIR / f"minute_bars_{date_file}.json.gz"
        
        if output_file.exists():
            print(f"⏭️ {date_str}: already cached")
            continue
        
        print(f"📥 {date_str}: downloading {len(symbols)} symbols...")
        data = {}
        for i, symbol in enumerate(symbols, 1):
            bars = download_minute_bars(client, symbol, date_str)
            if bars:
                data[symbol] = bars
            if i % 10 == 0:
                print(f"  ... {i}/{len(symbols)} symbols processed")
            time.sleep(0.15)  # rate limit: ~7 req/sec for free tier
        
        # Save
        with gzip.open(output_file, 'wt') as f:
            json.dump(data, f)
        print(f"  ✓ Saved {len(data)} symbols to {output_file}")

    print(f"\n✓ Download complete. Data stored in {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
