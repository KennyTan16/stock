"""
Calculate and cache historical statistics from Polygon S3 flat files
Processes daily aggregate files to calculate 20-day average volume and price range
Much faster than API calls - processes local files directly
"""

import os
import csv
import gzip
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# Configuration
BASE_DIR = Path(__file__).parent.resolve()
TICKER_FILE = os.getenv("TICKER_FILE", str(BASE_DIR / "data" / "tickers.csv"))
FLATFILES_DIR = BASE_DIR / "historical_data" / "polygon_flatfiles_daily"
OUTPUT_DIR = BASE_DIR / "historical_data"
OUTPUT_FILE = OUTPUT_DIR / "stats_cache.csv"
DAYS_LOOKBACK = 20

def read_tickers(filepath):
    """Read ticker symbols from CSV file"""
    tickers = set()
    try:
        with open(filepath, 'r') as f:
            for row in csv.reader(f):
                if row:
                    ticker = row[0].strip().upper()
                    if ticker and ticker != "SYMBOL":
                        tickers.add(ticker)
    except Exception as e:
        print(f"Error reading tickers: {e}")
        return set()
    return tickers

def get_available_dates():
    """Get list of available date files from flatfiles directory"""
    if not FLATFILES_DIR.exists():
        print(f"[X] Flatfiles directory not found: {FLATFILES_DIR}")
        return []
    
    date_files = []
    for file in FLATFILES_DIR.glob("*.csv.gz"):
        try:
            # Extract date from filename (format: YYYY-MM-DD.csv.gz or YYYYMMDD.csv.gz)
            # Remove both .csv and .gz extensions
            date_str = file.name.replace('.csv.gz', '')
            # Try both formats
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                date_obj = datetime.strptime(date_str, "%Y%m%d")
            date_files.append((date_obj, file))
        except ValueError:
            continue
    
    # Sort by date descending (most recent first)
    date_files.sort(reverse=True)
    return date_files

def parse_flatfile(filepath, target_tickers):
    """Parse a single gzipped CSV flat file and extract daily stats per symbol
    Works with both minute and daily aggregates (daily is preferred for efficiency)
    Returns: {symbol: {'volume': int, 'high': float, 'low': float}}
    """
    stats = {}
    
    try:
        with gzip.open(filepath, 'rt') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = row.get('ticker', '').strip().upper()
                
                if ticker not in target_tickers:
                    continue
                
                # Get OHLCV data
                try:
                    volume = int(float(row.get('volume', 0)))
                    high = float(row.get('high', 0))
                    low = float(row.get('low', 0))
                    
                    # For daily aggregates, each ticker appears once
                    # For minute aggregates, need to aggregate
                    if ticker not in stats:
                        stats[ticker] = {'volume': volume, 'high': high, 'low': low}
                    else:
                        # Aggregate if multiple bars (minute data)
                        stats[ticker]['volume'] += volume
                        stats[ticker]['high'] = max(stats[ticker]['high'], high)
                        stats[ticker]['low'] = min(stats[ticker]['low'], low)
                    
                except (ValueError, TypeError):
                    continue
    
    except Exception as e:
        print(f"  [X] Error parsing {filepath.name}: {e}")
        return {}
    
    return stats

def calculate_stats(tickers):
    """Calculate 20-day average volume and range for each ticker"""
    print("="*80)
    print("HISTORICAL STATS CALCULATION FROM POLYGON FLATFILES")
    print("="*80)
    
    # Get available date files
    date_files = get_available_dates()
    
    if not date_files:
        print(f"\n[X] No flatfiles found in {FLATFILES_DIR}")
        print(f"   Download files using: download_polygon_flatfiles.py")
        return
    
    print(f"\n[FILES] Found {len(date_files)} flatfiles")
    print(f"[DATE] Date range: {date_files[-1][0].strftime('%Y-%m-%d')} to {date_files[0][0].strftime('%Y-%m-%d')}")
    print(f"[STATS] Processing {len(tickers)} target symbols")
    print(f"[CALC] Calculating {DAYS_LOOKBACK}-day averages\n")
    
    # Use most recent N days
    files_to_process = date_files[:DAYS_LOOKBACK]
    
    if len(files_to_process) < DAYS_LOOKBACK:
        print(f"[WARN] Only {len(files_to_process)} days available (need {DAYS_LOOKBACK})")
        print(f"       Stats will be calculated from available data\n")
    
    # Aggregate data per symbol across all days
    symbol_data = defaultdict(lambda: {'volumes': [], 'ranges': []})
    
    for i, (date_obj, filepath) in enumerate(files_to_process, 1):
        print(f"[{i}/{len(files_to_process)}] Processing {date_obj.strftime('%Y-%m-%d')}...", end=" ")
        
        daily_stats = parse_flatfile(filepath, tickers)
        
        if not daily_stats:
            print("[X] No data")
            continue
        
        # Aggregate daily stats
        for symbol, stats in daily_stats.items():
            if stats['volume'] > 0:  # Only count days with actual trading
                symbol_data[symbol]['volumes'].append(stats['volume'])
                range_value = stats['high'] - stats['low']
                symbol_data[symbol]['ranges'].append(range_value)
        
        print(f"[OK] {len(daily_stats)} symbols")
    
    # Calculate averages
    print(f"\n[STATS] Calculating averages...")
    results = []
    
    for symbol in tickers:
        if symbol not in symbol_data:
            # No data for this symbol
            results.append({
                'symbol': symbol,
                'avg_volume_20d': '',
                'avg_range_20d': '',
                'bars_count': 0,
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            continue
        
        volumes = symbol_data[symbol]['volumes']
        ranges = symbol_data[symbol]['ranges']
        
        if not volumes:
            results.append({
                'symbol': symbol,
                'avg_volume_20d': '',
                'avg_range_20d': '',
                'bars_count': 0,
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            continue
        
        avg_volume = sum(volumes) / len(volumes)
        avg_range = sum(ranges) / len(ranges)
        
        results.append({
            'symbol': symbol,
            'avg_volume_20d': avg_volume,
            'avg_range_20d': avg_range,
            'bars_count': len(volumes),
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    
    # Save results
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    print(f"\n[SAVE] Saving to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'symbol', 'avg_volume_20d', 'avg_range_20d', 'bars_count', 'last_updated'
        ])
        writer.writeheader()
        writer.writerows(results)
    
    # Summary
    successful = sum(1 for r in results if r['bars_count'] > 0)
    failed = len(results) - successful
    
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Total Symbols: {len(tickers)}")
    print(f"[OK] With Data: {successful}")
    print(f"[X] No Data: {failed}")
    print(f"[DATE] Days Processed: {len(files_to_process)}")
    print(f"[SAVE] Cache File: {OUTPUT_FILE}")
    print(f"{'='*80}\n")
    
    # Show sample results
    if successful > 0:
        print("Sample Results:")
        samples = [r for r in results if r['bars_count'] > 0][:5]
        for r in samples:
            print(f"  {r['symbol']}: Vol={r['avg_volume_20d']:,.0f}, Range=${r['avg_range_20d']:.2f} ({r['bars_count']} days)")

if __name__ == "__main__":
    tickers = read_tickers(TICKER_FILE)
    if tickers:
        calculate_stats(tickers)
    else:
        print("[X] No tickers found in ticker file")
