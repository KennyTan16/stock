"""Expectation Builder

Reads cached Polygon flatfiles in historical_data/polygon_flatfiles and derives
expected alert trigger moments for Watch (Stage0), Setup (Stage1), and Confirmation (Stage2 primary/alt)
using the current threshold philosophy. Produces a consolidated JSON file:
  results/alert_expectations.json

Purpose:
  Provide a ground-truth style reference of when alerts *should* fire given
  objective threshold checks, enabling fine-tuning and replay validation without
  re-running full WebSocket detection for every iteration.

Method:
  - Iterate symbol-day bars from compressed flatfiles (*.csv.gz)
  - Maintain rolling 3-min volume for relative volume calculations
  - Compute per-minute percent change (open->close)
  - Classify session (PREMARKET / REGULAR / POSTMARKET) from timestamp hour
  - Apply Watch (Stage0) thresholds first; record earliest watch per symbol-day
  - Apply Stage1 thresholds; once setup flagged capture setup context
  - Track minutes since setup; evaluate both primary Stage2 breakout and
    alternative consolidation confirmation window.
  - Stop after first Stage2 (primary or alt) confirmation.

Output record fields:
  symbol, date, minute_ts (ISO), stage_expected (0/1/2), confirmation_type,
  session, pct_change, rel_vol, volume, trades, setup_price, expansion_pct,
  volume_sustained, acceleration, reason_flags (list of strings)

Threshold Source:
  Mirrors values currently embedded in polygon_websocket.check_spike (balanced-quality
  broadened thresholds) for consistency.

Usage:
  python expectation_builder.py  (from project root or backtest directory)

"""
from __future__ import annotations
import os, csv, gzip, json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path

# Robust Eastern Time fallback (align with polygon_websocket)
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo('America/New_York')
except Exception:
    try:
        import pytz
        ET = pytz.timezone('US/Eastern')
    except Exception:
        ET = timezone(timedelta(hours=-5))  # Fixed offset fallback

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FLATFILES_DIR = PROJECT_ROOT / 'historical_data' / 'polygon_flatfiles'
TICKERS_PATH_PRIMARY = PROJECT_ROOT / 'data' / 'tickers.csv'
TICKERS_PATH_FALLBACK = PROJECT_ROOT / 'tickers.csv'
OUTPUT_PATH = PROJECT_ROOT / 'results' / 'alert_expectations.json'
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Threshold profiles replicating polygon_websocket balanced broadened set
# Each session: vol_thresh, spread_limit, pct_thresh_early, pct_thresh_confirm,
#               min_rel_vol_stage1, min_rel_vol_stage2, watch_rel_vol, watch_pct
SESSION_THRESHOLDS = {
    'PREMARKET':  dict(vol_thresh=30000, spread_limit=0.030, pct_thresh_early=3.8, pct_thresh_confirm=7.8,
                       min_rel_vol_stage1=2.4, min_rel_vol_stage2=4.1, watch_rel_vol=1.8, watch_pct=2.5),
    'REGULAR':    dict(vol_thresh=90000, spread_limit=0.020, pct_thresh_early=4.5, pct_thresh_confirm=7.8,
                       min_rel_vol_stage1=2.5, min_rel_vol_stage2=4.3, watch_rel_vol=2.0, watch_pct=3.0),
    'POSTMARKET': dict(vol_thresh=24000, spread_limit=0.038, pct_thresh_early=3.8, pct_thresh_confirm=7.0,
                       min_rel_vol_stage1=2.3, min_rel_vol_stage2=4.0, watch_rel_vol=1.7, watch_pct=2.5)
}

MIN_TRADES_STAGE1 = 3
MIN_QUALITY_STAGE1 = 50.0  # align with polygon_websocket Stage1 gate
MAX_STAGE1_CANDIDATES = 2   # allow up to two qualifying Stage1 minutes for tolerance

# Simple utility to classify session by hour (Eastern)
def classify_session(dt: datetime) -> str:
    h = dt.hour
    m = dt.minute
    if 4 <= h < 9 or (h == 9 and m < 30):
        return 'PREMARKET'
    if (h == 9 and m >= 30) or (9 < h < 16):
        return 'REGULAR'
    if 16 <= h < 20:
        return 'POSTMARKET'
    return 'CLOSED'


def read_tickers() -> set[str]:
    path = TICKERS_PATH_PRIMARY if TICKERS_PATH_PRIMARY.exists() else TICKERS_PATH_FALLBACK
    tickers = set()
    if not path.exists():
        print(f"[WARN] Tickers file missing at {path}; proceeding with empty set.")
        return tickers
    with open(path, 'r') as f:
        for row in csv.reader(f):
            if row:
                t = row[0].strip().upper()
                if t and t != 'SYMBOL' and t != 'TICKER':
                    tickers.add(t)
    print(f"[INFO] Loaded {len(tickers)} tickers for expectation scan")
    return tickers


def parse_flatfile(path: Path, ticker_set: set[str]):
    bars_by_symbol = defaultdict(list)
    with gzip.open(path, 'rt') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row['ticker']
            if sym not in ticker_set:  # filter only monitored tickers
                continue
            ts_ns = int(row['window_start'])
            # Convert via UTC then to Eastern to respect DST
            ts_utc = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=timezone.utc)
            ts = ts_utc.astimezone(ET)
            bar = dict(
                symbol=sym,
                timestamp=ts,
                open=float(row['open']),
                close=float(row['close']),
                high=float(row['high']),
                low=float(row['low']),
                volume=int(row['volume']),
                trades=int(row.get('transactions', 0)),
            )
            bars_by_symbol[sym].append(bar)
    for sym in bars_by_symbol:
        bars_by_symbol[sym].sort(key=lambda b: b['timestamp'])
    return bars_by_symbol


def build_expectations():
    tickers = read_tickers()
    flatfiles = sorted(FLATFILES_DIR.glob('*.csv.gz'))
    if not flatfiles:
        print(f"[ERROR] No flatfiles found in {FLATFILES_DIR}")
        return []
    expectations = []
    for fp in flatfiles:
        raw_stem = fp.stem  # e.g. '2025-10-24.csv'
        date_str = raw_stem.replace('.csv', '')  # normalize to '2025-10-24'
        print(f"[SCAN] {date_str}")
        bars_by_symbol = parse_flatfile(fp, tickers)
        for symbol, bars in bars_by_symbol.items():
            # Rolling 3-minute volume window for rel_vol (average of previous 3 completed minutes)
            rolling_vol = []  # maintain last up to 3 volumes
            setup_flag = None  # dict capturing setup context
            stage1_minutes = []  # record multiple stage1 candidate minutes (up to limit)
            watch_minutes = []  # record multiple watch minutes until setup
            confirmed = False
            for i, bar in enumerate(bars):
                dt = bar['timestamp']
                session = classify_session(dt)
                if session == 'CLOSED':
                    continue
                cfg = SESSION_THRESHOLDS[session]
                # percent change open->close
                pct_change = ((bar['close'] - bar['open']) / bar['open']) * 100 if bar['open'] > 0 else 0
                # rel_vol (current volume divided by mean of rolling_vol) using previous 3 minutes only
                prev_avg = (sum(rolling_vol) / len(rolling_vol)) if rolling_vol else 1
                rel_vol = bar['volume'] / prev_avg if prev_avg > 0 else 0
                prev_minute_vol = rolling_vol[-1] if rolling_vol else 0  # for decline & alt volume checks
                # Update rolling AFTER computing rel_vol for this minute
                rolling_vol.append(bar['volume'])
                if len(rolling_vol) > 3:
                    rolling_vol.pop(0)
                reason_flags = []
                # Volume decline flag (mirror polygon logic threshold 40%)
                vol_declining = prev_minute_vol > 0 and bar['volume'] < prev_minute_vol * 0.4

                # Stage0 (Watch) expectation - accumulate until Stage1 appears
                if (setup_flag is None and rel_vol >= cfg['watch_rel_vol'] and pct_change >= cfg['watch_pct']
                        and bar['trades'] >= 2):
                    watch_minutes.append(dt)
                    expectations.append({
                        'symbol': symbol,
                        'date': date_str,
                        'minute_ts': dt.isoformat(),
                        'stage_expected': 0,
                        'confirmation_type': None,
                        'session': session,
                        'pct_change': round(pct_change, 3),
                        'rel_vol': round(rel_vol, 3),
                        'volume': bar['volume'],
                        'trades': bar['trades'],
                        'setup_price': None,
                        'expansion_pct': None,
                        'volume_sustained': None,
                        'acceleration': None,
                        'reason_flags': ['watch_thresholds']
                    })

                # Stage1 (Setup) with quality & decline gating
                if setup_flag is None:
                    stage1_thresholds_pass = (rel_vol >= cfg['min_rel_vol_stage1'] and pct_change >= cfg['pct_thresh_early']
                                              and bar['trades'] >= MIN_TRADES_STAGE1 and not vol_declining)
                    if stage1_thresholds_pass:
                        # Compute crude quality score (spread unavailable -> partial credit)
                        # Re-use weighting approximations from polygon (simplified inline)
                        # Relative volume component (cap at 8x)
                        rel_vol_capped = min(rel_vol, 8)
                        quality = (rel_vol_capped / 8) * 28
                        pct_capped = min(abs(pct_change), 14)
                        quality += (pct_capped / 14) * 18
                        if cfg['vol_thresh'] > 0:
                            vol_ratio = min(bar['volume'] / cfg['vol_thresh'], 2)
                            quality += (vol_ratio / 2) * 14
                        trade_ratio = min(bar['trades'] / max(MIN_TRADES_STAGE1, 1), 3)
                        quality += (trade_ratio / 3) * 12
                        quality += 5  # spread unknown partial credit
                        # No expansion yet
                        quality = max(0, min(round(quality, 1), 100))
                        if quality >= MIN_QUALITY_STAGE1:
                            stage1_minutes.append(dt)
                            if len(stage1_minutes) == 1:
                                setup_flag = dict(time=dt, price=bar['close'], volume=bar['volume'])
                            if len(stage1_minutes) <= MAX_STAGE1_CANDIDATES:
                                expectations.append({
                                    'symbol': symbol,
                                    'date': date_str,
                                    'minute_ts': dt.isoformat(),
                                    'stage_expected': 1,
                                    'confirmation_type': None,
                                    'session': session,
                                    'pct_change': round(pct_change, 3),
                                    'rel_vol': round(rel_vol, 3),
                                    'volume': bar['volume'],
                                    'trades': bar['trades'],
                                    'setup_price': round(stage1_minutes[0] == dt and bar['close'] or setup_flag['price'], 4),
                                    'expansion_pct': 0.0,
                                    'volume_sustained': None,
                                    'acceleration': None,
                                    'reason_flags': ['stage1_thresholds', 'candidate' if len(stage1_minutes) > 1 else 'primary', f'quality={quality}']
                                })
                        else:
                            reason_flags.append('quality_gate_failed')

                # Stage2 (Confirmation) primary or alt with stricter parity to live logic
                if setup_flag and not confirmed:
                    minutes_since = (dt - setup_flag['time']).total_seconds() / 60.0
                    expansion_pct = ((bar['close'] - setup_flag['price']) / setup_flag['price']) * 100 if setup_flag['price'] > 0 else 0
                    volume_sustained = bar['volume'] >= setup_flag['volume'] * 0.5
                    acceleration = rel_vol >= (cfg['min_rel_vol_stage2'] - 0.3 if expansion_pct >= 1.2 else cfg['min_rel_vol_stage2'])
                    primary_pass = (pct_change >= cfg['pct_thresh_confirm'] and bar['volume'] >= cfg['vol_thresh'] * 0.85
                                    and acceleration and expansion_pct >= 0.5 and volume_sustained and bar['trades'] >= int(MIN_TRADES_STAGE1 * 1.1))
                    # Alt path parity adjustments: retrace, previous minute volume checks
                    alt_pass = False
                    prev_minute_volume_for_alt = bars[i-1]['volume'] if i > 0 else 0
                    retrace_ok = bar['close'] >= setup_flag['price'] * 0.985
                    alt_volume_ok = (bar['volume'] >= setup_flag['volume'] * 0.6) and (prev_minute_volume_for_alt >= setup_flag['volume'] * 0.5)
                    if (not primary_pass and 2 <= minutes_since <= 3 and expansion_pct >= 0.3
                            and pct_change >= (cfg['pct_thresh_early'] + 0.5)
                            and volume_sustained and rel_vol >= (cfg['min_rel_vol_stage1'] + 0.3)
                            and retrace_ok and alt_volume_ok):
                        alt_pass = True
                    if primary_pass or alt_pass:
                        # Compute confirmation quality gate (reuse simplified model)
                        rel_vol_capped = min(rel_vol, 8)
                        quality = (rel_vol_capped / 8) * 28
                        pct_capped = min(abs(pct_change), 14)
                        quality += (pct_capped / 14) * 18
                        if cfg['vol_thresh'] > 0:
                            vol_ratio = min(bar['volume'] / cfg['vol_thresh'], 2)
                            quality += (vol_ratio / 2) * 14
                        trade_ratio = min(bar['trades'] / max(MIN_TRADES_STAGE1, 1), 3)
                        quality += (trade_ratio / 3) * 12
                        quality += 5  # spread unknown partial credit
                        # Expansion & follow-through
                        follow_components = 0.0
                        if expansion_pct >= 0.6:
                            follow_components += min(expansion_pct / 6, 0.6)
                        if acceleration:
                            follow_components += 0.3
                        if volume_sustained:
                            follow_components += 0.3
                        follow_components = min(follow_components, 1.0)
                        quality += follow_components * 18
                        # Parabolic penalty
                        if pct_change >= 11 and not volume_sustained:
                            excess = min(pct_change - 11, 6)
                            quality -= (excess / 6) * 6
                        quality = max(0, min(round(quality, 1), 100))
                        min_gate = 60 if primary_pass else 58
                        if quality < min_gate:
                            reason_flags.append('stage2_quality_gate_failed')
                        else:
                            confirmation_type = 'primary' if primary_pass else 'alt'
                            expectations.append({
                                'symbol': symbol,
                                'date': date_str,
                                'minute_ts': dt.isoformat(),
                                'stage_expected': 2,
                                'confirmation_type': confirmation_type,
                                'session': session,
                                'pct_change': round(pct_change, 3),
                                'rel_vol': round(rel_vol, 3),
                                'volume': bar['volume'],
                                'trades': bar['trades'],
                                'setup_price': round(setup_flag['price'], 4),
                                'expansion_pct': round(expansion_pct, 3),
                                'volume_sustained': volume_sustained,
                                'acceleration': acceleration,
                                'reason_flags': ['stage2_' + confirmation_type, f'quality={quality}']
                            })
                            confirmed = True
                            # No further confirmations for this symbol-day

    return expectations


def main():
    expectations = build_expectations()
    if not expectations:
        print('[DONE] No expectations generated.')
        return
    with open(OUTPUT_PATH, 'w') as f:
        json.dump({'generated_at': datetime.utcnow().isoformat() + 'Z',
                   'count': len(expectations),
                   'records': expectations}, f, indent=2)
    print(f"[OK] Wrote {len(expectations)} expectation records -> {OUTPUT_PATH}")
    # Quick summary stats
    stage_counts = defaultdict(int)
    for r in expectations:
        stage_counts[r['stage_expected']] += 1
    print('[SUMMARY] Stage counts:', dict(stage_counts))

if __name__ == '__main__':
    main()
