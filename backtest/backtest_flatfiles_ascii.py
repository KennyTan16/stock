"""
Backtest dual-stage momentum detector using Polygon.io Flat Files
Downloads and processes historical minute-bar data for all tickers
"""

import sys
import os
import csv
import gzip
from datetime import datetime, timedelta
from collections import defaultdict
import json
import boto3
from pathlib import Path

# Add parent directory to path to import main module
sys.path.insert(0, os.path.abspath('..'))
from polygon_websocket import (
    check_spike, momentum_flags, rolling_volume_3min, 
    latest_quotes, minute_aggregates, update_aggregates,
    get_minute_ts, ET_TIMEZONE
)

# ====================================================================================
# TESTING THRESHOLDS - Temporarily lowered to verify detection logic works
# ====================================================================================
TEST_MODE = True  # Set to False to use production thresholds

if TEST_MODE:
    # Lower thresholds for testing (should generate alerts on normal market moves)
    print("\n" + "="*80)
    print("WARNING: BACKTEST RUNNING IN TEST MODE - Using lowered thresholds")
    print("="*80)
    print("Stage 1: rel_vol >=1.5 (prod: 2.5), pct >=1.5-2.0% (prod: 3-4%)")
    print("Stage 2: rel_vol >=2.5 (prod: 4.0), pct >=3.5-4.0% (prod: 6-7%), vol >=15-50K (prod: 20-75K)")
    print("This should generate alerts on typical strong momentum moves")
    print("="*80 + "\n")
# ====================================================================================

# Polygon Flat Files configuration via Massive.io S3
# Access credentials for Polygon flat files
MASSIVE_ACCESS_KEY = "beea43df-4b8b-4a9a-87e5-2029718458da"
MASSIVE_SECRET_KEY = "lODb71RE6pKs8Vd7HVxUo3u2Up26o14S"
MASSIVE_ENDPOINT = "https://files.massive.com"
MASSIVE_BUCKET = "flatfiles"

# Store historical data in organized folder structure
CACHE_DIR = Path("../historical_data/polygon_flatfiles")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

class BacktestResult:
    def __init__(self):
        self.alerts = []
        self.total_alerts = 0
        self.profitable_alerts = 0
        self.breakeven_alerts = 0
        self.losing_alerts = 0
        self.stage1_count = 0
        self.stage2_count = 0
        self.stage3_count = 0
        self.avg_gain = 0
        self.max_gain = 0
        self.max_loss = 0
        self.false_positives = 0
        self.bars_processed = 0
        
    def add_alert(self, alert_data):
        """Record an alert and its outcome"""
        self.alerts.append(alert_data)
        self.total_alerts += 1
        
        # Track stage
        if alert_data.get('stage') == 1:
            self.stage1_count += 1
        elif alert_data.get('stage') == 2:
            self.stage2_count += 1
        elif alert_data.get('stage') == 3:
            self.stage3_count += 1
        
        # Track outcome if available
        if 'outcome' in alert_data:
            profit = alert_data['outcome']['profit_pct']
            if profit > 0.5:  # More than 0.5% profit
                self.profitable_alerts += 1
            elif profit < -0.5:  # More than 0.5% loss
                self.losing_alerts += 1
            else:
                self.breakeven_alerts += 1
                
    def calculate_metrics(self):
        """Calculate aggregate statistics"""
        if self.total_alerts > 0:
            total_profit = sum(a['outcome']['profit_pct'] for a in self.alerts if 'outcome' in a)
            self.avg_gain = total_profit / len([a for a in self.alerts if 'outcome' in a])
            
            profits = [a['outcome']['profit_pct'] for a in self.alerts if 'outcome' in a]
            if profits:
                self.max_gain = max(profits)
                self.max_loss = min(profits)
            
            # Win rate based on profitable vs total with outcome
            alerts_with_outcome = len([a for a in self.alerts if 'outcome' in a])
            if alerts_with_outcome > 0:
                self.win_rate = (self.profitable_alerts / alerts_with_outcome) * 100
            else:
                self.win_rate = 0
        else:
            self.win_rate = 0
            
    def print_summary(self):
        """Display backtest results"""
        print("\n" + "="*80)
        print(" "*25 + "???? BACKTEST RESULTS SUMMARY")
        print("="*80)
        print(f"Total Bars Processed: {self.bars_processed:,}")
        print(f"Total Alerts Generated: {self.total_alerts}")
        
        if self.total_alerts > 0:
            print(f"\n  Stage 1 (Early Detection): {self.stage1_count}")
            print(f"  Stage 2 (Confirmed Breakout): {self.stage2_count}")
            print(f"  Stage 3 (Fast-Break): {self.stage3_count}")
            
            alerts_with_outcome = len([a for a in self.alerts if 'outcome' in a])
            if alerts_with_outcome > 0:
                print(f"\nProfitable: {self.profitable_alerts} ({self.profitable_alerts/alerts_with_outcome*100:.1f}%)")
                print(f"Breakeven: {self.breakeven_alerts}")
                print(f"Losing: {self.losing_alerts} ({self.losing_alerts/alerts_with_outcome*100:.1f}%)")
                print(f"\nWin Rate: {self.win_rate:.1f}%")
                print(f"Average Gain: {self.avg_gain:.2f}%")
                print(f"Max Gain: {self.max_gain:.2f}%")
                print(f"Max Loss: {self.max_loss:.2f}%")
            else:
                print("\nNo outcome data available (alerts at end of data)")
        
        print("="*80)


def download_flat_file(date):
    """
    Download Polygon flat file for a specific date from Massive.io S3
    Files are in format: us_stocks_sip/minute_aggs_v1/YYYY/MM/YYYY-MM-DD.csv.gz
    """
    date_str = date.strftime("%Y-%m-%d")
    year = date.strftime("%Y")
    month = date.strftime("%m")
    
    cache_file = CACHE_DIR / f"{date_str}.csv.gz"
    
    # Check if already cached
    if cache_file.exists():
        print(f"  Using cached file: {date_str}")
        return cache_file
    
    # S3 object key
    s3_key = f"us_stocks_sip/minute_aggs_v1/{year}/{month}/{date_str}.csv.gz"
    
    print(f"  Downloading: {date_str}...", end=" ", flush=True)
    
    try:
        # Initialize S3 client with Massive.io credentials
        s3_client = boto3.client(
            's3',
            endpoint_url=MASSIVE_ENDPOINT,
            aws_access_key_id=MASSIVE_ACCESS_KEY,
            aws_secret_access_key=MASSIVE_SECRET_KEY
        )
        
        # Download file
        s3_client.download_file(MASSIVE_BUCKET, s3_key, str(cache_file))
        
        print(f"??? ({cache_file.stat().st_size / 1024 / 1024:.1f} MB)")
        return cache_file
        
    except Exception as e:
        print(f"??? Failed: {e}")
        # Clean up partial download
        if cache_file.exists():
            cache_file.unlink()
        return None


def parse_flat_file(file_path, ticker_set):
    """
    Parse compressed CSV flat file and extract bars for our tickers
    CSV format: ticker,volume,open,close,high,low,window_start,transactions
    Note: window_start is in nanoseconds, no VWAP in flat files
    """
    bars_by_symbol = defaultdict(list)
    
    with gzip.open(file_path, 'rt') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row['ticker']
            
            # Filter to only our tickers
            if ticker not in ticker_set:
                continue
            
            # Parse bar data
            timestamp_ns = int(row['window_start'])
            timestamp_ms = timestamp_ns // 1_000_000  # Convert nanoseconds to milliseconds
            
            open_price = float(row['open'])
            close_price = float(row['close'])
            volume = int(row['volume'])
            
            # Calculate VWAP approximation (use close price as proxy since flat files don't include VWAP)
            # In production, you'd want actual VWAP but this works for backtesting
            vwap = (float(row['high']) + float(row['low']) + close_price) / 3
            
            bar = {
                'symbol': ticker,
                'open': open_price,
                'high': float(row['high']),
                'low': float(row['low']),
                'close': close_price,
                'volume': volume,
                'vwap': vwap,
                'timestamp': timestamp_ms,
                'transactions': int(row['transactions']),
            }
            
            bars_by_symbol[ticker].append(bar)
    
    # Sort bars by timestamp for each symbol
    for symbol in bars_by_symbol:
        bars_by_symbol[symbol].sort(key=lambda x: x['timestamp'])
    
    return bars_by_symbol


def simulate_trading_outcome(entry_bar, future_bars, vwap):
    """
    Simulate trade outcome by checking if stop loss or target hit
    Entry: entry_bar['close']
    Stop: 2% below VWAP
    Target: 8% profit
    """
    entry_price = entry_bar['close']
    stop_loss = vwap * 0.98
    target = entry_price * 1.08
    
    for bar in future_bars:
        # Check if stop hit
        if bar['low'] <= stop_loss:
            profit_pct = ((stop_loss - entry_price) / entry_price) * 100
            return {
                'hit': 'stop',
                'exit_price': stop_loss,
                'profit_pct': profit_pct,
                'bars_held': future_bars.index(bar) + 1
            }
        
        # Check if target hit
        if bar['high'] >= target:
            profit_pct = ((target - entry_price) / entry_price) * 100
            return {
                'hit': 'target',
                'exit_price': target,
                'profit_pct': profit_pct,
                'bars_held': future_bars.index(bar) + 1
            }
    
    # Neither hit - hold to end
    if future_bars:
        final_price = future_bars[-1]['close']
        profit_pct = ((final_price - entry_price) / entry_price) * 100
    else:
        profit_pct = 0
    
    return {
        'hit': 'timeout',
        'exit_price': final_price if future_bars else entry_price,
        'profit_pct': profit_pct,
        'bars_held': len(future_bars)
    }


def backtest_symbol(symbol, bars, result):
    """Run backtest for a single symbol across all bars"""
    
    # Clear state for this symbol
    if symbol in momentum_flags:
        del momentum_flags[symbol]
    if symbol in rolling_volume_3min:
        rolling_volume_3min[symbol] = []
    if symbol in minute_aggregates:
        del minute_aggregates[symbol]
    if symbol in latest_quotes:
        del latest_quotes[symbol]
    
    for i, bar in enumerate(bars):
        result.bars_processed += 1
        
        # Convert timestamp to datetime
        minute_ts = datetime.fromtimestamp(bar['timestamp'] / 1000, tz=ET_TIMEZONE)
        
        # Manually populate minute_aggregates (backtest doesn't use update_aggregates)
        agg = minute_aggregates[minute_ts][symbol]
        agg['open'] = bar['open']
        agg['high'] = bar['high']
        agg['low'] = bar['low']
        agg['close'] = bar['close']
        agg['volume'] = bar['volume']
        agg['value'] = bar['vwap'] * bar['volume']
        agg['count'] = bar['transactions']
        agg['vwap'] = bar['vwap']
        
        # Update rolling 3-minute volume
        if symbol not in rolling_volume_3min:
            rolling_volume_3min[symbol] = []
        if len(rolling_volume_3min[symbol]) >= 3:
            rolling_volume_3min[symbol].pop(0)
        rolling_volume_3min[symbol].append(bar['volume'])
        
        # Calculate percentage change
        pct_change = ((bar['close'] - bar['open']) / bar['open']) * 100 if bar['open'] > 0 else 0
        
        # Set a mock quote for spread calculation (backtest doesn't have real quotes)
        # Use 0.1% spread as a reasonable default for liquid stocks
        latest_quotes[symbol] = {
            'bid': bar['close'] * 0.999,
            'ask': bar['close'] * 1.001,
            'timestamp': bar['timestamp']
        }
        
        # Track if flag exists before check
        flag_before = symbol in momentum_flags
        flag_data_before = momentum_flags.get(symbol, {})
        
        # Run check_spike
        check_spike(
            symbol=symbol,
            current_pct=pct_change,
            current_vol=bar['volume'],
            minute_ts=minute_ts,
            open_price=bar['open'],
            close_price=bar['close'],
            trade_count=bar['transactions'],
            vwap=bar['vwap']
        )
        
        # Track if flag exists after check
        flag_after = symbol in momentum_flags
        flag_data_after = momentum_flags.get(symbol, {})
        
        # Detect if alert was triggered
        # Stage 1: Flag created (SETUP flag appears)
        if not flag_before and flag_after:
            if flag_data_after.get('flag', '').startswith('SETUP_'):
                alert_triggered = True
                alert_stage = 1
        
        # Stage 2: Flag transitioned to CONFIRMED or removed (alert sent)
        elif flag_before and not flag_after:
            # Alert was triggered and flag cleared
            alert_triggered = True
            alert_stage = 2  # Assume stage 2 since flag was cleared after confirmation
        
        if alert_triggered:
            # Get future bars for outcome simulation (next 60 minutes)
            future_bars = bars[i+1:i+61]
            
            outcome = simulate_trading_outcome(bar, future_bars, bar['vwap'])
            
            alert_data = {
                'symbol': symbol,
                'timestamp': minute_ts.isoformat(),
                'stage': alert_stage,
                'entry_price': bar['close'],
                'volume': bar['volume'],
                'pct_change': pct_change,
                'vwap': bar['vwap'],
                'outcome': outcome
            }
            
            result.add_alert(alert_data)
            
            # Log alert
            session_hour = minute_ts.hour
            if 4 <= session_hour < 9 or (session_hour == 9 and minute_ts.minute < 30):
                session = "PREMARKET"
            elif 9 <= session_hour < 16 or (session_hour == 9 and minute_ts.minute >= 30):
                session = "REGULAR"
            elif 16 <= session_hour < 20:
                session = "POSTMARKET"
            else:
                session = "CLOSED"
            
            outcome_str = f"{outcome['hit'].upper()}: {outcome['profit_pct']:+.2f}% in {outcome['bars_held']} bars"
            print(f"ALERT: {symbol} {session} Stage{alert_stage} | ${bar['close']:.2f} | Vol={bar['volume']:,} | {pct_change:+.2f}% | {outcome_str}")


def load_tickers(csv_path):
    """Load ticker symbols from CSV file"""
    tickers = set()
    with open(csv_path, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            if row:  # Skip empty rows
                ticker = row[0].strip().upper()
                if ticker and ticker != 'TICKER':  # Skip header if exists
                    tickers.add(ticker)
    return tickers


def run_backtest(tickers_csv, days_back=10):
    """
    Main backtest function using Polygon flat files from Massive.io S3
    """
    print("\n" + "="*80)
    print("???? DUAL-STAGE MOMENTUM DETECTOR - BACKTEST (FLAT FILES)")
    print("="*80)
    
    # Load tickers
    tickers = load_tickers(tickers_csv)
    print(f"\nLoaded {len(tickers)} tickers from {tickers_csv}")
    
    # Calculate date range
    end_date = datetime.now()
    
    # Go back to most recent weekday
    while end_date.weekday() >= 5:  # Saturday=5, Sunday=6
        end_date -= timedelta(days=1)
    
    # Go back days_back trading days
    current_date = end_date
    dates_to_process = []
    days_found = 0
    
    while days_found < days_back:
        # Skip weekends
        if current_date.weekday() < 5:
            dates_to_process.append(current_date)
            days_found += 1
        current_date -= timedelta(days=1)
    
    dates_to_process.reverse()  # Process oldest to newest
    
    print(f"Date range: {dates_to_process[0].strftime('%Y-%m-%d')} to {dates_to_process[-1].strftime('%Y-%m-%d')}")
    print(f"\nDownloading {len(dates_to_process)} flat files...")
    
    # Download files
    flat_files = []
    for date in dates_to_process:
        file_path = download_flat_file(date)
        if file_path:
            flat_files.append(file_path)
    
    if not flat_files:
        print("\n??? No flat files downloaded. Check API key and network connection.")
        return None
    
    print(f"\n??? Downloaded {len(flat_files)} files")
    print("\nProcessing bars and running backtest...")
    print("-" * 80)
    
    # Process each file
    result = BacktestResult()
    
    for file_path in flat_files:
        date_str = file_path.stem  # Get date from filename
        print(f"\nProcessing {date_str}...")
        
        # Parse file
        bars_by_symbol = parse_flat_file(file_path, tickers)
        
        # Backtest each symbol
        for symbol in sorted(bars_by_symbol.keys()):
            bars = bars_by_symbol[symbol]
            if bars:
                backtest_symbol(symbol, bars, result)
    
    # Calculate metrics
    result.calculate_metrics()
    
    # Display summary
    result.print_summary()
    
    # Save detailed results to results folder
    output_file = f"../results/backtest_results_flatfiles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump({
            'backtest_config': {
                'tickers_file': tickers_csv,
                'num_tickers': len(tickers),
                'days_back': days_back,
                'start_date': dates_to_process[0].strftime('%Y-%m-%d'),
                'end_date': dates_to_process[-1].strftime('%Y-%m-%d'),
                'test_mode': TEST_MODE
            },
            'summary': {
                'bars_processed': result.bars_processed,
                'total_alerts': result.total_alerts,
                'stage1_alerts': result.stage1_count,
                'stage2_alerts': result.stage2_count,
                'stage3_alerts': result.stage3_count,
                'profitable': result.profitable_alerts,
                'breakeven': result.breakeven_alerts,
                'losing': result.losing_alerts,
                'win_rate': result.win_rate,
                'avg_gain': result.avg_gain,
                'max_gain': result.max_gain,
                'max_loss': result.max_loss,
            },
            'alerts': result.alerts
        }, f, indent=2)
    
    print(f"\n???? Detailed results saved to: {output_file}")
    
    if result.total_alerts == 0:
        print("\n?????? No alerts generated during backtest period")
        print("This means no bars met the detection criteria.")
        if TEST_MODE:
            print("Even with lowered test thresholds, no alerts were triggered.")
            print("Consider checking if data contains volatile enough stocks or time periods.")
    
    print("\n" + "="*80 + "\n")
    
    return result


if __name__ == "__main__":
    # Run backtest with tickers.csv from data folder
    tickers_csv = "../data/tickers.csv"
    
    if not os.path.exists(tickers_csv):
        print(f"??? Tickers file not found: {tickers_csv}")
        sys.exit(1)
    
    # Check if boto3 is installed
    try:
        import boto3
    except ImportError:
        print("??? boto3 not installed. Install with: pip install boto3")
        sys.exit(1)
    
    # Run backtest for last 10 trading days
    result = run_backtest(tickers_csv, days_back=10)
    
    if result and result.total_alerts > 0:
        print("??? Backtest complete!")
        print(f"Generated {result.total_alerts} alerts with {result.win_rate:.1f}% win rate")
        
        if result.win_rate >= 60:
            print("???? System performing well! Win rate above 60%")
        elif result.win_rate >= 50:
            print("?????? System acceptable but could be optimized")
        else:
            print("??? System needs threshold tuning - win rate below 50%")

