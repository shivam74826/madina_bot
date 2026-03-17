"""
=============================================================================
FOREX AI TRADING BOT - MAIN ENGINE
=============================================================================
The central orchestrator that ties all components together:

  1. Connects to MetaTrader 5
  2. Fetches market data across multiple timeframes
  3. Runs AI predictions + technical analysis
  4. Executes trades through the risk management filter
  5. Manages open positions (trailing stops, break-even)
  6. Launches a real-time web dashboard

Usage:
    python main.py              # Start with default settings
    python main.py --mode demo  # Explicit demo mode
    python main.py --mode live  # Live trading
    python main.py --dashboard  # Dashboard only (no trading)
=============================================================================
"""

import sys
import os
import time
import signal
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import config, TradingMode, TimeFrame
from core.mt5_connector import MT5Connector
from core.order_manager import OrderManager
from core.data_fetcher import DataFetcher
from analysis.technical import TechnicalAnalyzer
from analysis.sentiment import SentimentAnalyzer
from analysis.news_analyzer import NewsAnalyzer
from ai.predictor import AIPredictor
from strategy.trend_following import TrendFollowingStrategy
from strategy.mean_reversion import MeanReversionStrategy
from strategy.ai_strategy import AIStrategy, MultiStrategyManager
from strategy.smc_strategy import SMCStrategy
from strategy.breakout_strategy import BreakoutStrategy
from strategy.base_strategy import SignalType
from risk.risk_manager import RiskManager
from dashboard.app import Dashboard
from utils.logger import setup_logging, TradeLogger
from ai.trade_journal import TradingJournal
from core.live_trade_manager import LiveTradeManager, C
from utils.email_notifier import EmailNotifier

logger = logging.getLogger(__name__)


class ForexAIBot:
    """
    Main Trading Bot Engine.
    
    Orchestrates all components: data fetching, analysis, AI prediction,
    strategy execution, risk management, and position management.
    """

    def __init__(self):
        self.running = False
        self.cycle_count = 0
        self.last_analysis_time = {}

        # Core components
        self.connector = MT5Connector()
        self.order_manager = OrderManager(self.connector)
        self.data_fetcher = DataFetcher(self.connector)

        # Analysis
        self.technical = TechnicalAnalyzer()
        self.sentiment = SentimentAnalyzer()
        self.news_analyzer = NewsAnalyzer()

        # AI
        self.ai_predictor = AIPredictor()

        # Strategies — 5 strategies with weighted consensus
        self.strategy_manager = MultiStrategyManager()
        self.strategy_manager.add_strategy(TrendFollowingStrategy())
        self.strategy_manager.add_strategy(MeanReversionStrategy())
        self.strategy_manager.add_strategy(AIStrategy(self.ai_predictor))
        self.strategy_manager.add_strategy(SMCStrategy())
        self.strategy_manager.add_strategy(BreakoutStrategy())

        # Risk Management
        self.risk_manager = RiskManager(self.connector, self.order_manager)

        # Logging
        self.trade_logger = TradeLogger()

        # Learning system — reads past lessons and records new ones
        self.journal = TradingJournal()

        # Email notifications
        self.email_notifier = EmailNotifier()

        # Dashboard (initialized later)
        self.dashboard = None

        # Live trade manager — handles dedup, position monitoring, terminal display
        self.live_manager = LiveTradeManager(self.connector, self.order_manager)

        # Track open position tickets → detect closures for circuit breaker
        self._tracked_tickets: set = set()

        # Daily trade counter (reset each UTC day)
        self._trades_today = 0
        self._trade_count_date = None
        self._sync_trade_count()  # Restore count from MT5 history on startup

    def _sync_trade_count(self):
        """Count today's bot trades from MT5 deal history — survives restarts."""
        try:
            from datetime import datetime as _dt, timedelta
            from core.mt5_lock import mt5_safe as mt5
            utc_today = _dt.utcnow().date()
            date_from = _dt(utc_today.year, utc_today.month, utc_today.day)
            date_to = _dt.utcnow() + timedelta(hours=1)
            deals = mt5.history_deals_get(date_from, date_to)
            if deals:
                # Count entry deals (type 0=BUY, 1=SELL) with our magic number
                count = sum(
                    1 for d in deals
                    if d.magic == config.trading.magic_number
                    and d.entry == 0  # 0 = market entry (not exit)
                )
                self._trades_today = count
                self._trade_count_date = utc_today
                logger.info(f"Trade count synced from MT5: {count} trades today")
            else:
                self._trade_count_date = utc_today
        except Exception as e:
            logger.warning(f"Failed to sync trade count: {e}")
            self._trade_count_date = _dt.utcnow().date()

    def start(self, with_dashboard: bool = True):
        """Start the trading bot."""
        logger.info("=" * 70)
        logger.info("   FOREX AI TRADING BOT - STARTING")
        logger.info(f"   Mode: {config.trading.mode.value.upper()}")
        if config.prop_firm.enabled:
            logger.info(f"   Prop Firm: {config.prop_firm.firm_name} ${config.prop_firm.account_size:,.0f}")
            logger.info(f"   Phase: {config.prop_firm.current_phase}")
        logger.info(f"   Symbols: {', '.join(config.trading.symbols)}")
        logger.info(f"   Primary TF: {config.trading.primary_timeframe.value}")
        logger.info("=" * 70)

        # Connect to MT5
        if not self.connector.connect():
            logger.error("Failed to connect to MetaTrader 5!")
            logger.info("Make sure MetaTrader 5 is installed and running.")
            logger.info("Set your credentials in environment variables:")
            logger.info("  MT5_LOGIN, MT5_PASSWORD, MT5_SERVER")
            return False

        # ─── Auto-enable AutoTrading if disabled ─────────────────
        self._ensure_autotrading()

        # Initialize risk manager
        self.risk_manager.initialize()

        # ─── Account Capability Assessment ───────────────────────
        # Bot always starts — viability is informational, not blocking

        # Enable all symbols and check viability
        viable_symbols = []
        for symbol in config.trading.symbols:
            self.connector.enable_symbol(symbol)
            report = self.risk_manager.assess_symbol_viability(symbol)
            if report["viable"]:
                viable_symbols.append(symbol)
                logger.info(
                    f"  [OK] {symbol} | Min lot: {report['min_lot']} | "
                    f"Margin: ${report['margin_for_min_lot']} | "
                    f"Risk@min: {report['risk_pct_at_min_lot']}% | "
                    f"ATR: ${report['atr']}"
                )
            else:
                effective_cap = self.risk_manager._get_effective_max_risk_at_min_lot()
                logger.warning(
                    f"  [X] {symbol} | NOT VIABLE at ${report.get('equity', 0):.2f} -- "
                    f"risk@min_lot: {report.get('risk_pct_at_min_lot', 'N/A')}% "
                    f"(cap: {effective_cap * 100:.0f}% in {self.risk_manager._account_mode} mode)"
                )

        if not viable_symbols:
            logger.critical("No symbols viable at current balance! Cannot trade.")
            # Continue anyway (balance might change, or market conditions)

        # Enable all symbols
        for symbol in config.trading.symbols:
            self.connector.enable_symbol(symbol)

        # Train AI models
        self._train_ai_models()

        # Start dashboard
        if with_dashboard:
            self.dashboard = Dashboard(self)
            self.dashboard.run(threaded=True)

        # Load and display lessons from past trading
        self.journal.log_rules()

        # Start trading loop
        self.running = True
        self._trading_loop()

        return True

    def _ensure_autotrading(self):
        """Check if AutoTrading is enabled in MT5; try to enable it if not."""
        try:
            from core.mt5_lock import mt5_safe as mt5
            info = mt5.terminal_info()
            if info and info.trade_allowed:
                logger.info("AutoTrading: ENABLED")
                return
            logger.warning("AutoTrading is DISABLED in MT5 — attempting to enable via Ctrl+E...")
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32

            def find_mt5_hwnd():
                result = [None]
                def cb(hwnd, _):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        if 'MetaTrader' in buf.value or 'Exness' in buf.value:
                            if user32.IsWindowVisible(hwnd):
                                result[0] = hwnd
                    return True
                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
                user32.EnumWindows(WNDENUMPROC(cb), 0)
                return result[0]

            hwnd = find_mt5_hwnd()
            if not hwnd:
                logger.error("Could not find MT5 window — enable AutoTrading manually (Ctrl+E)")
                return
            user32.ShowWindow(hwnd, 9)
            import time as _t; _t.sleep(0.3)
            user32.SetForegroundWindow(hwnd)
            _t.sleep(0.5)
            try:
                import pyautogui
                pyautogui.hotkey('ctrl', 'e')
            except ImportError:
                user32.keybd_event(0x11, 0, 0, 0)
                user32.keybd_event(0x45, 0, 0, 0)
                _t.sleep(0.05)
                user32.keybd_event(0x45, 0, 2, 0)
                user32.keybd_event(0x11, 0, 2, 0)
            _t.sleep(1.5)
            info = mt5.terminal_info()
            if info and info.trade_allowed:
                logger.info("AutoTrading: ENABLED (auto-toggled)")
            else:
                logger.error("AutoTrading still DISABLED — please enable manually in MT5 (Ctrl+E)")
        except Exception as e:
            logger.error(f"AutoTrading check failed: {e}")

    def stop(self):
        """Gracefully stop the bot."""
        logger.info("Stopping bot...")
        self.running = False

        # Run end-of-day analysis and save lessons
        try:
            self._run_daily_analysis()
        except Exception as e:
            logger.error(f"Failed to run daily analysis: {e}")

        self.connector.disconnect()
        logger.info("Bot stopped successfully")

    # ─── Main Trading Loop ───────────────────────────────────────────────

    def _trading_loop(self):
        """Main trading loop - runs continuously."""
        logger.info("Trading loop started")
        self._start_time = time.time()

        while self.running:
            try:
                self.cycle_count += 1
                cycle_start = time.time()

                # Log first cycle to confirm bot is alive
                if self.cycle_count == 1:
                    logger.info("Cycle #1 starting — bot is actively trading")

                # Check connection (with circuit breaker)
                if not self.connector.is_connected():
                    logger.warning("Lost MT5 connection, reconnecting...")
                    reconnected = False
                    for reconnect_attempt in range(3):
                        if self.connector.reconnect():
                            reconnected = True
                            logger.info(f"Reconnected on attempt {reconnect_attempt + 1}")
                            break
                        time.sleep(10 * (reconnect_attempt + 1))
                    if not reconnected:
                        logger.critical(
                            "CIRCUIT BREAKER: Failed to reconnect after 3 attempts. "
                            "Halting for 5 minutes."
                        )
                        time.sleep(300)
                        continue

                # Emergency checks
                if self.risk_manager.check_emergency_conditions():
                    logger.critical("Emergency conditions detected! Pausing for 5 minutes.")
                    time.sleep(300)
                    continue

                # Update trailing stops for open positions
                self.order_manager.update_trailing_stops()

                # Live trade management — monitor & manage open positions
                self.live_manager.manage_positions(
                    data_fetcher=self.data_fetcher,
                    technical=self.technical,
                    sentiment=self.sentiment,
                )

                # Print cycle header for terminal visibility
                self.live_manager.print_cycle_header(self.cycle_count)

                # ─── Reset daily trade counter at UTC midnight ──
                utc_today = datetime.utcnow().date()
                if self._trade_count_date != utc_today:
                    self._trades_today = 0
                    self._trade_count_date = utc_today
                    # Re-sync from MT5 in case of race condition
                    self._sync_trade_count()
                    # Run daily analysis for the previous day
                    if self.cycle_count > 1:
                        try:
                            self._run_daily_analysis()
                            self.journal.log_rules()
                        except Exception as e:
                            logger.error(f"Daily analysis failed: {e}")

                # ─── Detect closed positions → feed circuit breaker ──
                self._check_closed_positions()

                # Analyze each symbol
                for symbol in config.trading.symbols:
                    try:
                        self._analyze_and_trade(symbol)
                    except Exception as e:
                        logger.error(f"Error analyzing {symbol}: {e}", exc_info=True)

                # Check if AI models need retraining
                if self.ai_predictor.should_retrain():
                    self._train_ai_models()

                # Clear data cache periodically
                if self.cycle_count % 60 == 0:
                    self.data_fetcher.clear_cache()

                # Auto-adjust strategy weights based on real performance
                if self.cycle_count % 120 == 0:
                    self._adjust_strategy_weights()

                # Log cycle stats
                cycle_time = time.time() - cycle_start
                if self.cycle_count % 5 == 0:
                    risk = self.risk_manager.get_risk_summary()
                    # News summary
                    upcoming_news = ""
                    try:
                        news_summary = self.news_analyzer.get_calendar_summary()
                        upcoming = news_summary.get("upcoming_events", [])
                        if upcoming:
                            upcoming_news = f" | News: {len(upcoming)} upcoming"
                    except Exception:
                        pass

                    # Prop firm status
                    pf_info = ""
                    pf = risk.get("prop_firm", {})
                    if pf.get("enabled"):
                        pf_info = (
                            f" | PF: {pf['firm']} Ph{pf['phase']} "
                            f"DailyDD:{pf['daily_dd_pct']:.1f}%/{pf['daily_dd_buffer']:.0f}% "
                            f"TotalDD:{pf['total_dd_pct']:.1f}%/{pf['total_dd_buffer']:.0f}% "
                            f"Profit:{pf['profit_pct']:+.1f}%/{pf['target_pct']:.0f}%"
                        )

                    logger.info(
                        f"Cycle #{self.cycle_count} | "
                        f"Time: {cycle_time:.1f}s | "
                        f"Equity: {risk['equity']:.2f} | "
                        f"DD: {risk['drawdown']:.2f}% | "
                        f"Mode: {risk.get('account_mode', 'normal')} | "
                        f"Positions: {risk['open_positions']}/{risk['max_positions']} | "
                        f"P&L: {risk['unrealized_pnl']:.2f}{pf_info}{upcoming_news}"
                    )

                    # Rich terminal position display
                    self.live_manager.print_status(
                        cycle_count=self.cycle_count,
                        equity=risk['equity'],
                        balance=risk.get('balance', risk['equity']),
                        risk_summary=risk,
                    )

                # Heartbeat every 30 cycles (~30 min) — proves bot is alive
                if self.cycle_count % 30 == 0:
                    equity = self.connector.get_equity()
                    logger.info(
                        f"HEARTBEAT | Cycle: {self.cycle_count} | "
                        f"Equity: ${equity:.2f} | "
                        f"Trades today: {self._trades_today} | "
                        f"Uptime: {(time.time() - getattr(self, '_start_time', time.time())) / 3600:.1f}h"
                    )

                # Wait before next cycle (1 minute for H1 timeframe)
                sleep_time = max(0, 60 - cycle_time)
                time.sleep(sleep_time)

            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received")
                self.stop()
                break
            except Exception as e:
                logger.error(f"Trading loop error: {e}", exc_info=True)
                time.sleep(10)

    def _check_closed_positions(self):
        """
        Detect positions that were open last cycle but are now closed.
        Feed their P&L into the risk manager's circuit breaker.
        """
        try:
            current_positions = self.connector.get_bot_positions()
            current_tickets = {p["ticket"] for p in current_positions}

            # Find newly closed tickets
            closed_tickets = self._tracked_tickets - current_tickets

            if closed_tickets:
                # Look up the actual P&L from deal history
                deals = self.connector.get_history_deals(days=1)
                for deal in deals:
                    if deal.get("position_id") in closed_tickets or \
                       deal.get("ticket") in closed_tickets:
                        profit = deal.get("profit", 0) + deal.get("swap", 0) + \
                                 deal.get("commission", 0)
                        deal_symbol = deal.get("symbol", "")
                        deal_comment = deal.get("comment", "")
                        # Extract strategy name from order comment (format: "AI_Multi(StratName)")
                        strategy_name = ""
                        if "AI_" in deal_comment:
                            strategy_name = deal_comment.replace("AI_", "")
                        if profit != 0:
                            self.risk_manager.record_trade_result(
                                profit, symbol=deal_symbol, strategy=strategy_name
                            )
                            result = "WIN" if profit > 0 else "LOSS"
                            color = C.GREEN if profit > 0 else C.RED
                            equity_after = self.connector.get_equity()
                            # ─── Prominent WIN/LOSS Display ──────────
                            logger.info("")
                            logger.info(f"{'='*50}")
                            logger.info(
                                f"  {color}{C.BOLD}TRADE {result}: ${profit:+.2f}{C.RESET}"
                            )
                            logger.info(
                                f"  Symbol: {deal_symbol} | Strategy: {strategy_name}"
                            )
                            logger.info(
                                f"  Balance after: ${equity_after:.2f} | "
                                f"Consecutive losses: {self.risk_manager._consecutive_losses}"
                            )
                            logger.info(f"{'='*50}")
                            logger.info("")
                            # ─── Email notification ──────────────────
                            try:
                                direction = "BUY" if deal.get("type", 0) == 0 else "SELL"
                                self.email_notifier.notify_trade_closed(
                                    symbol=deal_symbol,
                                    direction=direction,
                                    ticket=deal.get("ticket", 0),
                                    profit=profit,
                                    close_price=deal.get("price", 0),
                                    comment=f"{result} | {strategy_name} | Balance: ${equity_after:.2f}"
                                )
                            except Exception:
                                pass

            # Update tracked set
            self._tracked_tickets = current_tickets

        except Exception as e:
            logger.debug(f"Position tracking error: {e}")

    def _analyze_and_trade(self, symbol: str):
        """Analyze a symbol and execute trades if conditions are met."""
        # Throttle analysis (M15 timeframe — check every 60s)
        now = datetime.now()
        last_time = self.last_analysis_time.get(symbol)
        if last_time and (now - last_time).total_seconds() < 60:
            return

        self.last_analysis_time[symbol] = now

        # ─── Quick hours pre-check (log once per 10 cycles) ──
        from datetime import datetime as _dt
        utc_now = _dt.utcnow()
        if not self.risk_manager._is_trading_hours(symbol):
            if self.cycle_count % 10 == 0:
                logger.info(
                    f"{symbol} | Outside trading hours (UTC: {utc_now.strftime('%H:%M')}, "
                    f"day: {utc_now.strftime('%A')})"
                )
            return

        # ─── Journal: Overtrading Guard ─────────────────────────
        if self.journal.is_overtrading(self._trades_today):
            if self.cycle_count % 10 == 0:
                logger.info(
                    f"{symbol} | JOURNAL GUARD: Max trades/day reached "
                    f"({self._trades_today}/{self.journal.get_lessons().get('max_trades_per_day', 10)})"
                )
            return

        # ─── Journal: Bad Hour Guard ────────────────────────────
        utc_hour = utc_now.hour
        if self.journal.is_bad_hour(utc_hour):
            if self.cycle_count % 10 == 0:
                logger.info(
                    f"{symbol} | JOURNAL GUARD: Hour {utc_hour}:00 UTC is historically "
                    f"losing — skipping"
                )
            return

        # ─── News Check (BLOCKS trades during high-impact news) ────
        news_size_factor = 1.0
        try:
            can_trade, news_reason, size_factor = self.news_analyzer.should_trade(symbol)
            news_size_factor = size_factor
            if not can_trade:
                if self.cycle_count % 10 == 0:
                    logger.info(f"{symbol} | NEWS BLOCK: {news_reason}")
                return  # Actually block the trade
        except Exception as e:
            logger.debug(f"News check failed for {symbol}: {e}")

        # ─── Market Regime Detection ─────────────────────────────
        market_regime = "unknown"
        try:
            df_regime = self.data_fetcher.get_ohlcv(symbol, count=200)
            if df_regime is not None and len(df_regime) > 50:
                regime_info = self.sentiment.analyze_market_regime(df_regime)
                market_regime = regime_info.get("regime", "unknown")
        except Exception:
            pass

        # Fetch data
        df = self.data_fetcher.get_ohlcv(symbol, count=500)
        if df is None or len(df) < 200:
            return

        # ─── Volume Divergence Check ─────────────────────────────
        # Reject weak moves: price trending but volume declining
        volume_ok = True
        try:
            if 'tick_volume' in df.columns and len(df) >= 20:
                recent_vol = df['tick_volume'].iloc[-5:].mean()
                avg_vol = df['tick_volume'].iloc[-20:].mean()
                price_change = abs(df['close'].iloc[-1] - df['close'].iloc[-5])
                atr_recent = df['high'].iloc[-5:].values - df['low'].iloc[-5:].values
                avg_atr = atr_recent.mean() if len(atr_recent) > 0 else 1.0
                # If price moved significantly but volume is declining = weak move
                if price_change > avg_atr * 0.5 and recent_vol < avg_vol * 0.7:
                    volume_ok = False
                    if self.cycle_count % 10 == 0:
                        logger.info(
                            f"{symbol} | VOLUME DIVERGENCE: Price moving but volume "
                            f"declining ({recent_vol:.0f} vs avg {avg_vol:.0f}) -- weak move"
                        )
        except Exception:
            pass  # Volume check failed, proceed normally

        # ─── RSI Divergence Check ────────────────────────────────
        divergence_signal = None
        try:
            if len(df) >= 30 and 'close' in df.columns:
                from analysis.technical import TechnicalAnalyzer
                ta = TechnicalAnalyzer()
                rsi_series = ta.rsi(df['close'])
                if rsi_series is not None and len(rsi_series) >= 20:
                    divergence_signal = self.sentiment.detect_divergence(
                        df['close'], rsi_series, lookback=20
                    )
        except Exception:
            pass

        # Print market snapshot every 5 cycles for terminal visibility
        if self.cycle_count % 5 == 0:
            self.live_manager.print_market_snapshot(symbol, df)

        # Get multi-strategy signal
        signal = self.strategy_manager.get_best_signal(
            df, symbol,
            market_regime=market_regime,
            news_can_trade=True,
            news_size_factor=news_size_factor,
        )

        if signal.signal_type == SignalType.HOLD:
            # Log HOLD every 10 cycles so user can see signals ARE being evaluated
            if self.cycle_count % 10 == 0:
                logger.info(f"{symbol} | No actionable signal (HOLD) — strategies see no edge")
            return

        # ─── Journal: Direction Guard ────────────────────────
        if self.journal.should_avoid_direction(signal.signal_type.value):
            logger.info(
                f"{symbol} | JOURNAL GUARD: {signal.signal_type.value} direction "
                f"recently had 0% win rate -- reducing confidence"
            )
            signal.confidence *= 0.85  # Mild penalty (was 0.6 — too aggressive, killed all signals)

        # ─── Volume Divergence Penalty ───────────────────────
        if not volume_ok:
            signal.confidence *= 0.85
            signal.reason += " | Vol divergence penalty"

        # ─── RSI Divergence Boost/Penalty ────────────────────
        if divergence_signal:
            if (divergence_signal == "bullish_divergence" and signal.signal_type == SignalType.BUY) or \
               (divergence_signal == "bearish_divergence" and signal.signal_type == SignalType.SELL):
                signal.confidence *= 1.1  # Divergence confirms direction
                signal.reason += f" | {divergence_signal} confirms"
            elif (divergence_signal == "bullish_divergence" and signal.signal_type == SignalType.SELL) or \
                 (divergence_signal == "bearish_divergence" and signal.signal_type == SignalType.BUY):
                signal.confidence *= 0.85  # Divergence contradicts direction
                signal.reason += f" | {divergence_signal} contradicts"

        # ─── MICRO ACCOUNT SL TIGHTENER ─────────────────────
        # For tiny accounts: if the SL is too wide, tighten it to
        # a max dollar risk and adjust TP to maintain the R:R ratio.
        try:
            equity = self.connector.get_equity()
            max_risk_pct = config.risk.micro_max_risk_at_min_lot
            max_risk_usd = equity * max_risk_pct  # e.g. $16 * 0.25 = $4
            sl_dist = abs(signal.entry_price - signal.stop_loss)
            from core.mt5_lock import mt5_safe as mt5_info
            sym_info = mt5_info.symbol_info(symbol)
            if sym_info and sl_dist > 0:
                pip = sym_info.point * 10
                sl_pips = sl_dist / pip
                tick_val = sym_info.trade_tick_value
                min_lot = sym_info.volume_min
                risk_usd = sl_pips * tick_val * 10 * min_lot
                if risk_usd > max_risk_usd and max_risk_usd > 0:
                    # Calculate the max SL distance we can afford
                    max_sl_pips = max_risk_usd / (tick_val * 10 * min_lot)
                    max_sl_dist = max_sl_pips * pip
                    original_rr = signal.risk_reward if signal.risk_reward > 0 else 1.5
                    # Tighten SL
                    if signal.signal_type == SignalType.BUY:
                        signal.stop_loss = signal.entry_price - max_sl_dist
                        signal.take_profit = signal.entry_price + (max_sl_dist * original_rr)
                    else:
                        signal.stop_loss = signal.entry_price + max_sl_dist
                        signal.take_profit = signal.entry_price - (max_sl_dist * original_rr)
                    signal.risk_reward = original_rr
                    new_risk = max_sl_pips * tick_val * 10 * min_lot
                    logger.info(
                        f"{symbol} | SL TIGHTENED: ${risk_usd:.2f} -> ${new_risk:.2f} risk | "
                        f"SL dist: {sl_dist:.2f} -> {max_sl_dist:.2f} | "
                        f"R:R maintained at {original_rr:.1f}"
                    )
                    signal.reason += f" | SL tightened (${risk_usd:.0f}->${new_risk:.0f})"
        except Exception as e:
            logger.debug(f"SL tightener failed: {e}")

        # Validate through risk manager (basic checks only)
        validation = self.risk_manager.validate_trade(signal)

        if not validation["approved"]:
            logger.info(f"{symbol} | Signal rejected: {', '.join(validation['reasons'])}")
            # Show rejected signal in terminal
            self.live_manager.print_signal_analysis(
                symbol, signal, approved=False,
                reject_reasons=validation['reasons']
            )
            return

        # ─── Signal Dedup — prevent identical trades on same signal ───
        if self.live_manager.is_duplicate_signal(
            symbol, signal.signal_type.value,
            signal.stop_loss, signal.take_profit
        ):
            logger.info(
                f"{symbol} | DEDUP: Same {signal.signal_type.value} signal already traded "
                f"(same SL/TP zone within 10 min) — skipping duplicate"
            )
            return

        # Show approved signal in terminal  
        self.live_manager.print_signal_analysis(symbol, signal, approved=True)

        # Calculate position size (news-aware, balance-adaptive)
        lot_size = self.risk_manager.calculate_position_size(
            signal, news_size_factor=news_size_factor
        )

        # lot_size=0 means position sizing rejected the trade (too risky at min lot)
        if lot_size <= 0:
            logger.info(f"{symbol} | Position sizing rejected — SL too wide for current balance")
            return

        # Execute trade
        logger.info(f"EXECUTING | {signal.signal_type.value} {lot_size} {symbol} | "
                     f"Confidence: {signal.confidence:.2f} | "
                     f"Strategy: {signal.strategy_name} | "
                     f"R:R: {signal.risk_reward:.2f}")

        # Print detailed trade decision to terminal
        self.live_manager.print_trade_decision(
            symbol, signal, lot_size,
            market_regime, volume_ok, divergence_signal
        )

        # ─── Live Price Adjustment ────────────────────────────────
        # Market orders fill at live price, not the OHLCV close used by strategies.
        # Adjust entry/SL/TP to live price. Only reject if drift is extreme
        # (>2x ATR = data is fundamentally broken or market gap).
        if config.trading.mode != TradingMode.PAPER:
            try:
                from core.mt5_lock import mt5_safe as mt5
                tick = mt5.symbol_info_tick(symbol)
                if tick and signal.entry_price > 0:
                    live_price = tick.ask if signal.signal_type == SignalType.BUY else tick.bid
                    drift = abs(live_price - signal.entry_price)
                    atr_vals = (df['high'].iloc[-14:] - df['low'].iloc[-14:]).mean()
                    max_drift = atr_vals * 2.0  # Only reject extreme gaps

                    if drift > max_drift:
                        logger.warning(
                            f"{symbol} | PRICE DRIFT: Live {live_price:.2f} vs "
                            f"signal {signal.entry_price:.2f} (drift {drift:.2f} > "
                            f"max {max_drift:.2f}) -- extreme gap, skipping"
                        )
                        return

                    # Shift entry, SL, TP to live price
                    price_shift = live_price - signal.entry_price
                    signal.entry_price = live_price
                    signal.stop_loss += price_shift
                    signal.take_profit += price_shift
            except Exception:
                pass  # Proceed if tick fetch fails

        if config.trading.mode == TradingMode.PAPER:
            # Paper trading - just log
            logger.info(f"PAPER TRADE | {signal.signal_type.value} {lot_size} {symbol} @ {signal.entry_price}")
            self.trade_logger.log_trade(
                symbol=symbol,
                action=signal.signal_type.value,
                volume=lot_size,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                confidence=signal.confidence,
                strategy=signal.strategy_name,
                reason=signal.reason,
                result="PAPER",
            )
        else:
            # Real execution
            result = self.order_manager.place_market_order(
                symbol=symbol,
                order_type=signal.signal_type.value,
                volume=lot_size,
                sl=signal.stop_loss,
                tp=signal.take_profit,
                comment=f"AI_{signal.strategy_name}",
            )

            if result:
                self._trades_today += 1
                # Record trade opened for cooldown tracking
                self.risk_manager.record_trade_opened(symbol)
                # Record signal for dedup tracking
                self.live_manager.record_signal(
                    symbol, signal.signal_type.value,
                    signal.stop_loss, signal.take_profit
                )
                # Register position for live management
                self.live_manager.register_position(
                    ticket=result["ticket"],
                    symbol=symbol,
                    direction=signal.signal_type.value,
                    entry_price=result["price"],
                    sl=signal.stop_loss,
                    tp=signal.take_profit,
                    volume=lot_size,
                    strategy=signal.strategy_name,
                    confidence=signal.confidence,
                    regime=market_regime,
                )
                # ─── Trade Context Logging (full decision record) ────
                slippage = result.get("slippage", 0)
                logger.info(
                    f"TRADE_CONTEXT | {symbol} {signal.signal_type.value} | "
                    f"Strategy: {signal.strategy_name} | "
                    f"Confidence: {signal.confidence:.2f} | "
                    f"R:R: {signal.risk_reward:.2f} | "
                    f"Regime: {market_regime} | "
                    f"Volume_OK: {volume_ok} | "
                    f"Divergence: {divergence_signal} | "
                    f"Lot: {lot_size} | "
                    f"Slippage: {slippage:.5f} | "
                    f"Fill: {result['price']:.5f}"
                )
                self.trade_logger.log_trade(
                    symbol=symbol,
                    action=signal.signal_type.value,
                    volume=lot_size,
                    entry_price=result["price"],
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    confidence=signal.confidence,
                    strategy=signal.strategy_name,
                    reason=signal.reason,
                    ticket=result["ticket"],
                    result="OPENED",
                )
                logger.info(
                    f"JOURNAL: Trade #{self._trades_today} today | "
                    f"Max: {self.journal.get_lessons().get('max_trades_per_day', 10)}"
                )
            else:
                logger.error(f"Failed to execute {signal.signal_type.value} on {symbol}")

    # ─── Adaptive Strategy Weights ──────────────────────────────────────

    def _adjust_strategy_weights(self):
        """
        Auto-adjust strategy weights based on real trading performance.
        Strategies that lose money get lower weight; winners get promoted.
        This is the evolutionary learning loop that makes the system improve.
        """
        win_rates = self.risk_manager.get_strategy_win_rates()
        if not win_rates:
            return  # Not enough data yet

        for strategy_key, win_rate in win_rates.items():
            # Map the strategy key back to the weight key
            # Comments like "Multi(Smart_Money)" → look for "Smart_Money"
            for weight_key in self.strategy_manager._strategy_weights:
                if weight_key in strategy_key:
                    old = self.strategy_manager._strategy_weights[weight_key]
                    if win_rate >= 0.55:
                        # Good performer — raise weight slightly (max 2.0)
                        new = min(old * 1.05, 2.0)
                    elif win_rate < 0.35:
                        # Poor performer — reduce weight significantly (min 0.3)
                        new = max(old * 0.85, 0.3)
                    else:
                        new = old  # Neutral range — keep as-is

                    if new != old:
                        self.strategy_manager._strategy_weights[weight_key] = round(new, 2)
                        logger.info(
                            f"ADAPTIVE: {weight_key} weight {old:.2f} → {new:.2f} "
                            f"(win rate: {win_rate:.0%})"
                        )

    # ─── Daily Analysis & Learning ─────────────────────────────────────

    def _run_daily_analysis(self):
        """
        Run end-of-day analysis and save lessons for tomorrow.
        Called when bot stops or at UTC midnight.
        """
        from core.mt5_lock import mt5_safe as mt5
        from datetime import timedelta

        logger.info("Running daily analysis and saving lessons...")

        now = datetime.now()
        start = datetime(now.year, now.month, now.day) - timedelta(days=1)
        deals = mt5.history_deals_get(start, now)

        if not deals:
            logger.info("No deals to analyze")
            return

        bot_deals = [d for d in deals if d.magic == config.trading.magic_number]
        entries = [d for d in bot_deals if d.entry == 0]
        profit_deals = [d for d in bot_deals if d.profit != 0]

        if not profit_deals:
            logger.info("No closed trades to analyze")
            return

        wins = [d for d in profit_deals if d.profit > 0]
        losses = [d for d in profit_deals if d.profit < 0]
        total_profit = sum(d.profit for d in profit_deals)
        total_commission = sum(d.commission for d in profit_deals)
        total_swap = sum(d.swap for d in profit_deals)

        # Strategy performance
        strategy_stats = {}
        for d in profit_deals:
            strat = d.comment.replace("AI_", "") if d.comment else "Unknown"
            if strat not in strategy_stats:
                strategy_stats[strat] = {"wins": 0, "losses": 0, "pnl": 0.0}
            strategy_stats[strat]["pnl"] += d.profit
            if d.profit > 0:
                strategy_stats[strat]["wins"] += 1
            else:
                strategy_stats[strat]["losses"] += 1

        # Hour performance
        hour_stats = {}
        for d in profit_deals:
            entry_deal = None
            for e in entries:
                if e.position_id == d.position_id:
                    entry_deal = e
                    break
            if entry_deal:
                hour = datetime.fromtimestamp(entry_deal.time).hour
            else:
                hour = datetime.fromtimestamp(d.time).hour
            if hour not in hour_stats:
                hour_stats[hour] = {"wins": 0, "losses": 0, "pnl": 0.0}
            hour_stats[hour]["pnl"] += d.profit
            if d.profit > 0:
                hour_stats[hour]["wins"] += 1
            else:
                hour_stats[hour]["losses"] += 1

        # Direction performance
        dir_stats = {"BUY": {"wins": 0, "losses": 0, "pnl": 0.0},
                     "SELL": {"wins": 0, "losses": 0, "pnl": 0.0}}
        for d in profit_deals:
            entry_deal = None
            for e in entries:
                if e.position_id == d.position_id:
                    entry_deal = e
                    break
            if entry_deal:
                orig_side = "BUY" if entry_deal.type == 0 else "SELL"
            else:
                orig_side = "BUY" if d.type in [0, 2] else "SELL"
            dir_stats[orig_side]["pnl"] += d.profit
            if d.profit > 0:
                dir_stats[orig_side]["wins"] += 1
            else:
                dir_stats[orig_side]["losses"] += 1

        analysis = {
            "date": now.strftime("%Y-%m-%d"),
            "total_trades": len(profit_deals),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(profit_deals) * 100 if profit_deals else 0,
            "gross_profit": round(total_profit, 2),
            "commissions": round(total_commission, 2),
            "net_profit": round(total_profit + total_commission + total_swap, 2),
            "avg_win": round(sum(d.profit for d in wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(d.profit for d in losses) / len(losses), 2) if losses else 0,
            "max_streak_losses": 0,
            "strategy_performance": {k: v for k, v in strategy_stats.items()},
            "hour_performance": {str(k): v for k, v in hour_stats.items()},
            "direction_performance": dir_stats,
        }

        self.journal.save_daily_summary(analysis)

        logger.info(
            f"DAILY SUMMARY: {len(profit_deals)} trades | "
            f"W:{len(wins)} L:{len(losses)} | "
            f"WR: {analysis['win_rate']:.0f}% | "
            f"Net: ${analysis['net_profit']:+.2f}"
        )
        for rule in self.journal.get_active_rules():
            logger.info(f"  LESSON: {rule}")

    # ─── AI Model Training ───────────────────────────────────────────────

    def _train_ai_models(self):
        """Train AI models for all trading symbols."""
        logger.info("Training AI models...")

        for symbol in config.trading.symbols:
            try:
                # Try loading existing model first
                if self.ai_predictor.load_model(symbol):
                    if not self.ai_predictor.should_retrain():
                        continue

                # Fetch training data
                df = self.data_fetcher.get_training_data(symbol)
                if df is None or len(df) < 500:
                    logger.warning(f"Insufficient training data for {symbol}")
                    continue

                # Train
                metrics = self.ai_predictor.train(df, symbol)
                logger.info(f"Trained {symbol} | Accuracy: {metrics.get('test_accuracy', 0):.4f}")

            except Exception as e:
                logger.error(f"Failed to train model for {symbol}: {e}")

        logger.info("AI model training complete")


# ─── Entry Point ─────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Forex AI Trading Bot")
    parser.add_argument(
        "--mode", choices=["live", "demo", "paper", "backtest"],
        default="demo", help="Trading mode (default: demo)"
    )
    parser.add_argument(
        "--dashboard", action="store_true",
        help="Launch dashboard only (no trading)"
    )
    parser.add_argument(
        "--symbols", nargs="+",
        help="Override trading symbols (e.g., --symbols EURUSD GBPUSD)"
    )
    parser.add_argument(
        "--no-dashboard", action="store_true",
        help="Run without web dashboard"
    )
    return parser.parse_args()


def main():
    # Setup logging
    setup_logging()

    # Parse arguments
    args = parse_args()

    # Apply mode
    mode_map = {
        "live": TradingMode.LIVE,
        "demo": TradingMode.DEMO,
        "paper": TradingMode.PAPER,
        "backtest": TradingMode.BACKTEST,
    }
    config.trading.mode = mode_map.get(args.mode, TradingMode.DEMO)

    # Override symbols if provided
    if args.symbols:
        config.trading.symbols = args.symbols

    # Auto-fix symbol names for Exness (append 'm' suffix if missing)
    from core.mt5_lock import mt5_safe as mt5
    if mt5.initialize():
        fixed_symbols = []
        for sym in config.trading.symbols:
            info = mt5.symbol_info(sym)
            if info is not None:
                fixed_symbols.append(sym)
            else:
                # Try with 'm' suffix (Exness convention)
                alt = sym + "m"
                info_alt = mt5.symbol_info(alt)
                if info_alt is not None:
                    logger.warning(f"Symbol '{sym}' not found, using '{alt}' instead")
                    fixed_symbols.append(alt)
                else:
                    logger.error(f"Symbol '{sym}' not available on this broker (tried '{alt}' too)")
        config.trading.symbols = fixed_symbols if fixed_symbols else config.trading.symbols
        mt5.shutdown()

    # Create and start bot
    bot = ForexAIBot()

    # Handle graceful shutdown
    def signal_handler(sig, frame):
        logger.info("Shutdown signal received")
        bot.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.dashboard:
        # Dashboard-only mode
        logger.info("Starting in dashboard-only mode")
        dashboard = Dashboard(bot)
        if bot.connector.connect():
            bot.risk_manager.initialize()
            dashboard.run(threaded=False)
        else:
            logger.error("Cannot connect to MT5 for dashboard")
    else:
        # Full trading mode
        bot.start(with_dashboard=not args.no_dashboard)


if __name__ == "__main__":
    main()
