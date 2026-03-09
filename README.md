# Forex AI Trading Bot

A fully automated AI-powered Forex trading bot that integrates with **MetaTrader 5** for live/demo trading. Combines machine learning predictions with technical analysis across multiple strategies, wrapped in professional risk management.

## Features

### AI & Analysis
- **Machine Learning Predictor** - Ensemble model (Random Forest + Gradient Boosting) trained on 70+ engineered features
- **20+ Technical Indicators** - RSI, MACD, Bollinger Bands, ADX, Ichimoku, Stochastic, CCI, Parabolic SAR, and more
- **Candlestick Pattern Detection** - Doji, Engulfing, Morning/Evening Star, Three White Soldiers/Black Crows
- **Market Regime Detection** - Identifies trending, ranging, or volatile markets
- **Currency Strength Analysis** - Relative strength across all major currencies
- **Session-Aware Trading** - Adapts to Sydney, Tokyo, London, and New York sessions

### Trading Strategies
| Strategy | Description |
|----------|-------------|
| **Trend Following** | Rides strong trends using MA alignment + ADX confirmation + MACD + Ichimoku |
| **Mean Reversion** | Catches reversals at Bollinger Band extremes + RSI/Stochastic oversold/overbought |
| **AI Enhanced** | ML prediction as primary signal, confirmed by technical analysis and regime check |
| **Multi-Strategy Ensemble** | Combines all strategies — takes the highest-confidence signal with directional agreement |

### Risk Management
- **Position Sizing** - Automatic lot calculation based on account risk (default 2% per trade)
- **Daily Loss Limit** - Stops trading if daily loss exceeds threshold (default 6%)
- **Maximum Drawdown Protection** - Emergency close-all if drawdown limit hit (default 15%)
- **Trailing Stops** - Dynamic trailing stop loss management
- **Break-Even Protection** - Moves stop loss to entry price after profit threshold
- **Margin Level Monitoring** - Prevents over-leveraging

### Dashboard
- Real-time web dashboard at `http://127.0.0.1:5000`
- Live account stats, open positions, and trade history
- Per-symbol technical analysis signals
- Risk meters and session indicators
- One-click position closing

---

## Quick Start

### Prerequisites
1. **MetaTrader 5** installed and running on Windows
2. **Python 3.10+** (Windows)
3. A demo or live trading account with your broker

### Installation

```bash
# Clone or navigate to the project
cd "D:\Forex tradding bot"

# Install dependencies
pip install -r requirements.txt
```

### Configuration

**Option 1: Environment Variables** (recommended)
```bash
set MT5_LOGIN=12345678
set MT5_PASSWORD=your_password
set MT5_SERVER=YourBroker-Demo
```

**Option 2: .env file**
Copy `.env.example` to `.env` and fill in your credentials.

**Option 3: Edit config directly**
Modify `config/settings.py` with your MT5 credentials and preferences.

### Running the Bot

```bash
# Demo mode (default - safe for testing)
python main.py --mode demo

# Paper trading (logs signals, no real orders)
python main.py --mode paper

# Live trading (real money - use with caution!)
python main.py --mode live

# Dashboard only
python main.py --dashboard

# Custom symbols
python main.py --mode demo --symbols EURUSD GBPUSD USDJPY

# No dashboard
python main.py --mode demo --no-dashboard
```

Then open your browser to **http://127.0.0.1:5000** to see the dashboard.

---

## Project Structure

```
Forex tradding bot/
├── config/
│   └── settings.py              # All configuration (risk, AI, indicators, etc.)
├── core/
│   ├── mt5_connector.py         # MetaTrader 5 connection & data
│   ├── order_manager.py         # Order execution & trailing stops
│   └── data_fetcher.py          # Market data retrieval & caching
├── analysis/
│   ├── technical.py             # 20+ technical indicators & signals
│   └── sentiment.py             # Market regime, sessions, currency strength
├── ai/
│   ├── feature_engineering.py   # 70+ ML features from price data
│   └── predictor.py             # AI ensemble model (RF + GBM)
├── strategy/
│   ├── base_strategy.py         # Strategy interface
│   ├── trend_following.py       # Trend following strategy
│   ├── mean_reversion.py        # Mean reversion strategy
│   └── ai_strategy.py           # AI-enhanced + multi-strategy manager
├── risk/
│   └── risk_manager.py          # Position sizing, daily limits, drawdown
├── dashboard/
│   ├── app.py                   # Flask web server
│   └── templates/index.html     # Dashboard UI
├── utils/
│   └── logger.py                # Logging & trade CSV logger
├── main.py                      # Bot entry point
├── requirements.txt             # Python dependencies
└── .env.example                 # Credential template
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
| `max_trades_per_symbol` | 2 | Max positions per currency pair |
| `trading_hours_start` | 1 (UTC) | Start of trading window |
| `trading_hours_end` | 22 (UTC) | End of trading window |

---

## How It Works

### Trading Cycle (every 60 seconds)
1. **Connection Check** - Verify MT5 is connected, reconnect if needed
2. **Emergency Scan** - Check drawdown and margin levels
3. **Position Management** - Update trailing stops and break-even levels
4. **For Each Symbol:**
   - Fetch latest OHLCV data (500 candles)
   - Run all strategies in parallel
   - Select best signal (highest confidence + directional agreement)
   - Validate through risk manager (limits, margin, hours, R:R)
   - Calculate position size based on stop loss and risk %
   - Execute order on MetaTrader 5
5. **AI Retraining** - Retrain models if due (weekly)
6. **Logging** - Log all signals, trades, and performance

### AI Model Details
- **Features**: 70+ engineered features including returns, volatility, technical indicators, candle patterns, statistical moments, and time-of-day encoding
- **Models**: Voting ensemble of Random Forest (200 trees) + Gradient Boosting (150 estimators)
- **Training**: Time-series split (no data leakage), 80/20 train/test
- **Retraining**: Automatic weekly retraining with latest data

---

## Important Disclaimers

> **RISK WARNING**: Trading foreign exchange carries a high level of risk and may not be suitable for all investors. Past performance is not indicative of future results. Only trade with money you can afford to lose.

> **NO GUARANTEE**: This bot does not guarantee profits. Markets are unpredictable and no AI system can predict them with certainty.

> **START WITH DEMO**: Always start with a demo account. Only switch to live trading after thorough testing and understanding of the bot's behavior.

> **MONITOR ACTIVELY**: Even in automated mode, monitor the bot regularly. Technology can fail.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "MT5 initialization failed" | Ensure MetaTrader 5 is installed and running. Check the path in config. |
| "Login failed" | Verify your MT5 credentials (login, password, server). |
| "Symbol not found" | The symbol name must match your broker's naming (e.g., EURUSD vs EUR/USD). |
| "Insufficient data" | Wait for the market to be open, or increase the data lookback period. |
| Dashboard not loading | Check that port 5000 is free. Try `http://localhost:5000`. |

---

## License

This project is for educational and personal use. Use at your own risk.

Name     : aaditya pandey
Type     : Forex Hedged USD
Server   : MetaQuotes-Demo
Login    : 104105336
Password : Z_6oXjZn
Investor : @h1qArTw
