# Stock Momentum Detection System

A dual-stage momentum detector for stock trading with Telegram alerts and historical backtesting capabilities.

## Project Structure

```
stock/
├── polygon_websocket.py          # Main live trading system
├── data/                          # Static data files
│   ├── tickers.csv               # List of symbols to monitor
│   └── minute_data_*.json        # Cached minute data
├── backtest/                      # Backtesting scripts
│   ├── backtest_flatfiles.py     # Backtest using Polygon flat files
│   ├── backtest_flatfiles_ascii.py
│   └── backtest_momentum.py      # Backtest using REST API
├── tests/                         # Test scripts
│   ├── test_websocket_alerts.py
│   ├── test_live_telegram.py
│   ├── test_simple.py
│   └── test_*.py
├── historical_data/               # Historical market data
│   └── polygon_flatfiles/        # Downloaded Polygon flat files (CSV.gz)
├── results/                       # Backtest results and outputs
│   ├── backtest_results_*.json
│   └── backtest_output.txt
├── docs/                          # Documentation
│   ├── BACKTEST_IMPROVEMENTS.md
│   └── HEDGE_FUND_OPTIMIZATIONS.md
└── backup/                        # Backup files
    └── polygon_websocket_backup.py

```

## Quick Start

### Live Trading
```bash
# Run the live momentum detector
python polygon_websocket.py
```

### Backtesting
```bash
# Run enhanced backtest with historical flat files
cd backtest
python backtest_flatfiles.py
```

### Testing
```bash
# Run tests
cd tests
python test_websocket_alerts.py
```

## Data Organization

### Historical Data
- **Location**: `historical_data/polygon_flatfiles/`
- **Format**: Gzipped CSV files (YYYY-MM-DD.csv.gz)
- **Source**: Polygon.io via Massive.io S3
- **Retention**: Cached locally to avoid re-downloads

### Results
- **Location**: `results/`
- **Format**: JSON files with detailed backtest results
- **Naming**: `backtest_results_flatfiles_YYYYMMDD_HHMMSS.json`

### Data Files
- **Location**: `data/`
- **tickers.csv**: 7,665 symbols to monitor
- **minute_data_*.json**: Cached minute-level data for quick access

## Enhanced Thresholds (Production)

### Stage 1: Early Detection
- **Premarket**: rel_vol ≥3.5x, pct ≥5%, 10+ trades, vol ≥50K
- **Regular**: rel_vol ≥4.0x, pct ≥6%, 10+ trades, vol ≥150K
- **Postmarket**: rel_vol ≥3.5x, pct ≥5%, 10+ trades, vol ≥40K

### Stage 2: Confirmed Breakout
- **Premarket**: rel_vol ≥5.5x, pct ≥10%, vol ≥50K
- **Regular**: rel_vol ≥6.0x, pct ≥10%, vol ≥150K
- **Postmarket**: rel_vol ≥5.0x, pct ≥9%, vol ≥40K

### Quality Filters
- ✅ Price ≥0.5-1.0% above VWAP
- ✅ Minimum 10-15 trades per minute
- ✅ Candle range ≥1%
- ✅ Volume sustained (not declining)
- ✅ Price expansion ≥2% from setup

## Performance Targets

- **Win Rate**: 50%+ (previous: 15.17%)
- **Risk/Reward**: 1:4 (-2% stop, +8% target)
- **Alert Quality**: HIGH (filtered for explosive breakouts)
- **Frequency**: 5-15 quality alerts per day (vs 136/day unfiltered)

## Configuration

### API Keys
Edit `polygon_websocket.py`:
```python
API_KEY = "your_polygon_api_key"
TELEGRAM_BOT_TOKEN = "your_telegram_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"
```

### Massive.io S3 Credentials
Edit `backtest/backtest_flatfiles.py`:
```python
MASSIVE_ACCESS_KEY = "your_access_key"
MASSIVE_SECRET_KEY = "your_secret_key"
```

## Requirements

```bash
pip install polygon-api-client requests pytz boto3
```

## Features

- ✅ Dual-stage momentum detection (Early + Confirmed)
- ✅ Session-adaptive thresholds (Pre/Regular/Post market)
- ✅ Telegram alerts with trade plans
- ✅ VWAP-based risk management
- ✅ Historical backtesting with flat files
- ✅ Quality filtering (10+ criteria)
- ✅ Volume consistency checks
- ✅ Spread validation
- ✅ Trade count minimums

## Recent Updates

**November 6, 2025**: Enhanced thresholds to improve win rate
- Increased rel_vol requirements by 40-60%
- Raised price change minimums by 50-67%
- Added 6 new quality filters
- Reorganized project structure
- Moved historical data to dedicated folder

## License

Private trading system - Not for redistribution
