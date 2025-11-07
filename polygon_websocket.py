"""
Simplified Polygon.io WebSocket Client for Pre-Market Data
Tracks OHLC data and sends Telegram alerts for significant price movements
"""

try:
    from polygon import WebSocketClient
    from polygon.websocket.models import Feed, Market
except Exception:
    # Lightweight stubs to allow offline/backtest usage without polygon package
    class WebSocketClient:
        def __init__(self, *args, **kwargs):
            pass
        def subscribe(self, *args, **kwargs):
            pass
        def run(self, handler):
            # In backtest harness we won't call run; live usage will error if polygon not installed.
            pass
    class Feed:
        RealTime = None
    class Market:
        Stocks = None
from datetime import datetime, timedelta
import sys
import csv
import requests
import time
import threading
import json
import os
from collections import defaultdict
try:
    from zoneinfo import ZoneInfo
    ET_TIMEZONE = ZoneInfo('America/New_York')
except Exception:
    # Fallback for environments lacking IANA tz database (e.g., minimal Windows install)
    try:
        import pytz
        ET_TIMEZONE = pytz.timezone('US/Eastern')
    except Exception:
        from datetime import timezone, timedelta
        ET_TIMEZONE = timezone(timedelta(hours=-5))  # Approximate EST without DST handling
        print("[WARN] Using fixed-offset timezone fallback for Eastern Time")

# Configuration
DISABLE_NOTIFICATIONS = os.getenv("DISABLE_NOTIFICATIONS", "0") == "1"  # Set env var to suppress Telegram sends
STAGE2_DEBUG = os.getenv("STAGE2_DEBUG", "0") == "1"  # Enable detailed Stage 2 diagnostic logging
API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"
TELEGRAM_BOT_TOKEN = "8230689629:AAHtpdsVb8znDZ_DyKMzcOgee-aczA9acOE"
TELEGRAM_CHAT_ID = "8258742558"
PRE_MARKET_START = "03:59"
PRE_MARKET_END = "09:30"
ALERT_COOLDOWN_MINUTES = 5
DATA_FILE = "symbol_tracking_data.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Allow override via env TICKER_FILE; default to data/tickers.csv inside repo.
DEFAULT_TICKER_REL = os.path.join("data", "tickers.csv")
TICKER_FILE = os.getenv("TICKER_FILE", os.path.join(BASE_DIR, DEFAULT_TICKER_REL))

# Timezone defined above with fallbacks

# Global data structures
target_tickers = set()
minute_aggregates = defaultdict(lambda: defaultdict(lambda: {
    'open': None, 'close': 0, 'high': None, 'low': None,
    'volume': 0, 'value': 0, 'count': 0, 'vwap': 0
}))
# Track quotes for spread calculation
latest_quotes = {}  # {symbol: {'bid': price, 'ask': price, 'timestamp': ts}}
# Track momentum flags
momentum_flags = {}  # {symbol: {'flag': 'SETUP_SYMBOL', 'time': datetime, 'session': str, 'intraday_high': price, 'setup_price': float, 'setup_volume': int, 'flag_minute': datetime, 'quality_score': float, 'stage2_fail_reasons': {reason: count}}}
# Track lightweight watch alerts (Stage 0) for broader coverage
watch_alerts = []  # [{'symbol': str, 'timestamp': datetime, 'session': str, 'price': float, 'pct': float, 'rel_vol': float, 'volume': int, 'trades': int, 'quality': float}]
# Track confirmed breakout quality scores (Stage 2) for backtest consumption
breakout_quality = {}  # {symbol: {'quality': float, 'timestamp': datetime}}
# Track 3-minute rolling volume for comparison
rolling_volume_3min = defaultdict(lambda: [0, 0, 0])  # last 3 minutes of volume
# Track price action for structure validation
price_history = defaultdict(lambda: [])  # {symbol: [(timestamp, price, volume)]} - last 5 minutes
# Track session anchors for context
session_anchors = {}  # {symbol: {'day_open': price, 'prev_close': price, 'premarket_high': price, 'premarket_low': price}}
alert_tracker = {}  # {symbol: datetime} - last alert time
data_lock = threading.Lock()
telegram_lock = threading.Lock()
quote_lock = threading.Lock()

def get_et_time():
    """Get current Eastern Time"""
    return datetime.now(ET_TIMEZONE)

def is_premarket_session():
    """Check if currently in pre-market (4:00 AM - 9:30 AM ET, weekdays)"""
    dt = get_et_time()
    if dt.weekday() >= 5:
        return False
    
    current_time = dt.time()
    start = datetime.strptime(PRE_MARKET_START, "%H:%M").time()
    end = datetime.strptime(PRE_MARKET_END, "%H:%M").time()
    return start <= current_time < end

def is_regular_hours():
    """Check if currently in regular market hours (9:30 AM - 4:00 PM ET, weekdays)"""
    dt = get_et_time()
    if dt.weekday() >= 5:
        return False
    
    hour = dt.hour
    minute = dt.minute
    
    # 9:30 AM - 4:00 PM ET
    if hour < 9 or hour >= 16:
        return False
    if hour == 9 and minute < 30:
        return False
    
    return True

def is_postmarket_session():
    """Check if currently in post-market hours (4:00 PM - 8:00 PM ET, weekdays)"""
    dt = get_et_time()
    if dt.weekday() >= 5:
        return False
    
    hour = dt.hour
    
    # 4:00 PM - 8:00 PM ET
    return 16 <= hour < 20

def is_active_trading_session():
    """Check if currently in any active trading session (pre-market, regular, or post-market)"""
    return is_premarket_session() or is_regular_hours() or is_postmarket_session()

def get_next_premarket():
    """Get next pre-market start time"""
    now = get_et_time()
    today_start = ET_TIMEZONE.localize(
        datetime.combine(now.date(), datetime.strptime(PRE_MARKET_START, "%H:%M").time())
    )
    
    if now < today_start and now.weekday() < 5:
        return today_start
    
    # Find next weekday
    next_day = now.date() + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    
    return ET_TIMEZONE.localize(
        datetime.combine(next_day, datetime.strptime(PRE_MARKET_START, "%H:%M").time())
    )

def read_tickers(filepath):
    """Read ticker symbols from CSV with fallback to legacy path."""
    candidates = [filepath]
    legacy = os.path.join(BASE_DIR, "tickers.csv")
    if filepath != legacy:
        candidates.append(legacy)
    for path in candidates:
        if os.path.exists(path):
            tickers = []
            try:
                with open(path, 'r') as f:
                    for row in csv.reader(f):
                        if row:
                            ticker = row[0].strip().upper()
                            if ticker and ticker != "SYMBOL":
                                tickers.append(ticker)
                print(f"✓ Loaded {len(tickers)} tickers from {path}")
            except Exception as e:
                print(f"Error reading tickers from {path}: {e}")
                return []
            return tickers
    print(f"⚠️ Ticker file not found. Checked: {candidates}. Set TICKER_FILE env var if custom path needed.")
    return []

def get_minute_ts(timestamp):
    """Convert timestamp to minute-level datetime in ET timezone"""
    if isinstance(timestamp, int):
        if timestamp > 1000000000000000:  # Nanoseconds
            dt = datetime.fromtimestamp(timestamp / 1e9, tz=ET_TIMEZONE)
        elif timestamp > 1000000000000:  # Milliseconds
            dt = datetime.fromtimestamp(timestamp / 1000, tz=ET_TIMEZONE)
        else:
            dt = datetime.fromtimestamp(timestamp, tz=ET_TIMEZONE)
    else:
        dt = timestamp
        # If dt is naive, make it timezone-aware in ET
        if dt.tzinfo is None:
            dt = ET_TIMEZONE.localize(dt)
    return dt.replace(second=0, microsecond=0)

def send_telegram(message):
    """Send Telegram message unless DISABLE_NOTIFICATIONS flag set."""
    if DISABLE_NOTIFICATIONS:
        return False  # Suppressed during backtests / tuning
    with telegram_lock:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            response = requests.post(
                url,
                data={'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'},
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Telegram error: {e}")
            return False

def can_send_alert(symbol, minute_ts):
    """Check if alert can be sent (respects cooldown)"""
    if symbol not in alert_tracker:
        return True
    
    last_alert = alert_tracker[symbol]
    minutes_since = (minute_ts - last_alert).total_seconds() / 60
    return minutes_since >= ALERT_COOLDOWN_MINUTES

def mark_alerted(symbol, minute_ts):
    """Mark symbol as alerted"""
    alert_tracker[symbol] = minute_ts

def save_previous_minute():
    """Save minute aggregates to JSON file"""
    try:
        filename = f"minute_data_{get_et_time().strftime('%Y%m%d')}.json"
        
        with data_lock:
            # Convert to serializable format
            save_data = {}
            for minute_ts, symbols in minute_aggregates.items():
                minute_key = minute_ts.strftime('%Y-%m-%d %H:%M:%S')
                save_data[minute_key] = {}
                for symbol, agg in symbols.items():
                    save_data[minute_key][symbol] = dict(agg)
        
        with open(filename, 'w') as f:
            json.dump(save_data, f, indent=2)
        
        print(f"✓ Saved {len(save_data)} minutes of data")
        return True
    except Exception as e:
        print(f"Save error: {e}")
        return False

def load_previous_minute():
    """Load minute aggregates from JSON file"""
    filename = f"minute_data_{get_et_time().strftime('%Y%m%d')}.json"
    
    if not os.path.exists(filename):
        print("📂 No previous data found")
        return False
    
    try:
        with open(filename, 'r') as f:
            save_data = json.load(f)
        
        with data_lock:
            minute_aggregates.clear()
            for minute_key, symbols in save_data.items():
                minute_ts = datetime.strptime(minute_key, '%Y-%m-%d %H:%M:%S')
                for symbol, agg in symbols.items():
                    minute_aggregates[minute_ts][symbol] = agg
        
        print(f"✓ Loaded {len(save_data)} minutes of data")
        return True
    except json.JSONDecodeError as e:
        print(f"⚠️ Corrupted data file {filename}: {e}")
        print(f"   Renaming to {filename}.corrupt and starting fresh")
        try:
            os.rename(filename, f"{filename}.corrupt")
        except:
            pass
        return False
    except Exception as e:
        print(f"Load error: {e}")
        return False

def should_alert(pct_change, volume):
    """Check if conditions meet alert criteria - based on current minute only"""
    return (
        (pct_change >= 5 and volume >= 20000) or
        (pct_change >= 10 and volume >= 15000) or
        (pct_change >= 15 and volume >= 10000) or
        (pct_change >= 20 and volume >= 5000) or
        (pct_change >= 30 and volume >= 1000) or
        (volume >= 50000)
    )

def get_spread_ratio(symbol, fallback_price=None):
    """Calculate bid-ask spread as fraction of price.
    Falls back to estimated spread from price volatility if quotes unavailable.
    
    Args:
        symbol: Stock symbol
        fallback_price: Price to use for estimation if no quote available (optional)
    """
    with quote_lock:
        quote = latest_quotes.get(symbol)
        if quote and quote.get('bid') and quote.get('ask'):
            bid = quote['bid']
            ask = quote['ask']
            if bid > 0 and ask > 0:
                mid_price = (bid + ask) / 2
                if mid_price > 0:
                    return (ask - bid) / mid_price
    
    # Fallback: estimate from price
    # Priority: 1) passed fallback_price, 2) current minute aggregate, 3) None
    price = fallback_price
    if price is None or price <= 0:
        agg = minute_aggregates.get(get_minute_ts(get_et_time()), {}).get(symbol, {})
        price = agg.get('close')
    
    if price and price > 0:
        # Rough heuristic: 0.1% spread for >$5, 0.5% for $1-5, 1% for <$1
        if price >= 5:
            return 0.001  # 0.1%
        elif price >= 1:
            return 0.005  # 0.5%
        else:
            return 0.01   # 1.0%
    
    return None

def get_prev_3min_volume(symbol):
    """Get volume from 3 minutes ago for comparison"""
    vols = rolling_volume_3min.get(symbol, [0, 0, 0])
    return vols[0] if vols else 0

def update_rolling_volume(symbol, current_volume):
    """Shift rolling 3-minute volume window"""
    vols = rolling_volume_3min[symbol]
    vols[0] = vols[1]
    vols[1] = vols[2]
    vols[2] = current_volume

def update_price_history(symbol, timestamp, price, volume):
    """Track price action for last 5 minutes"""
    history = price_history[symbol]
    history.append((timestamp, price, volume))
    
    # Keep only last 5 minutes of data
    try:
        cutoff = timestamp - timedelta(minutes=5)
        price_history[symbol] = [(ts, p, v) for ts, p, v in history if ts > cutoff]
    except TypeError:
        # Handle timezone-aware vs naive datetime comparison issues
        # Just keep last 100 entries if comparison fails
        price_history[symbol] = history[-100:] if len(history) > 100 else history

def check_vwap_extension(price, vwap):
    """Check if price is overextended from VWAP (hedge fund quality control)"""
    if vwap <= 0:
        return True, 0
    
    extension = (price - vwap) / vwap
    
    # Flag if more than 8% extended
    if extension > 0.08:
        return False, extension
    
    return True, extension

def check_candle_quality(open_price, close_price, high, low):
    """Validate candle structure - avoid weak/indecisive candles"""
    if high <= low or high <= 0:
        return False, 0
    
    candle_range = high - low
    body = abs(close_price - open_price)
    body_ratio = body / candle_range
    
    # Require at least 50% body (avoid doji/spinning tops)
    if body_ratio < 0.50:
        return False, body_ratio
    
    return True, body_ratio

def check_momentum_persistence(symbol, required_minutes=3):
    """Ensure momentum is sustained, not just a flash spike"""
    flag = momentum_flags.get(symbol)
    if not flag:
        return False, 0
    
    time_held = (get_et_time() - flag['time']).total_seconds() / 60
    return time_held >= required_minutes, time_held

def check_price_consolidation(symbol, price, tolerance=0.02):
    """Check if price is consolidating (holding gains) - hedge fund confirmation"""
    history = price_history.get(symbol, [])
    if len(history) < 10:  # Need at least 10 data points
        return True  # Not enough data, allow
    
    # Get recent prices (last 2 minutes)
    recent = [p for ts, p, v in history[-20:]]
    if not recent:
        return True
    
    avg_price = sum(recent) / len(recent)
    
    # Check if current price within tolerance of recent average
    if abs(price - avg_price) / avg_price < tolerance:
        return True  # Consolidating
    
    return False  # Too volatile

def check_volume_profile(symbol, current_vol, trade_count):
    """Analyze volume distribution - detect institutional vs retail"""
    if trade_count == 0:
        return "unknown", 0
    
    avg_trade_size = current_vol / trade_count
    
    # Institutional fingerprint: larger avg trade size, steady flow
    if avg_trade_size > 500:
        return "institutional", avg_trade_size
    elif avg_trade_size > 200:
        return "mixed", avg_trade_size
    else:
        return "retail", avg_trade_size

def invalidate_flag_if_broken(symbol, price, vwap, volume, prev_volume):
    """Clear momentum flag if setup breaks down - risk management"""
    flag = momentum_flags.get(symbol)
    if not flag:
        return False
    
    # Invalidation conditions
    if price < vwap * 0.99:  # Dropped 1% below VWAP
        print(f"⚠️ Flag invalidated: {symbol} broke below VWAP (${price:.2f} < ${vwap*0.99:.2f})")
        momentum_flags.pop(symbol, None)
        return True
    
    # Volume dried up (less than 30% of previous)
    if prev_volume > 0 and volume < prev_volume * 0.3:
        print(f"⚠️ Flag invalidated: {symbol} volume dried up ({volume:,} < {prev_volume*0.3:,.0f})")
        momentum_flags.pop(symbol, None)
        return True
    
    return False

def get_market_cap_tier(symbol):
    """Classify symbol by market cap for adaptive thresholds"""
    # This is a placeholder - in production, fetch from API or database
    # For now, apply conservative thresholds universally
    return "small"  # Can be "small", "mid", "large"

def get_volume_threshold_by_tier(tier, session):
    """Get volume threshold based on market cap and session"""
    thresholds = {
        "small": {"premarket": 50000, "regular": 100000, "postmarket": 75000},
        "mid": {"premarket": 100000, "regular": 200000, "postmarket": 150000},
        "large": {"premarket": 200000, "regular": 500000, "postmarket": 300000}
    }
    return thresholds.get(tier, thresholds["small"]).get(session, 50000)

def compute_quality_score(rel_vol, pct_change, volume, vol_thresh, trade_count, min_trades, spread_ratio, spread_limit, price_expansion_pct=0, acceleration=False, volume_sustained=False):
    """Compute a refined quality score (0-100) for a momentum candidate.
    Revised weighting emphasizes sustainable momentum over raw percent spike.
    Weights (sum 100):
      - Relative Volume (28)
      - Percent Change (18)
      - Volume vs Threshold (14)
      - Trade Density (12)
      - Spread Tightness (10)
      - Expansion & Follow-through (18)
    Penalties:
      - Parabolic early spike without sustained volume
      - Retail churn (very low average trade size)
    """
    score = 0.0
    # Relative volume (cap at 8x)
    rel_vol_capped = min(rel_vol, 8)
    score += (rel_vol_capped / 8) * 28
    # Percent change (cap influence at 14%) to avoid overweight parabolic prints
    pct_capped = min(abs(pct_change), 14)
    score += (pct_capped / 14) * 18
    # Volume vs threshold (reward proportional up to 2x threshold)
    if vol_thresh > 0:
        vol_ratio = min(volume / vol_thresh, 2)
        score += (vol_ratio / 2) * 14
    # Trade density (higher trades per minute indicates broad participation)
    trade_ratio = min(trade_count / max(min_trades, 1), 3)
    score += (trade_ratio / 3) * 12
    # Spread tightness
    if spread_ratio is not None and spread_limit > 0:
        tightness = max(0.0, (spread_limit - spread_ratio) / spread_limit)
        score += tightness * 10
    else:
        score += 5  # partial credit when unknown
    # Expansion & follow-through components
    follow_components = 0.0
    # Require meaningful expansion (>0.6%) to start rewarding follow-through
    if price_expansion_pct >= 0.6:
        # scale: modest expansion + acceleration + sustained volume
        base_expansion = min(price_expansion_pct / 6, 0.6)  # cap base at 0.6 (~3.6% move)
        follow_components += base_expansion
    if acceleration:
        follow_components += 0.3
    if volume_sustained:
        follow_components += 0.3
    # cap follow components at 1.0
    follow_components = min(follow_components, 1.0)
    score += follow_components * 18
    # Penalties
    # Parabolic penalty: very high pct change without sustained volume yet
    if pct_change >= 11 and not volume_sustained:
        # scale penalty with pct_change beyond 11% (max 6 points after refinement)
        excess = min(pct_change - 11, 6)
        parabolic_penalty = (excess / 6) * 6
        score -= parabolic_penalty
    # Retail churn penalty: extremely small average trade size (<120 shares)
    avg_trade_size = volume / trade_count if trade_count > 0 else 0
    if avg_trade_size < 120:
        score -= 4
    elif avg_trade_size < 200:
        score -= 2
    # Clamp score
    score = max(0, min(score, 100))
    return round(score, 1)

def check_spike(symbol, current_pct, current_vol, minute_ts, open_price, close_price, trade_count, vwap):
    """Time-based spike logic with adaptive filters per session.
    Adjusted to restore alert flow (avoid zero) while introducing quality scoring for manual discretion."""
    
    # Use minute_ts for session detection (supports historical/simulated data)
    # For live data, minute_ts will be current minute; for testing, it's the simulated time
    if isinstance(minute_ts, int):
        dt = datetime.fromtimestamp(minute_ts / 1000, tz=ET_TIMEZONE)
    else:
        dt = minute_ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET_TIMEZONE)
    
    hour = dt.hour
    minute = dt.minute
    price = close_price
    high = minute_aggregates.get(minute_ts, {}).get(symbol, {}).get('high', close_price)
    low = minute_aggregates.get(minute_ts, {}).get(symbol, {}).get('low', close_price)
    spread_ratio = get_spread_ratio(symbol, fallback_price=close_price)
    vol_now = current_vol
    # Use 5-min average for rel_vol
    vols = rolling_volume_3min.get(symbol, [0, 0, 0])
    vol_prev5 = sum(vols) / max(len(vols), 1)
    rel_vol = vol_now / max(vol_prev5, 1)
    session = None
    if 4 <= hour < 9 or (hour == 9 and minute < 30):
        session = "PREMARKET"
    elif (hour == 9 and minute >= 30) or (9 < hour < 16):
        session = "REGULAR"
    elif 16 <= hour < 20:
        session = "POSTMARKET"
    else:
        session = "CLOSED"
    


    # BALANCED-QUALITY THRESHOLDS (dialed back from over-tight final)
    # Goal: restore ~80-160 alerts over 8-9 days while improving ranking via quality score.
    if session == "PREMARKET":
        vol_thresh = 30000
        spread_limit = 0.030
        pct_thresh_early = 3.8  # broaden coverage
        pct_thresh_confirm = 7.8
        min_rel_vol_stage1 = 2.4
        min_rel_vol_stage2 = 4.1
        watch_rel_vol = 1.8
        watch_pct = 2.5
    elif session == "REGULAR":
        vol_thresh = 90000
        spread_limit = 0.020
        pct_thresh_early = 4.5
        pct_thresh_confirm = 7.8
        min_rel_vol_stage1 = 2.5
        min_rel_vol_stage2 = 4.3
        watch_rel_vol = 2.0
        watch_pct = 3.0
    elif session == "POSTMARKET":
        vol_thresh = 24000
        spread_limit = 0.038
        pct_thresh_early = 3.8
        pct_thresh_confirm = 7.0
        min_rel_vol_stage1 = 2.3
        min_rel_vol_stage2 = 4.0
        watch_rel_vol = 1.7
        watch_pct = 2.5
    else:
        return

    # SIMPLIFIED QUALITY FILTERS - Focus on core momentum signals
    # 1. Trade count filter - need real activity, not just spoofing
    min_trade_count = 3  # At least 3 trades in the minute (was 5)
    
    # 2. Volume consistency - check if volume is declining (sign of exhaustion)
    vol_declining = False
    if len(vols) >= 3 and vols[-1] > 0:
        # If current vol is less than 40% of previous minute, it's declining
        if len(vols) >= 2 and vols[-2] > 0:
            vol_declining = vol_now < vols[-2] * 0.4

    # Stage 0: Broad WATCH alert (captures potential names early for manual review)
    watch_pass = (
        rel_vol >= watch_rel_vol and
        current_pct >= watch_pct and
        trade_count >= 2 and
        (spread_ratio is None or spread_ratio < spread_limit * 1.4) and
        not vol_declining
    )
    if watch_pass:
        watch_quality = compute_quality_score(
            rel_vol=rel_vol,
            pct_change=current_pct,
            volume=vol_now,
            vol_thresh=vol_thresh,
            trade_count=trade_count,
            min_trades=3,
            spread_ratio=spread_ratio,
            spread_limit=spread_limit,
            price_expansion_pct=0,
            acceleration=False,
            volume_sustained=False
        )
        # Append to in-memory watch list for backtest consumption
        watch_alerts.append({
            'symbol': symbol,
            'timestamp': dt,
            'session': session,
            'price': price,
            'pct': current_pct,
            'rel_vol': rel_vol,
            'volume': vol_now,
            'trades': trade_count,
            'quality': watch_quality
        })
        # Optional immediate Telegram watch alert (can be noisier)
        if watch_quality >= 45 and can_send_alert(symbol, dt):
            mark_alerted(symbol, dt)
            # Prepare spread display safely (can't embed conditional in format specifier)
            spread_display = f"{spread_ratio:.3f}" if (spread_ratio is not None) else "n/a"
            send_telegram(
                f"WATCH LIST - {session}\n{symbol} @ ${price:.2f}\nPct: +{current_pct:.2f}% | RelVol {rel_vol:.2f}x | Vol {vol_now:,}\nTrades {trade_count} | Spread {spread_display}\nQuality {watch_quality:.1f}/100"
            )

    # Stage 1: Early Detection - Setup flag
    stage1_pct_ok = current_pct >= pct_thresh_early
    stage1_pass = (
        rel_vol >= min_rel_vol_stage1 and
        stage1_pct_ok and
        (spread_ratio is None or spread_ratio < spread_limit) and
        trade_count >= min_trade_count and
        not vol_declining
    )
    
    # Only set flag if it doesn't already exist (avoid resetting intraday_high)
    if stage1_pass and symbol not in momentum_flags:
        # Compute preliminary quality score (no expansion yet)
        prelim_quality = compute_quality_score(
            rel_vol=rel_vol,
            pct_change=current_pct,
            volume=vol_now,
            vol_thresh=vol_thresh,
            trade_count=trade_count,
            min_trades=min_trade_count,
            spread_ratio=spread_ratio,
            spread_limit=spread_limit,
            price_expansion_pct=0,
            acceleration=False,
            volume_sustained=False
        )
        MIN_QUALITY_STAGE1 = 50.0  # further relaxed for coverage
        if prelim_quality < MIN_QUALITY_STAGE1:
            return  # Discard low-quality early spike
        momentum_flags[symbol] = {
            'flag': f'SETUP_{symbol}',
            'time': dt,
            'session': session,
            'intraday_high': high,
            'setup_price': price,
            'setup_volume': vol_now,
            'flag_minute': minute_ts,
            'quality_score': prelim_quality,
            'stage2_fail_reasons': defaultdict(int)
        }
        spread_display = f"{spread_ratio:.3f}" if spread_ratio is not None else "n/a"
        print(f"EARLY DETECTION: {symbol} {session} | rel_vol={rel_vol:.2f} | pct={current_pct:.2f}% | Q={prelim_quality:.1f} | spread={spread_display} | trades={trade_count}")

    # Helper: compute cumulative volume since flag minute (inclusive)
    def _cumulative_volume_since_flag(symbol, flag_minute):
        total = 0
        # Ensure timezone consistency for comparison
        # Convert flag_minute and minute_ts to timestamps (unix epoch) for safe comparison
        flag_ts = flag_minute.timestamp() if hasattr(flag_minute, 'timestamp') else flag_minute
        current_ts = minute_ts.timestamp() if hasattr(minute_ts, 'timestamp') else minute_ts
        # We only sum up to current minute_ts
        for m_ts, sym_map in minute_aggregates.items():
            m_ts_val = m_ts.timestamp() if hasattr(m_ts, 'timestamp') else m_ts
            if m_ts_val >= flag_ts and m_ts_val <= current_ts:
                vol = sym_map.get(symbol, {}).get('volume')
                if vol:
                    total += vol
        return total

    # Stage 2: Confirmed Breakout - REVISED
    # Previous logic relied on current minute % change (open->close), causing misses after the setup minute.
    # Revision: use cumulative expansion from setup_price plus cumulative volume & sustained behavior across minutes.
    flag_data = momentum_flags.get(symbol)
    if flag_data and flag_data['flag'] == f'SETUP_{symbol}':
        setup_price = flag_data.get('setup_price', open_price)
        setup_volume = flag_data.get('setup_volume', 0)
        flag_minute = flag_data.get('flag_minute', minute_ts)
        
        # Cumulative expansion from setup (core metric)
        price_expansion_pct = ((price - setup_price) / setup_price) * 100 if setup_price > 0 else 0
        # Cumulative volume since flag (multi-minute support)
        cumulative_volume = _cumulative_volume_since_flag(symbol, flag_minute)
        # Minutes since flag
        minutes_since_flag = (dt - flag_data['time']).total_seconds() / 60 if 'time' in flag_data else 0

        # Dynamic expansion requirements (revised):
        # Observation: Cumulative expansion from setup is typically smaller than absolute minute spike percent thresholds.
        # Previous requirement (>= pct_thresh_confirm ~7-8%) was too strict, producing zero confirmations.
        # New logic:
        #  - First minute after flag: need modest follow-through (>=0.6%) OR explosive per-minute bar.
        #  - Minutes 1-4: require cumulative expansion >= (pct_thresh_confirm - pct_thresh_early + 1.0) buffer.
        #    Example PREMARKET: 7.8 - 3.8 + 1.0 = 5.0% cumulative expansion from setup.
        #  - Safety floor retains minimum 0.6%.
        #  - After 4 minutes without confirmation, flag expires (cleanup) if expansion < safety threshold.
        if minutes_since_flag < 1.1:
            required_cum_expansion = 0.6
            expansion_gate = price_expansion_pct >= required_cum_expansion or current_pct >= pct_thresh_confirm
        else:
            required_cum_expansion = max(0.6, (pct_thresh_confirm - pct_thresh_early + 1.0))
            expansion_gate = price_expansion_pct >= required_cum_expansion
        # Expiry: if >4 minutes and still below half of required_cum_expansion, invalidate silently
        if minutes_since_flag > 4.0 and price_expansion_pct < (required_cum_expansion * 0.5):
            if STAGE2_DEBUG:
                print(f"STAGE2 EXPIRE {symbol} after {minutes_since_flag:.1f}m exp={price_expansion_pct:.2f}% < {(required_cum_expansion*0.5):.2f}%")
            momentum_flags.pop(symbol, None)
            return

        # Volume sustain logic:
        #  - Accept if (a) cumulative volume >= 1.25 * setup_volume OR (b) current minute volume >= 0.55 * setup_volume
        #  - Also allow if cumulative volume already cleared 0.5 * vol_thresh (bigger picture participation)
        volume_sustained = (
            (setup_volume > 0 and (
                cumulative_volume >= setup_volume * 1.25 or
                vol_now >= setup_volume * 0.55
            )) or (vol_thresh > 0 and cumulative_volume >= vol_thresh * 0.5)
        )

        # Acceleration: use rel_vol OR cumulative participation ratio
        cumulative_rel_vol = 0
        if vol_thresh > 0:
            cumulative_rel_vol = cumulative_volume / max(vol_thresh, 1)
        acceleration = (
            rel_vol >= (min_rel_vol_stage2 - 0.4) or  # slight relaxation
            cumulative_rel_vol >= 0.55  # half threshold worth of volume since flag
        )

        # Spread gate (unchanged but tolerant of unknown)
        spread_gate = (spread_ratio is None) or (spread_ratio < spread_limit)

        # Trade density: accumulate approximate total trades since flag (cheap approximate by summing minute counts)
        total_trades_since_flag = 0
        flag_ts = flag_minute.timestamp() if hasattr(flag_minute, 'timestamp') else flag_minute
        current_ts = minute_ts.timestamp() if hasattr(minute_ts, 'timestamp') else minute_ts
        for m_ts, sym_map in minute_aggregates.items():
            m_ts_val = m_ts.timestamp() if hasattr(m_ts, 'timestamp') else m_ts
            if m_ts_val >= flag_ts and m_ts_val <= current_ts:
                c = sym_map.get(symbol, {}).get('count')
                if c:
                    total_trades_since_flag += c
        trade_gate = total_trades_since_flag >= max(5, int(min_trade_count * 1.6))  # need broader participation

        stage2_pass = all([
            expansion_gate,
            volume_sustained,
            acceleration,
            spread_gate,
            trade_gate
        ])

        # Alternative confirmation path (Adaptive Consolidation) triggers if
        # primary breakout criteria not met but price holds and volume sustains over 2 consecutive minutes.
        # Conditions:
        #  - 2 <= minutes since flag <= 3
        #  - Price hasn't retraced more than 1.5% below setup
        #  - At least 0.3% expansion from setup
        #  - Current pct change exceeds early threshold + 0.5%
        #  - Current and previous minute volumes >= 50-60% of setup volume
        #  - Relative volume remains elevated (>= min_rel_vol_stage1 + 0.3)
        # This path helps capture orderly consolidations that proceed without explosive breakout bar.
        alt_stage2_pass = False
        prev_vol_list = rolling_volume_3min.get(symbol, [])
        prev_minute_vol = prev_vol_list[-2] if len(prev_vol_list) >= 2 else 0
        max_retrace_allowed = setup_price * 0.985  # 1.5% retrace floor
        retrace_ok = price >= max_retrace_allowed
        alt_expansion_ok = price_expansion_pct >= 0.4  # slightly higher now that primary relaxed
        # Use cumulative expansion instead of per-minute pct change for alt path gating
        alt_pct_ok = price_expansion_pct >= (pct_thresh_early + 1.0)  # require progression beyond early threshold
        # Volume: need current AND previous (if available) to be at least 50% setup_volume
        alt_volume_ok = (
            (vol_now >= setup_volume * 0.5) and
            (prev_minute_vol == 0 or prev_minute_vol >= setup_volume * 0.5)
        )
        alt_relvol_ok = rel_vol >= (min_rel_vol_stage1 + 0.3)
        if (not stage2_pass and 2 <= minutes_since_flag <= 3 and retrace_ok and alt_expansion_ok and alt_pct_ok
                and alt_volume_ok and alt_relvol_ok and (spread_ratio is None or spread_ratio < spread_limit)):
            alt_stage2_pass = True
        
        # Stage 2 failure diagnostics (only if debugging and not passing either path)
        if STAGE2_DEBUG and not (stage2_pass or alt_stage2_pass):
            reasons = flag_data.get('stage2_fail_reasons')
            if reasons is not None:
                if not expansion_gate:
                    reasons['expansion'] += 1
                if not volume_sustained:
                    reasons['volume'] += 1
                if not acceleration:
                    reasons['acceleration'] += 1
                if not spread_gate:
                    reasons['spread'] += 1
                if not trade_gate:
                    reasons['trades'] += 1
                # Periodically emit snapshot
                if sum(reasons.values()) % 10 == 1:  # slightly denser logging for tuning
                    print(
                        f"STAGE2 DEBUG {symbol} mins_since={minutes_since_flag:.1f} exp={price_expansion_pct:.2f}% req={required_cum_expansion:.2f}% cumVol={cumulative_volume:,} volNow={vol_now:,} "
                        f"reasons={dict(reasons)} relVol={rel_vol:.2f} accel={acceleration} tradeTot={total_trades_since_flag} spread={spread_ratio}"
                    )
        
        if stage2_pass or alt_stage2_pass:
            # Recompute quality score with expansion context
            confirmed_quality = compute_quality_score(
                rel_vol=rel_vol,
                pct_change=current_pct,
                volume=vol_now,
                vol_thresh=vol_thresh,
                trade_count=trade_count,
                min_trades=min_trade_count,
                spread_ratio=spread_ratio,
                spread_limit=spread_limit,
                price_expansion_pct=price_expansion_pct,
                acceleration=True,
                volume_sustained=volume_sustained
            )
            # Stage 2 quality gate to avoid weak confirmations
            # Slightly lower gate for alt path since expansion is milder
            min_gate = 60 if stage2_pass else 58
            if confirmed_quality < min_gate:
                return
            # Alert
            confirmation_type = "BREAKOUT CONFIRMED" if stage2_pass else "ALT CONFIRM (CONSOLIDATION)"
            spread_display = f"{spread_ratio:.3f}" if spread_ratio is not None else "n/a"
            print(f"{confirmation_type}: {symbol} {session} | rel_vol={rel_vol:.2f} | exp_from_setup={price_expansion_pct:.2f}% | cum_vol={cumulative_volume:,} | Q={confirmed_quality:.1f} | spread={spread_display}")
            stop_loss = vwap * 0.98
            take_profit = price * 1.08
            print(f"Entry: {price:.2f} | Stop: {stop_loss:.2f} | Target: {take_profit:.2f}")
            
            # Send Telegram alert with enhanced context
            # Calculate price vs VWAP for alert message
            price_vwap_strength = ((price - vwap) / vwap) * 100 if vwap > 0 else 0
            
            alert_msg = (
                f"{confirmation_type} - {session}\n"
                f"{symbol} @ ${price:.2f}\n\n"
                f"Momentum:\n"
                f"• Rel Volume: {rel_vol:.2f}x\n"
                f"• Expansion From Setup: +{price_expansion_pct:.2f}%\n"
                f"• Volume: {vol_now:,}\n"
                f"• Trades: {trade_count}\n"
                f"• Spread: {spread_display} {(f'({spread_ratio*100:.2f}%)' if spread_ratio is not None else '')}\n"
                f"• Cumulative Volume Since Flag: {cumulative_volume:,}\n"
                f"• Price vs VWAP: +{price_vwap_strength:.2f}%\n\n"
                f"Plan:\n"
                f"• Entry: ${price:.2f}\n"
                f"• Stop Loss: ${stop_loss:.2f}\n"
                f"• Target: ${take_profit:.2f}\n"
                f"• VWAP: ${vwap:.2f}\n\n"
                f"Quality Score: {confirmed_quality:.1f}/100\n"
                f"Passed {min_trade_count} trade minimum\n"
                f"Volume sustained from setup\n"
                f"{price_expansion_pct:.1f}% expansion confirmed\n"
                f"Alt Path: {alt_stage2_pass}\n\n"
                f"{dt.strftime('%I:%M:%S %p ET')}"
            )
            send_telegram(alert_msg)
            
            # Remove flag
            breakout_quality[symbol] = {'quality': confirmed_quality, 'timestamp': dt, 'expansion_pct': price_expansion_pct, 'cumulative_volume': cumulative_volume}
            momentum_flags.pop(symbol, None)

    # Stage 3: Fast-Break Mode
    if (
        vol_prev5 > 0 and
        vol_now >= 6 * vol_prev5 and  # Slightly easier trigger than 8x
        current_pct >= 9 and
        (spread_ratio is None or spread_ratio < spread_limit * 1.6)
    ):
        fb_quality = compute_quality_score(
            rel_vol=rel_vol,
            pct_change=current_pct,
            volume=vol_now,
            vol_thresh=vol_thresh,
            trade_count=trade_count,
            min_trades=min_trade_count,
            spread_ratio=spread_ratio,
            spread_limit=spread_limit,
            price_expansion_pct=current_pct,  # use pct as proxy
            acceleration=True,
            volume_sustained=not vol_declining
        )
        spread_display = f"{spread_ratio:.3f}" if spread_ratio is not None else "n/a"
        print(f"FAST-BREAK MODE: {symbol} {session} | vol_now={vol_now:,} | vol_prev5={vol_prev5:,} | pct={current_pct:.2f}% | Q={fb_quality:.1f} | spread={spread_display}")
        # Send Telegram alert for parabolic move
        alert_msg = (
            f"FAST-BREAK MODE - {session}\n"
            f"{symbol} @ ${price:.2f}\n\n"
            f"Parabolic Move:\n"
            f"• Volume Surge: {vol_now:,} ({rel_vol:.1f}x average)\n"
            f"• % Change: +{current_pct:.2f}%\n"
            f"• Spread: {spread_display}\n"
            f"• Quality Score: {fb_quality:.1f}/100\n\n"
            f"High volatility - use extreme caution\n"
            f"{dt.strftime('%I:%M:%S %p ET')}"
        )
        send_telegram(alert_msg)

def update_aggregates(symbol, price, size, timestamp):
    """Update minute-level aggregates with VWAP and trade count"""
    minute_ts = get_minute_ts(timestamp)
    
    with data_lock:
        agg = minute_aggregates[minute_ts][symbol]
        
        # Update OHLC
        if agg['open'] is None:
            agg['open'] = price
        agg['close'] = price
        
        if agg['high'] is None or price > agg['high']:
            agg['high'] = price
        if agg['low'] is None or price < agg['low']:
            agg['low'] = price
        
        # Update volume and value for VWAP
        agg['volume'] += size
        agg['value'] += price * size
        agg['count'] += 1
        
        # Calculate VWAP
        vwap = agg['value'] / agg['volume'] if agg['volume'] > 0 else price
        
        # Calculate percentage change within the current minute (open to close)
        pct_change = 0
        if agg['open'] and agg['open'] > 0:
            pct_change = ((agg['close'] - agg['open']) / agg['open']) * 100
        
        return minute_ts, agg['volume'], pct_change, agg['open'], agg['close'], agg['count'], vwap

def handle_msg(msgs):
    """Handle incoming WebSocket messages"""
    if not isinstance(msgs, list):
        msgs = [msgs]
    
    for msg in msgs:
        try:
            # Get event type (check both 'ev' and 'event_type' attributes)
            event_type = None
            if hasattr(msg, 'ev'):
                event_type = msg.ev
            elif hasattr(msg, 'event_type'):
                event_type = msg.event_type
            
            # Handle quote messages for spread calculation
            if event_type == 'Q':
                # Check for both old and new attribute names
                symbol = getattr(msg, 'sym', None) or getattr(msg, 'symbol', None)
                bid = getattr(msg, 'bp', None) or getattr(msg, 'bid_price', None)
                ask = getattr(msg, 'ap', None) or getattr(msg, 'ask_price', None)
                
                if symbol and bid and ask:
                    if symbol in target_tickers:
                        with quote_lock:
                            latest_quotes[symbol] = {
                                'bid': bid,
                                'ask': ask,
                                'timestamp': get_et_time()
                            }
                continue
            
            # Only process trade messages for target tickers
            if not hasattr(msg, 'symbol') or not hasattr(msg, 'price'):
                continue
            
            symbol = msg.symbol
            if symbol not in target_tickers:
                continue
            
            price = msg.price
            size = msg.size
            timestamp = msg.timestamp
            
            # Update price history for structure analysis
            update_price_history(symbol, get_et_time(), price, size)
            
            # Update aggregates and check for spike
            minute_ts, volume, pct_change, open_price, close_price, trade_count, vwap = update_aggregates(symbol, price, size, timestamp)
            
            # On minute change, update rolling volume window
            et_time = get_et_time()
            current_minute = et_time.replace(second=0, microsecond=0)
            
            # Check if we should update rolling volume (when minute completes)
            # Convert to timestamps for comparison to avoid timezone issues
            minute_ts_int = int(minute_ts.timestamp()) if hasattr(minute_ts, 'timestamp') else minute_ts
            current_minute_int = int(current_minute.timestamp())
            
            if minute_ts_int < current_minute_int:
                # Update rolling volume window
                if symbol not in rolling_volume_3min:
                    rolling_volume_3min[symbol] = [0, 0, 0]
                update_rolling_volume(symbol, volume)
            
            # Check for spike on every trade (real-time detection)
            check_spike(symbol, pct_change, volume, minute_ts, open_price, close_price, trade_count, vwap)
            
        except Exception as e:
            import traceback
            print(f"Error processing message: {e}")
            print(f"Traceback: {traceback.format_exc()}")

def run_session():
    """Run WebSocket session during active trading hours (pre-market, regular, post-market)"""
    print(f"✓ Session started: {get_et_time().strftime('%H:%M:%S ET')}")
    
    # Load previous data if available
    load_previous_minute()
    
    # Clear alert tracker for new session
    with data_lock:
        alert_tracker.clear()
    
    try:
        client = WebSocketClient(
            api_key=API_KEY,
            feed=Feed.RealTime,
            market=Market.Stocks
        )
        
        # Subscribe to trades and quotes for spread calculation
        client.subscribe('T.*')  # All trades
        client.subscribe('Q.*')  # All quotes
        
        # Run in background thread
        ws_running = [True]
        
        def ws_runner():
            try:
                client.run(handle_msg)
            except Exception as e:
                print(f"WebSocket error: {e}")
                ws_running[0] = False
        
        ws_thread = threading.Thread(target=ws_runner, daemon=True)
        ws_thread.start()
        
        # Monitor session - run during any active trading session
        while is_active_trading_session() and ws_running[0]:
            time.sleep(5)
        
        ws_running[0] = False
        print(f"✓ Session ended: {get_et_time().strftime('%H:%M:%S ET')}")
        
        # Save data at end of session
        save_previous_minute()
        
    except Exception as e:
        print(f"Session error: {e}")

def main():
    """Main function"""
    global target_tickers
    
    print("🚀 Extended Hours Monitor")
    print(f"⏰ Pre-Market: {PRE_MARKET_START} - 09:30 ET")
    print(f"⏰ Regular Hours: 09:30 - 16:00 ET")
    print(f"⏰ Post-Market: 16:00 - 20:00 ET")
    
    # Load tickers from configurable path
    target_tickers = set(read_tickers(TICKER_FILE))
    print(f"📊 Monitoring {len(target_tickers)} tickers")
    
    try:
        while True:
            if is_active_trading_session():
                run_session()
            else:
                next_session = get_next_premarket()
                wait_time = (next_session - get_et_time()).total_seconds()
                
                hours = int(wait_time // 3600)
                minutes = int((wait_time % 3600) // 60)
                
                print(f"💤 Next session: {next_session.strftime('%Y-%m-%d %H:%M ET')} ({hours}h {minutes}m)")
                time.sleep(min(300, max(1, wait_time - 10)))  # Check every 5 min or sooner
                
    except KeyboardInterrupt:
        print("\n💾 Saving data before exit...")
        save_previous_minute()
        print("✓ Shutdown complete")
        sys.exit(0)

if __name__ == "__main__":
    main()