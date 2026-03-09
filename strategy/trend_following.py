"""
=============================================================================
Trend Following Strategy
=============================================================================
A robust trend-following strategy that combines:
- Moving Average alignment for trend direction
- ADX for trend strength confirmation
- RSI for momentum confirmation
- ATR-based stop loss and take profit
- Volume confirmation
=============================================================================
"""

import pandas as pd
import numpy as np
from typing import Dict
import logging

from config.settings import config
from strategy.base_strategy import BaseStrategy, TradeSignal, SignalType
from analysis.technical import TechnicalAnalyzer

logger = logging.getLogger(__name__)


class TrendFollowingStrategy(BaseStrategy):
    """Trend Following Strategy: Ride the trend with confirmation."""

    def __init__(self):
        super().__init__("Trend_Following")
        self.ta = TechnicalAnalyzer()

    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        """Analyze for trend following opportunities."""
        if len(df) < 200:
            return self.hold_signal(symbol, "Insufficient data for trend analysis")

        indicators = self.ta.compute_all(df)
        latest = indicators.iloc[-1]
        prev = indicators.iloc[-2]
        price = latest["close"]

        score = 0
        reasons = []

        # ─── Trend Direction (Moving Average Alignment) ──────────────
        ma_aligned_bull = (
            latest["ema_fast"] > latest["ema_slow"]
            and latest["sma_fast"] > latest["sma_slow"]
            and price > latest["sma_trend"]
        )
        ma_aligned_bear = (
            latest["ema_fast"] < latest["ema_slow"]
            and latest["sma_fast"] < latest["sma_slow"]
            and price < latest["sma_trend"]
        )

        if ma_aligned_bull:
            score += 2
            reasons.append("MA alignment bullish")
        elif ma_aligned_bear:
            score -= 2
            reasons.append("MA alignment bearish")
        else:
            score += 0  # No alignment but don't block

        # ─── Trend Strength (ADX) ───────────────────────────────
        adx_val = latest["adx"]
        if adx_val > 40:
            score += 2 if score > 0 else -2
            reasons.append(f"Very strong trend (ADX: {adx_val:.1f})")
        elif adx_val > config.indicators.adx_threshold:
            score += 1 if score > 0 else -1
            reasons.append(f"Strong trend (ADX: {adx_val:.1f})")
        elif adx_val > 15:
            # Moderate trend — still allow
            reasons.append(f"Moderate trend (ADX: {adx_val:.1f})")
        else:
            return self.hold_signal(symbol, f"No trend (ADX: {adx_val:.1f})")

        # ─── Momentum (RSI) ─────────────────────────────────────────
        rsi = latest["rsi"]
        if score > 0:  # Bullish
            if 40 < rsi < 70:
                score += 1
                reasons.append(f"RSI confirms uptrend ({rsi:.1f})")
            elif rsi >= 70:
                score -= 1
                reasons.append(f"RSI overbought risk ({rsi:.1f})")
        else:  # Bearish
            if 30 < rsi < 60:
                score += -1
                reasons.append(f"RSI confirms downtrend ({rsi:.1f})")
            elif rsi <= 30:
                score += 1
                reasons.append(f"RSI oversold risk ({rsi:.1f})")

        # ─── MACD Confirmation ───────────────────────────────────────
        if score > 0 and latest["macd_hist"] > 0:
            score += 1
            reasons.append("MACD histogram positive")
        elif score < 0 and latest["macd_hist"] < 0:
            score -= 1
            reasons.append("MACD histogram negative")

        # ─── Ichimoku Cloud Confirmation ─────────────────────────────
        if score > 0:
            if price > latest.get("ichi_senkou_span_a", 0) and price > latest.get("ichi_senkou_span_b", 0):
                score += 1
                reasons.append("Price above Ichimoku cloud")
        elif score < 0:
            span_a = latest.get("ichi_senkou_span_a", float("inf"))
            span_b = latest.get("ichi_senkou_span_b", float("inf"))
            if price < span_a and price < span_b:
                score -= 1
                reasons.append("Price below Ichimoku cloud")

        # ─── Calculate Entry, SL, TP ────────────────────────────────
        atr = latest["atr"]
        if atr == 0 or np.isnan(atr):
            return self.hold_signal(symbol, "Cannot calculate ATR")

        if score >= 2:
            # BUY Signal
            entry = price
            sl = price - (atr * 2.0)
            tp = price + (atr * 2.0 * config.risk.risk_reward_ratio)
            confidence = min(abs(score) / 6.0, 0.85)

            return self._create_signal(
                SignalType.BUY, symbol, confidence, entry, sl, tp,
                " | ".join(reasons),
            )

        elif score <= -2:
            # SELL Signal
            entry = price
            sl = price + (atr * 2.0)
            tp = price - (atr * 2.0 * config.risk.risk_reward_ratio)
            confidence = min(abs(score) / 6.0, 0.85)

            return self._create_signal(
                SignalType.SELL, symbol, confidence, entry, sl, tp,
                " | ".join(reasons),
            )

        return self.hold_signal(symbol, f"Score too low: {score}")
