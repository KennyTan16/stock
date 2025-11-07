"""
Quick Grid Search - Tests key parameter extremes only
Runs 16 combinations instead of 256 for faster iteration
"""
import sys
sys.path.insert(0, '.')
from grid_search import *

# Override GRID with focused extremes
GRID = {
    'pct_thresh_early': [2.5, 4.5],        # Just low and high
    'min_rel_vol_stage1': [1.5, 2.8],      # Just low and high  
    'pct_thresh_confirm': [5.0, 8.5],      # Just low and high
    'min_rel_vol_stage2': [3.0, 5.0],      # Just low and high
}

if __name__ == "__main__":
    print("=== QUICK Grid Search (16 combinations) ===\n")
    main()
