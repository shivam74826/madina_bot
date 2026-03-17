"""
=============================================================================
Risk Manager — Hardened V2
=============================================================================
Comprehensive risk management system that protects the trading account:
- Dynamic position sizing based on account equity & SL distance (1% rule)
- Daily loss limits & maximum drawdown protection
- Consecutive loss pausing (circuit breaker)
- Spread & slippage filters (reject unrealistic fills)
- Minimum TP distance enforcement
- Volatility-adaptive position sizing
- NO martingale, NO grid, NO trading without stops
=============================================================================
"""

from core.mt5_lock import mt5_safe as mt5
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import logging

from config.settings import config
from core.mt5_connector import MT5Connector
from core.order_manager import OrderManager
from strategy.base_strategy import TradeSignal, SignalType

logger = logging.getLogger(__name__)


class RiskManager:
    """Manages all risk-related decisions and protections."""

    def __init__(self, connector: MT5Connector, order_manager: OrderManager):
        self.connector = connector
        self.order_manager = order_manager
        self._daily_losses = {}
        self._initial_balance = 0.0
        self._peak_equity = 0.0
        self._news_size_factor = 1.0
        self._consecutive_losses = 0
        self._loss_pause_until: Optional[datetime] = None  # Pause until this time
        self._total_trades_taken = 0     # Lifetime count for scaling discipline
        self._last_trade_time: Dict[str, datetime] = {}   # Per-symbol cooldown
        self._last_trade_result: Dict[str, float] = {}    # Per-symbol last P&L
        self._strategy_performance: Dict[str, Dict] = {}  # Track strategy W/L
        self._account_mode = "normal"    # "micro", "small", or "normal"
        # ─── Prop Firm Tracking ──────────────────────────────────
        self._prop_firm_start_balance = 0.0  # Starting balance for DD calculation
        self._prop_firm_daily_start = 0.0    # Balance at start of trading day
        self._prop_firm_day_date = None      # Current trading day
        self._prop_firm_halted = False       # Emergency halt flag

    def initialize(self):
        """
        Initialize risk manager with CURRENT live account state.
        Always resets to current balance/equity — no stale peaks carried over.
        Auto-detects account size and adjusts parameters accordingly.
        """
        self._initial_balance = self.connector.get_balance()
        self._peak_equity = self.connector.get_equity()
        self._daily_losses = {}
        self._consecutive_losses = 0
        self._loss_pause_until = None
        self._total_trades_taken = 0
        self._last_trade_time = {}
        self._last_trade_result = {}
        self._strategy_performance = {}

        # ─── Prop Firm Initialization ────────────────────────────
        if config.prop_firm.enabled:
            self._prop_firm_start_balance = config.prop_firm.account_size
            self._prop_firm_daily_start = self._peak_equity
            self._prop_firm_day_date = date.today()
            self._prop_firm_halted = False
            self._account_mode = "normal"  # Always normal for prop firm

            phase = config.prop_firm.current_phase
            target_pct = config.prop_firm.phase1_target if phase == 1 else config.prop_firm.phase2_target
            target_usd = config.prop_firm.account_size * target_pct

            logger.info(
                f"=======================================================\n"
                f"  PROP FIRM MODE: {config.prop_firm.firm_name}\n"
                f"  Account Size: ${config.prop_firm.account_size:,.0f}\n"
                f"  Current Balance: ${self._initial_balance:,.2f}\n"
                f"  Current Equity: ${self._peak_equity:,.2f}\n"
                f"  Phase: {phase} | Target: {target_pct:.0%} (${target_usd:,.0f})\n"
                f"  Daily DD Limit: {config.prop_firm.daily_drawdown_limit:.0%} "
                f"(${config.prop_firm.account_size * config.prop_firm.daily_drawdown_limit:,.0f})\n"
                f"  Bot Daily Buffer: {config.prop_firm.daily_drawdown_buffer:.0%} "
                f"(${config.prop_firm.account_size * config.prop_firm.daily_drawdown_buffer:,.0f})\n"
                f"  Max DD Limit: {config.prop_firm.max_drawdown_limit:.0%} "
                f"(${config.prop_firm.account_size * config.prop_firm.max_drawdown_limit:,.0f})\n"
                f"  Bot DD Buffer: {config.prop_firm.max_drawdown_buffer:.0%} "
                f"(${config.prop_firm.account_size * config.prop_firm.max_drawdown_buffer:,.0f})\n"
                f"  Risk/Trade: {config.prop_firm.max_risk_per_trade:.2%}\n"
                f"  Max Open Trades: {config.prop_firm.max_open_trades}\n"
                f"  Max Lot: {config.prop_firm.max_lot_size}\n"
                f"======================================================="
            )
            return

        # ─── Auto-detect account mode from live balance ──────────
        equity = self._peak_equity
        if equity < config.risk.min_viable_balance:
            self._account_mode = "micro"
            logger.warning(
                f"VERY LOW BALANCE: ${equity:.2f} — will attempt to trade at minimum "
                f"lot size. Consider topping up for better risk management."
            )
        elif equity < config.risk.micro_account_threshold:
            self._account_mode = "micro"
            eff_risk = self._get_effective_risk_pct()
            eff_dd = self._get_effective_max_drawdown()
            eff_rr = self._get_effective_rr_ratio()
            logger.info(
                f"═══ MICRO ACCOUNT MODE ═══\n"
                f"  Balance: ${self._initial_balance:.2f}\n"
                f"  Equity:  ${equity:.2f}\n"
                f"  Risk/trade: {eff_risk:.0%} (normal: {config.risk.max_risk_per_trade:.0%})\n"
                f"  Max DD:     {eff_dd:.0%} (normal: {config.risk.max_drawdown:.0%})\n"
                f"  Min R:R:    {eff_rr:.1f} (normal: {config.risk.risk_reward_ratio:.1f})\n"
                f"  Scaling:    DISABLED (already at minimum size)\n"
                f"  Min lot will be used — risk per trade may exceed target %"
            )
        elif equity < config.risk.small_account_threshold:
            self._account_mode = "small"
            logger.info(
                f"═══ SMALL ACCOUNT MODE ═══\n"
                f"  Balance: ${self._initial_balance:.2f} | Risk/trade: "
                f"{self._get_effective_risk_pct():.0%} | Max DD: {self._get_effective_max_drawdown():.0%}"
            )
        else:
            self._account_mode = "normal"
            logger.info(f"Risk Manager initialized | Balance: ${self._initial_balance:.2f}")

    # ─── Balance-Adaptive Helpers ────────────────────────────────────────

    def _get_effective_risk_pct(self) -> float:
        """
        Return the risk-per-trade percentage scaled to account size.
        Smaller accounts need higher risk % to reach minimum lot sizes.
        """
        if not config.risk.auto_risk_scaling:
            return config.risk.max_risk_per_trade

        if self._account_mode == "micro":
            return config.risk.micro_risk_per_trade        # 5%
        elif self._account_mode == "small":
            return config.risk.small_risk_per_trade         # 3%
        else:
            return config.risk.max_risk_per_trade           # 1%

    def _get_effective_max_drawdown(self) -> float:
        """Return the DD limit scaled to account size."""
        if self._account_mode == "micro":
            return config.risk.micro_max_drawdown           # 30%
        return config.risk.max_drawdown                     # 10%

    def _get_effective_rr_ratio(self) -> float:
        """Return the min R:R scaled to account size."""
        if self._account_mode == "micro":
            return config.risk.micro_risk_reward_ratio      # 1.5
        return config.risk.risk_reward_ratio                # 2.0

    def _get_effective_max_risk_at_min_lot(self) -> float:
        """Return the max acceptable risk % when forced to use minimum lot.
        Micro accounts MUST accept higher risk because min lot is fixed by broker."""
        if self._account_mode == "micro":
            return config.risk.micro_max_risk_at_min_lot    # 80%
        elif self._account_mode == "small":
            return config.risk.small_max_risk_at_min_lot    # 50%
        return config.risk.max_risk_at_min_lot              # 25%

    def is_account_viable(self) -> bool:
        """Check if equity is above the bankruptcy floor. Protects the prop firm account."""
        equity = self.connector.get_equity()
        # Equity floor = 20% below prop firm starting balance (absolute minimum)
        if config.prop_firm.enabled:
            floor = config.prop_firm.account_size * (1.0 - config.prop_firm.max_drawdown_limit)
        else:
            floor = self._initial_balance * 0.80  # 80% of starting balance
        if equity < floor:
            logger.critical(
                f"EQUITY FLOOR BREACH: ${equity:.2f} < ${floor:.2f} — "
                f"ALL TRADING HALTED to protect account"
            )
            return False
        return True

    def assess_symbol_viability(self, symbol: str) -> Dict:
        """
        Check if the account can trade this symbol at the current balance.
        Queries the broker for min lot, tick value, margin requirements.
        Returns a report dict.
        """
        equity = self.connector.get_equity()
        sym_info = mt5.symbol_info(symbol)

        if sym_info is None:
            return {"viable": False, "symbol": symbol, "reason": "Symbol not found on broker"}

        min_vol = sym_info.volume_min
        tick_value = sym_info.trade_tick_value
        contract_size = sym_info.trade_contract_size
        current_price = (sym_info.bid + sym_info.ask) / 2

        # Get leverage from account
        acct = self.connector.get_account_info()
        leverage = acct.get("leverage", 500) if acct else 500

        # Margin required for minimum lot
        margin_for_min = contract_size * min_vol * current_price / leverage

        # Risk at min lot with a typical SL (use 1.5 ATR as reference)
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 20)
            if rates and len(rates) >= 14:
                highs = np.array([r[2] for r in rates])
                lows = np.array([r[3] for r in rates])
                closes = np.array([r[4] for r in rates])
                tr = np.maximum(
                    highs[1:] - lows[1:],
                    np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
                )
                atr = float(np.mean(tr[-14:]))
            else:
                atr = current_price * 0.005  # Fallback: 0.5%
        except Exception:
            atr = current_price * 0.005

        # Typical SL distance = 1.5 ATR
        typical_sl_price = atr * 1.5

        # Risk at min lot with typical SL
        # For gold: 1 pip = (depends on digits), tick_value per point per lot
        point = sym_info.point
        if sym_info.digits in (3, 5):
            pip = point * 10
        else:
            pip = point
        sl_pips = typical_sl_price / pip if pip > 0 else 0

        # Risk = sl_pips * tick_value * 10 * min_vol
        # (matching the formula in order_manager.calculate_lot_size: lot = risk / (sl_pips * tick_value * 10))
        risk_at_min_lot = sl_pips * tick_value * 10 * min_vol if tick_value > 0 else 0
        risk_pct_at_min_lot = risk_at_min_lot / equity if equity > 0 else 1.0

        effective_max_risk = self._get_effective_max_risk_at_min_lot()
        viable = (
            margin_for_min < equity * 0.5 and  # Margin < 50% of equity
            risk_pct_at_min_lot < effective_max_risk  # Risk < adaptive cap
        )

        return {
            "viable": viable,
            "symbol": symbol,
            "equity": equity,
            "min_lot": min_vol,
            "margin_for_min_lot": round(margin_for_min, 2),
            "atr": round(atr, 2),
            "typical_sl": round(typical_sl_price, 2),
            "risk_at_min_lot": round(risk_at_min_lot, 2),
            "risk_pct_at_min_lot": round(risk_pct_at_min_lot * 100, 1),
            "tick_value": tick_value,
            "contract_size": contract_size,
            "leverage": leverage,
        }

    # ─── Trade Validation ────────────────────────────────────────────────

    def validate_trade(self, signal: TradeSignal) -> Dict:
        """
        Comprehensive trade validation before execution.

        Checks:
        1. Signal validity (SL & TP required — no naked trades)
        2. Risk/reward ratio (minimum 1:2)
        3. Position limits (max open trades, max per symbol)
        4. Daily loss limit
        5. Max drawdown
        6. Consecutive loss pause (circuit breaker)
        7. Margin requirements
        8. Trading hours
        9. Confidence threshold
        10. Spread filter (reject if spread too wide vs ATR)
        11. Minimum TP distance (must be realistic, not sub-spread)
        """
        reasons = []
        approved = True

        # 0. Equity floor — absolute bankruptcy protection
        if not self.is_account_viable():
            return {"approved": False, "reasons": [
                "EQUITY FLOOR: Account below minimum viable equity — no new trades"
            ]}

        # 1. Signal validity — EVERY trade MUST have SL and TP
        if not signal.is_valid():
            return {"approved": False, "reasons": ["Invalid signal data (missing SL/TP)"]}

        if signal.signal_type == SignalType.HOLD:
            return {"approved": False, "reasons": ["HOLD signal - no trade"]}

        if signal.stop_loss <= 0 or signal.take_profit <= 0:
            return {"approved": False, "reasons": ["REJECTED: No trade without SL and TP"]}

        # ─── PROP FIRM CHECKS (highest priority) ────────────────
        if config.prop_firm.enabled:
            if self._prop_firm_halted:
                return {"approved": False, "reasons": [
                    "PROP FIRM HALTED: Account protection active — no new trades"
                ]}

            pf_ok, pf_reason = self._check_prop_firm_limits()
            if not pf_ok:
                return {"approved": False, "reasons": [pf_reason]}

        # 2. Risk/Reward ratio — adaptive minimum based on account size
        rr = signal.risk_reward
        min_rr = self._get_effective_rr_ratio()
        if rr < min_rr:
            approved = False
            reasons.append(f"R:R too low ({rr:.2f}, min: {min_rr})")

        # 3. Position limits
        open_positions = self.connector.get_bot_positions()
        if len(open_positions) >= config.trading.max_open_trades:
            approved = False
            reasons.append(f"Max open trades reached ({len(open_positions)}/{config.trading.max_open_trades})")

        symbol_positions = [p for p in open_positions if p["symbol"] == signal.symbol]
        if len(symbol_positions) >= config.trading.max_trades_per_symbol:
            approved = False
            reasons.append(f"Max trades for {signal.symbol} reached ({len(symbol_positions)})")

        # Block conflicting positions (no hedging)
        for pos in symbol_positions:
            if (signal.signal_type == SignalType.BUY and pos["type"] == "SELL") or \
               (signal.signal_type == SignalType.SELL and pos["type"] == "BUY"):
                approved = False
                reasons.append(f"BLOCKED: Conflicting position on {signal.symbol} — close first")

        # 3b. Hard daily trade cap — prevents overtrading even across restarts
        try:
            date_from = datetime.combine(date.today(), datetime.min.time())
            date_to = datetime.now() + timedelta(hours=1)
            from core.mt5_lock import mt5_safe as _mt5
            deals = _mt5.history_deals_get(date_from, date_to)
            if deals:
                daily_entries = sum(
                    1 for d in deals
                    if d.magic == config.trading.magic_number and d.entry == 0
                )
                max_daily = 6  # Hard cap — never exceed 6 trades per day
                if daily_entries >= max_daily:
                    approved = False
                    reasons.append(f"HARD CAP: {daily_entries}/{max_daily} trades today — done for the day")
        except Exception:
            pass  # If history query fails, rely on other guards

        # 4. Daily loss limit
        if self._is_daily_loss_exceeded():
            approved = False
            reasons.append("Daily loss limit exceeded — no new trades today")

        # 5. Max drawdown (adaptive to account size)
        if self._is_drawdown_exceeded():
            approved = False
            dd_limit = self._get_effective_max_drawdown()
            reasons.append(f"Maximum drawdown limit exceeded ({dd_limit:.0%}) — trading halted")

        # 6. Consecutive loss circuit breaker
        if self._is_loss_paused():
            approved = False
            remaining = ""
            if self._loss_pause_until:
                mins_left = (self._loss_pause_until - datetime.now()).total_seconds() / 60
                remaining = f" ({mins_left:.0f} min remaining)"
            reasons.append(
                f"PAUSED: {self._consecutive_losses} consecutive losses{remaining}"
            )

        # 7. Margin check (adaptive floor for micro accounts)
        account = self.connector.get_account_info()
        if account:
            equity = self.connector.get_equity()
            # Micro accounts: 10% free margin floor; normal: 20%
            margin_floor_pct = 0.10 if self._account_mode == "micro" else 0.20
            min_free_margin = max(equity * margin_floor_pct, 5.0)
            if account["free_margin"] < min_free_margin:
                approved = False
                reasons.append(f"Insufficient margin (Free: {account['free_margin']:.2f}, need: {min_free_margin:.2f})")
            margin_level = account.get("margin_level", 0)
            min_margin_level = 150 if self._account_mode == "micro" else 200
            if margin_level > 0 and margin_level < min_margin_level:
                approved = False
                reasons.append(f"Margin level too low ({margin_level:.1f}%, min: {min_margin_level}%)")

        # 8. Trading hours
        if not self._is_trading_hours(signal.symbol):
            approved = False
            reasons.append("Outside trading hours")

        # 8b. Session filter (gold = London + US only)
        if not self._is_optimal_session(signal.symbol):
            approved = False
            reasons.append("Outside optimal trading session for this instrument")

        # 8c. Trade cooldown — prevent rapid-fire trades on same symbol
        cooldown_ok, cooldown_reason = self._check_trade_cooldown(signal.symbol)
        if not cooldown_ok:
            approved = False
            reasons.append(cooldown_reason)

        # 9. Confidence check (slightly relaxed for micro accounts)
        min_conf = config.ai.min_confidence
        if self._account_mode == "micro":
            min_conf = max(min_conf - 0.05, 0.45)  # 0.50 instead of 0.55
        if signal.confidence < min_conf:
            approved = False
            reasons.append(f"Confidence too low ({signal.confidence:.2f}, min: {min_conf})")

        if approved:
            reasons.append("All checks passed")

        return {
            "approved": approved,
            "reasons": reasons,
            "signal": signal.signal_type.value,
            "symbol": signal.symbol,
            "confidence": signal.confidence,
            "risk_reward": signal.risk_reward,
        }

    # ─── Position Sizing ─────────────────────────────────────────────────

    def calculate_position_size(
        self, signal: TradeSignal, news_size_factor: float = 1.0
    ) -> float:
        """
        Calculate position size using balance-adaptive risk sizing.

        Auto-scales to account size:
        - Normal ($500+): risk 1% of equity, commission-adjusted
        - Small ($200-500): risk 3% of equity
        - Micro (<$200): risk 5%, clamp to min lot if needed, cap at 25% actual risk

        Rules:
        - ALWAYS calculate from SL distance — never use fixed lot
        - Reduce after consecutive losses
        - Reduce near news events
        - NEVER increase size after wins (no martingale)
        - If forced to min-lot, check actual risk doesn't exceed hard cap
        """
        sl_distance = abs(signal.entry_price - signal.stop_loss)
        sl_pips = self._price_to_pips(signal.symbol, sl_distance)

        # ─── Slippage Budget: widen effective SL for sizing ──────
        sl_pips += config.risk.estimated_slippage_pips

        if sl_pips <= 0:
            logger.warning(f"Invalid SL pips for {signal.symbol}, using minimum lot")
            return config.risk.min_lot_size

        # Use BALANCE for sizing (stable), equity only for DD checks
        balance = self.connector.get_balance()
        equity = self.connector.get_equity()
        sizing_base = balance if balance > 0 else equity
        eff_risk = self._get_effective_risk_pct()

        # ─── Dynamic Risk Scaling (reduce when in drawdown) ──────
        dd = self._current_drawdown()
        eff_dd = self._get_effective_max_drawdown()
        if dd > 0 and eff_dd > 0:
            # Linear reduction: at 50% of max DD, risk drops to 50%
            dd_ratio = dd / eff_dd
            if dd_ratio > 0.3:
                risk_multiplier = max(0.25, 1.0 - dd_ratio)
                eff_risk *= risk_multiplier
                logger.info(
                    f"DYNAMIC RISK: DD at {dd:.2%} ({dd_ratio:.0%} of max) "
                    f"-- risk reduced to {eff_risk:.3%}"
                )

        # Calculate base lot size using BALANCE (not equity) for stable sizing
        base = self.order_manager.calculate_lot_size(
            signal.symbol, sl_pips, eff_risk, use_balance=True
        )

        # Commission deduction — only for accounts where it's meaningful
        # Skip for micro accounts (commission > risk budget is nonsensical)
        if self._account_mode == "normal":
            commission_cost = config.risk.estimated_commission_per_lot
            if base > 0 and commission_cost > 0:
                gross_risk = sizing_base * eff_risk
                net_risk = gross_risk - (commission_cost * base)
                if net_risk > 0:
                    adjustment = net_risk / gross_risk
                    base *= adjustment

        # ─── Risk Adjustments (only reductions, never increases) ─────
        # 1. News factor
        base *= news_size_factor

        # 2. Losing streak reduction (progressive)
        if self._consecutive_losses >= 5:
            base *= 0.25
            logger.info(f"Position at 25%: {self._consecutive_losses} consecutive losses")
        elif self._consecutive_losses >= 3:
            base *= 0.5
            logger.info(f"Position at 50%: {self._consecutive_losses} consecutive losses")

        # 3. Drawdown-based reduction is now handled above via dynamic risk scaling

        # NO confidence scaling — removed

        # 4. Scaling discipline — DISABLED
        # (Previously reduced size for first N trades)

        # ─── Min-Lot Clamping with Risk Cap ──────────────────────
        # Get actual broker minimum lot
        sym_info = mt5.symbol_info(signal.symbol)
        actual_min_lot = sym_info.volume_min if sym_info else config.risk.min_lot_size

        if base < actual_min_lot:
            # Check if trading at min lot is within acceptable risk
            tick_value = sym_info.trade_tick_value if sym_info else 0
            actual_risk = sl_pips * tick_value * 10 * actual_min_lot if tick_value > 0 else 0
            actual_risk_pct = actual_risk / equity if equity > 0 else 1.0

            effective_max_risk = self._get_effective_max_risk_at_min_lot()
            if actual_risk_pct > effective_max_risk:
                # Too risky even at min lot — reject
                logger.warning(
                    f"{signal.symbol} | Min lot {actual_min_lot} risks "
                    f"{actual_risk_pct:.0%} of equity (cap: {effective_max_risk:.0%}) — "
                    f"SL too wide for this balance"
                )
                return 0.0  # Signal to caller: can't size this trade

            # Use min lot with elevated risk — acceptable for small accounts
            logger.info(
                f"{signal.symbol} | Using min lot {actual_min_lot} "
                f"(actual risk: {actual_risk_pct:.1%} of ${equity:.2f})"
            )
            base = actual_min_lot

        # Clamp to limits (use stricter of risk config and prop firm config)
        max_lot = config.risk.max_lot_size
        if config.prop_firm.enabled:
            max_lot = min(max_lot, config.prop_firm.max_lot_size)
        base = max(actual_min_lot, min(base, max_lot))

        # Round to volume step (floor to avoid oversizing)
        if sym_info:
            step = sym_info.volume_step
            import math
            base = math.floor(base / step) * step

        return round(base, 2)

    def record_trade_opened(self, symbol: str):
        """Record that a trade was just opened — starts the cooldown timer."""
        self._last_trade_time[symbol] = datetime.now()

    def record_trade_result(self, profit: float, symbol: str = "", strategy: str = ""):
        """Track consecutive wins/losses for position sizing and circuit breaker."""
        self._total_trades_taken += 1

        if profit < 0:
            self._consecutive_losses += 1
            if self._consecutive_losses >= config.risk.max_consecutive_losses:
                pause_mins = config.risk.pause_after_losses_minutes
                self._loss_pause_until = datetime.now() + timedelta(minutes=pause_mins)
                logger.warning(
                    f"CIRCUIT BREAKER: {self._consecutive_losses} consecutive losses. "
                    f"Trading paused for {pause_mins} minutes until {self._loss_pause_until}"
                )
        else:
            self._consecutive_losses = 0

        # Per-symbol cooldown tracking
        if symbol:
            self._last_trade_time[symbol] = datetime.now()
            self._last_trade_result[symbol] = profit

        # Per-strategy performance tracking (for adaptive weights)
        if strategy:
            if strategy not in self._strategy_performance:
                self._strategy_performance[strategy] = {
                    "wins": 0, "losses": 0, "total_pnl": 0.0
                }
            perf = self._strategy_performance[strategy]
            perf["total_pnl"] += profit
            if profit >= 0:
                perf["wins"] += 1
            else:
                perf["losses"] += 1

    def get_strategy_win_rates(self) -> Dict[str, float]:
        """Get win rate for each strategy — used to auto-adjust weights."""
        rates = {}
        for name, perf in self._strategy_performance.items():
            total = perf["wins"] + perf["losses"]
            if total >= 5:  # Need at least 5 trades for meaningful data
                rates[name] = perf["wins"] / total
        return rates

    # ─── Prop Firm Protection ────────────────────────────────────────────

    def _prop_firm_daily_reset(self):
        """Reset daily tracking at the start of each new trading day."""
        today = date.today()
        if self._prop_firm_day_date != today:
            self._prop_firm_daily_start = self.connector.get_equity()
            self._prop_firm_day_date = today
            logger.info(
                f"PROP FIRM | New trading day | Daily start equity: "
                f"${self._prop_firm_daily_start:,.2f}"
            )

    def _prop_firm_daily_dd(self) -> float:
        """Calculate current daily drawdown as fraction of starting balance."""
        if not config.prop_firm.enabled:
            return 0.0
        self._prop_firm_daily_reset()
        equity = self.connector.get_equity()
        daily_loss = self._prop_firm_daily_start - equity
        if daily_loss <= 0:
            return 0.0
        return daily_loss / config.prop_firm.account_size

    def _prop_firm_total_dd(self) -> float:
        """Calculate total drawdown from starting balance as fraction."""
        if not config.prop_firm.enabled:
            return 0.0
        equity = self.connector.get_equity()
        total_loss = config.prop_firm.account_size - equity
        if total_loss <= 0:
            return 0.0
        return total_loss / config.prop_firm.account_size

    def _check_prop_firm_limits(self) -> tuple:
        """
        Check all prop firm drawdown limits. Returns (ok, reason).
        Uses bot safety buffers which are tighter than actual firm limits.
        """
        if not config.prop_firm.enabled:
            return True, ""

        # Check total drawdown against bot buffer
        total_dd = self._prop_firm_total_dd()
        if total_dd >= config.prop_firm.max_drawdown_buffer:
            reason = (
                f"PROP FIRM HALT: Total DD {total_dd:.2%} hit bot buffer "
                f"({config.prop_firm.max_drawdown_buffer:.0%}). "
                f"Firm limit: {config.prop_firm.max_drawdown_limit:.0%}"
            )
            return False, reason

        # Check daily drawdown against bot buffer
        daily_dd = self._prop_firm_daily_dd()
        if daily_dd >= config.prop_firm.daily_drawdown_buffer:
            reason = (
                f"PROP FIRM PAUSE: Daily DD {daily_dd:.2%} hit bot buffer "
                f"({config.prop_firm.daily_drawdown_buffer:.0%}). "
                f"Firm limit: {config.prop_firm.daily_drawdown_limit:.0%}"
            )
            return False, reason

        # Early warning at pause threshold
        if daily_dd >= config.prop_firm.pause_at_daily_dd_pct:
            logger.warning(
                f"PROP FIRM WARNING: Daily DD at {daily_dd:.2%} "
                f"({config.prop_firm.pause_at_daily_dd_pct:.0%} pause threshold)"
            )

        return True, ""

    def check_prop_firm_emergency(self) -> bool:
        """
        Emergency check — close ALL positions if approaching firm hard limits.
        Returns True if emergency action was taken.
        """
        if not config.prop_firm.enabled:
            return False

        total_dd = self._prop_firm_total_dd()
        daily_dd = self._prop_firm_daily_dd()

        # Emergency close at 6.5% total DD (firm limit is 8%)
        if total_dd >= config.prop_firm.emergency_close_at_dd_pct:
            logger.critical(
                f"PROP FIRM EMERGENCY: Total DD {total_dd:.2%} — "
                f"CLOSING ALL POSITIONS to protect account!"
            )
            self.order_manager.close_all_positions()
            self._prop_firm_halted = True
            return True

        # Emergency close if daily DD approaches hard firm limit
        if daily_dd >= config.prop_firm.daily_drawdown_limit * 0.90:
            logger.critical(
                f"PROP FIRM EMERGENCY: Daily DD {daily_dd:.2%} — "
                f"90% of firm limit! CLOSING ALL POSITIONS!"
            )
            self.order_manager.close_all_positions()
            self._prop_firm_halted = True
            return True

        return False

    def get_prop_firm_status(self) -> Dict:
        """Get current prop firm account status."""
        if not config.prop_firm.enabled:
            return {"enabled": False}

        equity = self.connector.get_equity()
        balance = self.connector.get_balance()
        total_dd = self._prop_firm_total_dd()
        daily_dd = self._prop_firm_daily_dd()
        phase = config.prop_firm.current_phase
        target_pct = config.prop_firm.phase1_target if phase == 1 else config.prop_firm.phase2_target
        profit_pct = (equity - config.prop_firm.account_size) / config.prop_firm.account_size
        target_remaining = target_pct - max(0, profit_pct)

        return {
            "enabled": True,
            "firm": config.prop_firm.firm_name,
            "account_size": config.prop_firm.account_size,
            "balance": balance,
            "equity": equity,
            "phase": phase,
            "profit_pct": round(profit_pct * 100, 2),
            "target_pct": target_pct * 100,
            "target_remaining_pct": round(max(0, target_remaining) * 100, 2),
            "daily_dd_pct": round(daily_dd * 100, 2),
            "daily_dd_limit": config.prop_firm.daily_drawdown_limit * 100,
            "daily_dd_buffer": config.prop_firm.daily_drawdown_buffer * 100,
            "total_dd_pct": round(total_dd * 100, 2),
            "total_dd_limit": config.prop_firm.max_drawdown_limit * 100,
            "total_dd_buffer": config.prop_firm.max_drawdown_buffer * 100,
            "halted": self._prop_firm_halted,
        }

    # ─── Session Filter ────────────────────────────────────────────────

    def _is_optimal_session(self, symbol: str) -> bool:
        """
        Check if we're in an optimal trading session for this instrument.
        Gold has specific high-probability windows; trading outside them
        leads to choppy price action and more stop-outs.
        """
        if not config.sessions.use_session_filter:
            return True

        now = datetime.utcnow()
        hour = now.hour

        # Skip weekends regardless
        if now.weekday() >= 5:
            return False

        # Determine which session windows apply
        sym_upper = symbol.upper().replace("M", "").replace(".PRO", "")
        if "XAU" in sym_upper or "GOLD" in sym_upper:
            sessions = config.sessions.gold_sessions
        else:
            sessions = config.sessions.forex_sessions

        for session in sessions:
            if session["start"] <= hour < session["end"]:
                return True

        return False

    def _check_trade_cooldown(self, symbol: str) -> tuple:
        """
        Enforce minimum wait time after closing a trade on the same symbol.
        Prevents revenge trading and overtrading.
        """
        last_time = self._last_trade_time.get(symbol)
        if last_time is None:
            return True, ""

        elapsed = (datetime.now() - last_time).total_seconds() / 60

        # Longer cooldown after a loss
        last_pnl = self._last_trade_result.get(symbol, 0)
        if last_pnl < 0:
            required = config.risk.cooldown_after_loss_minutes
        else:
            required = config.risk.cooldown_after_trade_minutes

        if elapsed < required:
            remaining = required - elapsed
            return False, (
                f"Cooldown: {remaining:.0f}min remaining after "
                f"{'loss' if last_pnl < 0 else 'trade'} on {symbol}"
            )

        return True, ""

    def _get_scaling_factor(self) -> float:
        """
        Gradual scaling discipline: start small, prove the system works,
        then gradually increase to full size.

        Returns a multiplier 0.25 → 0.50 → 1.0 based on trade count.
        """
        n = self._total_trades_taken
        if n < config.risk.scaling_warmup_trades:
            factor = config.risk.scaling_warmup_factor  # 25%
            logger.debug(f"Scaling: warmup phase ({n}/{config.risk.scaling_warmup_trades}), factor={factor}")
            return factor
        elif n < config.risk.scaling_full_after_trades:
            factor = config.risk.scaling_proven_factor  # 50%
            logger.debug(f"Scaling: proving phase ({n}/{config.risk.scaling_full_after_trades}), factor={factor}")
            return factor
        else:
            return 1.0

    # ─── Higher Timeframe Confirmation ───────────────────────────────────

    def check_htf_alignment(self, symbol: str, direction: str) -> bool:
        """
        Check if the Higher Timeframe (H4) trend agrees with the trade direction.
        This is the single most impactful filter — it prevents counter-trend
        entries that are the #1 cause of losses in trend-following systems.

        Returns True if H4 trend aligns with direction, or if check fails.
        """
        if not config.sessions.require_htf_confirmation:
            return True

        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 60)
            if rates is None or len(rates) < 50:
                return True  # Can't check — allow

            closes = np.array([r[4] for r in rates])

            # Simple but effective: 50-period SMA on H4
            sma50 = float(np.mean(closes[-50:]))
            sma20 = float(np.mean(closes[-20:]))
            current = float(closes[-1])

            if direction.upper() == "BUY":
                # For longs: price should be above H4 SMA50 and SMA20 > SMA50
                if current < sma50 or sma20 < sma50:
                    logger.info(
                        f"HTF FILTER: {symbol} BUY rejected — H4 trend is bearish "
                        f"(price={current:.2f}, SMA20={sma20:.2f}, SMA50={sma50:.2f})"
                    )
                    return False

            elif direction.upper() == "SELL":
                # For shorts: price should be below H4 SMA50 and SMA20 < SMA50
                if current > sma50 or sma20 > sma50:
                    logger.info(
                        f"HTF FILTER: {symbol} SELL rejected — H4 trend is bullish "
                        f"(price={current:.2f}, SMA20={sma20:.2f}, SMA50={sma50:.2f})"
                    )
                    return False

            return True

        except Exception as e:
            logger.debug(f"HTF check failed for {symbol}: {e}")
            return True  # Fail open

    # ─── Spread & Slippage Filter ────────────────────────────────────────

    def _check_spread(self, symbol: str) -> tuple:
        """
        Reject trade if current spread is too wide relative to ATR.
        This prevents trading in illiquid conditions or during spreads
        that would eat the profit target.
        """
        try:
            sym_info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            if sym_info is None or tick is None:
                return True, ""  # Can't check — allow

            spread = tick.ask - tick.bid

            # Get ATR for context
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 20)
            if rates is None or len(rates) < 14:
                return True, ""

            highs = np.array([r[2] for r in rates])
            lows = np.array([r[3] for r in rates])
            closes = np.array([r[4] for r in rates])
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(
                    np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:] - closes[:-1]),
                ),
            )
            atr = float(np.mean(tr[-14:]))

            if atr <= 0:
                return True, ""

            spread_pct = spread / atr
            max_spread_pct = config.risk.max_spread_atr_pct

            if spread_pct > max_spread_pct:
                return False, (
                    f"Spread too wide: {spread:.5f} = {spread_pct:.1%} of ATR "
                    f"(max: {max_spread_pct:.0%})"
                )

            return True, ""

        except Exception as e:
            logger.debug(f"Spread check failed for {symbol}: {e}")
            return True, ""

    def _check_min_tp_distance(self, signal: TradeSignal) -> tuple:
        """
        Ensure TP is far enough to be realistic after spread + slippage.
        Prevents micro-scalping strategies that fail in live conditions.
        """
        try:
            tp_distance = abs(signal.take_profit - signal.entry_price)

            rates = mt5.copy_rates_from_pos(signal.symbol, mt5.TIMEFRAME_H1, 0, 20)
            if rates is None or len(rates) < 14:
                return True, ""

            highs = np.array([r[2] for r in rates])
            lows = np.array([r[3] for r in rates])
            closes = np.array([r[4] for r in rates])
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(
                    np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:] - closes[:-1]),
                ),
            )
            atr = float(np.mean(tr[-14:]))

            if atr <= 0:
                return True, ""

            min_tp = atr * config.risk.min_tp_atr_mult

            if tp_distance < min_tp:
                return False, (
                    f"TP too close: {tp_distance:.5f} < {min_tp:.5f} "
                    f"({config.risk.min_tp_atr_mult}x ATR)"
                )

            return True, ""

        except Exception:
            return True, ""

    # ─── Circuit Breaker ─────────────────────────────────────────────────

    def _is_loss_paused(self) -> bool:
        """Check if trading is paused due to consecutive losses."""
        if self._loss_pause_until is None:
            return False
        if datetime.now() >= self._loss_pause_until:
            logger.info("Loss pause expired — resuming trading")
            self._loss_pause_until = None
            self._consecutive_losses = 0  # Reset after pause
            return False
        return True

    # ─── Daily Risk Tracking ─────────────────────────────────────────────

    def _is_daily_loss_exceeded(self) -> bool:
        """Check if daily loss limit has been hit (% or USD)."""
        deals = self.connector.get_history_deals(days=1)
        daily_pl = sum(d["profit"] + d.get("swap", 0) + d.get("commission", 0)
                       for d in deals if d.get("magic") == config.trading.magic_number)

        positions = self.connector.get_bot_positions()
        unrealized = sum(p["profit"] for p in positions)

        total_daily = daily_pl + unrealized
        balance = self.connector.get_balance()
        max_daily_loss = balance * config.risk.max_daily_risk

        # Hard USD daily loss limit
        usd_limit = getattr(config.risk, 'daily_loss_limit_usd', 0)
        if usd_limit > 0 and total_daily < -usd_limit:
            logger.warning(f"DAILY USD LOSS LIMIT: {total_daily:.2f} / -${usd_limit:.0f} — stopping trades")
            return True

        if total_daily < -max_daily_loss:
            logger.warning(f"Daily loss limit reached: {total_daily:.2f} / -{max_daily_loss:.2f}")
            return True
        return False

    def _is_drawdown_exceeded(self) -> bool:
        """Check if maximum drawdown limit has been hit (adaptive to account size)."""
        equity = self.connector.get_equity()
        if equity > self._peak_equity:
            self._peak_equity = equity

        max_dd = self._get_effective_max_drawdown()
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown > max_dd:
                logger.warning(f"Max drawdown exceeded: {drawdown:.2%} / {max_dd:.2%}")
                return True
        return False

    def _current_drawdown(self) -> float:
        """Get current drawdown as a fraction (0.0 to 1.0)."""
        equity = self.connector.get_equity()
        if equity > self._peak_equity:
            self._peak_equity = equity
        if self._peak_equity > 0:
            return (self._peak_equity - equity) / self._peak_equity
        return 0.0

    def _is_trading_hours(self, symbol: str = "") -> bool:
        """Check if current time is within trading hours."""
        now = datetime.utcnow()

        # Crypto trades 24/7
        sym_upper = symbol.upper().replace("M", "")
        if any(c in sym_upper for c in ["BTC", "ETH", "LTC", "XRP", "DOGE", "SOL"]):
            return True

        # Skip weekends
        if now.weekday() >= 5:
            return False

        hour = now.hour
        return config.trading.trading_hours_start <= hour <= config.trading.trading_hours_end

    # ─── Emergency Actions ───────────────────────────────────────────────

    def check_emergency_conditions(self) -> bool:
        """
        Check for emergency conditions that require immediate action.
        Returns True if emergency action was taken.
        Uses adaptive drawdown limit based on account size.
        """
        emergency = False

        # ─── Equity Floor Check ──────────────────────────────────
        if not self.is_account_viable():
            logger.critical("EMERGENCY: Equity below bankruptcy floor! Closing all positions!")
            self.order_manager.close_all_positions()
            return True

        # ─── Prop Firm Emergency Check (top priority) ────────────
        if config.prop_firm.enabled:
            if self.check_prop_firm_emergency():
                return True

        # Don't trigger emergency on dead accounts (nothing to protect)
        if self._account_mode == "dead":
            return False

        equity = self.connector.get_equity()
        max_dd = self._get_effective_max_drawdown()
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown > max_dd * 1.2:  # 120% of effective max DD
                logger.critical(f"EMERGENCY: Drawdown at {drawdown:.2%}! Closing all positions!")
                self.order_manager.close_all_positions()
                emergency = True

        account = self.connector.get_account_info()
        if account:
            margin_level = account.get("margin_level", 9999)
            margin_used = account.get("margin", 0)
            if margin_used > 0 and margin_level < 120:
                logger.critical(f"EMERGENCY: Margin level at {margin_level:.1f}%! Closing positions!")
                self.order_manager.close_all_positions()
                emergency = True

        return emergency

    def get_risk_summary(self) -> Dict:
        """Get current risk status summary (balance-adaptive)."""
        equity = self.connector.get_equity()
        balance = self.connector.get_balance()
        positions = self.connector.get_bot_positions()

        drawdown = 0.0
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity

        total_exposure = sum(abs(p.get("volume", 0)) for p in positions)
        total_unrealized = sum(p.get("profit", 0) for p in positions)

        eff_dd = self._get_effective_max_drawdown()

        return {
            "balance": balance,
            "equity": equity,
            "peak_equity": self._peak_equity,
            "drawdown": round(drawdown * 100, 2),
            "max_drawdown_limit": eff_dd * 100,
            "account_mode": self._account_mode,
            "effective_risk_pct": self._get_effective_risk_pct() * 100,
            "open_positions": len(positions),
            "max_positions": config.trading.max_open_trades,
            "total_exposure_lots": total_exposure,
            "unrealized_pnl": round(total_unrealized, 2),
            "is_trading_hours": self._is_trading_hours(),
            "daily_loss_exceeded": self._is_daily_loss_exceeded(),
            "drawdown_exceeded": self._is_drawdown_exceeded(),
            "consecutive_losses": self._consecutive_losses,
            "is_paused": self._is_loss_paused(),
            "total_trades_taken": self._total_trades_taken,
            "scaling_factor": self._get_scaling_factor() if (config.risk.scaling_enabled and self._account_mode == "normal") else 1.0,
            "strategy_performance": dict(self._strategy_performance),
            "prop_firm": self.get_prop_firm_status(),
        }

    # ─── Utility ─────────────────────────────────────────────────────────

    def _price_to_pips(self, symbol: str, price_distance: float) -> float:
        """Convert price distance to pips."""
        info = self.connector.get_symbol_info(symbol)
        if info is None:
            return 0.0

        point = info["point"]
        if info["digits"] in (3, 5):
            pip = point * 10
        else:
            pip = point

        return price_distance / pip if pip > 0 else 0.0
