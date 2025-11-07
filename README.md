# Stock Momentum Alert System# Stock Momentum Detection System



Real-time stock momentum detection system using Polygon.io WebSocket API with multi-stage confirmation logic.A dual-stage momentum detector for stock trading with Telegram alerts and historical backtesting capabilities.



## 🎯 Features## Project Structure



- **Multi-Stage Detection**: ```

  - Stage 0: Watch List (broad coverage)stock/

  - Stage 1: Early Detection (momentum setup)├── polygon_websocket.py          # Main live trading system

  - Stage 2: Breakout Confirmation (cumulative expansion validation)├── data/                          # Static data files

  - Stage 3: Fast-Break Mode (parabolic moves)│   ├── tickers.csv               # List of symbols to monitor

│   └── minute_data_*.json        # Cached minute data

- **Quality Scoring**: 100-point scale evaluating relative volume, price expansion, trade density, spread tightness, and follow-through├── backtest/                      # Backtesting scripts

│   ├── backtest_flatfiles.py     # Backtest using Polygon flat files

- **Session-Adaptive**: Different thresholds for pre-market, regular hours, and post-market│   ├── backtest_flatfiles_ascii.py

│   └── backtest_momentum.py      # Backtest using REST API

- **Real-time Quotes**: Bid-ask spread calculation with fallback estimation├── tests/                         # Test scripts

│   ├── test_websocket_alerts.py

- **Telegram Alerts**: Instant notifications with entry, stop-loss, and take-profit levels│   ├── test_live_telegram.py

│   ├── test_simple.py

## 📁 Project Structure│   └── test_*.py

├── historical_data/               # Historical market data

```│   └── polygon_flatfiles/        # Downloaded Polygon flat files (CSV.gz)

stock/├── results/                       # Backtest results and outputs

├── polygon_websocket.py        # Main WebSocket client and detection engine│   ├── backtest_results_*.json

├── backtest_runner.py          # Backtesting framework│   └── backtest_output.txt

├── grid_search.py              # Threshold optimization (full grid)├── docs/                          # Documentation

├── grid_search_quick.py        # Quick grid search (extremes only)│   ├── BACKTEST_IMPROVEMENTS.md

├── download_minute_data.py     # Historical data downloader│   └── HEDGE_FUND_OPTIMIZATIONS.md

│└── backup/                        # Backup files

├── data/    └── polygon_websocket_backup.py

│   └── tickers.csv             # Monitored symbols list (7,665 stocks)

│```

├── historical_data/            # Downloaded minute bars (CSV.gz from Polygon)

├── results/                    # Grid search results## Quick Start

├── backtest/                   # Backtest scripts and output files

│### Live Trading

├── tests/                      # Test and diagnostic scripts```bash

│   ├── check_spread.py# Run the live momentum detector

│   ├── test_quotes.pypython polygon_websocket.py

│   └── README.md               # Test documentation```

│

├── docs/                       # Documentation### Backtesting

│   ├── SPREAD_FIX.md```bash

│   ├── README_GRID_SEARCH.md# Run enhanced backtest with historical flat files

│   ├── BACKTEST_IMPROVEMENTS.mdcd backtest

│   ├── HEDGE_FUND_OPTIMIZATIONS.mdpython backtest_flatfiles.py

│   └── PROJECT_STRUCTURE.md```

│

└── README.md                   # This file### Testing

``````bash

# Run tests

## 🚀 Quick Startcd tests

python test_websocket_alerts.py

### 1. Install Dependencies```

```bash

pip install polygon-api-client requests pytz boto3## Data Organization

```

### Historical Data

### 2. Configure API Keys- **Location**: `historical_data/polygon_flatfiles/`

Edit `polygon_websocket.py`:- **Format**: Gzipped CSV files (YYYY-MM-DD.csv.gz)

```python- **Source**: Polygon.io via Massive.io S3

API_KEY = "your_polygon_api_key"- **Retention**: Cached locally to avoid re-downloads

TELEGRAM_BOT_TOKEN = "your_telegram_bot_token"

TELEGRAM_CHAT_ID = "your_chat_id"### Results

```- **Location**: `results/`

- **Format**: JSON files with detailed backtest results

### 3. Run Live Monitoring- **Naming**: `backtest_results_flatfiles_YYYYMMDD_HHMMSS.json`

```bash

python polygon_websocket.py### Data Files

```- **Location**: `data/`

- **tickers.csv**: 7,665 symbols to monitor

The system will:- **minute_data_*.json**: Cached minute-level data for quick access

- Connect to Polygon.io WebSocket

- Load tickers from `data/tickers.csv`## Enhanced Thresholds (Production)

- Monitor pre-market (4:00-9:30 AM), regular hours (9:30 AM-4:00 PM), and post-market (4:00-8:00 PM ET)

- Send Telegram alerts for confirmed setups### Stage 1: Early Detection

- **Premarket**: rel_vol ≥3.5x, pct ≥5%, 10+ trades, vol ≥50K

## 📊 Grid Search (Threshold Optimization)- **Regular**: rel_vol ≥4.0x, pct ≥6%, 10+ trades, vol ≥150K

- **Postmarket**: rel_vol ≥3.5x, pct ≥5%, 10+ trades, vol ≥40K

### Run Full Grid Search

```bash### Stage 2: Confirmed Breakout

python grid_search.py- **Premarket**: rel_vol ≥5.5x, pct ≥10%, vol ≥50K

```- **Regular**: rel_vol ≥6.0x, pct ≥10%, vol ≥150K

- Tests 256 threshold combinations (4×4×4×4 grid)- **Postmarket**: rel_vol ≥5.0x, pct ≥9%, vol ≥40K

- Runs backtest on historical data

- Generates CSV with metrics for each combination### Quality Filters

- Outputs top performers by win rate and alert count- ✅ Price ≥0.5-1.0% above VWAP

- ✅ Minimum 10-15 trades per minute

### Run Quick Grid Search- ✅ Candle range ≥1%

```bash- ✅ Volume sustained (not declining)

python grid_search_quick.py- ✅ Price expansion ≥2% from setup

```

- Tests 16 combinations (parameter extremes only)## Performance Targets

- Faster for initial exploration

- **Win Rate**: 50%+ (previous: 15.17%)

See `docs/README_GRID_SEARCH.md` for detailed grid search documentation.- **Risk/Reward**: 1:4 (-2% stop, +8% target)

- **Alert Quality**: HIGH (filtered for explosive breakouts)

## 🧪 Testing- **Frequency**: 5-15 quality alerts per day (vs 136/day unfiltered)



See `tests/README.md` for full test suite documentation.## Configuration



Quick tests:### API Keys

```bashEdit `polygon_websocket.py`:

python tests/check_spread.py        # Verify spread calculation```python

python tests/test_quotes.py          # Test quote receptionAPI_KEY = "your_polygon_api_key"

python tests/test_all_feeds.py       # Test all Polygon feedsTELEGRAM_BOT_TOKEN = "your_telegram_bot_token"

```TELEGRAM_CHAT_ID = "your_chat_id"

```

## 📈 Backtesting

### Massive.io S3 Credentials

```bashEdit `backtest/backtest_flatfiles.py`:

python backtest_runner.py```python

```MASSIVE_ACCESS_KEY = "your_access_key"

MASSIVE_SECRET_KEY = "your_secret_key"

Features:```

- Replay historical minute bars

- Simulate entry/exit with stop-loss and take-profit## Requirements

- Track win rate, average gain, max gain/loss

- Export trade log to `backtest/` folder```bash

pip install polygon-api-client requests pytz boto3

## ⚙️ Configuration```



### Environment Variables## Features

- `TICKER_FILE`: Custom ticker list path (default: `data/tickers.csv`)

- `DISABLE_NOTIFICATIONS="1"`: Suppress Telegram alerts (useful for backtesting)- ✅ Dual-stage momentum detection (Early + Confirmed)

- `STAGE2_DEBUG="1"`: Enable detailed Stage 2 diagnostic logging- ✅ Session-adaptive thresholds (Pre/Regular/Post market)

- ✅ Telegram alerts with trade plans

### Session Thresholds (Current Production)- ✅ VWAP-based risk management

- ✅ Historical backtesting with flat files

#### Pre-Market (4:00-9:30 AM ET)- ✅ Quality filtering (10+ criteria)

- Volume threshold: 30,000- ✅ Volume consistency checks

- Spread limit: 3.0%- ✅ Spread validation

- Stage 1: 3.8% move, 2.4x relative volume- ✅ Trade count minimums

- Stage 2: 7.8% expansion, 4.1x relative volume

## Recent Updates

#### Regular Hours (9:30 AM-4:00 PM ET)

- Volume threshold: 90,000**November 6, 2025**: Enhanced thresholds to improve win rate

- Spread limit: 2.0%- Increased rel_vol requirements by 40-60%

- Stage 1: 4.5% move, 2.5x relative volume- Raised price change minimums by 50-67%

- Stage 2: 7.8% expansion, 4.3x relative volume- Added 6 new quality filters

- Reorganized project structure

#### Post-Market (4:00-8:00 PM ET)- Moved historical data to dedicated folder

- Volume threshold: 24,000

- Spread limit: 3.8%## License

- Stage 1: 3.8% move, 2.3x relative volume

- Stage 2: 7.0% expansion, 4.0x relative volumePrivate trading system - Not for redistribution


**Optimize these using grid search results!**

## 📋 Quality Score Breakdown

**Total: 100 points**
- **Relative Volume (28 pts)**: Capped at 8x average volume
- **Percent Change (18 pts)**: Capped at 14% to avoid parabolic traps
- **Volume vs Threshold (14 pts)**: Proportional up to 2x threshold
- **Trade Density (12 pts)**: Higher trade count = broader participation
- **Spread Tightness (10 pts)**: Penalizes illiquid stocks
- **Expansion & Follow-through (18 pts)**: Cumulative price expansion + acceleration + sustained volume

**Penalties**:
- Parabolic spike without volume sustain: -6 pts max
- Retail churn (avg trade size <120 shares): -4 pts

Minimum quality gates:
- Stage 1: 50 points
- Stage 2: 60 points (58 for alternative confirmation path)

## 🔧 Troubleshooting

### No Quotes Received
- Verify Polygon.io plan includes real-time quotes (not just trades)
- System will use fallback spread estimation if quotes unavailable (0.1%-1.0% based on price tier)

### No Alerts Generated
- Enable Stage 2 debug: `$env:STAGE2_DEBUG="1"`
- Review grid search results for optimal parameters
- Verify tickers in `data/tickers.csv` are active and liquid

### Backtest Issues
- Ensure historical data downloaded: `python download_minute_data.py`
- Check `historical_data/` folder for CSV.gz files

## 📚 Documentation

- **[Grid Search Guide](docs/README_GRID_SEARCH.md)**: Threshold optimization workflow
- **[Spread Fix](docs/SPREAD_FIX.md)**: Spread calculation implementation
- **[Backtest Improvements](docs/BACKTEST_IMPROVEMENTS.md)**: Backtesting enhancements
- **[Hedge Fund Optimizations](docs/HEDGE_FUND_OPTIMIZATIONS.md)**: Quality filter rationale
- **[Project Structure](docs/PROJECT_STRUCTURE.md)**: Architecture overview
- **[Test Suite](tests/README.md)**: Testing documentation

## 🎯 Performance Targets

- **Win Rate**: 50%+ (historical backtest baseline: 15-40%)
- **Risk/Reward**: 1:4 (-2% stop-loss, +8% take-profit)
- **Alert Quality**: Focus on high-quality setups only
- **Frequency**: 5-15 quality alerts per day

## ⚠️ Disclaimer

This software is for educational purposes only. Not financial advice. Trading stocks involves substantial risk of loss. Always do your own research and never invest more than you can afford to lose.

## 🔗 Resources

- [Polygon.io API Documentation](https://polygon.io/docs)
- [WebSocket Streams](https://polygon.io/docs/stocks/ws_stocks_t)
- [Telegram Bot API](https://core.telegram.org/bots/api)

## 📝 Recent Updates

**November 7, 2025**: Project reorganization
- Moved all test files to `tests/` folder
- Moved documentation to `docs/` folder
- Removed unnecessary debug logging
- Created comprehensive READMEs
- Cleaned up polygon_websocket.py

**November 6, 2025**: Spread calculation fix
- Fixed spread showing "n/a" in alerts
- Added fallback_price parameter for reliable estimation
