"""
=============================================================================
MetaTrader 5 Connector
=============================================================================
Handles connection, initialization, and communication with MetaTrader 5.
Provides methods for account info, symbol data, and market data retrieval.
=============================================================================
"""

from core.mt5_lock import mt5_safe as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import logging

from config.settings import config, TimeFrame

logger = logging.getLogger(__name__)

# Timeframe mapping
TIMEFRAME_MAP = {
    TimeFrame.M1: mt5.TIMEFRAME_M1,
    TimeFrame.M5: mt5.TIMEFRAME_M5,
    TimeFrame.M15: mt5.TIMEFRAME_M15,
    TimeFrame.M30: mt5.TIMEFRAME_M30,
    TimeFrame.H1: mt5.TIMEFRAME_H1,
    TimeFrame.H4: mt5.TIMEFRAME_H4,
    TimeFrame.D1: mt5.TIMEFRAME_D1,
    TimeFrame.W1: mt5.TIMEFRAME_W1,
    TimeFrame.MN1: mt5.TIMEFRAME_MN1,
}


class MT5Connector:
    """Manages the connection to MetaTrader 5 terminal."""

    def __init__(self):
        self.connected = False
        self._account_info = None

    def connect(self) -> bool:
        """Initialize and connect to MetaTrader 5."""
        try:
            # Initialize MT5
            if not mt5.initialize(
                path=config.mt5.path,
                login=config.mt5.login,
                password=config.mt5.password,
                server=config.mt5.server,
                timeout=config.mt5.timeout,
            ):
                error = mt5.last_error()
                logger.error(f"MT5 initialization failed: {error}")
                return False

            # Login to account
            if config.mt5.login > 0:
                authorized = mt5.login(
                    login=config.mt5.login,
                    password=config.mt5.password,
                    server=config.mt5.server,
                )
                if not authorized:
                    error = mt5.last_error()
                    logger.error(f"MT5 login failed: {error}")
                    mt5.shutdown()
                    return False

            self.connected = True
            self._account_info = mt5.account_info()
            logger.info(f"Connected to MT5 | Account: {self._account_info.login} | "
                        f"Server: {self._account_info.server} | "
                        f"Balance: {self._account_info.balance}")
            return True

        except Exception as e:
            logger.error(f"MT5 connection error: {e}")
            return False

    def disconnect(self):
        """Shutdown MT5 connection."""
        if self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("Disconnected from MT5")

    def is_connected(self) -> bool:
        """Check if still connected to MT5."""
        if not self.connected:
            return False
        try:
            info = mt5.terminal_info()
            return info is not None
        except:
            self.connected = False
            return False

    def reconnect(self) -> bool:
        """Attempt to reconnect to MT5."""
        logger.info("Attempting to reconnect to MT5...")
        self.disconnect()
        return self.connect()

    # ─── Account Information ─────────────────────────────────────────────

    def get_account_info(self) -> Optional[Dict]:
        """Get current account information."""
        if not self.is_connected():
            return None
        info = mt5.account_info()
        if info is None:
            return None
        return {
            "login": info.login,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "margin_level": info.margin_level,
            "profit": info.profit,
            "leverage": info.leverage,
            "currency": info.currency,
            "trade_allowed": info.trade_allowed,
            "trade_mode": info.trade_mode,
        }

    def get_balance(self) -> float:
        """Get current account balance."""
        info = mt5.account_info()
        return info.balance if info else 0.0

    def get_equity(self) -> float:
        """Get current account equity."""
        info = mt5.account_info()
        return info.equity if info else 0.0

    def get_free_margin(self) -> float:
        """Get available margin."""
        info = mt5.account_info()
        return info.margin_free if info else 0.0

    # ─── Symbol Information ──────────────────────────────────────────────

    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """Get detailed symbol information."""
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.warning(f"Symbol {symbol} not found")
            return None
        return {
            "name": info.name,
            "bid": info.bid,
            "ask": info.ask,
            "spread": info.spread,
            "point": info.point,
            "digits": info.digits,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "trade_contract_size": info.trade_contract_size,
            "swap_long": info.swap_long,
            "swap_short": info.swap_short,
            "trade_mode": info.trade_mode,
        }

    def get_symbol_tick(self, symbol: str) -> Optional[Dict]:
        """Get the latest tick for a symbol."""
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return {
            "time": datetime.fromtimestamp(tick.time),
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "volume": tick.volume,
        }

    def enable_symbol(self, symbol: str) -> bool:
        """Ensure a symbol is visible in Market Watch."""
        selected = mt5.symbol_select(symbol, True)
        if not selected:
            logger.warning(f"Failed to select symbol: {symbol}")
        return selected

    # ─── Market Data ─────────────────────────────────────────────────────

    def get_rates(
        self,
        symbol: str,
        timeframe: TimeFrame,
        count: int = 500,
        start_pos: int = 0,
    ) -> Optional[pd.DataFrame]:
        """
        Get historical OHLCV data as a DataFrame.
        
        Args:
            symbol: Trading symbol (e.g., 'EURUSD')
            timeframe: TimeFrame enum value
            count: Number of candles to fetch
            start_pos: Starting position (0 = current candle)
            
        Returns:
            DataFrame with columns: time, open, high, low, close, tick_volume, spread
        """
        mt5_tf = TIMEFRAME_MAP.get(timeframe)
        if mt5_tf is None:
            logger.error(f"Invalid timeframe: {timeframe}")
            return None

        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, start_pos, count)
        if rates is None or len(rates) == 0:
            logger.warning(f"No data for {symbol} {timeframe.value}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        return df

    def get_rates_range(
        self,
        symbol: str,
        timeframe: TimeFrame,
        date_from: datetime,
        date_to: datetime,
    ) -> Optional[pd.DataFrame]:
        """Get historical data between two dates."""
        mt5_tf = TIMEFRAME_MAP.get(timeframe)
        if mt5_tf is None:
            return None

        rates = mt5.copy_rates_range(symbol, mt5_tf, date_from, date_to)
        if rates is None or len(rates) == 0:
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        return df

    def get_ticks(
        self,
        symbol: str,
        date_from: datetime,
        count: int = 1000,
    ) -> Optional[pd.DataFrame]:
        """Get tick data."""
        ticks = mt5.copy_ticks_from(symbol, date_from, count, mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            return None

        df = pd.DataFrame(ticks)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    # ─── Open Positions ──────────────────────────────────────────────────

    def get_positions(self, symbol: str = None) -> List[Dict]:
        """Get all open positions, optionally filtered by symbol."""
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()

        if positions is None:
            return []

        result = []
        for pos in positions:
            result.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "price_current": pos.price_current,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
                "swap": pos.swap,
                "time": datetime.fromtimestamp(pos.time),
                "magic": pos.magic,
                "comment": pos.comment,
            })
        return result

    def get_bot_positions(self) -> List[Dict]:
        """Get positions opened by this bot (filtered by magic number)."""
        all_positions = self.get_positions()
        return [p for p in all_positions if p["magic"] == config.trading.magic_number]

    # ─── Order History ───────────────────────────────────────────────────

    def get_history_orders(self, days: int = 30) -> List[Dict]:
        """Get order history for the last N days."""
        date_from = datetime.now() - timedelta(days=days)
        date_to = datetime.now()

        orders = mt5.history_orders_get(date_from, date_to)
        if orders is None:
            return []

        result = []
        for order in orders:
            result.append({
                "ticket": order.ticket,
                "symbol": order.symbol,
                "type": order.type,
                "volume": order.volume_current,
                "price": order.price_current,
                "sl": order.sl,
                "tp": order.tp,
                "state": order.state,
                "time_setup": datetime.fromtimestamp(order.time_setup),
                "magic": order.magic,
                "comment": order.comment,
            })
        return result

    def get_history_deals(self, days: int = 30) -> List[Dict]:
        """Get deal history for the last N days."""
        date_from = datetime.now() - timedelta(days=days)
        date_to = datetime.now()

        deals = mt5.history_deals_get(date_from, date_to)
        if deals is None:
            return []

        result = []
        for deal in deals:
            result.append({
                "ticket": deal.ticket,
                "order": deal.order,
                "position_id": deal.position_id,
                "symbol": deal.symbol,
                "type": deal.type,
                "volume": deal.volume,
                "price": deal.price,
                "profit": deal.profit,
                "swap": deal.swap,
                "commission": deal.commission,
                "time": datetime.fromtimestamp(deal.time),
                "magic": deal.magic,
                "comment": deal.comment,
            })
        return result
