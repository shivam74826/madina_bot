"""
=============================================================================
Base Strategy
=============================================================================
Abstract base class for all trading strategies.
Defines the interface that all strategies must implement.
=============================================================================
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, List
from dataclasses import dataclass
from enum import Enum
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE_BUY = "CLOSE_BUY"
    CLOSE_SELL = "CLOSE_SELL"


@dataclass
class TradeSignal:
    """Represents a trading signal from a strategy."""
    signal_type: SignalType
    symbol: str
    confidence: float       # 0.0 to 1.0
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float = 0.0   # 0 means calculate automatically
    reason: str = ""
    strategy_name: str = ""
    risk_reward: float = 0.0
    timeframe: str = ""

    def is_valid(self) -> bool:
        """Check if signal has all required data."""
        if self.signal_type == SignalType.HOLD:
            return True
        return (
            self.confidence > 0
            and self.entry_price > 0
            and self.stop_loss > 0
            and self.take_profit > 0
            and self.stop_loss != self.entry_price
        )


class BaseStrategy(ABC):
    """Abstract base class for trading strategies."""

    def __init__(self, name: str):
        self.name = name
        self.signals_generated = 0
        self.signals_executed = 0

    @abstractmethod
    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        """
        Analyze market data and generate a trading signal.
        
        Args:
            df: OHLCV DataFrame with sufficient history
            symbol: Trading symbol
            
        Returns:
            TradeSignal object
        """
        pass

    def _create_signal(
        self,
        signal_type: SignalType,
        symbol: str,
        confidence: float,
        entry: float,
        sl: float,
        tp: float,
        reason: str = "",
    ) -> TradeSignal:
        """Helper to create a TradeSignal."""
        if signal_type in (SignalType.BUY, SignalType.SELL):
            sl_distance = abs(entry - sl)
            tp_distance = abs(tp - entry)
            rr = tp_distance / sl_distance if sl_distance > 0 else 0
        else:
            rr = 0

        signal = TradeSignal(
            signal_type=signal_type,
            symbol=symbol,
            confidence=confidence,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            reason=reason,
            strategy_name=self.name,
            risk_reward=round(rr, 2),
        )
        self.signals_generated += 1
        return signal

    def hold_signal(self, symbol: str, reason: str = "No clear setup") -> TradeSignal:
        """Generate a HOLD signal."""
        return TradeSignal(
            signal_type=SignalType.HOLD,
            symbol=symbol,
            confidence=0,
            entry_price=0,
            stop_loss=0,
            take_profit=0,
            reason=reason,
            strategy_name=self.name,
        )
