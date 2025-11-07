"""
Grid Search for Optimal Momentum Detection Thresholds
Iterates over parameter combinations, runs backtest replay on historical flatfiles,
and outputs a CSV with performance metrics (win rate, avg gain, alert count, false positives).

Usage:
  python grid_search.py

Requirements:
  - Historical minute flatfiles in data/minute_bars/ (gzipped JSON from Polygon)
  - Ticker list in data/tickers.csv (or TICKER_FILE env var)
  - Backtest outcome simulation (stop/target/timeout logic)

Outputs:
  - results/grid_search_YYYYMMDD_HHMMSS.csv: detailed metrics per combination
  - Best combination printed to console with summary statistics
"""

import os
import sys
import gzip
import json
import itertools
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict, namedtuple
from pathlib import Path

# Suppress polygon_websocket main execution
os.environ["DISABLE_NOTIFICATIONS"] = "1"
os.environ["STAGE2_DEBUG"] = "0"

# Import detection logic (will use our injected thresholds)
from polygon_websocket import (
    check_spike,
    momentum_flags,
    breakout_quality,
    watch_alerts,
    minute_aggregates,
    rolling_volume_3min,
    get_minute_ts,
    ET_TIMEZONE,
    read_tickers,
    TICKER_FILE,
)

# Grid search parameter space
# WIDER RANGES for more diverse results
GRID = {
    'pct_thresh_early': [2.5, 3.5, 4.5, 5.5],      # Wider range: 2.5% to 5.5%
    'min_rel_vol_stage1': [1.5, 2.0, 2.5, 3.0],    # Wider range: 1.5x to 3.0x
    'pct_thresh_confirm': [5.0, 6.5, 8.0, 9.5],    # Wider range: 5% to 9.5%
    'min_rel_vol_stage2': [3.0, 3.8, 4.6, 5.5],    # Wider range: 3.0x to 5.5x
}

# Backtest configuration
DATA_DIR = Path("historical_data/polygon_flatfiles")
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

# Outcome thresholds for trade simulation
STOP_LOSS_PCT = 0.02  # 2% stop from entry
TARGET_PCT = 0.08     # 8% target from entry
TIMEOUT_MINUTES = 30  # exit if no stop/target within 30 minutes

AlertRecord = namedtuple("AlertRecord", ["symbol", "timestamp", "entry_price", "session", "quality", "stage"])

def clear_state():
    """Reset all global detection state between runs."""
    momentum_flags.clear()
    breakout_quality.clear()
    watch_alerts.clear()
    minute_aggregates.clear()
    rolling_volume_3min.clear()

def load_minute_flatfiles(date_str, symbols):
    """Load minute bars for given date and symbols from gzipped CSV flatfiles.
    Returns: {symbol: [(timestamp, open, close, high, low, volume, trades, vwap), ...]}
    """
    import csv
    bars = defaultdict(list)
    symbol_set = set(symbols)  # Convert to set for O(1) lookup
    # Try both date formats: YYYY-MM-DD and YYYYMMDD
    filename1 = DATA_DIR / f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}.csv.gz"
    filename2 = DATA_DIR / f"minute_bars_{date_str}.json.gz"
    
    filename = filename1 if filename1.exists() else filename2 if filename2.exists() else None
    
    if not filename or not filename.exists():
        return bars
    
    try:
        with gzip.open(filename, 'rt') as f:
            # Check if it's CSV or JSON
            first_char = f.read(1)
            f.seek(0)
            
            if first_char == '{' or first_char == '[':
                # JSON format
                data = json.load(f)
                for symbol in symbol_set:
                    if symbol in data:
                        for bar in data[symbol]:
                            ts = datetime.fromisoformat(bar['timestamp']).replace(tzinfo=ET_TIMEZONE)
                            bars[symbol].append((
                                ts,
                                bar['open'],
                                bar['close'],
                                bar.get('high', bar['close']),
                                bar.get('low', bar['open']),
                                bar['volume'],
                                bar.get('trades', 0),
                                bar.get('vwap', bar['close'])
                            ))
            else:
                # CSV format: ticker,volume,open,close,high,low,window_start,transactions
                # window_start is Unix timestamp in nanoseconds
                reader = csv.DictReader(f)
                found_symbols = set()
                for row in reader:
                    symbol = row['ticker']
                    if symbol in symbol_set:
                        found_symbols.add(symbol)
                        # Convert nanoseconds to datetime
                        nanos = int(row['window_start'])
                        ts = datetime.fromtimestamp(nanos / 1e9, tz=ET_TIMEZONE)
                        # Calculate vwap as close price (since not provided)
                        close = float(row['close'])
                        bars[symbol].append((
                            ts,
                            float(row['open']),
                            close,
                            float(row['high']),
                            float(row['low']),
                            int(row['volume']),
                            int(row.get('transactions', 0)),
                            close  # use close as vwap approximation
                        ))
                        # Early exit if we've found all symbols
                        if len(found_symbols) == len(symbol_set):
                            break
    except Exception as e:
        print(f"[WARN] Failed to load {filename}: {e}")
    return bars

def replay_minute(symbol, ts, open_price, close_price, volume, trades, vwap, thresholds):
    """Replay a single minute bar through detection logic with injected thresholds."""
    # Aggregate the minute data
    minute_ts = get_minute_ts(ts)
    agg = minute_aggregates[minute_ts][symbol]
    if agg['open'] is None:
        agg['open'] = open_price
    agg['close'] = close_price
    agg['high'] = max(agg.get('high') or close_price, close_price)
    agg['low'] = min(agg.get('low') or close_price, close_price) if agg.get('low') else close_price
    agg['volume'] = volume
    agg['value'] = volume * vwap
    agg['count'] = trades
    agg['vwap'] = vwap

    pct_change = ((close_price - open_price) / open_price) * 100 if open_price > 0 else 0

    # SIMPLIFIED DETECTION LOGIC WITH INJECTED THRESHOLDS
    # Extract grid search parameters
    pct_thresh_early = thresholds['pct_thresh_early']
    min_rel_vol_stage1 = thresholds['min_rel_vol_stage1']
    pct_thresh_confirm = thresholds['pct_thresh_confirm']
    min_rel_vol_stage2 = thresholds['min_rel_vol_stage2']
    
    # Calculate relative volume
    vols = rolling_volume_3min.get(symbol, [0, 0, 0])
    vol_prev_avg = sum(vols) / max(len(vols), 1)
    rel_vol = volume / max(vol_prev_avg, 1)
    
    # Stage 1: Early Detection - Setup flag
    stage1_pass = (
        rel_vol >= min_rel_vol_stage1 and
        pct_change >= pct_thresh_early and
        trades >= 3
    )
    
    if stage1_pass and symbol not in momentum_flags:
        # Determine session based on timestamp (ts is already a datetime object)
        if isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.fromtimestamp(ts / 1e9, tz=timezone.utc).astimezone(ZoneInfo("America/New_York"))
        
        time_num = dt.hour * 100 + dt.minute
        if time_num < 930:
            session = 'PREMARKET'
        elif time_num >= 1600:
            session = 'POSTMARKET'
        else:
            session = 'REGULAR'
        
        momentum_flags[symbol] = {
            'flag': f'SETUP_{symbol}',
            'time': ts,
            'setup_price': close_price,
            'setup_volume': volume,
            'flag_minute': minute_ts,
            'session': session,
            'quality_score': 60
        }
    
    # Stage 2: Confirmed Breakout
    flag_data = momentum_flags.get(symbol)
    if flag_data:
        setup_price = flag_data.get('setup_price', open_price)
        price_expansion_pct = ((close_price - setup_price) / setup_price) * 100 if setup_price > 0 else 0
        
        # Simple confirmation: expansion meets threshold and volume sustained
        stage2_pass = (
            price_expansion_pct >= (pct_thresh_confirm - pct_thresh_early) and
            rel_vol >= min_rel_vol_stage2 and
            volume >= flag_data.get('setup_volume', 0) * 0.5
        )
        
        if stage2_pass:
            breakout_quality[symbol] = {
                'quality': 70,  # Simplified quality score
                'timestamp': ts,
                'expansion_pct': price_expansion_pct,
                'entry_price': close_price  # Entry at current close
            }
            momentum_flags.pop(symbol, None)
    
    # Update rolling volume tracking for next iteration
    if symbol not in rolling_volume_3min:
        rolling_volume_3min[symbol] = []
    rolling_volume_3min[symbol].append(volume)
    if len(rolling_volume_3min[symbol]) > 3:
        rolling_volume_3min[symbol].pop(0)

def simulate_outcome(alert, future_bars):
    """Simulate trade outcome (stop/target/timeout) given future minute bars.
    Returns: ('stop'|'target'|'timeout', gain_pct, minutes_held)
    """
    entry = alert.entry_price
    stop_price = entry * (1 - STOP_LOSS_PCT)
    target_price = entry * (1 + TARGET_PCT)
    for i, (ts, o, c, h, l, v, t, vw) in enumerate(future_bars, start=1):
        # Check if low touched stop or high touched target
        if l <= stop_price:
            return 'stop', -STOP_LOSS_PCT * 100, i
        if h >= target_price:
            return 'target', TARGET_PCT * 100, i
        if i >= TIMEOUT_MINUTES:
            gain = ((c - entry) / entry) * 100
            return 'timeout', gain, i
    # End of data
    gain = ((future_bars[-1][2] - entry) / entry) * 100 if future_bars else 0
    return 'timeout', gain, len(future_bars)

def run_backtest(thresholds, dates, symbols):
    """Run backtest over specified dates and symbols with given threshold set.
    Returns: dict with metrics (alerts, win_rate, avg_gain, max_gain, max_loss, etc.)
    """
    clear_state()
    alerts = []
    all_bars = {}  # {symbol: [(ts, o, c, h, l, v, t, vw), ...]} across all dates

    # Load all date files
    for date_str in dates:
        print(f"  Loading {date_str}...", end='', flush=True)
        bars = load_minute_flatfiles(date_str, symbols)
        print(f" {sum(len(b) for b in bars.values())} bars")
        for sym, data in bars.items():
            all_bars.setdefault(sym, []).extend(data)

    # Sort bars chronologically per symbol
    for sym in all_bars:
        all_bars[sym].sort(key=lambda x: x[0])

    # Replay bars in global chronological order
    all_events = []
    for sym, bars in all_bars.items():
        for bar in bars:
            all_events.append((bar[0], sym, bar))
    all_events.sort(key=lambda x: x[0])

    for ts, sym, (bar_ts, o, c, h, l, v, t, vw) in all_events:
        replay_minute(sym, bar_ts, o, c, v, t, vw, thresholds)
        # Check for new Stage1 or Stage2 alerts
        # Stage1: momentum_flags added
        if sym in momentum_flags and momentum_flags[sym].get('flag') == f'SETUP_{sym}':
            flag = momentum_flags[sym]
            # Record only once per flag (avoid duplicates)
            if not any(a.symbol == sym and a.timestamp == flag['time'] for a in alerts):
                alerts.append(AlertRecord(
                    symbol=sym,
                    timestamp=flag['time'],
                    entry_price=flag['setup_price'],
                    session=flag['session'],
                    quality=flag.get('quality_score', 0),
                    stage=1
                ))
        # Stage2: breakout_quality added
        if sym in breakout_quality:
            bq = breakout_quality[sym]
            if not any(a.symbol == sym and a.timestamp == bq['timestamp'] and a.stage == 2 for a in alerts):
                # Find setup price from flag or approximate
                setup_price = bq.get('entry_price', c)  # fallback to close if missing
                alerts.append(AlertRecord(
                    symbol=sym,
                    timestamp=bq['timestamp'],
                    entry_price=setup_price,
                    session='UNKNOWN',  # derive if needed
                    quality=bq['quality'],
                    stage=2
                ))

    # Simulate outcomes for each alert
    outcomes = []
    for alert in alerts:
        sym = alert.symbol
        alert_idx = next((i for i, (ts, s, _) in enumerate(all_events) if s == sym and ts >= alert.timestamp), None)
        if alert_idx is None:
            continue
        future = [all_events[i][2] for i in range(alert_idx+1, len(all_events)) if all_events[i][1] == sym]
        if not future:
            continue
        outcome_type, gain, minutes = simulate_outcome(alert, future)
        outcomes.append({
            'symbol': sym,
            'timestamp': alert.timestamp,
            'stage': alert.stage,
            'quality': alert.quality,
            'outcome': outcome_type,
            'gain_pct': gain,
            'minutes_held': minutes
        })

    # Calculate metrics
    total = len(outcomes)
    if total == 0:
        return {
            'alerts': 0, 'stage1': 0, 'stage2': 0,
            'win_rate': 0, 'avg_gain': 0, 'max_gain': 0, 'max_loss': 0,
            'avg_hold_time': 0, 'stops': 0, 'targets': 0, 'timeouts': 0
        }
    
    stage1_count = sum(1 for o in outcomes if o['stage'] == 1)
    stage2_count = sum(1 for o in outcomes if o['stage'] == 2)
    wins = sum(1 for o in outcomes if o['gain_pct'] > 0)
    avg_gain = sum(o['gain_pct'] for o in outcomes) / total
    max_gain = max((o['gain_pct'] for o in outcomes), default=0)
    max_loss = min((o['gain_pct'] for o in outcomes), default=0)
    avg_hold = sum(o['minutes_held'] for o in outcomes) / total
    stops = sum(1 for o in outcomes if o['outcome'] == 'stop')
    targets = sum(1 for o in outcomes if o['outcome'] == 'target')
    timeouts = sum(1 for o in outcomes if o['outcome'] == 'timeout')
    
    return {
        'alerts': total,
        'stage1': stage1_count,
        'stage2': stage2_count,
        'win_rate': (wins / total) * 100,
        'avg_gain': avg_gain,
        'max_gain': max_gain,
        'max_loss': max_loss,
        'avg_hold_time': avg_hold,
        'stops': stops,
        'targets': targets,
        'timeouts': timeouts
    }

def main():
    """Run grid search over all parameter combinations and output results."""
    print("=== Grid Search for Optimal Detection Thresholds ===")
    
    # Load tickers
    symbols = read_tickers(TICKER_FILE)
    if not symbols:
        print("[WARN] No tickers loaded. Ensure data/tickers.csv exists.")
        sys.exit(1)
    print(f"[OK] Loaded {len(symbols)} symbols")

    # Define date range (last 9 days for quick test; expand for production)
    end_date = datetime.now()
    dates = [(end_date - timedelta(days=i)).strftime('%Y%m%d') for i in range(9)]
    print(f"[OK] Testing over {len(dates)} days: {dates[0]} to {dates[-1]}")

    # Check data availability
    available = []
    for d in dates:
        # Try both formats: YYYY-MM-DD.csv.gz and minute_bars_YYYYMMDD.json.gz
        filename1 = DATA_DIR / f"{d[:4]}-{d[4:6]}-{d[6:]}.csv.gz"
        filename2 = DATA_DIR / f"minute_bars_{d}.json.gz"
        if filename1.exists() or filename2.exists():
            available.append(d)
    
    if not available:
        print(f"[WARN] No flatfiles found in {DATA_DIR}. Generate them first with data ingestion script.")
        sys.exit(1)
    print(f"[OK] Found {len(available)} data files")
    
    # Generate all combinations
    keys = list(GRID.keys())
    values = [GRID[k] for k in keys]
    combinations = list(itertools.product(*values))
    print(f"[OK] Testing {len(combinations)} parameter combinations")

    # Run grid search
    results = []
    for i, combo in enumerate(combinations, 1):
        thresholds = dict(zip(keys, combo))
        print(f"\n[{i}/{len(combinations)}] Testing: {thresholds}")
        metrics = run_backtest(thresholds, available, symbols[:10])  # limit to 10 symbols for speed
        results.append({**thresholds, **metrics})
        print(f"  → Alerts: {metrics['alerts']} | Win Rate: {metrics['win_rate']:.1f}% | Avg Gain: {metrics['avg_gain']:.2f}%")

    # Write results to CSV
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = RESULTS_DIR / f"grid_search_{timestamp}.csv"
    with open(output_file, 'w') as f:
        header = list(results[0].keys())
        f.write(','.join(header) + '\n')
        for r in results:
            f.write(','.join(str(r[k]) for k in header) + '\n')
    print(f"\n[OK] Results saved to {output_file}")
    
    # Show diversity statistics
    print("\n=== Results Diversity ===")
    alerts_range = [r['alerts'] for r in results]
    winrate_range = [r['win_rate'] for r in results if r['alerts'] > 0]
    gain_range = [r['avg_gain'] for r in results if r['alerts'] > 0]
    
    print(f"Alerts range: {min(alerts_range)} to {max(alerts_range)} (avg: {sum(alerts_range)/len(alerts_range):.1f})")
    if winrate_range:
        print(f"Win rate range: {min(winrate_range):.1f}% to {max(winrate_range):.1f}% (avg: {sum(winrate_range)/len(winrate_range):.1f}%)")
    if gain_range:
        print(f"Avg gain range: {min(gain_range):.2f}% to {max(gain_range):.2f}% (avg: {sum(gain_range)/len(gain_range):.2f}%)")
    
    # Show top 5 by different metrics
    print("\n=== Top 5 by Win Rate (≥10 alerts) ===")
    valid_by_wr = sorted([r for r in results if r['alerts'] >= 10], key=lambda x: x['win_rate'], reverse=True)[:5]
    for i, r in enumerate(valid_by_wr, 1):
        print(f"{i}. WR={r['win_rate']:.1f}% Alerts={r['alerts']} AvgGain={r['avg_gain']:.2f}% | early={r['pct_thresh_early']} relvol1={r['min_rel_vol_stage1']} confirm={r['pct_thresh_confirm']}")
    
    print("\n=== Top 5 by Alert Count ===")
    top_by_alerts = sorted(results, key=lambda x: x['alerts'], reverse=True)[:5]
    for i, r in enumerate(top_by_alerts, 1):
        print(f"{i}. Alerts={r['alerts']} WR={r['win_rate']:.1f}% AvgGain={r['avg_gain']:.2f}% | early={r['pct_thresh_early']} relvol1={r['min_rel_vol_stage1']}")

    # Find best combination (highest win rate with >10 alerts)
    valid = [r for r in results if r['alerts'] >= 10]
    if not valid:
        print("[WARN] No combinations produced >=10 alerts. Consider widening grid ranges.")
        return
    
    best = max(valid, key=lambda x: (x['win_rate'], x['avg_gain']))
    print("\n=== Best Configuration ===")
    for k in keys:
        print(f"  {k}: {best[k]}")
    print(f"\nPerformance:")
    print(f"  Alerts: {best['alerts']} (Stage1: {best['stage1']}, Stage2: {best['stage2']})")
    print(f"  Win Rate: {best['win_rate']:.2f}%")
    print(f"  Avg Gain: {best['avg_gain']:.2f}%")
    print(f"  Max Gain: {best['max_gain']:.2f}%")
    print(f"  Max Loss: {best['max_loss']:.2f}%")
    print(f"  Avg Hold: {best['avg_hold_time']:.1f} minutes")
    print(f"  Outcomes: {best['targets']} targets, {best['stops']} stops, {best['timeouts']} timeouts")

if __name__ == "__main__":
    main()
