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
# Track 3-minute rolling volume for comparison
rolling_volume_3min = defaultdict(lambda: [0, 0, 0])  # last 3 minutes of volume
# Track price action for structure validation
price_history = defaultdict(lambda: [])  # {symbol: [(timestamp, price, volume)]} - last 5 minutes
# Track momentum persistence across bars
momentum_counter = {}  # {symbol: count} - consecutive bars meeting momentum criteria
# Track session anchors for context
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
        filename = os.path.join("data", f"minute_data_{get_et_time().strftime('%Y%m%d')}.json")
        
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
    filename = os.path.join("data", f"minute_data_{get_et_time().strftime('%Y%m%d')}.json")
    
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

def normalize_timestamp(ts):
    """Convert timestamp to timezone-aware datetime."""
    if isinstance(ts, int):
        if ts > 1000000000000000:  # Nanoseconds
            dt = datetime.fromtimestamp(ts / 1e9, tz=ET_TIMEZONE)
        elif ts > 1000000000000:  # Milliseconds
            dt = datetime.fromtimestamp(ts / 1000, tz=ET_TIMEZONE)
        else:
            dt = datetime.fromtimestamp(ts, tz=ET_TIMEZONE)
    else:
        dt = ts if ts.tzinfo else ts.replace(tzinfo=ET_TIMEZONE)
    return dt

def BASE_VOL_THRESH(session):
    """Return base volume threshold for session."""
    return {"PREMARKET": 30000, "REGULAR": 90000, "POSTMARKET": 24000}.get(session, 90000)

def BASE_PCT_THRESH(session):
    """Return base percentage threshold for session."""
    return {"PREMARKET": 3.8, "REGULAR": 4.5, "POSTMARKET": 3.8}.get(session, 4.5)

def get_spread_limit(session):
    """Return spread limit for session."""
    return {"PREMARKET": 0.03, "REGULAR": 0.02, "POSTMARKET": 0.038}.get(session, 0.03)

def get_recent_prices(symbol, n=3):
    """Get last n closing prices for symbol from minute aggregates."""
    prices = []
    sorted_minutes = sorted(minute_aggregates.keys(), reverse=True)
    
    for minute_ts in sorted_minutes[:n]:
        agg = minute_aggregates[minute_ts].get(symbol)
        if agg and agg.get('close'):
            prices.append(agg['close'])
        if len(prices) >= n:
            break
    
    return prices[::-1]  # Return in chronological order

def get_recent_vwaps(symbol, n=3):
    """Get last n VWAPs for symbol from minute aggregates."""
    vwaps = []
    sorted_minutes = sorted(minute_aggregates.keys(), reverse=True)
    
    for minute_ts in sorted_minutes[:n]:
        agg = minute_aggregates[minute_ts].get(symbol)
        if agg and agg.get('vwap'):
            vwaps.append(agg['vwap'])
        if len(vwaps) >= n:
            break
    
    return vwaps[::-1]  # Return in chronological order

def vwap_bias(symbol, n=3):
    """Check if last n bars are above or below VWAP.
    Returns 'bullish' if all recent prices > VWAP, 'bearish' if all < VWAP, else 'neutral'.
    """
    recent_prices = get_recent_prices(symbol, n)
    recent_vwaps = get_recent_vwaps(symbol, n)
    
    if len(recent_prices) < n or len(recent_vwaps) < n:
        return "neutral"  # Not enough data
    
    if all(p > v for p, v in zip(recent_prices, recent_vwaps)):
        return "bullish"
    elif all(p < v for p, v in zip(recent_prices, recent_vwaps)):
        return "bearish"
    else:
        return "neutral"

# Cache for historical statistics (loaded on startup)
historical_stats_cache = {}  # {symbol: {'avg_volume': float, 'avg_range': float, 'last_updated': datetime}}

def load_historical_stats():
    """Load historical statistics from cached CSV files in historical_data/ folder.
    Expected format: historical_data/stats_cache.csv with columns:
    symbol,avg_volume_20d,avg_range_20d,last_updated
    """
    global historical_stats_cache
    cache_file = os.path.join(BASE_DIR, "historical_data", "stats_cache.csv")
    
    if not os.path.exists(cache_file):
        print(f"[WARN] Historical stats cache not found: {cache_file}")
        print("   Run update_historical_stats.py to download from Polygon API")
        return
    
    try:
        import csv
        with open(cache_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row['symbol'].strip().upper()
                historical_stats_cache[symbol] = {
                    'avg_volume': float(row['avg_volume_20d']) if row['avg_volume_20d'] else None,
                    'avg_range': float(row['avg_range_20d']) if row['avg_range_20d'] else None,
                    'last_updated': row.get('last_updated', '')
                }
        print(f"[OK] Loaded historical stats for {len(historical_stats_cache)} symbols")
    except Exception as e:
        print(f"[WARN] Error loading historical stats: {e}")

def get_average_volume(symbol, days=20):
    """Get average daily volume from cached historical data.
    Returns None if not available in cache.
    """
    stats = historical_stats_cache.get(symbol)
    return stats['avg_volume'] if stats else None

def get_average_price_range(symbol, days=20):
    """Get average daily price range (high-low) from cached historical data.
    Returns None if not available in cache.
    """
    stats = historical_stats_cache.get(symbol)
    return stats['avg_range'] if stats else None

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
    """
    Enhanced spike detector with:
      1. Dynamic per-symbol thresholds (volatility + liquidity aware)
      2. Multi-bar persistence confirmation
      3. Liquidity-weighted quality scoring
      4. VWAP alignment & trend confirmation
    """

    # === 0. Setup and timestamp normalization ===
    dt = normalize_timestamp(minute_ts)
    hour, minute = dt.hour, dt.minute
    price = close_price

    # === 1. Determine session type ===
    if 4 <= hour < 9 or (hour == 9 and minute < 30):
        session = "PREMARKET"
    elif (hour == 9 and minute >= 30) or (9 < hour < 16):
        session = "REGULAR"
    elif 16 <= hour < 20:
        session = "POSTMARKET"
    else:
        return  # market closed

    # === 2. Compute baseline metrics for adaptive thresholds ===
    avg_vol_20d = get_average_volume(symbol, days=20)
    avg_range_20d = get_average_price_range(symbol, days=20)
    spread_ratio = get_spread_ratio(symbol, fallback_price=price)
    vols = rolling_volume_3min.get(symbol, [0, 0, 0])
    vol_prev5 = sum(vols) / max(len(vols), 1)
    rel_vol = current_vol / max(vol_prev5, 1)

    # Dynamic volume threshold scaled by average liquidity
    # If avg_vol_20d is None (no historical data), fall back to base threshold
    if avg_vol_20d is not None:
        vol_thresh = max(BASE_VOL_THRESH(session), avg_vol_20d * 0.12)
    else:
        vol_thresh = BASE_VOL_THRESH(session)
    
    # Dynamic percent threshold scaled by volatility
    if avg_range_20d is not None and open_price > 0:
        pct_thresh_early = max(BASE_PCT_THRESH(session), (avg_range_20d / open_price) * 1.2)
    else:
        pct_thresh_early = BASE_PCT_THRESH(session)

    # Liquidity weighting (for small caps vs large caps)
    if avg_vol_20d is not None:
        liquidity_score = min(1.0, avg_vol_20d / 1_000_000)
        if liquidity_score < 0.1:
            return  # illiquid, skip alert
    else:
        # If no historical data, assume moderate liquidity (don't filter out)
        liquidity_score = 0.5

    # === 3. Multi-bar persistence check ===
    # Track number of consecutive bars meeting min momentum criteria
    # Use dynamically calculated pct_thresh_early (adapts to symbol volatility)
    backtest_mode = os.getenv("BACKTEST_MODE", "0") == "1"
    
    if backtest_mode:
        # Relaxed thresholds for backtest
        relvol_ok = rel_vol >= 1.5
        pct_ok = current_pct >= (pct_thresh_early * 0.65)  # 65% of dynamic threshold
        min_persistence = 1  # Allow 1-bar signals in backtest
    else:
        # Production thresholds - use full dynamic threshold
        relvol_ok = rel_vol >= 2.0
        pct_ok = current_pct >= pct_thresh_early
        
        # Adaptive persistence based on liquidity
        # Illiquid stocks need more confirmation, liquid stocks can move faster
        if avg_vol_20d is not None:
            if avg_vol_20d < 500_000:
                min_persistence = 3  # Slower confirmation for illiquid stocks
            elif avg_vol_20d > 3_000_000:
                min_persistence = 1  # Fast-moving large caps can alert quickly
            else:
                min_persistence = 2  # Standard confirmation for mid-liquidity
        else:
            min_persistence = 2  # Default if no historical data
    
    if relvol_ok and pct_ok:
        momentum_counter[symbol] = momentum_counter.get(symbol, 0) + 1
    else:
        momentum_counter[symbol] = max(0, momentum_counter.get(symbol, 0) - 1)

    # Require persistence to avoid one-bar noise
    if momentum_counter[symbol] < min_persistence:
        return  # too early, not persistent yet

    # === 4. VWAP alignment ===
    # Confirm that price is consistently above VWAP across multiple lookback periods
    # This prevents false negatives from one-bar VWAP noise
    vwap_trend = vwap_bias(symbol, n=3)  # Check last 3 bars
    vwap_trend_2bar = vwap_bias(symbol, n=2)  # Check last 2 bars
    
    # Require at least one lookback period to NOT be bearish
    # (both can be bearish = skip, at least one neutral/bullish = proceed)
    if vwap_trend == "bearish" and vwap_trend_2bar == "bearish":
        return  # Price moving opposite VWAP trend consistently

    # === 5. Volume & price validation ===
    if current_vol < vol_thresh:
        return  # weak volume
    
    if spread_ratio is not None and spread_ratio > get_spread_limit(session):
        return  # spread too wide

    # === 6. Calculate momentum dynamics for quality scoring ===
    # Price expansion within current bar (intrabar move)
    price_expansion_pct = abs(close_price - open_price) / max(open_price, 0.01) * 100
    
    # Acceleration: compare current move to recent average
    recent_prices = get_recent_prices(symbol, n=3)
    acceleration = False
    if len(recent_prices) >= 2:
        # Calculate previous bar's percentage change
        prev_pct = ((recent_prices[-1] - recent_prices[-2]) / max(recent_prices[-2], 0.01)) * 100
        acceleration = current_pct > prev_pct * 1.2  # Current move is 20% stronger
    
    # Volume sustained: current volume compared to recent average
    volume_sustained = False
    vols = rolling_volume_3min.get(symbol, [0, 0, 0])
    if len(vols) >= 2 and sum(vols[:2]) > 0:
        avg_recent_vol = sum(vols[:2]) / 2  # Average of previous 2 bars
        volume_sustained = current_vol >= avg_recent_vol * 1.1  # 10% above average

    # === 7. Compute liquidity-weighted quality score ===
    base_quality = compute_quality_score(
        rel_vol=rel_vol,
        pct_change=current_pct,
        volume=current_vol,
        vol_thresh=vol_thresh,
        trade_count=trade_count,
        min_trades=3,
        spread_ratio=spread_ratio,
        spread_limit=get_spread_limit(session),
        price_expansion_pct=price_expansion_pct,
        acceleration=acceleration,
        volume_sustained=volume_sustained
    )

    quality = base_quality * (0.5 + 0.5 * liquidity_score)

    # === 8. Multi-stage alert system based on quality tiers ===
    # Determine alert stage based on quality score and persistence level
    stage = None
    if quality >= 50 and momentum_counter[symbol] >= 2:
        stage = "STAGE 1"
    if quality >= 65 and momentum_counter[symbol] >= 3:
        stage = "STAGE 2"
    
    # No alert if quality/persistence insufficient for any stage
    if stage is None:
        return None

    # === 9. Final validation and alert ===
    # BACKTEST MODE: Use moderately lower quality threshold for testing
    backtest_mode = os.getenv("BACKTEST_MODE", "0") == "1"
    
    # BACKTEST MODE: Only trade REGULAR hours (best performance)
    if backtest_mode and session != "REGULAR":
        return None
    
    # Only send alert if symbol not recently alerted (cooldown)
    if can_send_alert(symbol, dt):
        mark_alerted(symbol, dt)
        spread_display = f"{spread_ratio:.3f}" if spread_ratio is not None else "n/a"
        send_telegram(
            f"🔥 {stage} SPIKE DETECTED ({session})\n"
            f"{symbol} @ ${price:.2f}\n"
            f"Pct: +{current_pct:.2f}% | RelVol {rel_vol:.2f}x | Vol {current_vol:,}\n"
            f"Liquidity {liquidity_score:.2f} | VWAP Trend {vwap_trend}\n"
            f"Spread {spread_display} | Trades {trade_count}\n"
            f"Quality {quality:.1f}/100 | Persistence {momentum_counter[symbol]}\n"
            f"{dt.strftime('%I:%M:%S %p ET')}"
        )
        print(f"[{stage}] {symbol} {session} | pct={current_pct:.2f}% | rel_vol={rel_vol:.2f}x | Q={quality:.1f} | persist={momentum_counter[symbol]}")
        
        # Return alert data for backtest capture
        return {
            'symbol': symbol,
            'timestamp': dt,
            'session': session,
            'stage': stage,
            'entry_price': price,
                'pct_change': current_pct,
                'rel_vol': rel_vol,
                'volume': current_vol,
                'vwap': vwap,
                'quality_score': quality,
                'liquidity_score': liquidity_score,
                'vwap_trend': vwap_trend,
                'spread_ratio': spread_ratio,
                'trade_count': trade_count,
                'momentum_bars': momentum_counter.get(symbol, 0)
            }
    
    return None


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
    
    # Load historical statistics for adaptive thresholds
    print("📈 Loading historical statistics...")
    load_historical_stats()
    
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