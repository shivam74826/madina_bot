"""
=============================================================================
FOREX AI TRADING BOT - CONFIGURATION
=============================================================================
All bot settings are centralized here. Modify these values to customize
the bot's behavior, risk parameters, and trading preferences.
=============================================================================
"""

import os
from dataclasses import dataclass, field
from typing import List, Dict
from enum import Enum
from dotenv import load_dotenv

# Load .env file BEFORE any os.getenv() calls
load_dotenv()


class TimeFrame(Enum):
    """MetaTrader 5 Timeframes"""
    M1 = "TIMEFRAME_M1"
    M5 = "TIMEFRAME_M5"
    M15 = "TIMEFRAME_M15"
    M30 = "TIMEFRAME_M30"
    H1 = "TIMEFRAME_H1"
    H4 = "TIMEFRAME_H4"
    D1 = "TIMEFRAME_D1"
    W1 = "TIMEFRAME_W1"
    MN1 = "TIMEFRAME_MN1"


class TradingMode(Enum):
    """Bot operating modes"""
    LIVE = "live"
    DEMO = "demo"
    BACKTEST = "backtest"
    PAPER = "paper"


@dataclass
class MT5Config:
    """MetaTrader 5 Connection Settings"""
    login: int = int(os.getenv("MT5_LOGIN", "0"))
    password: str = os.getenv("MT5_PASSWORD", "")
    server: str = os.getenv("MT5_SERVER", "")
    path: str = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
    timeout: int = 60000  # Connection timeout in ms


@dataclass
class TradingConfig:
    """Trading Parameters"""
    mode: TradingMode = TradingMode.DEMO
    symbols: List[str] = field(default_factory=lambda: [
        "XAUUSDm"
    ])
    primary_timeframe: TimeFrame = TimeFrame.M15
    analysis_timeframes: List[TimeFrame] = field(default_factory=lambda: [
        TimeFrame.M5, TimeFrame.M15, TimeFrame.H1, TimeFrame.H4
    ])
    max_open_trades: int = 2                    # 2 max for prop firm (limit exposure)
    max_trades_per_symbol: int = 2              # Allow 2 trades on same symbol (needed when trading single instrument)
    trading_hours_start: int = 1   # UTC hour (London session start)
    trading_hours_end: int = 23    # UTC hour (extended to 11 PM UTC)
    magic_number: int = 123456     # Unique ID for bot's orders


@dataclass
class PropFirmConfig:
    """Prop Firm Account Configuration — Goat Funded Trader $5K"""
    enabled: bool = True                       # Enable prop firm protection mode
    firm_name: str = "Goat Funded Trader"
    account_size: float = 5000.0               # Starting balance
    # ─── Prop Firm Hard Limits (DO NOT TRADE PAST THESE) ─────────
    daily_drawdown_limit: float = 0.04         # 4% daily DD = $200 (firm rule)
    max_drawdown_limit: float = 0.08           # 8% total DD = $400 (firm rule)
    # ─── Bot Safety Buffers (tighter than firm limits) ───────────
    daily_drawdown_buffer: float = 0.03        # 3% bot limit = $150 (leaves $50 buffer)
    max_drawdown_buffer: float = 0.06          # 6% bot limit = $300 (leaves $100 buffer)
    # ─── Profit Targets ──────────────────────────────────────────
    phase1_target: float = 0.08               # 8% = $400
    phase2_target: float = 0.05               # 5% = $250
    current_phase: int = 1                    # 1 or 2
    # ─── Prop Firm Trading Rules ─────────────────────────────────
    min_trading_days: int = 3                 # Minimum trading days required
    allow_weekend_holding: bool = False        # Close all before weekend
    allow_news_trading: bool = True            # Goat Funded allows news trading
    max_risk_per_trade: float = 0.0075         # 0.75% per trade (conservative for challenge)
    max_open_trades: int = 2                   # Limit total exposure
    max_lot_size: float = 0.02                 # Max lot cap — limit per-trade damage
    # ─── Emergency Shutdown ──────────────────────────────────────
    emergency_close_at_dd_pct: float = 0.065   # Close ALL trades if DD hits 6.5%
    pause_at_daily_dd_pct: float = 0.025       # Pause after 2.5% daily loss


@dataclass
class RiskConfig:
    """Risk Management Settings"""
    max_risk_per_trade: float = 0.0075     # 0.75% per trade (prop firm safe)
    max_daily_risk: float = 0.03           # 3% max daily loss (buffer under 4% firm limit)
    max_drawdown: float = 0.06             # 6% max drawdown (buffer under 8% firm limit)
    default_stop_loss_pips: float = 50.0
    default_take_profit_pips: float = 100.0
    risk_reward_ratio: float = 1.5         # Minimum 1:1.5 R:R — prop firm needs consistency
    trailing_stop_pips: float = 30.0       # Fallback if ATR unavailable
    break_even_pips: float = 20.0          # Fallback if ATR unavailable
    trailing_stop_atr_mult: float = 2.0    # Trailing distance = ATR * this (wider to let winners run)
    break_even_atr_mult: float = 1.5       # Move to BE after ATR * 1.5 in profit (avoid noise stops)
    use_atr_trailing: bool = True          # Use ATR-based (True) or fixed pips (False)
    max_lot_size: float = 0.02             # Capped to limit per-trade damage
    min_lot_size: float = 0.01
    use_trailing_stop: bool = True
    use_break_even: bool = True
    # ─── Safety Limits ───────────────────────────────────────────
    max_consecutive_losses: int = 3        # Pause after 3 losses (prevent spiral)
    pause_after_losses_minutes: int = 60   # 1 hour pause after loss streak
    max_spread_atr_pct: float = 0.10       # Tighter spread filter (10% of ATR)
    min_tp_atr_mult: float = 1.5           # TP must be at least 1.5x ATR away
    max_correlated_exposure: int = 1       # Only 1 position in correlated instruments
    # ─── Balance-Adaptive Mode (disabled for prop firm) ──────────
    auto_risk_scaling: bool = False         # Disabled — use fixed prop firm risk
    micro_account_threshold: float = 200.0
    small_account_threshold: float = 500.0
    micro_risk_per_trade: float = 0.05
    small_risk_per_trade: float = 0.03
    micro_max_drawdown: float = 0.30
    micro_risk_reward_ratio: float = 1.0
    max_risk_at_min_lot: float = 0.02       # Only 2% max risk at min lot (prop firm)
    micro_max_risk_at_min_lot: float = 0.80
    small_max_risk_at_min_lot: float = 0.50
    min_viable_balance: float = 1.0
    # ─── Commission & Slippage Budget ────────────────────────────
    estimated_commission_per_lot: float = 7.0
    estimated_slippage_pips: float = 1.0
    # ─── Scaling Discipline ──────────────────────────────────────
    scaling_enabled: bool = False
    scaling_warmup_trades: int = 50
    scaling_warmup_factor: float = 0.25
    scaling_proven_factor: float = 0.50
    scaling_full_after_trades: int = 150
    # ─── Trade Cooldown ─────────────────────────────────────────
    cooldown_after_trade_minutes: int = 15     # 15 min cooldown (prevent overtrading)
    cooldown_after_loss_minutes: int = 60      # 60 min cooldown after loss
    daily_loss_limit_usd: float = 75.0         # Conservative daily loss cap (~1.5% of $5K)


@dataclass
class SessionConfig:
    """Trading Session Windows (UTC hours) — high-probability windows only"""
    # Gold (XAUUSD) optimal sessions: Asian + London + US session
    gold_sessions: list = field(default_factory=lambda: [
        {"name": "Asian", "start": 0, "end": 7},
        {"name": "London", "start": 7, "end": 12},
        {"name": "US_Session", "start": 12, "end": 23},
    ])
    # Forex major pairs
    forex_sessions: list = field(default_factory=lambda: [
        {"name": "London", "start": 7, "end": 16},
        {"name": "New_York", "start": 13, "end": 21},
    ])
    # Use session filter (False = trade all hours)
    use_session_filter: bool = True
    # Higher timeframe trend confirmation
    require_htf_confirmation: bool = False


@dataclass
class AIConfig:
    """AI/ML Model Settings"""
    model_type: str = "ensemble"           # ensemble, lstm, xgboost, random_forest
    prediction_horizon: int = 24           # Predict X candles ahead
    training_lookback_days: int = 90       # Historical data for training (90 days ~1500 H1 candles)
    retrain_interval_hours: int = 168      # Retrain weekly
    min_confidence: float = 0.45           # Minimum prediction confidence (lowered to allow signals through)
    feature_window: int = 50               # Lookback window for features
    use_sentiment: bool = True
    use_fundamentals: bool = True
    model_save_path: str = "models/"


@dataclass
class IndicatorConfig:
    """Technical Indicator Settings"""
    # Moving Averages
    sma_fast: int = 20
    sma_slow: int = 50
    sma_trend: int = 200
    ema_fast: int = 12
    ema_slow: int = 26

    # RSI
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # Bollinger Bands
    bb_period: int = 20
    bb_std: float = 2.0

    # ATR
    atr_period: int = 14

    # Stochastic
    stoch_k: int = 14
    stoch_d: int = 3
    stoch_smooth: int = 3

    # ADX
    adx_period: int = 14
    adx_threshold: float = 25.0

    # Ichimoku
    ichimoku_tenkan: int = 9
    ichimoku_kijun: int = 26
    ichimoku_senkou: int = 52


@dataclass
class NewsConfig:
    """Economic News Filter Settings"""
    enabled: bool = True
    high_impact_freeze_minutes: int = 30   # Freeze trading X min before HIGH news
    high_impact_cooldown_minutes: int = 15 # Wait X min after HIGH news
    medium_impact_freeze_minutes: int = 15
    medium_impact_cooldown_minutes: int = 10
    reduce_size_near_news: bool = True     # Halve position near medium events
    ultra_high_events: List[str] = field(default_factory=lambda: [
        "Non-Farm Employment Change", "FOMC Statement", "Fed Interest Rate Decision",
        "ECB Interest Rate Decision", "BOE Interest Rate Decision",
        "CPI m/m", "CPI y/y", "GDP q/q", "GDP Advance", "Retail Sales m/m",
    ])


@dataclass
class DashboardConfig:
    """Web Dashboard Settings"""
    host: str = "127.0.0.1"
    port: int = 5000
    debug: bool = False
    secret_key: str = os.getenv("DASHBOARD_SECRET", "change-this-secret-key")
    refresh_interval: int = 5  # Seconds between data refreshes


@dataclass
class LogConfig:
    """Logging Configuration"""
    log_level: str = "INFO"
    log_file: str = "logs/trading_bot.log"
    max_file_size: int = 10 * 1024 * 1024  # 10 MB
    backup_count: int = 5
    log_trades: bool = True
    trade_log_file: str = "logs/trades.csv"


@dataclass
class BotConfig:
    """Master Configuration - Aggregates All Settings"""
    mt5: MT5Config = field(default_factory=MT5Config)
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    prop_firm: PropFirmConfig = field(default_factory=PropFirmConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    logging: LogConfig = field(default_factory=LogConfig)


# Global configuration instance
config = BotConfig()
