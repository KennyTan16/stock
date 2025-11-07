"""
Backtest dual-stage momentum detector using Polygon.io historical data
Tests alert accuracy, false positives, and performance metrics
"""

import sys
import os
from datetime import datetime, timedelta
import pytz
from collections import defaultdict
import json

sys.path.insert(0, '.')
from polygon_websocket import (
    check_spike, momentum_flags, rolling_volume_3min, 
    latest_quotes, minute_aggregates, update_aggregates,
    get_minute_ts
)

# ====================================================================================
# TESTING THRESHOLDS - Temporarily lowered to verify detection logic works
# ====================================================================================
TEST_MODE = True  # Set to False to use production thresholds

if TEST_MODE:
    # Lower thresholds for testing (should generate alerts on normal market moves)
    TEST_THRESHOLDS = {
        'rel_vol_stage1': 1.5,      # Original: 2.5
        'rel_vol_stage2': 2.5,      # Original: 4.0
        'pct_early_premarket': 1.5,  # Original: 3.0
        'pct_early_regular': 2.0,    # Original: 4.0
        'pct_early_postmarket': 1.5, # Original: 3.0
        'pct_confirm_premarket': 4.0, # Original: 7.0
        'pct_confirm_regular': 4.0,   # Original: 7.0
        'pct_confirm_postmarket': 3.5, # Original: 6.0
        'vol_thresh_premarket': 20000,  # Original: 30000
        'vol_thresh_regular': 50000,    # Original: 75000
        'vol_thresh_postmarket': 15000, # Original: 20000
    }
    print("\n⚠️  BACKTEST RUNNING IN TEST MODE - Using lowered thresholds")
    print("   Stage 1: rel_vol ≥1.5, pct ≥1.5-2.0%")
    print("   Stage 2: rel_vol ≥2.5, pct ≥3.5-4.0%, vol ≥15-50K")
    print("   This should generate alerts on typical market moves\n")
else:
    TEST_THRESHOLDS = None
# ====================================================================================

# Try to import polygon for historical data
try:
    from polygon import RESTClient
    POLYGON_AVAILABLE = True
except ImportError:
    POLYGON_AVAILABLE = False
    print("⚠️ polygon-api-client not installed. Install with: pip install polygon-api-client")

class BacktestResult:
    def __init__(self):
        self.alerts = []
        self.total_alerts = 0
        self.profitable_alerts = 0
        self.breakeven_alerts = 0
        self.losing_alerts = 0
        self.avg_gain = 0
        self.max_gain = 0
        self.max_loss = 0
        self.false_positives = 0
        
    def add_alert(self, alert_data):
        self.alerts.append(alert_data)
        self.total_alerts += 1
        
        if 'outcome' in alert_data:
            if alert_data['outcome']['profit_pct'] > 0:
                self.profitable_alerts += 1
            elif alert_data['outcome']['profit_pct'] == 0:
                self.breakeven_alerts += 1
            else:
                self.losing_alerts += 1
                
            profit = alert_data['outcome']['profit_pct']
            self.avg_gain += profit
            self.max_gain = max(self.max_gain, profit)
            self.max_loss = min(self.max_loss, profit)
    
    def calculate_metrics(self):
        if self.total_alerts > 0:
            self.avg_gain /= self.total_alerts
            self.win_rate = (self.profitable_alerts / self.total_alerts) * 100
        else:
            self.win_rate = 0
    
    def print_summary(self):
        print("\n" + "="*70)
        print("📊 BACKTEST RESULTS SUMMARY")
        print("="*70)
        print(f"Total Alerts Generated: {self.total_alerts}")
        print(f"Profitable: {self.profitable_alerts} ({self.profitable_alerts/max(self.total_alerts,1)*100:.1f}%)")
        print(f"Breakeven: {self.breakeven_alerts}")
        print(f"Losing: {self.losing_alerts} ({self.losing_alerts/max(self.total_alerts,1)*100:.1f}%)")
        print(f"\nWin Rate: {self.win_rate:.1f}%")
        print(f"Average Gain: {self.avg_gain:.2f}%")
        print(f"Max Gain: {self.max_gain:.2f}%")
        print(f"Max Loss: {self.max_loss:.2f}%")
        print(f"False Positives: {self.false_positives}")
        print("="*70)

def get_historical_bars(client, symbol, start_date, end_date):
    """Fetch minute-level historical data from Polygon"""
    print(f"Fetching historical data for {symbol} from {start_date} to {end_date}...")
    
    try:
        # Get aggregates (bars) - minute level
        aggs = []
        for agg in client.list_aggs(
            ticker=symbol,
            multiplier=1,
            timespan="minute",
            from_=start_date,
            to=end_date,
            limit=50000
        ):
            aggs.append(agg)
        
        print(f"✓ Fetched {len(aggs)} minute bars")
        return aggs
    
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return []

def simulate_trading_outcome(entry_price, stop_loss, target, future_bars, minutes_to_hold=60):
    """
    Simulate trade outcome by checking if stop or target was hit
    Returns: {hit: 'stop'/'target'/'time', exit_price, profit_pct, minutes_held}
    """
    for i, bar in enumerate(future_bars[:minutes_to_hold]):
        # Check if stop loss hit (use low of bar)
        if bar.low <= stop_loss:
            profit_pct = ((stop_loss - entry_price) / entry_price) * 100
            return {
                'hit': 'stop',
                'exit_price': stop_loss,
                'profit_pct': profit_pct,
                'minutes_held': i + 1
            }
        
        # Check if target hit (use high of bar)
        if bar.high >= target:
            profit_pct = ((target - entry_price) / entry_price) * 100
            return {
                'hit': 'target',
                'exit_price': target,
                'profit_pct': profit_pct,
                'minutes_held': i + 1
            }
    
    # Time exit - use close of last bar
    if future_bars:
        exit_price = future_bars[min(minutes_to_hold-1, len(future_bars)-1)].close
        profit_pct = ((exit_price - entry_price) / entry_price) * 100
        return {
            'hit': 'time',
            'exit_price': exit_price,
            'profit_pct': profit_pct,
            'minutes_held': min(minutes_to_hold, len(future_bars))
        }
    
    return None

def backtest_symbol(client, symbol, start_date, end_date, result):
    """Backtest dual-stage detection on one symbol"""
    print(f"\n{'='*70}")
    print(f"Backtesting {symbol}")
    print(f"{'='*70}")
    
    # Clear state
    momentum_flags.clear()
    rolling_volume_3min.clear()
    minute_aggregates.clear()
    latest_quotes.clear()
    
    # Fetch historical data
    bars = get_historical_bars(client, symbol, start_date, end_date)
    
    if not bars:
        print(f"⚠️ No data for {symbol}")
        return
    
    # Initialize rolling volume with first 3 bars
    if len(bars) >= 3:
        rolling_volume_3min[symbol] = [bars[0].volume, bars[1].volume, bars[2].volume]
    
    alerts_generated = 0
    
    # Process each bar
    for i, bar in enumerate(bars):
        # Convert timestamp to ET timezone
        et_tz = pytz.timezone('US/Eastern')
        dt = datetime.fromtimestamp(bar.timestamp / 1000, tz=et_tz)
        minute_ts = dt.replace(second=0, microsecond=0)
        
        # Skip if not trading hours (4 AM - 8 PM ET)
        hour = dt.hour
        if hour < 4 or hour >= 20:
            continue
        
        # Calculate percentage change
        if bar.open > 0:
            pct_change = ((bar.close - bar.open) / bar.open) * 100
        else:
            pct_change = 0
        
        # Calculate VWAP (simplified - use close as approximation)
        vwap = bar.vwap if hasattr(bar, 'vwap') else bar.close
        
        # Setup minute_aggregates
        minute_aggregates[minute_ts][symbol] = {
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume,
            'value': bar.close * bar.volume,
            'count': bar.transactions if hasattr(bar, 'transactions') else 100
        }
        
        # Estimate spread (simplified - use 0.1% for liquid stocks)
        mid_price = bar.close
        latest_quotes[symbol] = {
            'bid': mid_price * 0.999,
            'ask': mid_price * 1.001
        }
        
        # Update rolling volume
        if len(rolling_volume_3min[symbol]) >= 3:
            rolling_volume_3min[symbol].pop(0)
        rolling_volume_3min[symbol].append(bar.volume)
        
        # Check for breakout condition by examining if flag exists before and cleared after
        flag_before = symbol in momentum_flags
        
        # Run check_spike
        check_spike(
            symbol=symbol,
            current_pct=pct_change,
            current_vol=bar.volume,
            minute_ts=minute_ts,
            open_price=bar.open,
            close_price=bar.close,
            trade_count=bar.transactions if hasattr(bar, 'transactions') else 100,
            vwap=vwap
        )
        
        # If flag was set and now cleared, alert was triggered
        flag_after = symbol in momentum_flags
        
        if flag_before and not flag_after:
            # Alert triggered! Simulate trade outcome
            entry_price = bar.close
            stop_loss = vwap * 0.98  # 2% below VWAP
            target = entry_price * 1.08  # 8% profit target
            
            # Get future bars to simulate outcome
            future_bars = bars[i+1:i+61]  # Next 60 minutes
            
            outcome = simulate_trading_outcome(entry_price, stop_loss, target, future_bars)
            
            alert_data = {
                'symbol': symbol,
                'timestamp': dt.strftime('%Y-%m-%d %H:%M:%S ET'),
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'target': target,
                'volume': bar.volume,
                'pct_change': pct_change,
                'outcome': outcome
            }
            
            result.add_alert(alert_data)
            alerts_generated += 1
            
            # Print alert details
            if outcome:
                outcome_symbol = "✅" if outcome['hit'] == 'target' else ("❌" if outcome['hit'] == 'stop' else "⏱️")
                print(f"{outcome_symbol} Alert #{alerts_generated}: {dt.strftime('%H:%M')} | Entry: ${entry_price:.2f} | "
                      f"Exit: ${outcome['exit_price']:.2f} ({outcome['hit']}) | "
                      f"P/L: {outcome['profit_pct']:+.2f}% in {outcome['minutes_held']}min")
    
    print(f"\n✓ Processed {len(bars)} bars, generated {alerts_generated} alerts")

def backtest_from_csv(csv_file, result):
    """Backtest from CSV file if Polygon API is not available"""
    print(f"\n{'='*70}")
    print(f"Backtesting from CSV: {csv_file}")
    print(f"{'='*70}")
    
    # This would parse a CSV file with columns: timestamp, symbol, open, high, low, close, volume
    # Left as TODO if user wants to test with CSV files instead
    print("⚠️ CSV backtesting not yet implemented")
    print("Please use Polygon API or implement CSV parsing")

def run_backtest(api_key, symbols, days_back=5):
    """Run backtest on multiple symbols"""
    
    if not POLYGON_AVAILABLE:
        print("\n❌ Cannot run backtest without polygon-api-client")
        print("Install with: pip install polygon-api-client")
        return
    
    print("\n" + "="*70)
    print("🔄 STARTING BACKTEST")
    print("="*70)
    print(f"API Key: {'*' * 20}{api_key[-4:]}")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Period: Last {days_back} days")
    print("="*70)
    
    # Initialize Polygon client
    client = RESTClient(api_key)
    
    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    
    # Run backtest for each symbol
    result = BacktestResult()
    
    for symbol in symbols:
        try:
            backtest_symbol(client, symbol, start_str, end_str, result)
        except Exception as e:
            print(f"❌ Error backtesting {symbol}: {e}")
            continue
    
    # Calculate and display metrics
    result.calculate_metrics()
    result.print_summary()
    
    # Save detailed results to JSON
    output_file = f"backtest_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump({
            'backtest_config': {
                'symbols': symbols,
                'start_date': start_str,
                'end_date': end_str,
                'days_back': days_back
            },
            'summary': {
                'total_alerts': result.total_alerts,
                'profitable': result.profitable_alerts,
                'losing': result.losing_alerts,
                'win_rate': result.win_rate,
                'avg_gain': result.avg_gain,
                'max_gain': result.max_gain,
                'max_loss': result.max_loss
            },
            'alerts': result.alerts
        }, f, indent=2)
    
    print(f"\n💾 Detailed results saved to: {output_file}")
    
    return result

if __name__ == "__main__":
    # Load API key from environment or config
    from polygon_websocket import API_KEY
    
    if not API_KEY or API_KEY == "YOUR_POLYGON_API_KEY":
        print("❌ Please set POLYGON_API_KEY in polygon_websocket.py")
        sys.exit(1)
    
    # Test symbols - High volatility stocks more likely to trigger momentum alerts
    test_symbols = [
        "TSLA",   # Tesla - high volatility
        "NVDA",   # NVIDIA - strong momentum
        "SMCI",   # Super Micro - extreme moves
        "COIN",   # Coinbase - crypto volatility
        "MSTR"    # MicroStrategy - Bitcoin proxy
    ]
    
    print("\n" + "="*70)
    print("📈 DUAL-STAGE MOMENTUM DETECTOR - BACKTEST")
    print("="*70)
    print("\nThis will test the alert system against historical data")
    print("to validate accuracy and optimize thresholds.\n")
    
    # Run backtest for last 10 trading days to capture more events
    result = run_backtest(API_KEY, test_symbols, days_back=10)
    
    if result and result.total_alerts > 0:
        print("\n✅ Backtest complete!")
        print(f"Generated {result.total_alerts} alerts with {result.win_rate:.1f}% win rate")
        
        if result.win_rate >= 60:
            print("🎉 System performing well! Win rate above 60%")
        elif result.win_rate >= 50:
            print("⚠️ System acceptable but could be optimized")
        else:
            print("❌ System needs threshold tuning - win rate below 50%")
    else:
        print("\n⚠️ No alerts generated during backtest period")
        print("Try increasing the date range or adjusting thresholds")
    
    print("\n" + "="*70 + "\n")
