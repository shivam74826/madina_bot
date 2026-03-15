# Forex AI Trading Bot — Exness XAUUSD

A fully automated AI-powered Forex trading bot built for **Exness** broker, integrated with **MetaTrader 5** for live/demo trading. Specializes in **XAUUSD (Gold)** trading using machine learning predictions combined with technical analysis across multiple strategies, wrapped in professional risk management.

## Broker

- **Exness** — [www.exness.com](https://www.exness.com)
- Connected via MetaTrader 5 (MT5)
- Primary symbol: **XAUUSDm** (Gold micro on Exness)
- Supports both Exness Demo and Real accounts

---

## Features

### AI & Analysis
- **Machine Learning Predictor** — Ensemble model (Random Forest + Gradient Boosting) trained on 70+ engineered features
- **20+ Technical Indicators** — RSI, MACD, Bollinger Bands, ADX, Ichimoku, Stochastic, CCI, Parabolic SAR, and more
- **Smart Money Concepts (SMC)** — Order blocks, fair value gaps, break of structure, liquidity sweeps
- **Candlestick Pattern Detection** — Doji, Engulfing, Morning/Evening Star, Three White Soldiers/Black Crows
- **Market Regime Detection** — Identifies trending, ranging, or volatile markets
- **News Impact Analysis** — Fetches and scores economic news to avoid high-impact events
- **Session-Aware Trading** — Adapts to Sydney, Tokyo, London, and New York sessions
- **Trade Journal & AI Learning** — Automatically journals trades and extracts lessons for continuous improvement

### Trading Strategies
| Strategy | Description |
|----------|-------------|
| **Trend Following** | Rides strong trends using MA alignment + ADX confirmation + MACD + Ichimoku |
| **Mean Reversion** | Catches reversals at Bollinger Band extremes + RSI/Stochastic oversold/overbought |
| **Smart Money (SMC)** | Institutional order flow — order blocks, FVG, BOS, liquidity sweeps |
| **Breakout** | Detects range breakouts with volume confirmation |
| **AI Enhanced** | ML prediction as primary signal, confirmed by technical analysis and regime check |
| **Multi-Strategy Ensemble** | Combines all strategies — takes the highest-confidence signal with directional agreement |

### Risk Management
- **Position Sizing** — Automatic lot calculation based on account risk (default 2% per trade)
- **Daily Loss Limit** — Stops trading if daily loss exceeds threshold (default 6%)
- **Maximum Drawdown Protection** — Emergency close-all if drawdown limit hit (default 15%)
- **Trailing Stops** — Dynamic trailing stop loss management
- **Break-Even Protection** — Moves stop loss to entry price after profit threshold
- **Margin Level Monitoring** — Prevents over-leveraging
- **Live Trade Manager** — Manages open positions with real-time SL/TP adjustments

### Dashboard
- Real-time web dashboard at `http://127.0.0.1:5000`
- Live Exness account stats, open positions, and trade history
- Per-symbol technical analysis signals
- Risk meters and session indicators
- One-click position closing

### Email Notifications
- Trade entry/exit alerts via email
- Daily P&L summaries
- Error and emergency notifications

---

## Quick Start

### Prerequisites
1. **Exness Account** — Register at [www.exness.com](https://www.exness.com) (Demo or Real)
2. **MetaTrader 5** — Download from Exness Personal Area and install on Windows
3. **Python 3.10+** (Windows)

### Installation

```bash
# Clone the repository
git clone https://github.com/shivam74826/AI-forex-trading-boat.git
cd AI-forex-trading-boat

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root with your Exness MT5 credentials:

```env
MT5_LOGIN=your_exness_login
MT5_PASSWORD=your_exness_password
MT5_SERVER=Exness-MT5Trial    # or Exness-MT5Real for live
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
```

> **Security Note:** Never commit your `.env` file or share your credentials. The `.env` file is excluded from version control via `.gitignore`.

You can also set these as environment variables:
```bash
set MT5_LOGIN=your_exness_login
set MT5_PASSWORD=your_exness_password
set MT5_SERVER=Exness-MT5Trial
```

### Running the Bot

```bash
# Demo mode on Exness (default - safe for testing)
python main.py --mode demo --symbols XAUUSDm

# Paper trading (logs signals, no real orders)
python main.py --mode paper --symbols XAUUSDm

# Live trading on Exness (real money - use with caution!)
python main.py --mode live --symbols XAUUSDm

# Quick start script for XAUUSD
python run_xauusd.py

# Dashboard only
python main.py --dashboard

# No dashboard
python main.py --mode demo --symbols XAUUSDm --no-dashboard
```

Then open your browser to **http://127.0.0.1:5000** to see the dashboard.

---

## Exness-Specific Notes

- **Symbol naming**: Exness uses suffix formats like `XAUUSDm` (micro), `XAUUSDc` (cent), or `XAUUSD` (standard). Make sure the symbol in your config matches your account type.
- **Server names**: Common Exness servers include `Exness-MT5Trial` (demo), `Exness-MT5Real` and numbered variants like `Exness-MT5Real2`, `Exness-MT5Real15`, etc.
- **Spread**: Exness offers competitive spreads on Gold — the bot accounts for spread in position sizing and risk calculations.
- **Leverage**: Exness provides high leverage on Gold (up to 1:2000). The bot's risk management ensures safe position sizing regardless of available leverage.
- **Trading hours**: XAUUSD is available nearly 24/5 on Exness. The bot respects configured trading hours and session windows.

---

## Project Structure

```
AI-forex-trading-boat/
├── config/
│   └── settings.py              # All configuration (risk, AI, indicators, etc.)
├── core/
│   ├── mt5_connector.py         # MetaTrader 5 connection & data
│   ├── order_manager.py         # Order execution & trailing stops
│   ├── live_trade_manager.py    # Live position management
│   ├── mt5_lock.py              # Thread-safe MT5 access
│   └── data_fetcher.py          # Market data retrieval & caching
├── analysis/
│   ├── technical.py             # 20+ technical indicators & signals
│   ├── market_structure.py      # SMC market structure analysis
│   ├── news_analyzer.py         # Economic news impact scoring
│   └── sentiment.py             # Market regime, sessions, currency strength
├── ai/
│   ├── feature_engineering.py   # 70+ ML features from price data
│   ├── predictor.py             # AI ensemble model (RF + GBM)
│   └── trade_journal.py         # AI trade journaling & lesson extraction
├── strategy/
│   ├── base_strategy.py         # Strategy interface
│   ├── trend_following.py       # Trend following strategy
│   ├── mean_reversion.py        # Mean reversion strategy
│   ├── breakout_strategy.py     # Breakout detection strategy
│   ├── smc_strategy.py          # Smart Money Concepts strategy
│   └── ai_strategy.py           # AI-enhanced + multi-strategy manager
├── risk/
│   └── risk_manager.py          # Position sizing, daily limits, drawdown
├── dashboard/
│   ├── app.py                   # Flask web server
│   └── templates/
│       ├── index.html           # Dashboard UI
│       └── chart.html           # Chart page
├── utils/
│   ├── logger.py                # Logging & trade CSV logger
│   └── email_notifier.py        # Email alerts & notifications
├── logs/                        # Trade logs & daily analysis
├── models/                      # Saved ML models
├── main.py                      # Bot entry point
├── run_xauusd.py                # Quick-start script for XAUUSD
├── backtest.py                  # Strategy backtesting
├── analyze_today.py             # Daily market analysis tool
├── analyze_timeframe.py         # Multi-timeframe analysis tool
├── check_status.py              # Bot status checker
├── diagnose_signal.py           # Signal diagnostics
├── requirements.txt             # Python dependencies
└── .env                         # Your Exness credentials (not committed)
```

---

## Configuration Guide

All settings are in `config/settings.py`. Key parameters:

### Risk Parameters
| Setting | Default | Description |
|---------|---------|-------------|
| `max_risk_per_trade` | 2% | Maximum account risk per trade |
| `max_daily_risk` | 6% | Daily loss limit |
| `max_drawdown` | 15% | Maximum drawdown before emergency shutdown |
| `risk_reward_ratio` | 2.0 | Minimum R:R to accept a trade |
| `trailing_stop_pips` | 30 | Trailing stop distance |
| `break_even_pips` | 20 | Move SL to break-even after this profit |

### AI Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `min_confidence` | 0.65 | Minimum AI confidence to trade |
| `prediction_horizon` | 24 | Candles ahead to predict |
| `retrain_interval_hours` | 168 | Retrain models weekly |
| `training_lookback_days` | 365 | Historical data for training |

### Trading Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `max_open_trades` | 5 | Maximum simultaneous positions |
| `max_trades_per_symbol` | 2 | Max positions per symbol |
| `trading_hours_start` | 1 (UTC) | Start of trading window |
| `trading_hours_end` | 22 (UTC) | End of trading window |

---

## How It Works

### Trading Cycle (every 60 seconds)
1. **Connection Check** — Verify Exness MT5 is connected, reconnect if needed
2. **Emergency Scan** — Check drawdown and margin levels
3. **Position Management** — Update trailing stops and break-even levels
4. **For Each Symbol (XAUUSD):**
   - Fetch latest OHLCV data (500 candles)
   - Run all strategies in parallel (Trend, Mean Reversion, SMC, Breakout, AI)
   - Select best signal (highest confidence + directional agreement)
   - Validate through risk manager (limits, margin, hours, R:R)
   - Calculate position size based on stop loss and risk %
   - Execute order on Exness via MetaTrader 5
5. **AI Retraining** — Retrain models if due (weekly)
6. **Trade Journaling** — Log signals, trades, and extract lessons
7. **Email Alerts** — Notify on trade entries, exits, and errors

### AI Model Details
- **Features**: 70+ engineered features including returns, volatility, technical indicators, candle patterns, statistical moments, and time-of-day encoding
- **Models**: Voting ensemble of Random Forest (200 trees) + Gradient Boosting (150 estimators)
- **Training**: Time-series split (no data leakage), 80/20 train/test
- **Retraining**: Automatic weekly retraining with latest data

---

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `run_xauusd.py` | Quick-start the bot for XAUUSD on Exness |
| `backtest.py` | Run strategy backtests on historical data |
| `analyze_today.py` | Get today's market analysis summary |
| `analyze_timeframe.py` | Multi-timeframe analysis for any symbol |
| `check_status.py` | Check bot and MT5 connection status |
| `diagnose_signal.py` | Debug why a signal was or wasn't generated |
| `test_email.py` | Test email notification setup |
| `verify_config.py` | Validate configuration before running |

---

## Important Disclaimers

> **RISK WARNING**: Trading foreign exchange and CFDs (including Gold/XAUUSD) carries a high level of risk and may not be suitable for all investors. Past performance is not indicative of future results. Only trade with money you can afford to lose.

> **NO GUARANTEE**: This bot does not guarantee profits. Markets are unpredictable and no AI system can predict them with certainty.

> **START WITH DEMO**: Always start with an Exness demo account. Only switch to live trading after thorough testing and understanding of the bot's behavior.

> **MONITOR ACTIVELY**: Even in automated mode, monitor the bot regularly. Technology can fail.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "MT5 initialization failed" | Ensure MetaTrader 5 (Exness) is installed and running. Check the path in config. |
| "Login failed" | Verify your Exness MT5 credentials (login, password, server). Check server name matches your account (e.g., `Exness-MT5Trial`). |
| "Symbol not found" | Exness uses suffixed symbols — try `XAUUSDm` (micro) or `XAUUSD` (standard) depending on your account type. |
| "Insufficient data" | Wait for the market to be open, or increase the data lookback period. |
| Dashboard not loading | Check that port 5000 is free. Try `http://localhost:5000`. |

---

## Author

**Aaditya Pandey**

## License

This project is for educational and personal use. Use at your own risk.
