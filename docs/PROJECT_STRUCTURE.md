# Quick Reference - Project Organization

## Folder Structure

```
📁 stock/
│
├── 📄 polygon_websocket.py       ← Main live trading system
├── 📄 README.md                   ← Project documentation
│
├── 📁 data/                       ← Static data & configuration
│   ├── tickers.csv               ← 7,665 symbols to monitor
│   └── minute_data_*.json        ← Cached minute data
│
├── 📁 backtest/                   ← Backtesting scripts
│   ├── backtest_flatfiles.py     ← Enhanced backtest (flat files)
│   ├── backtest_flatfiles_ascii.py
│   └── backtest_momentum.py      ← REST API backtest
│
├── 📁 tests/                      ← Test scripts
│   ├── test_websocket_alerts.py
│   ├── test_live_telegram.py
│   └── test_*.py
│
├── 📁 historical_data/            ← Downloaded market data
│   └── polygon_flatfiles/        ← Polygon CSV.gz files
│       ├── 2025-10-24.csv.gz
│       ├── 2025-10-25.csv.gz
│       └── ...
│
├── 📁 results/                    ← Backtest outputs
│   ├── backtest_results_*.json
│   └── backtest_output.txt
│
├── 📁 docs/                       ← Documentation
│   ├── BACKTEST_IMPROVEMENTS.md
│   └── HEDGE_FUND_OPTIMIZATIONS.md
│
└── 📁 backup/                     ← Backup files
    └── polygon_websocket_backup.py
```

## File Paths Changed

### Before Reorganization
```python
CACHE_DIR = Path("polygon_cache")           # Old location
tickers_csv = "tickers.csv"                 # Root folder
output_file = "backtest_results_*.json"     # Root folder
```

### After Reorganization
```python
CACHE_DIR = Path("../historical_data/polygon_flatfiles")  # Organized
tickers_csv = "../data/tickers.csv"                       # Data folder
output_file = "../results/backtest_results_*.json"        # Results folder
```

## Running Commands

### From Root Directory
```bash
# Live trading
python polygon_websocket.py

# View structure
tree /F
```

### From Backtest Directory
```bash
cd backtest
python backtest_flatfiles.py        # Enhanced backtest
python backtest_momentum.py         # REST API backtest
```

### From Tests Directory
```bash
cd tests
python test_websocket_alerts.py
python test_live_telegram.py
```

## Key Benefits

✅ **Organized**: Clear separation of concerns
✅ **Clean**: No clutter in root directory
✅ **Scalable**: Easy to add new modules
✅ **Professional**: Industry-standard structure
✅ **Maintainable**: Easy to find files
✅ **Git-friendly**: Better .gitignore organization

## Data Flow

```
Live Trading:
polygon_websocket.py → Polygon API → Telegram Alerts

Backtesting:
1. backtest_flatfiles.py downloads data
2. Stores in historical_data/polygon_flatfiles/
3. Processes bars for all tickers
4. Outputs results to results/
5. Uses tickers from data/tickers.csv
```

## Import Path Updates

Backtest scripts now use relative imports:
```python
sys.path.insert(0, os.path.abspath('..'))
from polygon_websocket import check_spike, ...
```

This allows them to import the main module from the parent directory.

## Historical Data Storage

- **Old**: `polygon_cache/2025-10-24.csv.gz` (root folder)
- **New**: `historical_data/polygon_flatfiles/2025-10-24.csv.gz` (organized)

Benefits:
- Clear separation from code
- Easy to backup/archive
- Can gitignore entire folder
- Room for other data sources

## Results Organization

All backtest outputs now go to `results/`:
- JSON files with detailed metrics
- Output logs
- Performance summaries
- Easy to compare different runs

## Next Steps

1. **Test the structure**: Run a backtest
2. **Update .gitignore**: Add `historical_data/`, `results/`, `__pycache__/`
3. **Archive old results**: Move to dated folders
4. **Document**: Keep README.md updated
