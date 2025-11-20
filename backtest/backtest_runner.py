"""Synthetic backtest harness to validate revised Stage2 logic.
Generates a simple sequence of minute bars for a single symbol to
force Stage1 setup then Stage2 confirmation using cumulative expansion & volume.

Usage:
  SET STAGE2_DEBUG=1
  SET DISABLE_NOTIFICATIONS=1
  python backtest_runner.py

This is NOT a historical data replay. Replace the synthetic scenario list with
real minute-by-minute trade events for production backtesting.
"""
import os
import math
from datetime import datetime, timedelta
from collections import namedtuple

# Ensure debug & notification suppression defaults for harness
os.environ.setdefault("STAGE2_DEBUG", "1")
os.environ.setdefault("DISABLE_NOTIFICATIONS", "1")

from polygon_websocket import (
    check_spike,
    momentum_flags,
    breakout_quality,
    minute_aggregates,
    rolling_volume_3min,
    get_minute_ts,
    ET_TIMEZONE,
)

ScenarioMinute = namedtuple("ScenarioMinute", ["offset_min", "open", "close", "volume", "trades"])  # simple model

# Construct a scenario:
# Minute 0: strong early spike to trigger Stage1 (premarket thresholds assumed)
# Minute 1: modest follow-through to build cumulative expansion & volume
# Minute 2: further consolidation + slight uptick satisfying Stage2 gates
# Feel free to tweak prices/volumes if Stage2 does not trigger.
SCENARIO = [
    ScenarioMinute(0, 1.00, 1.052, 42000, 6),   # ~5.2% minute change, > vol_thresh(30k) triggers Stage1
    ScenarioMinute(1, 1.052, 1.060, 23000, 5),  # +0.76% expansion from setup price, adds volume
    ScenarioMinute(2, 1.060, 1.082, 25000, 6),  # cumulative expansion > 8% from setup; cumulative volume > setup*1.25 should confirm Stage2
]

SYMBOL = "TEST"
START_DT = datetime.now(ET_TIMEZONE).replace(hour=5, minute=0, second=0, microsecond=0)  # premarket

# Helper to simulate trades within a minute
def simulate_minute(minute: ScenarioMinute):
    minute_dt = START_DT + timedelta(minutes=minute.offset_min)
    minute_ts = minute_dt.replace(second=0, microsecond=0)

    # Split volume into trades (uniform sizes for simplicity)
    trade_size = max(1, minute.volume // minute.trades)
    remaining = minute.volume

    # Linear price path from open to close across trades
    price_step = (minute.close - minute.open) / max(minute.trades, 1)
    current_price = minute.open

    for i in range(minute.trades):
        size = trade_size if remaining >= trade_size else remaining
        timestamp_ms = int(minute_ts.timestamp() * 1000)
        # We call update_aggregates through check_spike side-effects by emulating trades:
        # Build a synthetic per-minute percentage change using open->close delta; we pass 'open_price' and 'close_price' as current price.
        # However check_spike relies on update_aggregates having been called via handle_msg. We reproduce minimal aggregate effect manually.
        # Direct aggregate manipulation:
        agg = minute_aggregates[minute_ts][SYMBOL]
        if agg['open'] is None:
            agg['open'] = current_price
        agg['close'] = current_price
        if agg['high'] is None or current_price > agg['high']:
            agg['high'] = current_price
        if agg['low'] is None or current_price < agg['low']:
            agg['low'] = current_price
        agg['volume'] += size
        agg['value'] += current_price * size
        agg['count'] += 1
        vwap = agg['value'] / agg['volume'] if agg['volume'] > 0 else current_price
        pct_change = 0
        if agg['open'] and agg['open'] > 0:
            pct_change = ((agg['close'] - agg['open']) / agg['open']) * 100
        # Invoke spike logic each trade
        check_spike(
            SYMBOL,
            pct_change,
            agg['volume'],
            minute_ts,
            agg['open'],
            agg['close'],
            agg['count'],
            vwap,
        )
        current_price += price_step
        remaining -= size

    # After minute completes, update rolling volume window
    vols = rolling_volume_3min[SYMBOL]
    vols[0] = vols[1]
    vols[1] = vols[2]
    vols[2] = minute.volume


def run_scenario():
    print("=== Synthetic Backtest Start ===")
    for m in SCENARIO:
        simulate_minute(m)
    print("=== Synthetic Backtest End ===")
    print("Momentum Flags Remaining:", momentum_flags)
    print("Breakout Quality Map:")
    for sym, data in breakout_quality.items():
        print(f"  {sym}: {data}\n")
    if SYMBOL not in breakout_quality:
        print("[WARN] Stage2 did not confirm in synthetic scenario; consider tweaking volumes or expansion.")

if __name__ == "__main__":
    run_scenario()
