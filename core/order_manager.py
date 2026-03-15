"""
=============================================================================
Order Manager
=============================================================================
Handles all order operations: placing trades, modifying orders, closing
positions, and managing trailing stops with MetaTrader 5.
=============================================================================
"""

from core.mt5_lock import mt5_safe as mt5
import numpy as np
import logging
from typing import Optional, Dict, Tuple
from datetime import datetime

from config.settings import config, TimeFrame
from utils.email_notifier import notifier

logger = logging.getLogger(__name__)


class OrderManager:
    """Manages trade execution and order operations."""

    def __init__(self, connector):
        self.connector = connector
        self.trade_log = []
        # Track tickets that already had partial TP taken
        self._partial_tp_taken: set = set()

    def _get_filling_mode(self, symbol: str) -> int:
        """Get the correct filling mode for a symbol."""
        info = mt5.symbol_info(symbol)
        if info is None:
            return mt5.ORDER_FILLING_FOK
        filling = info.filling_mode
        if filling & 1:  # FOK supported
            return mt5.ORDER_FILLING_FOK
        if filling & 2:  # IOC supported
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    # ─── Place Orders ────────────────────────────────────────────────────

    def place_market_order(
        self,
        symbol: str,
        order_type: str,  # "BUY" or "SELL"
        volume: float,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "AI_Bot",
        deviation: int = None,
    ) -> Optional[Dict]:
        """
        Place a market order (instant execution).
        
        Args:
            symbol: Trading symbol
            order_type: 'BUY' or 'SELL'
            volume: Lot size
            sl: Stop loss price (0 = no SL)
            tp: Take profit price (0 = no TP)
            comment: Order comment
            deviation: Max price deviation in points (None = ATR-based)
            
        Returns:
            Order result dict or None if failed
        """
        if not self.connector.is_connected():
            logger.error("Not connected to MT5")
            return None

        # Ensure symbol is selected
        self.connector.enable_symbol(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"Cannot get tick for {symbol}")
            return None

        # Determine order type and price
        if order_type.upper() == "BUY":
            mt5_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        elif order_type.upper() == "SELL":
            mt5_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            logger.error(f"Invalid order type: {order_type}")
            return None

        # ATR-based deviation (points) — prevents accepting terrible fills
        if deviation is None:
            try:
                atr = self._get_atr(symbol)
                sym_info = mt5.symbol_info(symbol)
                point = sym_info.point if sym_info else 0.01
                # Deviation = half ATR in points, min 10 max 50
                deviation = max(10, min(50, int(atr / (2 * point)))) if point > 0 else 20
            except Exception:
                deviation = 20

        # Build request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": mt5_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": deviation,
            "magic": config.trading.magic_number,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        }

        # ─── SL/TP Sanity Check ────────────────────────────────
        if sl > 0:
            if order_type.upper() == "BUY" and sl >= price:
                logger.error(f"Invalid SL for BUY: SL {sl} >= entry {price}")
                return None
            if order_type.upper() == "SELL" and sl <= price:
                logger.error(f"Invalid SL for SELL: SL {sl} <= entry {price}")
                return None
        if tp > 0:
            if order_type.upper() == "BUY" and tp <= price:
                logger.error(f"Invalid TP for BUY: TP {tp} <= entry {price}")
                return None
            if order_type.upper() == "SELL" and tp >= price:
                logger.error(f"Invalid TP for SELL: TP {tp} >= entry {price}")
                return None

        # ─── Send order with retry logic ─────────────────────────
        import time as _time
        result = None
        last_error = None
        for attempt in range(3):
            result = mt5.order_send(request)
            if result is None:
                last_error = mt5.last_error()
                logger.warning(f"Order attempt {attempt+1}/3 failed: {last_error}")
                _time.sleep(0.5 * (attempt + 1))
                # Refresh price before retry
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    request["price"] = tick.ask if order_type.upper() == "BUY" else tick.bid
                continue
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                break
            # Retryable error codes: requote, price changed, timeout
            if result.retcode in (10004, 10006, 10007, 10014, 10021):
                logger.warning(f"Order attempt {attempt+1}/3 retryable | Code: {result.retcode} | {result.comment}")
                _time.sleep(0.5 * (attempt + 1))
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    request["price"] = tick.ask if order_type.upper() == "BUY" else tick.bid
                continue
            else:
                # Non-retryable error
                break

        if result is None:
            logger.error(f"Order send failed after 3 attempts: {last_error}")
            return None

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Order failed | Code: {result.retcode} | "
                         f"Comment: {result.comment}")
            return None

        # ─── Slippage Tracking ───────────────────────────────────
        requested_price = price
        filled_price = result.price
        slippage_points = abs(filled_price - requested_price)
        if slippage_points > 0:
            logger.info(f"SLIPPAGE | {symbol} {order_type} | "
                        f"Requested: {requested_price:.5f} | Filled: {filled_price:.5f} | "
                        f"Slip: {slippage_points:.5f} points")

        order_result = {
            "ticket": result.order,
            "deal": result.deal,
            "symbol": symbol,
            "type": order_type,
            "volume": volume,
            "price": result.price,
            "requested_price": requested_price,
            "slippage": slippage_points,
            "sl": sl,
            "tp": tp,
            "comment": comment,
            "time": datetime.now(),
        }

        self.trade_log.append(order_result)
        logger.info(f"ORDER PLACED | {order_type} {volume} {symbol} @ {result.price} | "
                     f"SL: {sl} | TP: {tp} | Ticket: {result.order}")
        notifier.notify_trade_opened(order_result)
        return order_result

    def place_pending_order(
        self,
        symbol: str,
        order_type: str,  # "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"
        volume: float,
        price: float,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "AI_Bot_Pending",
        expiration: datetime = None,
    ) -> Optional[Dict]:
        """Place a pending order."""
        if not self.connector.is_connected():
            return None

        self.connector.enable_symbol(symbol)

        type_map = {
            "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
            "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
            "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
            "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
        }

        mt5_type = type_map.get(order_type.upper())
        if mt5_type is None:
            logger.error(f"Invalid pending order type: {order_type}")
            return None

        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": float(volume),
            "type": mt5_type,
            "price": float(price),
            "sl": float(sl),
            "tp": float(tp),
            "magic": config.trading.magic_number,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        }

        if expiration:
            request["type_time"] = mt5.ORDER_TIME_SPECIFIED
            request["expiration"] = int(expiration.timestamp())

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error = result.comment if result else mt5.last_error()
            logger.error(f"Pending order failed: {error}")
            return None

        logger.info(f"PENDING ORDER | {order_type} {volume} {symbol} @ {price} | "
                     f"Ticket: {result.order}")
        return {"ticket": result.order, "symbol": symbol, "type": order_type,
                "volume": volume, "price": price, "sl": sl, "tp": tp}

    # ─── Modify Orders ───────────────────────────────────────────────────

    def modify_position(
        self,
        ticket: int,
        sl: float = None,
        tp: float = None,
    ) -> bool:
        """Modify stop loss and/or take profit of an open position."""
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            logger.error(f"Position {ticket} not found")
            return False

        pos = position[0]
        new_sl = sl if sl is not None else pos.sl
        new_tp = tp if tp is not None else pos.tp

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": pos.symbol,
            "sl": float(new_sl),
            "tp": float(new_tp),
            "magic": config.trading.magic_number,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error = result.comment if result else mt5.last_error()
            logger.error(f"Modify position {ticket} failed: {error}")
            return False

        logger.info(f"MODIFIED | Ticket: {ticket} | SL: {new_sl} | TP: {new_tp}")
        if sl is not None and sl != pos.sl:
            notifier.notify_sl_modified(pos.symbol, ticket, pos.sl, new_sl)
        return True

    # ─── Close Positions ─────────────────────────────────────────────────

    def close_position(self, ticket: int, comment: str = "AI_Bot_Close") -> bool:
        """Close a specific position by ticket number."""
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            logger.error(f"Position {ticket} not found")
            return False

        pos = position[0]
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return False

        # Opposite type to close
        if pos.type == mt5.ORDER_TYPE_BUY:
            close_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            close_type = mt5.ORDER_TYPE_BUY
            price = tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": config.trading.magic_number,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(pos.symbol),
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error = result.comment if result else mt5.last_error()
            logger.error(f"Close position {ticket} failed: {error}")
            return False

        logger.info(f"CLOSED | Ticket: {ticket} | {pos.symbol} | "
                     f"Profit: {pos.profit}")
        direction = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"
        notifier.notify_trade_closed(pos.symbol, direction, ticket, pos.profit,
                                     close_price=price, comment=comment)
        return True

    def close_all_positions(self, symbol: str = None) -> int:
        """Close all open positions (optionally for a specific symbol)."""
        positions = self.connector.get_bot_positions()
        if symbol:
            positions = [p for p in positions if p["symbol"] == symbol]

        closed = 0
        for pos in positions:
            if self.close_position(pos["ticket"]):
                closed += 1

        logger.info(f"Closed {closed}/{len(positions)} positions")
        return closed

    def partial_close(self, ticket: int, fraction: float = 0.5,
                      comment: str = "AI_PartialTP") -> bool:
        """
        Close a fraction of a position (e.g. 50% at 1R profit).
        Returns True if partial close succeeded.
        """
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            return False

        pos = position[0]
        sym_info = mt5.symbol_info(pos.symbol)
        if sym_info is None:
            return False

        close_volume = pos.volume * fraction
        # Round down to volume step
        step = sym_info.volume_step
        close_volume = int(close_volume / step) * step
        close_volume = round(close_volume, 2)

        if close_volume < sym_info.volume_min:
            return False  # Too small to partial close

        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return False

        if pos.type == mt5.ORDER_TYPE_BUY:
            close_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            close_type = mt5.ORDER_TYPE_BUY
            price = tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": close_volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": config.trading.magic_number,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(pos.symbol),
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error = result.comment if result else mt5.last_error()
            logger.error(f"Partial close {ticket} failed: {error}")
            return False

        logger.info(
            f"PARTIAL TP | {pos.symbol} #{ticket} | "
            f"Closed {close_volume} of {pos.volume} lots | "
            f"Profit locked: {pos.profit * fraction:.2f}"
        )
        notifier.notify_partial_close(pos.symbol, ticket, fraction, pos.profit * fraction)
        return True

    # ─── Trailing Stop Management ────────────────────────────────────────

    def update_trailing_stops(self):
        """Update trailing stops for all bot positions."""
        if not config.risk.use_trailing_stop:
            return

        positions = self.connector.get_bot_positions()
        for pos in positions:
            self._apply_trailing_stop(pos)

    def _get_atr(self, symbol: str, period: int = 14) -> float:
        """
        Calculate current ATR for a symbol using M15 candles (matches primary TF).
        Returns ATR in price units, or 0.0 on failure.
        """
        try:
            from config.settings import TimeFrame
            tf_map = {
                TimeFrame.H1: mt5.TIMEFRAME_H1,
            }
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, period + 5)
            if rates is None or len(rates) < period:
                return 0.0
            highs = np.array([r[2] for r in rates])   # high
            lows = np.array([r[3] for r in rates])    # low
            closes = np.array([r[4] for r in rates])  # close
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(
                    np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:] - closes[:-1]),
                ),
            )
            atr = float(np.mean(tr[-period:]))
            return atr
        except Exception as e:
            logger.debug(f"ATR calculation failed for {symbol}: {e}")
            return 0.0

    def _apply_trailing_stop(self, position: Dict):
        """
        Apply trailing stop logic to a single position.
        Includes:
        - Partial TP: close 50% at 1R profit, move SL to break-even
        - Chandelier trailing: trail from highest high / lowest low minus ATR
        - ATR-based fallback distances
        """
        symbol = position["symbol"]
        tick = mt5.symbol_info_tick(symbol)
        sym_info = mt5.symbol_info(symbol)
        if tick is None or sym_info is None:
            return

        point = sym_info.point
        ticket = position["ticket"]

        # ── Compute distances: ATR-based or fixed-pip fallback ──
        if config.risk.use_atr_trailing:
            atr = self._get_atr(symbol)
            if atr > 0:
                trail_distance = atr * config.risk.trailing_stop_atr_mult
                be_distance = atr * config.risk.break_even_atr_mult
            else:
                trail_distance = config.risk.trailing_stop_pips * point * 10
                be_distance = config.risk.break_even_pips * point * 10
        else:
            trail_distance = config.risk.trailing_stop_pips * point * 10
            be_distance = config.risk.break_even_pips * point * 10

        # ── Compute 1R distance (SL distance from entry) ──
        sl_distance = abs(position["price_open"] - position["sl"]) if position["sl"] > 0 else be_distance

        # ── Chandelier stop: use recent highs/lows for tighter trailing ──
        chandelier_sl = None
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 20)
            if rates is not None and len(rates) >= 10:
                highs = [r[2] for r in rates[-10:]]
                lows = [r[3] for r in rates[-10:]]
                if position["type"] == "BUY":
                    chandelier_sl = max(highs) - trail_distance
                else:
                    chandelier_sl = min(lows) + trail_distance
        except Exception:
            pass

        if position["type"] == "BUY":
            current_price = tick.bid
            profit_distance = current_price - position["price_open"]

            # ── Partial TP at 1R ──
            if ticket not in self._partial_tp_taken and profit_distance >= sl_distance and sl_distance > 0:
                if self.partial_close(ticket, fraction=0.5, comment="AI_PartialTP_1R"):
                    self._partial_tp_taken.add(ticket)
                    # Move SL to break-even on remaining
                    new_sl = position["price_open"] + point
                    self.modify_position(ticket, sl=new_sl)
                    logger.info(f"PARTIAL TP + BE | BUY #{ticket} | 1R reached ({sl_distance:.2f})")
                    return

            # ── Break even ──
            if config.risk.use_break_even and profit_distance >= be_distance:
                if position["sl"] < position["price_open"]:
                    new_sl = position["price_open"] + point
                    logger.info(
                        f"BREAK-EVEN | {symbol} BUY #{ticket} | "
                        f"Profit: {profit_distance:.2f} | New SL: {new_sl:.5f}"
                    )
                    self.modify_position(ticket, sl=new_sl)
                    return

            # ── Chandelier + ATR trailing (use the tighter of the two) ──
            if profit_distance >= trail_distance:
                atr_sl = current_price - trail_distance
                candidates = [atr_sl]
                if chandelier_sl is not None and chandelier_sl > position["price_open"]:
                    candidates.append(chandelier_sl)
                new_sl = max(candidates)  # Pick the tighter (higher) SL
                if new_sl > position["sl"]:
                    self.modify_position(ticket, sl=new_sl)

        elif position["type"] == "SELL":
            current_price = tick.ask
            profit_distance = position["price_open"] - current_price

            # ── Partial TP at 1R ──
            if ticket not in self._partial_tp_taken and profit_distance >= sl_distance and sl_distance > 0:
                if self.partial_close(ticket, fraction=0.5, comment="AI_PartialTP_1R"):
                    self._partial_tp_taken.add(ticket)
                    new_sl = position["price_open"] - point
                    self.modify_position(ticket, sl=new_sl)
                    logger.info(f"PARTIAL TP + BE | SELL #{ticket} | 1R reached ({sl_distance:.2f})")
                    return

            # ── Break even ──
            if config.risk.use_break_even and profit_distance >= be_distance:
                if position["sl"] > position["price_open"] or position["sl"] == 0:
                    new_sl = position["price_open"] - point
                    logger.info(
                        f"BREAK-EVEN | {symbol} SELL #{ticket} | "
                        f"Profit: {profit_distance:.2f} | New SL: {new_sl:.5f}"
                    )
                    self.modify_position(ticket, sl=new_sl)
                    return

            # ── Chandelier + ATR trailing ──
            if profit_distance >= trail_distance:
                atr_sl = current_price + trail_distance
                candidates = [atr_sl]
                if chandelier_sl is not None and chandelier_sl < position["price_open"]:
                    candidates.append(chandelier_sl)
                new_sl = min(candidates)  # Pick the tighter (lower) SL
                if position["sl"] == 0 or new_sl < position["sl"]:
                    self.modify_position(ticket, sl=new_sl)

    # ─── Utility Methods ─────────────────────────────────────────────────

    def calculate_lot_size(
        self,
        symbol: str,
        sl_pips: float,
        risk_percent: float = None,
        use_balance: bool = False,
    ) -> float:
        """
        Calculate optimal lot size based on risk management.
        
        Args:
            symbol: Trading symbol
            sl_pips: Stop loss distance in pips
            risk_percent: Risk percentage (defaults to config)
            use_balance: If True, size from balance (stable); False = equity
            
        Returns:
            Calculated lot size, clamped to min/max limits
        """
        if risk_percent is None:
            risk_percent = config.risk.max_risk_per_trade

        # Use balance for stable sizing (institutional standard)
        if use_balance:
            sizing_base = self.connector.get_balance()
            if sizing_base <= 0:
                sizing_base = self.connector.get_equity()
        else:
            sizing_base = self.connector.get_equity()
            if sizing_base <= 0:
                sizing_base = self.connector.get_balance()
        risk_amount = sizing_base * risk_percent

        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            return config.risk.min_lot_size

        # Pip value calculation
        point = sym_info.point
        contract_size = sym_info.trade_contract_size

        # For JPY pairs, pip = 0.01; for others, pip = 0.0001
        if sym_info.digits == 3 or sym_info.digits == 5:
            pip_value = point * 10
        else:
            pip_value = point

        # Calculate lot size
        tick_value = sym_info.trade_tick_value
        if tick_value == 0 or sl_pips == 0:
            return config.risk.min_lot_size

        lot_size = risk_amount / (sl_pips * tick_value * 10)

        # Clamp to limits
        lot_size = max(config.risk.min_lot_size, lot_size)
        lot_size = min(config.risk.max_lot_size, lot_size)

        # Round to volume step
        step = sym_info.volume_step
        lot_size = round(lot_size / step) * step
        lot_size = round(lot_size, 2)

        return lot_size

    def get_pip_value(self, symbol: str) -> float:
        """Get the pip value in account currency for 1 lot."""
        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            return 0.0
        return sym_info.trade_tick_value * 10  # tick_value is per point, pip = 10 points

    def get_spread_pips(self, symbol: str) -> float:
        """Get current spread in pips."""
        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            return 0.0
        return sym_info.spread / 10.0  # Spread is in points
