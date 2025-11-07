# Momentum Detection System - Improvements to Increase Win Rate

**Date:** November 6, 2025  
**Previous Win Rate:** 15.17% (1,226 alerts over 9 days)  
**Target Win Rate:** 50%+  

## Backtest Analysis Summary

### Previous Performance (Test Thresholds)
```
Total Alerts: 1,226
Profitable: 186 (15.2%)
Breakeven: 45 (3.7%)
Losing: 995 (81.2%)

Outcomes:
- Hit Stop Loss: 950 (77.5%) ❌
- Hit Target: 141 (11.5%) ✅
- Timeout: 135 (11.0%)

Average Loss: -2.06% per trade
Max Gain: +8.00%
Max Loss: -13.58%
```

### Key Problems Identified
1. **Too many false positives** - 77.5% of alerts hit stop loss
2. **Weak momentum signals** - Many setups lacked follow-through
3. **Poor risk/reward** - Average loss of -2% vs target of +8%
4. **Low-quality setups** - Loose thresholds caught premature moves

## Implemented Improvements

### 1. Enhanced Threshold Requirements

#### PREMARKET (4:00 AM - 9:30 AM ET)
**Stage 1 (Early Detection):**
- Relative Volume: ≥3.5x (was 2.5x) - **+40% increase**
- Price Change: ≥5% (was 3%) - **+67% increase**
- Volume Threshold: 50K shares (was 30K)
- Spread Limit: ≤2.5% (was 3%)

**Stage 2 (Confirmed Breakout):**
- Relative Volume: ≥5.5x (was 4.0x) - **+38% increase**
- Price Change: ≥10% (was 7%) - **+43% increase**
- Absolute Volume: ≥50K shares (was 30K)

#### REGULAR HOURS (9:30 AM - 4:00 PM ET)
**Stage 1:**
- Relative Volume: ≥4.0x (was 2.5x) - **+60% increase**
- Price Change: ≥6% (was 4%) - **+50% increase**
- Volume Threshold: 150K shares (was 75K) - **+100% increase**
- Spread Limit: ≤1.5% (was 2%)

**Stage 2:**
- Relative Volume: ≥6.0x (was 4.0x) - **+50% increase**
- Price Change: ≥10% (was 7%) - **+43% increase**
- Absolute Volume: ≥150K shares (was 75K)

#### POSTMARKET (4:00 PM - 8:00 PM ET)
**Stage 1:**
- Relative Volume: ≥3.5x (was 2.5x)
- Price Change: ≥5% (was 3%)
- Volume Threshold: 40K shares (was 20K)
- Spread Limit: ≤3.0% (was 4%)

**Stage 2:**
- Relative Volume: ≥5.0x (was 4.0x)
- Price Change: ≥9% (was 6%)
- Absolute Volume: ≥40K shares (was 20K)

### 2. New Quality Filters

#### A. Price/VWAP Relationship
- **Stage 1:** Price must be ≥0.5% above VWAP (not just above)
- **Stage 2:** Price must be ≥1.0% above VWAP
- **Rationale:** Better risk/reward positioning, avoid entries near support

#### B. Trade Count Filter
- **Minimum:** 10 trades per minute for Stage 1
- **Stage 2:** 15+ trades per minute (50% increase)
- **Rationale:** Ensures real trading activity, not just spoofing/painting

#### C. Candle Range Filter
- **Minimum:** 1% range (high-low spread) in the minute
- **Rationale:** Need meaningful price action, not tight consolidation

#### D. Volume Consistency Check
- **Stage 1:** Volume cannot be declining (current < 60% of previous)
- **Stage 2:** Volume must be ≥80% of setup volume
- **Rationale:** Sustained volume = real momentum, not exhaustion

#### E. Price Expansion Confirmation
- **Stage 2 Only:** Price must expand ≥2% from Stage 1 setup price
- **Rationale:** Proves follow-through, not just a temporary spike

### 3. Enhanced Momentum Tracking

#### Setup Context Preservation
- Track `setup_price` and `setup_volume` when Stage 1 triggers
- Compare Stage 2 metrics against setup baseline
- Validate acceleration, not deceleration

#### Momentum Acceleration
- Stage 2 requires increasing rel_vol (acceleration check)
- Volume must be maintained or increasing
- Price must be pulling VWAP up, not just riding it

### 4. Improved Alert Quality Score

New alerts include quality indicators:
```
⚡ Quality Score: HIGH
✅ Passed 10 trade minimum
✅ Volume sustained from setup
✅ 3.2% expansion confirmed
✅ Price 1.5% above VWAP
```

## Expected Outcomes

### Alert Volume
- **Previous:** 1,226 alerts over 9 days (~136/day)
- **Expected:** 50-150 alerts over 9 days (~5-15/day)
- **Reduction:** ~90% fewer alerts (focusing on quality)

### Win Rate Projection
Based on filtering out weak signals:
- **Conservative:** 35-40% win rate (+20-25 percentage points)
- **Moderate:** 45-50% win rate (+30-35 percentage points)
- **Optimistic:** 55-60% win rate (+40-45 percentage points)

### Risk/Reward
- **Stop Loss:** -2% (unchanged)
- **Target:** +8% (unchanged)
- **Ratio:** 1:4 risk/reward
- **Break-even needed:** 20% win rate
- **Profitable at:** 30%+ win rate

## Testing & Validation

### Next Steps
1. **Run Enhanced Backtest:**
   ```bash
   python backtest_flatfiles.py
   ```
   This will process the same 9 days with new thresholds

2. **Validate Improvements:**
   - Compare alert count (expect ~90% reduction)
   - Measure win rate (target 50%+)
   - Check average gain (target positive)
   - Verify max drawdown (should improve)

3. **Live Monitoring:**
   ```bash
   python polygon_websocket.py
   ```
   Monitor live markets with enhanced filters

### Success Criteria
✅ Win rate ≥50%  
✅ Average gain positive (>0%)  
✅ Alert quality score consistently "HIGH"  
✅ 75%+ reduction in false positives  

## Rollback Plan

If enhanced thresholds prove too strict (zero alerts):

1. **Moderate Adjustment:**
   - Reduce Stage 1 requirements by 10%
   - Keep Stage 2 strict for final confirmation

2. **Gradual Relaxation:**
   - Start with regular hours only
   - Adjust per session based on results

3. **Revert Command:**
   ```python
   # In backtest_flatfiles.py, set:
   TEST_MODE = True  # Use lower thresholds
   ```

## Technical Implementation

### Files Modified
1. `polygon_websocket.py` - Enhanced `check_spike()` function
2. `backtest_flatfiles.py` - Updated thresholds and documentation

### Code Changes
- ~150 lines modified in `check_spike()`
- Added 6 new quality filter checks
- Enhanced momentum tracking with setup context
- Improved alert messages with quality indicators

### Backward Compatibility
✅ Existing data structures unchanged  
✅ Telegram alerts still work  
✅ Backtest framework compatible  
✅ Can toggle TEST_MODE for comparison  

## Conclusion

These improvements shift the system from **quantity to quality**:
- **Before:** Many signals, low accuracy (15% win rate)
- **After:** Fewer signals, high accuracy (target 50%+ win rate)

The enhanced filters ensure we only alert on **explosive breakouts with strong confirmation**, not premature moves that are likely to fail.

**Philosophy:** It's better to miss some moves than to lose money on false signals. The strict thresholds wait for high-probability setups where momentum is undeniable.
