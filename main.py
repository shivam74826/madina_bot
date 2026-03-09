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

        # Dashboard (initialized later)
        self.dashboard = None

        # Track open position tickets → detect closures for circuit breaker
        self._tracked_tickets: set = set()

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
                    f"  ✓ {symbol} | Min lot: {report['min_lot']} | "
                    f"Margin: ${report['margin_for_min_lot']} | "
                    f"Risk@min: {report['risk_pct_at_min_lot']}% | "
                    f"ATR: ${report['atr']}"
                )
            else:
                effective_cap = self.risk_manager._get_effective_max_risk_at_min_lot()
                logger.warning(
                    f"  ✗ {symbol} | NOT VIABLE at ${report.get('equity', 0):.2f} — "
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

        # Start trading loop
        self.running = True
        self._trading_loop()

        return True

    def stop(self):
        """Gracefully stop the bot."""
        logger.info("Stopping bot...")
        self.running = False
        self.connector.disconnect()
        logger.info("Bot stopped successfully")

    # ─── Main Trading Loop ───────────────────────────────────────────────

    def _trading_loop(self):
        """Main trading loop - runs continuously."""
        logger.info("Trading loop started")

        while self.running:
            try:
                self.cycle_count += 1
                cycle_start = time.time()

                # Check connection
                if not self.connector.is_connected():
                    logger.warning("Lost MT5 connection, reconnecting...")
                    if not self.connector.reconnect():
                        time.sleep(30)
                        continue

                # Emergency checks
                if self.risk_manager.check_emergency_conditions():
                    logger.critical("Emergency conditions detected! Pausing for 5 minutes.")
                    time.sleep(300)
                    continue

                # Update trailing stops for open positions
                self.order_manager.update_trailing_stops()

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
                if self.cycle_count % 10 == 0:
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
                            logger.info(
                                f"Position closed: {result} {profit:+.2f} | "
                                f"{deal_symbol} | {strategy_name} | "
                                f"Consecutive losses: {self.risk_manager._consecutive_losses}"
                            )

            # Update tracked set
            self._tracked_tickets = current_tickets

        except Exception as e:
            logger.debug(f"Position tracking error: {e}")

    def _analyze_and_trade(self, symbol: str):
        """Analyze a symbol and execute trades if conditions are met."""
        # Throttle analysis (don't re-analyze too frequently)
        now = datetime.now()
        last_time = self.last_analysis_time.get(symbol)
        if last_time and (now - last_time).total_seconds() < 30:
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

        # ─── News Check (informational only, does not block) ────
        news_size_factor = 1.0
        try:
            can_trade, news_reason, size_factor = self.news_analyzer.should_trade(symbol)
            news_size_factor = size_factor
            if not can_trade:
                logger.info(f"{symbol} | NEWS INFO: {news_reason} (not blocking)")
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

        # Validate through risk manager (basic checks only)
        validation = self.risk_manager.validate_trade(signal)

        if not validation["approved"]:
            logger.info(f"{symbol} | Signal rejected: {', '.join(validation['reasons'])}")
            return

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
