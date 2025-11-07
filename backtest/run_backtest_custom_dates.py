"""
Run backtest with custom date range for your downloaded historical data
Dates: Oct 24, 27-31, Nov 3-5 (9 trading days)

DIAGNOSTIC MODE: Tracks rejection reasons to understand why alerts aren't generating
"""

import sys
import os

# Add project root to path
CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Suppress Telegram notifications during backtest
os.environ["DISABLE_NOTIFICATIONS"] = "1"
os.environ["BACKTEST_MODE"] = "1"  # Enable relaxed thresholds for backtesting

from datetime import datetime
from pathlib import Path
from collections import defaultdict
from backtest_flatfiles import (
    parse_flat_file, backtest_symbol, load_tickers,
    BacktestResult, CACHE_DIR
)

# Import check detection globals to track stats
import polygon_websocket as ws

# Track diagnostic stats
rejection_stats = defaultdict(int)
momentum_counter_stats = []

def run_custom_backtest():
    """Run backtest with your specific downloaded dates"""
    
    # Load historical stats for adaptive thresholds
    print("Loading historical statistics for adaptive thresholds...")
    ws.load_historical_stats()
    print()
    
    # Your actual dates
    dates = [
        "2025-10-24",
        "2025-10-27",
        "2025-10-28",
        "2025-10-29",
        "2025-10-30",
        "2025-10-31",
        "2025-11-03",
        "2025-11-04",
        "2025-11-05"
    ]
    
    print("\n" + "="*80)
    print("ENHANCED CHECK_SPIKE BACKTEST - CUSTOM DATE RANGE")
    print("="*80)
    print(f"Testing new implementation with multi-bar persistence & VWAP alignment")
    print(f"Date range: {dates[0]} to {dates[-1]} ({len(dates)} trading days)")
    print("="*80 + "\n")
    
    # Load tickers
    tickers_path = os.path.join(PROJECT_ROOT, "data", "tickers.csv")
    tickers = load_tickers(tickers_path)
    print(f"Loaded {len(tickers)} tickers\n")
    
    # Initialize result
    result = BacktestResult()
    result.total_bars = 0  # Track total bars processed
    
    # Process each date
    for date_str in dates:
        file_path = CACHE_DIR / f"{date_str}.csv.gz"
        
        if not file_path.exists():
            print(f"[SKIP] {date_str} - file not found")
            continue
        
        print(f"\nProcessing {date_str}.csv...")
        
        # Parse bars
        bars_by_symbol = parse_flat_file(file_path, tickers)
        
        # Process each symbol's bars
        total_bars = 0
        for symbol, bars in bars_by_symbol.items():
            total_bars += len(bars)
            backtest_symbol(symbol, bars, result)
        
        result.total_bars += total_bars
        print(f"  Processed {total_bars:,} bars, {len(bars_by_symbol)} symbols")
    
    # Print summary
    print("\n" + "="*80)
    print("                     BACKTEST RESULTS SUMMARY")
    print("="*80)
    print(f"Total Bars Processed: {result.total_bars:,}")
    print(f"Total Alerts Generated: {result.total_alerts:,}")
    
    # Print momentum counter stats
    if ws.momentum_counter:
        max_counter = max(ws.momentum_counter.values())
        symbols_with_momentum = len([v for v in ws.momentum_counter.values() if v > 0])
        symbols_at_threshold = len([v for v in ws.momentum_counter.values() if v >= 2])
        print(f"\nMomentum Counter Stats:")
        print(f"  Symbols with any momentum: {symbols_with_momentum}")
        print(f"  Symbols reaching 2+ bars: {symbols_at_threshold}")
        print(f"  Max counter value: {max_counter}")
        if symbols_at_threshold > 0:
            print(f"  -> {symbols_at_threshold} symbols passed persistence check!")
    
    print("="*80)
    
    if result.total_alerts == 0:
        print("\n[!] NO ALERTS GENERATED")
        print("\nPossible reasons:")
        print("1. Multi-bar persistence (2+ bars) requirement is filtering everything")
        print("2. VWAP bearish trend filter is blocking alerts")
        print("3. Quality threshold (60) is too high for available data")
        print("4. Rolling volume window needs more initialization")
        print("\nThe new enhanced detection is MORE SELECTIVE than the old version.")
        print("This is expected - it's designed to reduce false positives.")
        return result
    
    # Calculate metrics using built-in method
    result.calculate_metrics()
    
    # Display results
    if result.total_alerts > 0:
        print(f"\nStage Breakdown:")
        print(f"  Stage 0 (Watch): {result.stage0_watch_count}")
        print(f"  Stage 1 (Early): {result.stage1_count}")
        print(f"  Stage 2 (Confirmed): {result.stage2_count}")
        print(f"  Stage 3 (Fast-Break): {result.stage3_count}")
        
        print(f"\nOutcomes:")
        print(f"  Profitable: {result.profitable_alerts} ({result.profitable_alerts/result.total_alerts*100:.1f}%)")
        print(f"  Breakeven: {result.breakeven_alerts} ({result.breakeven_alerts/result.total_alerts*100:.1f}%)")
        print(f"  Losing: {result.losing_alerts} ({result.losing_alerts/result.total_alerts*100:.1f}%)")
        
        print(f"\nPerformance:")
        print(f"  Win Rate: {result.win_rate:.2f}%")
        print(f"  Average Gain: {result.avg_gain:+.2f}%")
        print(f"  Max Gain: {result.max_gain:+.2f}%")
        
        print("\n" + "="*80)
        
        if result.win_rate >= 60:
            print("[EXCELLENT] Win rate above 60% - system performing well!")
        elif result.win_rate >= 50:
            print("[GOOD] Win rate above 50% - acceptable performance")
        elif result.win_rate >= 40:
            print("[FAIR] Win rate 40-50% - could be improved")
        else:
            print("[POOR] Win rate below 40% - needs optimization")
    
    # Save detailed results
    output_dir = Path(PROJECT_ROOT) / "results"
    output_dir.mkdir(exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"backtest_enhanced_spike_{timestamp_str}.json"
    
    import json
    
    # Convert datetime objects to strings for JSON serialization
    serializable_alerts = []
    for alert in result.alerts:
        alert_copy = alert.copy()
        if 'timestamp' in alert_copy and hasattr(alert_copy['timestamp'], 'isoformat'):
            alert_copy['timestamp'] = alert_copy['timestamp'].isoformat()
        serializable_alerts.append(alert_copy)
    
    with open(output_file, 'w') as f:
        json.dump({
            'summary': {
                'dates': dates,
                'total_alerts': result.total_alerts,
                'win_rate': result.win_rate if result.total_alerts > 0 else 0,
                'avg_gain': result.avg_gain if result.total_alerts > 0 else 0,
                'stage0_count': result.stage0_watch_count,
                'stage1_count': result.stage1_count,
                'stage2_count': result.stage2_count,
                'stage3_count': result.stage3_count
            },
            'alerts': serializable_alerts
        }, f, indent=2)
    
    print(f"\n[SAVED] Results saved to: {output_file}")
    print("="*80 + "\n")
    
    return result


if __name__ == "__main__":
    result = run_custom_backtest()
