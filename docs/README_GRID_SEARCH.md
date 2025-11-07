# Grid Search for Optimal Detection Thresholds

Automated parameter optimization to find the best momentum detection thresholds by testing all combinations and measuring backtest performance.

## Quick Start

### 1. Download Historical Data

First, download minute-level bars from Polygon.io:

```powershell
python download_minute_data.py --days 9
```

This creates cached data in `data/minute_bars/minute_bars_YYYYMMDD.json.gz` for each day.

**Note**: Free Polygon tier has rate limits (~7 req/sec). Download may take 5-10 minutes for 9 days × 7665 tickers.

### 2. Run Grid Search

Execute the grid search over all threshold combinations:

```powershell
python grid_search.py
```

This will:
- Test all combinations of:
  - `pct_thresh_early`: [3.0, 3.8, 4.5]
  - `min_rel_vol_stage1`: [2.0, 2.4, 2.8]
  - `pct_thresh_confirm`: [6.0, 7.0, 7.8]
  - `min_rel_vol_stage2`: [3.5, 4.1, 4.8]
- Run backtest on each combination (limited to 20 symbols for speed)
- Simulate trade outcomes (2% stop, 8% target, 30min timeout)
- Output results to `results/grid_search_YYYYMMDD_HHMMSS.csv`
- Print best configuration to console

### 3. Analyze Results

The CSV contains columns:
- Threshold parameters (pct_thresh_early, min_rel_vol_stage1, etc.)
- Performance metrics:
  - `alerts`: Total alerts generated
  - `stage1`, `stage2`: Breakdown by stage
  - `win_rate`: % of trades with positive gain
  - `avg_gain`: Average % gain per trade
  - `max_gain`, `max_loss`: Extreme outcomes
  - `avg_hold_time`: Minutes held on average
  - `stops`, `targets`, `timeouts`: Outcome distribution

Sort by `win_rate` and `avg_gain` to identify best parameters.

## Customization

### Expand Grid Space

Edit `GRID` in `grid_search.py`:

```python
GRID = {
    'pct_thresh_early': [2.0, 3.0, 4.0, 5.0],  # add more values
    'min_rel_vol_stage1': [1.5, 2.0, 2.5, 3.0, 3.5],
    'pct_thresh_confirm': [5.0, 6.0, 7.0, 8.0, 9.0],
    'min_rel_vol_stage2': [3.0, 4.0, 5.0, 6.0],
}
```

**Warning**: Combinations grow exponentially (4×5×5×4 = 400 combinations). Runtime scales linearly.

### Adjust Date Range

Modify `dates` generation in `main()`:

```python
# Test over 30 days instead of 9
dates = [(end_date - timedelta(days=i)).strftime('%Y%m%d') for i in range(30)]
```

### Change Outcome Thresholds

Edit constants at top of `grid_search.py`:

```python
STOP_LOSS_PCT = 0.015  # 1.5% stop
TARGET_PCT = 0.10      # 10% target
TIMEOUT_MINUTES = 45   # 45 minute timeout
```

## Heatmap Visualization

To generate a heatmap (requires pandas + seaborn):

```python
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

df = pd.read_csv('results/grid_search_YYYYMMDD_HHMMSS.csv')
pivot = df.pivot_table(
    values='win_rate',
    index='pct_thresh_early',
    columns='min_rel_vol_stage1',
    aggfunc='mean'
)
sns.heatmap(pivot, annot=True, fmt='.1f', cmap='RdYlGn')
plt.title('Win Rate by Early % Threshold vs Rel Vol')
plt.show()
```

## Limitations

1. **Threshold Injection**: Current implementation replays bars through `check_spike` with **internal** thresholds. For true threshold override, refactor `check_spike` to accept kwargs.
2. **Symbol Subset**: Grid search limits to 20 symbols for speed. Expand `symbols[:20]` to `symbols` for full coverage (slower).
3. **Spread Data**: Backtest uses flatfile data without live bid/ask spreads; spread_ratio will be `None` for all bars.
4. **Single Session**: Grid currently tests one threshold set across all sessions (pre/regular/post). Consider session-specific grids.

## Next Steps

After identifying optimal thresholds:
1. Update `polygon_websocket.py` with best values
2. Re-run full backtest on all symbols
3. Monitor live alerts for 1-2 days
4. Fine-tune based on real-world false positive rate
5. Consider session-specific optimization (separate grids for PREMARKET/REGULAR/POSTMARKET)

## Performance Tips

- **Parallel Processing**: Modify `run_backtest` to use `multiprocessing.Pool` for parallel combination testing
- **Caching**: Pre-load all flatfiles once into memory before loop
- **Sampling**: Test on random sample of dates/symbols first to narrow grid range before full search
