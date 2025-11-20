"""
Diagnostic test to understand why alerts aren't being sent during regular hours
"""
import sys
sys.path.insert(0, '.')

import polygon_websocket as ws
from datetime import datetime
import pytz

ET_TIMEZONE = pytz.timezone('America/New_York')

def diagnose_alert_requirements():
    """Check alert requirements for regular hours"""
    print("=" * 80)
    print("ALERT REQUIREMENTS DIAGNOSIS - REGULAR HOURS")
    print("=" * 80)
    
    session = "REGULAR"
    
    print(f"\nBase Thresholds for {session}:")
    print(f"  Volume Threshold: {ws.BASE_VOL_THRESH(session):,}")
    print(f"  Percent Threshold: {ws.BASE_PCT_THRESH(session):.2f}%")
    print(f"  Spread Limit: {ws.get_spread_limit(session):.3f}")
    
    print(f"\nStage 1 EARLY Requirements:")
    print(f"  1. momentum_likelihood >= 0.6")
    print(f"  2. acceleration > 0 (increasing likelihood)")
    print(f"  3. current_vol > vol_thresh")
    print(f"  4. Alert cooldown not active (5 min)")
    
    print(f"\nMomentum Likelihood Components:")
    print(f"  - Relative Volume (40%): min(rel_vol / 3.0, 1.0) * 0.40")
    print(f"  - Percent Change (30%): min(current_pct / pct_thresh, 1.0) * 0.30")
    print(f"  - VWAP Alignment (15%): bullish=0.15, neutral=0.075, bearish=0.0")
    print(f"  - Spread Tightness (10%): max(0, 1.0 - spread_ratio/spread_limit) * 0.10")
    print(f"  - Liquidity (5%): min(avg_vol_20d / 1M, 1.0) * 0.05")
    
    print(f"\nExample Calculations:")
    print(f"-" * 80)
    
    # Example 1: Strong momentum
    print(f"\nScenario 1: Strong Momentum")
    rel_vol = 4.0
    current_pct = 5.0
    pct_thresh = 3.8
    vwap_trend = "bullish"
    spread_ratio = 0.01
    spread_limit = 0.02
    avg_vol_20d = 5_000_000
    
    rel_vol_comp = min(rel_vol / 3.0, 1.0) * 0.40
    pct_comp = min(current_pct / pct_thresh, 1.0) * 0.30
    vwap_comp = 1.0 * 0.15 if vwap_trend == "bullish" else (0.5 * 0.15 if vwap_trend == "neutral" else 0.0)
    spread_comp = max(0, 1.0 - (spread_ratio / spread_limit)) * 0.10
    liquidity_comp = min(1.0, avg_vol_20d / 1_000_000) * 0.05
    
    momentum_likelihood = rel_vol_comp + pct_comp + vwap_comp + spread_comp + liquidity_comp
    
    print(f"  Rel Vol: {rel_vol:.1f}x → {rel_vol_comp:.3f}")
    print(f"  Pct Change: {current_pct:.1f}% (thresh {pct_thresh:.1f}%) → {pct_comp:.3f}")
    print(f"  VWAP: {vwap_trend} → {vwap_comp:.3f}")
    print(f"  Spread: {spread_ratio:.3f} (limit {spread_limit:.3f}) → {spread_comp:.3f}")
    print(f"  Liquidity: {avg_vol_20d:,} → {liquidity_comp:.3f}")
    print(f"  Total Momentum Likelihood: {momentum_likelihood:.3f}")
    print(f"  Meets threshold (>=0.6)? {'✓ YES' if momentum_likelihood >= 0.6 else '✗ NO'}")
    
    # Example 2: Weak momentum
    print(f"\nScenario 2: Weak Momentum")
    rel_vol = 1.5
    current_pct = 2.5
    vwap_trend = "neutral"
    
    rel_vol_comp = min(rel_vol / 3.0, 1.0) * 0.40
    pct_comp = min(current_pct / pct_thresh, 1.0) * 0.30
    vwap_comp = 0.5 * 0.15
    
    momentum_likelihood = rel_vol_comp + pct_comp + vwap_comp + spread_comp + liquidity_comp
    
    print(f"  Rel Vol: {rel_vol:.1f}x → {rel_vol_comp:.3f}")
    print(f"  Pct Change: {current_pct:.1f}% (thresh {pct_thresh:.1f}%) → {pct_comp:.3f}")
    print(f"  VWAP: {vwap_trend} → {vwap_comp:.3f}")
    print(f"  Spread: {spread_ratio:.3f} → {spread_comp:.3f}")
    print(f"  Liquidity: {avg_vol_20d:,} → {liquidity_comp:.3f}")
    print(f"  Total Momentum Likelihood: {momentum_likelihood:.3f}")
    print(f"  Meets threshold (>=0.6)? {'✓ YES' if momentum_likelihood >= 0.6 else '✗ NO'}")
    
    # Example 3: Volume threshold check
    print(f"\nScenario 3: Volume Threshold Check")
    avg_vol_20d = 10_000_000
    vol_multiplier = 0.015  # REGULAR hours
    vol_thresh_dynamic = max(ws.BASE_VOL_THRESH(session), avg_vol_20d * vol_multiplier)
    
    print(f"  Avg 20-day Volume: {avg_vol_20d:,}")
    print(f"  Dynamic Threshold: max({ws.BASE_VOL_THRESH(session):,}, {avg_vol_20d:,} * {vol_multiplier}) = {vol_thresh_dynamic:,.0f}")
    
    current_vols = [50000, 100000, 150000, 200000]
    for cv in current_vols:
        meets = cv > vol_thresh_dynamic
        print(f"  Current Vol: {cv:,} → {'✓ PASS' if meets else '✗ FAIL'}")
    
    print("\n" + "=" * 80)
    print("DIAGNOSIS COMPLETE")
    print("=" * 80)
    print("\nKey Insights:")
    print("  - For REGULAR hours, volume threshold is quite high (70K base + 1.5% of avg)")
    print("  - Momentum likelihood needs multiple strong components to reach 0.6")
    print("  - VWAP alignment provides significant boost (0.15 for bullish)")
    print("  - High relative volume (>3x) needed for full rel_vol component")
    print("  - If alerts aren't triggering, likely causes:")
    print("    1. Volume not exceeding threshold")
    print("    2. VWAP trending bearish or neutral (reducing likelihood)")
    print("    3. Percent change too small relative to threshold")
    print("    4. Alert cooldown active (5 minutes)")

if __name__ == "__main__":
    diagnose_alert_requirements()
