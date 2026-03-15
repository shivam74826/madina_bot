"""
=============================================================================
Live Trade Manager
=============================================================================
Actively manages open positions based on real-time market conditions:

  1. Signal Dedup - prevents opening identical trades on the same signal
  2. Market monitoring - tracks live price vs SL/TP/entry for each position
  3. Reversal detection - closes/tightens if market structure flips
  4. Dynamic SL management - tighten SL when momentum fades
  5. Early exit - close if the original thesis is invalidated
  6. Rich terminal display - prints clear, color-coded status every cycle

Usage:
    Integrated into main.py trading loop - called every cycle.
=============================================================================
"""

import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from core.mt5_lock import mt5_safe as mt5
from config.settings import config
from strategy.base_strategy import SignalType

logger = logging.getLogger(__name__)


# --- ANSI Colors for Terminal Output -------------------------------------
class C:
    """Terminal colors."""
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"
    GRAY    = "\033[90m"
    BG_RED  = "\033[41m"
    BG_GREEN = "\033[42m"


@dataclass
class PositionState:
    """Tracks the live state of a managed position."""
    ticket: int
    symbol: str
    direction: str          # "BUY" or "SELL"
    entry_price: float
    sl: float
    tp: float
    volume: float
    open_time: datetime
    strategy: str
    confidence: float
    # Live tracking
    peak_profit: float = 0.0        # Highest profit reached
    worst_drawdown: float = 0.0     # Worst drawdown from peak
    sl_tightened: bool = False       # Whether we already tightened SL
    break_even_set: bool = False     # Whether BE was set
    original_sl: float = 0.0        # Original SL for reference
    regime_at_entry: str = "unknown"


class LiveTradeManager:
    """
    Manages open positions in real-time based on live market conditions.
    Also prevents duplicate signals from opening redundant positions.
    """

    def __init__(self, connector, order_manager):
        self.connector = connector
        self.order_manager = order_manager
        # Signal dedup: tracks the last executed signal per symbol
        self._last_signal: Dict[str, Dict] = {}
        # Managed positions: ticket -> PositionState
        self._positions: Dict[int, PositionState] = {}
        # Display throttle
        self._last_display_time: Optional[datetime] = None
        self._display_interval = 60  # seconds between full display

    # --- Signal Dedup ----------------------------------------------------

    def is_duplicate_signal(self, symbol: str, direction: str,
                            sl: float, tp: float) -> bool:
        """
        Check if this signal is essentially the same as one we already traded.
        Prevents the bot from opening 2 identical trades on consecutive cycles.
        """
        last = self._last_signal.get(symbol)
        if last is None:
            return False

        # Same direction?
        if last["direction"] != direction:
            return False

        # Same SL/TP zone? (within 0.5% tolerance)
        sl_diff = abs(last["sl"] - sl) / sl if sl > 0 else 0
        tp_diff = abs(last["tp"] - tp) / tp if tp > 0 else 0

        if sl_diff < 0.005 and tp_diff < 0.005:
            # Check time - only block if last signal was within 10 minutes
            time_diff = (datetime.now() - last["time"]).total_seconds()
            if time_diff < 600:
                return True

        return False

    def record_signal(self, symbol: str, direction: str,
                      sl: float, tp: float):
        """Record a signal that was executed (for dedup tracking)."""
        self._last_signal[symbol] = {
            "direction": direction,
            "sl": sl,
            "tp": tp,
            "time": datetime.now(),
        }

    # --- Position Registration -------------------------------------------

    def register_position(self, ticket: int, symbol: str, direction: str,
                          entry_price: float, sl: float, tp: float,
                          volume: float, strategy: str, confidence: float,
                          regime: str = "unknown"):
        """Register a newly opened position for live management."""
        self._positions[ticket] = PositionState(
            ticket=ticket,
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            sl=sl,
            tp=tp,
            volume=volume,
            open_time=datetime.now(),
            strategy=strategy,
            confidence=confidence,
            original_sl=sl,
            regime_at_entry=regime,
        )

    def sync_positions(self):
        """Sync internal state with actual MT5 positions."""
        try:
            positions = mt5.positions_get()
            if positions is None:
                return

            live_tickets = set()
            for p in positions:
                if p.magic != config.trading.magic_number:
                    continue
                live_tickets.add(p.ticket)

                # If we don't know this position, register it from MT5 data
                if p.ticket not in self._positions:
                    direction = "BUY" if p.type == 0 else "SELL"
                    strategy = p.comment.replace("AI_", "") if p.comment else "Unknown"
                    self._positions[p.ticket] = PositionState(
                        ticket=p.ticket,
                        symbol=p.symbol,
                        direction=direction,
                        entry_price=p.price_open,
                        sl=p.sl,
                        tp=p.tp,
                        volume=p.volume,
                        open_time=datetime.fromtimestamp(p.time),
                        strategy=strategy,
                        confidence=0.0,
                        original_sl=p.sl,
                    )
                else:
                    # Update live SL/TP (might have been modified by trailing stop)
                    self._positions[p.ticket].sl = p.sl
                    self._positions[p.ticket].tp = p.tp
                    self._positions[p.ticket].volume = p.volume

            # Remove closed positions from tracking
            closed = set(self._positions.keys()) - live_tickets
            for ticket in closed:
                pos = self._positions.pop(ticket, None)
                if pos:
                    logger.info(
                        f"{C.YELLOW}POSITION CLOSED{C.RESET} | "
                        f"#{ticket} {pos.direction} {pos.symbol} | "
                        f"Entry: {pos.entry_price:.2f} | "
                        f"Peak profit: {pos.peak_profit:+.2f}"
                    )

        except Exception as e:
            logger.debug(f"Position sync error: {e}")

    # --- Live Market Analysis for Open Positions -------------------------

    def manage_positions(self, data_fetcher=None, technical=None, sentiment=None):
        """
        Main management cycle - called every loop iteration.
        Analyzes live market conditions and takes action on open positions.
        """
        self.sync_positions()

        if not self._positions:
            return

        for ticket, pos in list(self._positions.items()):
            try:
                self._manage_single_position(pos, data_fetcher, technical, sentiment)
            except Exception as e:
                logger.debug(f"Error managing position #{ticket}: {e}")

    def _manage_single_position(self, pos: PositionState,
                                 data_fetcher=None, technical=None,
                                 sentiment=None):
        """Analyze and manage a single open position."""
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return

        # Current P&L in price terms
        if pos.direction == "BUY":
            current_price = tick.bid
            pnl_points = current_price - pos.entry_price
        else:
            current_price = tick.ask
            pnl_points = pos.entry_price - current_price

        # Track peak profit and drawdown from peak
        if pnl_points > pos.peak_profit:
            pos.peak_profit = pnl_points
        drawdown_from_peak = pos.peak_profit - pnl_points
        if drawdown_from_peak > pos.worst_drawdown:
            pos.worst_drawdown = drawdown_from_peak

        sl_distance = abs(pos.entry_price - pos.original_sl)

        # --- Check 1: Momentum Fade - tighten SL if profit gave back >50% --
        if (pos.peak_profit > sl_distance * 0.5 and
                drawdown_from_peak > pos.peak_profit * 0.5 and
                not pos.sl_tightened):
            # Price reached a good profit but is giving it back
            # Tighten SL to protect some gains
            if pos.direction == "BUY":
                new_sl = max(pos.sl, pos.entry_price + pos.peak_profit * 0.2)
                if new_sl > pos.sl and new_sl < current_price:
                    self.order_manager.modify_position(pos.ticket, sl=new_sl)
                    pos.sl_tightened = True
                    logger.info(
                        f"{C.YELLOW}SL TIGHTENED{C.RESET} | "
                        f"#{pos.ticket} BUY {pos.symbol} | "
                        f"Profit fading (peak: {pos.peak_profit:+.2f}, now: {pnl_points:+.2f}) | "
                        f"SL: {pos.sl:.2f} -> {new_sl:.2f}"
                    )
            else:
                new_sl = min(pos.sl, pos.entry_price - pos.peak_profit * 0.2)
                if new_sl < pos.sl and new_sl > current_price:
                    self.order_manager.modify_position(pos.ticket, sl=new_sl)
                    pos.sl_tightened = True
                    logger.info(
                        f"{C.YELLOW}SL TIGHTENED{C.RESET} | "
                        f"#{pos.ticket} SELL {pos.symbol} | "
                        f"Profit fading (peak: {pos.peak_profit:+.2f}, now: {pnl_points:+.2f}) | "
                        f"SL: {pos.sl:.2f} -> {new_sl:.2f}"
                    )

        # --- Check 2: Market Structure Reversal ---------------------
        if data_fetcher and technical:
            try:
                df = data_fetcher.get_ohlcv(pos.symbol, count=50)
                if df is not None and len(df) >= 20:
                    self._check_market_structure(pos, df, pnl_points, sl_distance)
            except Exception:
                pass

    def _check_market_structure(self, pos: PositionState, df,
                                 pnl_points: float, sl_distance: float):
        """Check if market structure has changed against the position."""
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values

        # Simple structure: check if making lower highs/lows (bearish) or higher (bullish)
        recent_highs = highs[-5:]
        recent_lows = lows[-5:]
        prev_highs = highs[-10:-5]
        prev_lows = lows[-10:-5]

        if len(prev_highs) == 0:
            return

        structure_bullish = (max(recent_highs) > max(prev_highs) and
                            min(recent_lows) > min(prev_lows))
        structure_bearish = (max(recent_highs) < max(prev_highs) and
                            min(recent_lows) < min(prev_lows))

        # EMA trend check
        if len(closes) >= 21:
            ema9 = self._ema(closes, 9)
            ema21 = self._ema(closes, 21)
            ema_bullish = ema9 > ema21
        else:
            ema_bullish = None

        # Check for reversal against position
        if pos.direction == "BUY" and structure_bearish and ema_bullish is False:
            if pnl_points > 0:
                # In profit but structure turning - tighten aggressively
                logger.info(
                    f"{C.RED}STRUCTURE SHIFT{C.RESET} | "
                    f"#{pos.ticket} BUY {pos.symbol} | "
                    f"Market turning bearish (lower HH/LL + EMA cross) | "
                    f"P&L: {pnl_points:+.2f} - tightening SL"
                )
        elif pos.direction == "SELL" and structure_bullish and ema_bullish is True:
            if pnl_points > 0:
                logger.info(
                    f"{C.RED}STRUCTURE SHIFT{C.RESET} | "
                    f"#{pos.ticket} SELL {pos.symbol} | "
                    f"Market turning bullish (higher HH/HL + EMA cross) | "
                    f"P&L: {pnl_points:+.2f} - tightening SL"
                )

    def _ema(self, data, period):
        """Fast EMA calculation."""
        result = np.zeros_like(data, dtype=float)
        result[0] = data[0]
        m = 2.0 / (period + 1)
        for i in range(1, len(data)):
            result[i] = data[i] * m + result[i - 1] * (1 - m)
        return result[-1]

    # --- Rich Terminal Display -------------------------------------------

    def print_status(self, cycle_count: int, equity: float, balance: float,
                     risk_summary: dict = None, force: bool = False):
        """
        Print a rich, readable status to the terminal.
        Called every cycle but only prints full display at intervals.
        """
        now = datetime.now()

        # Full display every N seconds
        if not force and self._last_display_time:
            elapsed = (now - self._last_display_time).total_seconds()
            if elapsed < self._display_interval:
                return

        self._last_display_time = now

        if not self._positions:
            return

        # Header
        utc_now = datetime.utcnow()
        print(f"\n{C.CYAN}{'=' * 80}{C.RESET}")
        print(f"{C.BOLD}{C.WHITE}  LIVE POSITION MONITOR{C.RESET}  |  "
              f"{now.strftime('%H:%M:%S')} (UTC: {utc_now.strftime('%H:%M')})  |  "
              f"Cycle #{cycle_count}")
        print(f"{C.CYAN}{'-' * 80}{C.RESET}")

        # Account line
        dd = risk_summary.get("drawdown", 0) if risk_summary else 0
        pf = risk_summary.get("prop_firm", {}) if risk_summary else {}
        dd_color = C.GREEN if dd < 1 else C.YELLOW if dd < 2 else C.RED
        print(f"  {C.BOLD}Account{C.RESET}  |  "
              f"Equity: {C.BOLD}${equity:,.2f}{C.RESET}  |  "
              f"Balance: ${balance:,.2f}  |  "
              f"DD: {dd_color}{dd:.2f}%{C.RESET}")

        if pf.get("enabled"):
            print(f"  {C.BOLD}PropFirm{C.RESET} |  "
                  f"Daily DD: {pf.get('daily_dd_pct', 0):.1f}%/{pf.get('daily_dd_buffer', 3):.0f}%  |  "
                  f"Total DD: {pf.get('total_dd_pct', 0):.1f}%/{pf.get('total_dd_buffer', 6):.0f}%  |  "
                  f"Profit: {pf.get('profit_pct', 0):+.1f}%/{pf.get('target_pct', 8):.0f}%")

        print(f"{C.CYAN}{'-' * 80}{C.RESET}")

        total_pnl = 0.0
        for ticket, pos in self._positions.items():
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                continue

            # Calculate live P&L
            if pos.direction == "BUY":
                current_price = tick.bid
                pnl_points = current_price - pos.entry_price
            else:
                current_price = tick.ask
                pnl_points = pos.entry_price - current_price

            # Distances
            dist_to_sl = abs(current_price - pos.sl)
            dist_to_tp = abs(current_price - pos.tp)
            sl_distance = abs(pos.entry_price - pos.original_sl)
            r_multiple = pnl_points / sl_distance if sl_distance > 0 else 0

            # Get actual dollar P&L from MT5
            mt5_pos = mt5.positions_get(ticket=ticket)
            dollar_pnl = mt5_pos[0].profit if mt5_pos and len(mt5_pos) > 0 else 0
            total_pnl += dollar_pnl

            # Color coding
            if pnl_points > 0:
                pnl_color = C.GREEN
                dir_icon = "^" if pos.direction == "BUY" else "v"
            else:
                pnl_color = C.RED
                dir_icon = "^" if pos.direction == "BUY" else "v"

            # Risk bar (visual SL-to-TP progress)
            total_range = dist_to_sl + dist_to_tp
            if total_range > 0:
                progress = dist_to_sl / total_range  # 0=at SL, 1=at TP
                bar_len = 20
                filled = int(progress * bar_len)
                bar = f"SL {'#' * filled}{'.' * (bar_len - filled)} TP"
            else:
                bar = ""

            # Time in trade
            duration = datetime.now() - pos.open_time
            mins = int(duration.total_seconds() / 60)
            time_str = f"{mins}m" if mins < 60 else f"{mins // 60}h{mins % 60}m"

            # Direction label
            dir_color = C.GREEN if pos.direction == "BUY" else C.RED

            print(f"  {dir_color}{C.BOLD}{dir_icon} {pos.direction}{C.RESET} "
                  f"#{ticket}  |  {pos.symbol}")
            print(f"    Entry: {pos.entry_price:.2f}  |  "
                  f"Now: {C.BOLD}{current_price:.2f}{C.RESET}  |  "
                  f"P&L: {pnl_color}{C.BOLD}{dollar_pnl:+.2f}{C.RESET} "
                  f"({pnl_points:+.2f} pts)  |  "
                  f"R: {pnl_color}{r_multiple:+.1f}R{C.RESET}")
            print(f"    SL: {pos.sl:.2f} ({dist_to_sl:.1f} away)  |  "
                  f"TP: {pos.tp:.2f} ({dist_to_tp:.1f} away)  |  "
                  f"Time: {time_str}")
            print(f"    Strategy: {pos.strategy}  |  "
                  f"Conf: {pos.confidence:.0%}  |  "
                  f"Peak: {pos.peak_profit:+.2f}")
            print(f"    {C.GRAY}{bar}{C.RESET}")
            print(f"{C.CYAN}{'-' * 80}{C.RESET}")

        # Total
        total_color = C.GREEN if total_pnl >= 0 else C.RED
        print(f"  {C.BOLD}TOTAL P&L: {total_color}{total_pnl:+.2f}{C.RESET}  |  "
              f"Positions: {len(self._positions)}/{config.trading.max_open_trades}")
        print(f"{C.CYAN}{'=' * 80}{C.RESET}\n")

    def print_trade_decision(self, symbol: str, signal, lot_size: float,
                             market_regime: str, volume_ok: bool,
                             divergence: str, consensus_info: str = ""):
        """Print a detailed breakdown of WHY a trade is being taken."""
        direction = signal.signal_type.value
        dir_color = C.GREEN if direction == "BUY" else C.RED

        # Risk/reward visual
        sl_dist = abs(signal.entry_price - signal.stop_loss)
        tp_dist = abs(signal.entry_price - signal.take_profit)

        print(f"\n{C.BOLD}{C.WHITE}{'=' * 80}{C.RESET}")
        print(f"  {dir_color}{C.BOLD}>>> NEW TRADE: {direction} {symbol} <<<{C.RESET}")
        print(f"{C.WHITE}{'-' * 80}{C.RESET}")
        print(f"  {C.BOLD}WHY:{C.RESET}")
        print(f"    Strategy: {C.BOLD}{signal.strategy_name}{C.RESET}")
        print(f"    Confidence: {C.BOLD}{signal.confidence:.0%}{C.RESET}")
        print(f"    Market Regime: {market_regime}")
        print(f"    Volume Healthy: {'Yes' if volume_ok else 'No (divergence penalty applied)'}")
        if divergence:
            print(f"    RSI Divergence: {divergence}")
        print(f"    Reason: {signal.reason[:100]}")
        print(f"{C.WHITE}{'-' * 80}{C.RESET}")
        print(f"  {C.BOLD}LEVELS:{C.RESET}")
        print(f"    Entry: {signal.entry_price:.2f}")
        print(f"    SL:    {signal.stop_loss:.2f}  ({sl_dist:.2f} pts risk)")
        print(f"    TP:    {signal.take_profit:.2f}  ({tp_dist:.2f} pts reward)")
        print(f"    R:R:   {C.BOLD}{signal.risk_reward:.2f}{C.RESET}")
        print(f"    Lot:   {lot_size}")
        print(f"{C.BOLD}{C.WHITE}{'=' * 80}{C.RESET}\n")

    def print_signal_analysis(self, symbol: str, signal, approved: bool,
                              reject_reasons: list = None):
        """Print what the bot is seeing and deciding (even for rejected signals)."""
        now = datetime.now()
        utc_now = datetime.utcnow()

        if signal.signal_type == SignalType.HOLD:
            return  # Don't spam HOLD signals

        direction = signal.signal_type.value
        dir_color = C.GREEN if direction == "BUY" else C.RED

        if approved:
            status = f"{C.GREEN}APPROVED{C.RESET}"
        else:
            status = f"{C.RED}REJECTED{C.RESET}"

        print(f"  {C.GRAY}{now.strftime('%H:%M:%S')}{C.RESET} | "
              f"{dir_color}{direction}{C.RESET} {symbol} | "
              f"Conf: {signal.confidence:.0%} | "
              f"R:R: {signal.risk_reward:.2f} | "
              f"{signal.strategy_name} | "
              f"{status}")

        if not approved and reject_reasons:
            for reason in reject_reasons[:2]:
                print(f"    {C.GRAY}+-- {reason}{C.RESET}")

    def print_cycle_header(self, cycle_count: int):
        """Print a minimal cycle separator."""
        now = datetime.now()
        utc_now = datetime.utcnow()
        if cycle_count % 5 == 0:
            print(f"\n  {C.GRAY}-- Cycle #{cycle_count} | "
                  f"{now.strftime('%H:%M:%S')} | "
                  f"UTC: {utc_now.strftime('%H:%M')} --{C.RESET}")

    def print_market_snapshot(self, symbol: str, df):
        """Print a quick market snapshot for context."""
        if df is None or len(df) < 20:
            return

        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        current = closes[-1]

        # Simple EMA
        ema9 = self._ema(closes, 9)
        ema21 = self._ema(closes, 21)

        # RSI approximation
        deltas = np.diff(closes[-15:])
        gains = np.mean(np.where(deltas > 0, deltas, 0))
        losses_val = np.mean(np.where(deltas < 0, -deltas, 0))
        rsi = 100 - (100 / (1 + gains / losses_val)) if losses_val > 0 else 50

        # ATR
        trs = []
        for i in range(max(1, len(df) - 14), len(df)):
            h, l = highs[i], lows[i]
            pc = closes[i - 1] if i > 0 else closes[i]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        atr = np.mean(trs) if trs else 0

        trend = "BULLISH" if ema9 > ema21 else "BEARISH"
        trend_color = C.GREEN if trend == "BULLISH" else C.RED

        # Last candle
        last_open = df['open'].values[-1] if 'open' in df.columns else closes[-2]
        candle = "GREEN" if current > last_open else "RED"
        candle_color = C.GREEN if candle == "GREEN" else C.RED

        print(f"  {C.GRAY}Market:{C.RESET} {symbol} @ {C.BOLD}{current:.2f}{C.RESET} | "
              f"EMA: {trend_color}{trend}{C.RESET} | "
              f"RSI: {rsi:.0f} | "
              f"ATR: {atr:.1f} | "
              f"Candle: {candle_color}{candle}{C.RESET}")
