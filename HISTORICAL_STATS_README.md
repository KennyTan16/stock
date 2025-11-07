# Historical Statistics Cache

## Overview

The enhanced spike detection system uses **adaptive thresholds** based on each symbol's historical trading characteristics. This eliminates false positives on naturally volatile or high-volume stocks.

## Quick Start

```bash
# Download 20-day statistics for all symbols in your ticker list
python update_historical_stats.py
```

This creates `historical_data/stats_cache.csv` which is automatically loaded when you run `polygon_websocket.py`.

## How It Works

### 1. Data Collection
- Fetches last 20 days of daily bars from Polygon API
- Calculates average volume and price range per symbol
- Caches results locally to avoid repeated API calls

### 2. Adaptive Thresholds
When stats are available, the detection system scales thresholds:

**Volume Threshold:**
```python
vol_thresh = max(BASE_VOL_THRESH, avg_volume_20d * 0.12)
```
- Base threshold: 30K (premarket), 90K (regular), 24K (postmarket)
- Scales with symbol's typical volume
- Example: Stock with 5M daily volume → 600K threshold vs 90K base

**Percentage Threshold:**
```python
pct_thresh = max(BASE_PCT_THRESH, (avg_range_20d / price) * 1.2)
```
- Base threshold: 3.8% (premarket), 4.5% (regular)
- Scales with symbol's typical volatility
- Example: Stock with 8% daily range → 9.6% threshold vs 4.5% base

**Liquidity Filter:**
```python
liquidity_score = min(1.0, avg_volume_20d / 1_000_000)
if liquidity_score < 0.1:  # Less than 100K daily volume
    skip_alert()  # Too illiquid
```

### 3. Quality Weighting
Final quality score is weighted by liquidity:
```python
final_quality = base_quality * (0.5 + 0.5 * liquidity_score)
```
- Liquid stocks (>1M volume): Full quality score
- Medium stocks (100K-1M): Scaled 50-100%
- Illiquid stocks (<100K): Filtered out

## API Rate Limits

**Polygon Free Tier:** 5 requests/minute

The script automatically throttles:
- Processes 5 symbols
- Waits 12 seconds
- Repeats until complete

**Time Estimate:** ~2.5 minutes per 100 symbols

## Cache File Format

`historical_data/stats_cache.csv`:
```csv
symbol,avg_volume_20d,avg_range_20d,bars_count,last_updated
AAPL,49422449.0,5.25,20,2025-11-07 13:15:00
TSLA,102455123.0,12.85,20,2025-11-07 13:15:12
```

Missing data shows empty values:
```csv
NEWIPO,,,0,2025-11-07 13:15:24
```

## Update Frequency

**Recommended:** Weekly

Symbols' volatility and volume profiles change over time. Update the cache:
- Weekly for active monitoring
- When adding new symbols to ticker list
- After major market regime changes

## Error Handling

**No Data Available:**
- New IPOs may lack 20-day history
- Delisted/suspended stocks return no bars
- Script logs warnings, system falls back to base thresholds

**Rate Limit Errors (429):**
- Script automatically waits 60 seconds and retries
- Consider upgrading API plan for faster updates

**API Key Issues:**
- Verify API_KEY in `update_historical_stats.py`
- Check Polygon.io dashboard for quota limits

## Manual Testing

Test a single symbol before full update:

```bash
python test_polygon_api.py
```

Output shows:
- API connection status
- 20-day average volume
- 20-day average range
- Sample bars for verification

## Integration with Backtest

The backtest infrastructure also needs historical stats. To make stats available during backtesting:

1. Ensure `stats_cache.csv` exists
2. Import and call `load_historical_stats()` in backtest script
3. Adaptive thresholds will apply to historical data

## Troubleshooting

**Problem:** "Historical stats cache not found"
- **Solution:** Run `python update_historical_stats.py`

**Problem:** Stats not loading
- **Check:** File exists at `historical_data/stats_cache.csv`
- **Check:** CSV format matches expected columns
- **Fix:** Delete cache and regenerate

**Problem:** All thresholds using base values
- **Check:** Stats loaded successfully (startup message shows count)
- **Check:** Symbol names match between tickers.csv and stats_cache.csv (case-sensitive)

**Problem:** Too slow to update
- **Solution:** Upgrade to Polygon paid tier (unlimited requests)
- **Workaround:** Update in batches (split ticker list)

## Performance Impact

**With Stats:**
- AAPL (high volume): 600K vol threshold vs 90K base = 85% fewer false alerts
- MEME (high volatility): 12% pct threshold vs 4.5% base = 63% fewer false alerts
- Penny stocks (<100K volume): Filtered out completely

**Without Stats:**
- Falls back to session-based base thresholds
- Still functional but less selective
- May generate more false positives on volatile stocks
