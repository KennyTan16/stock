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
try:
    import boto3  # optional when not using cached-only mode
except ImportError:
    boto3 = None
from pathlib import Path

# Add project root (parent of this backtest directory) to sys.path for module imports
CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from polygon_websocket import (
    check_spike, momentum_flags, rolling_volume_3min,
    latest_quotes, minute_aggregates, update_aggregates,
    get_minute_ts, ET_TIMEZONE, watch_alerts, breakout_quality
)

# ====================================================================================
# BALANCED THRESHOLDS - Middle ground between loose (15% win rate) and strict (0 alerts)
# ====================================================================================
# History:
# - Original loose thresholds: 1,226 alerts, 15.17% win rate (too many false positives)
# - Enhanced strict thresholds: 0 alerts, undefined win rate (too restrictive)
# - NEW BALANCED approach: Target 50-200 alerts with 35-50% win rate
#
# BALANCED STRATEGY: Moderate filtering for quality signals
# - Raise thresholds moderately (not extremely)
# - Use balanced quality filters
# - Focus on consistent momentum, not just explosive spikes
# ====================================================================================
TEST_MODE = False  # Using BALANCED production thresholds now

if TEST_MODE:
    # DEPRECATED - Old test thresholds (generated 1,226 alerts with 15% win rate)
    print("\n" + "="*80)
    print("WARNING: BACKTEST RUNNING IN TEST MODE - Using OLD lowered thresholds")
    print("="*80)
    print("Stage 1: rel_vol >=1.5 (prod: 3.0-3.2), pct >=1.5-2.0% (prod: 4-5%)")
    print("Stage 2: rel_vol >=2.5 (prod: 4.5-5.0), pct >=3.5-4.0% (prod: 7.5-8.5%), vol >=15-50K (prod: 30-100K)")
    print("This should generate alerts on typical strong momentum moves")
    print("="*80 + "\n")
else:
    print("\n" + "="*80)
    print("BACKTEST RUNNING WITH BALANCED-QUALITY THRESHOLDS + SCORING")
    print("="*80)
    print("Goal: Restore alert flow (avoid 0) while ranking by quality score for manual discretion")
    print("Scoring factors: rel_vol, pct_change, volume vs threshold, trade density, spread tightness, follow-through")
    print("")
    print("PREMARKET:")
    print("  Stage 1: rel_vol >=2.8, pct >=4.0%, 3+ trades, no vol fade")
    print("  Stage 2: rel_vol >=4.5, pct >=8.0%, vol >=30K")
    print("")
    print("REGULAR HOURS:")
    print("  Stage 1: rel_vol >=2.9, pct >=5.0%, 3+ trades, no vol fade")
    print("  Stage 2: rel_vol >=4.7, pct >=8.0%, vol >=90K")
    print("")
    print("POSTMARKET:")
    print("  Stage 1: rel_vol >=2.7, pct >=4.0%, 3+ trades, no vol fade")
    print("  Stage 2: rel_vol >=4.4, pct >=7.2%, vol >=24K")
    print("="*80 + "\n")
# ====================================================================================

# Polygon Flat Files configuration via Massive.io S3
# Access credentials for Polygon flat files
MASSIVE_ACCESS_KEY = "beea43df-4b8b-4a9a-87e5-2029718458da"
MASSIVE_SECRET_KEY = "lODb71RE6pKs8Vd7HVxUo3u2Up26o14S"
MASSIVE_ENDPOINT = "https://files.massive.com"
MASSIVE_BUCKET = "flatfiles"

# Cached-only mode: use pre-downloaded flat files in historical_data/polygon_flatfiles
USE_CACHED_ONLY = True  # User indicated data already stored locally

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
        self.stage0_watch_count = 0
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
        elif alert_data.get('stage') == 0:
            self.stage0_watch_count += 1
        
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
        print(" "*25 + "BACKTEST RESULTS SUMMARY")
        print("="*80)
        print(f"Total Bars Processed: {self.bars_processed:,}")
        print(f"Total Alerts Generated: {self.total_alerts}")
        
        if self.total_alerts > 0:
            print(f"\n  Stage 0 (Watch Alerts): {self.stage0_watch_count}")
            print(f"  Stage 1 (Early Detection): {self.stage1_count}")
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
    
    # In cached-only mode we never attempt remote download; just return existing file if present
    if USE_CACHED_ONLY:
        if cache_file.exists():
            print(f"  [CACHE] {date_str} available")
            return cache_file
        else:
            print(f"  [MISS] {date_str} not found in cache (skipping)")
            return None

    # Check if already cached (download mode)
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
        
        print(f"[OK] ({cache_file.stat().st_size / 1024 / 1024:.1f} MB)")
        return cache_file
        
    except Exception as e:
        print(f"[X] Failed: {e}")
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
    """Simulate trade outcome with dynamic risk based on quality tier.
    Entry: entry_bar['close']
    Base Stop: 2% below VWAP (quality <=62)
    Tight Stop: 1.5% below VWAP (quality >62)
    Parabolic Relaxed Stop: 2.5% below VWAP if pct_change > 11% and quality < 70
    Target baseline: 8% profit. Adaptive scaling: if quality >74 and pct_change > 6%, extend to 9.5%.
    """
    entry_price = entry_bar['close']
    quality = entry_bar.get('quality_score')
    pct_change = entry_bar.get('pct_change', 0)
    # Determine stop tier
    if quality is not None and quality > 62:
        stop_loss = vwap * 0.985  # 1.5% below VWAP
    else:
        stop_loss = vwap * 0.98   # 2%
    # Parabolic relaxed stop widening
    if pct_change > 11 and (quality is None or quality < 70):
        stop_loss = vwap * 0.975  # 2.5% below VWAP
    # Adaptive target sizing
    target_mult = 1.08
    if quality is not None and quality > 74 and pct_change > 6:
        target_mult = 1.095
    target = entry_price * target_mult
    
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
    
    processed_watch_indices = set()
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

        # Capture any new Stage 0 watch alerts emitted in this minute for this symbol
        for idx, wa in enumerate(watch_alerts):
            if idx in processed_watch_indices:
                continue
            if wa['symbol'] != symbol:
                continue
            # Only consider alerts at or before current minute timestamp
            if hasattr(wa['timestamp'], 'isoformat'):
                wa_minute = wa['timestamp']
            else:
                wa_minute = datetime.fromtimestamp(wa['timestamp'], tz=ET_TIMEZONE)
            if wa_minute == minute_ts:
                # Record watch alert (no trade outcome simulation for watch tier)
                alert_data = {
                    'symbol': symbol,
                    'timestamp': wa_minute.isoformat(),
                    'stage': 0,
                    'entry_price': bar['close'],
                    'volume': bar['volume'],
                    'pct_change': pct_change,
                    'vwap': bar['vwap'],
                    'quality_score': wa.get('quality')
                }
                result.add_alert(alert_data)
                processed_watch_indices.add(idx)
        
        # Track if flag exists after check
        flag_after = symbol in momentum_flags
        flag_data_after = momentum_flags.get(symbol, {})
        
        # Detect if alert was triggered
        alert_triggered = False
        alert_stage = 0
        
        # Stage 1: Flag created (SETUP flag appears)
        if not flag_before and flag_after:
            if flag_data_after.get('flag', '').startswith('SETUP_'):
                alert_triggered = True
                alert_stage = 1
                current_quality = flag_data_after.get('quality_score')
        
        # Stage 2: Flag transitioned to CONFIRMED or removed (alert sent)
        elif flag_before and not flag_after:
            # Alert was triggered and flag cleared (Stage 2 confirmation)
            alert_triggered = True
            alert_stage = 2
            current_quality = flag_data_before.get('quality_score')
        
        if alert_triggered:
            # Get future bars for outcome simulation (next 60 minutes)
            future_bars = bars[i+1:i+61]
            
            # Inject quality & pct_change into entry bar for dynamic outcome simulation
            bar_with_quality = dict(bar)
            bar_with_quality['quality_score'] = current_quality if 'current_quality' in locals() else None
            bar_with_quality['pct_change'] = pct_change
            outcome = simulate_trading_outcome(bar_with_quality, future_bars, bar['vwap'])
            
            alert_data = {
                'symbol': symbol,
                'timestamp': minute_ts.isoformat(),
                'stage': alert_stage,
                'entry_price': bar['close'],
                'volume': bar['volume'],
                'pct_change': pct_change,
                'vwap': bar['vwap'],
                'quality_score': current_quality if 'current_quality' in locals() else None,
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
    print("DUAL-STAGE MOMENTUM DETECTOR - BACKTEST (FLAT FILES)")
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
    if USE_CACHED_ONLY:
        print(f"\n[CACHED-ONLY] Gathering existing flat files for {len(dates_to_process)} trading days...")
    else:
        print(f"\nDownloading {len(dates_to_process)} flat files...")
    
    # Download files
    flat_files = []
    for date in dates_to_process:
        file_path = download_flat_file(date)
        if file_path:
            flat_files.append(file_path)
    
    if not flat_files:
        if USE_CACHED_ONLY:
            print("\nERROR: No cached flat files found for requested date range.")
            print("Populate 'historical_data/polygon_flatfiles' with YYYY-MM-DD.csv.gz files.")
        else:
            print("\nERROR: No flat files downloaded. Check API key and network connection.")
        return None
    
    print(f"\n[OK] Using {len(flat_files)} flat files")
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
                'stage0_watch_alerts': result.stage0_watch_count,
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
    
    print(f"\nSAVED: Detailed results saved to: {output_file}")
    
    if result.total_alerts == 0:
        print("\nWARNING: No alerts generated during backtest period")
        print("This means no bars met the detection criteria.")
        if TEST_MODE:
            print("Even with lowered test thresholds, no alerts were triggered.")
            print("Consider checking if data contains volatile enough stocks or time periods.")
    
    print("\n" + "="*80 + "\n")
    
    return result


if __name__ == "__main__":
    # Resolve tickers file using absolute project root paths
    primary_path = os.path.join(PROJECT_ROOT, "data", "tickers.csv")
    fallback_path = os.path.join(PROJECT_ROOT, "tickers.csv")
    if os.path.exists(primary_path):
        tickers_csv = primary_path
    elif os.path.exists(fallback_path):
        tickers_csv = fallback_path
        print(f"[INFO] Using fallback tickers file: {fallback_path}")
    else:
        print(f"ERROR: No tickers file found. Expected {primary_path} or {fallback_path}")
        sys.exit(1)
    
    # Validate required library only if downloading
    if not USE_CACHED_ONLY:
        if boto3 is None:
            print("ERROR: boto3 not installed and download mode active. Install with: pip install boto3 or enable cached-only mode.")
            sys.exit(1)
    else:
        print("[MODE] Cached-only backtest (skipping downloads).")
    
    # Run backtest for last 9 trading days (using cached data only)
    result = run_backtest(tickers_csv, days_back=9)
    
    if result and result.total_alerts > 0:
        print("COMPLETE: Backtest complete!")
        print(f"Generated {result.total_alerts} alerts with {result.win_rate:.1f}% win rate")
        
        if result.win_rate >= 60:
            print("SUCCESS: System performing well! Win rate above 60%")
        elif result.win_rate >= 50:
            print("WARNING: System acceptable but could be optimized")
        else:
            print("ERROR: System needs threshold tuning - win rate below 50%")
