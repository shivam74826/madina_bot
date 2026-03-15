"""
=============================================================================
Mean Reversion Strategy
=============================================================================
A mean reversion strategy that identifies overextended price moves:
- Bollinger Band extremes for entry triggers
- RSI divergence confirmation
- Support/Resistance levels
- ATR-based dynamic SL/TP
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


class MeanReversionStrategy(BaseStrategy):
    """Mean Reversion Strategy: Trade reversals at extremes."""

    def __init__(self):
        super().__init__("Mean_Reversion")
        self.ta = TechnicalAnalyzer()

    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        """Analyze for mean reversion opportunities."""
        if len(df) < 100:
            return self.hold_signal(symbol, "Insufficient data")

        indicators = self.ta.compute_all(df)
        latest = indicators.iloc[-1]
        prev = indicators.iloc[-2]
        price = latest["close"]

        score = 0
        reasons = []

        # ─── Reject trends (mean reversion only works in ranging markets) ──
        adx_val = latest["adx"]
        if adx_val > 25:
            return self.hold_signal(symbol, f"Trend too strong for MR (ADX: {adx_val:.1f})")

        # ─── Bollinger Band Extremes ────────────────────────────────
        bb_pct = latest["bb_pct"]
        if bb_pct < 0.0:
            score += 2
            reasons.append(f"Price below lower BB (BB%: {bb_pct:.2f})")
        elif bb_pct < 0.1:
            score += 1
            reasons.append(f"Price near lower BB (BB%: {bb_pct:.2f})")
        elif bb_pct > 1.0:
            score -= 2
            reasons.append(f"Price above upper BB (BB%: {bb_pct:.2f})")
        elif bb_pct > 0.9:
            score -= 1
            reasons.append(f"Price near upper BB (BB%: {bb_pct:.2f})")
        else:
            # Price within BB range — no BB signal but don't block
            pass

        # ─── RSI Extremes ───────────────────────────────────────────
        rsi = latest["rsi"]
        if rsi < 25:
            score += 2
            reasons.append(f"RSI extremely oversold ({rsi:.1f})")
        elif rsi < config.indicators.rsi_oversold:
            score += 1
            reasons.append(f"RSI oversold ({rsi:.1f})")
        elif rsi > 75:
            score -= 2
            reasons.append(f"RSI extremely overbought ({rsi:.1f})")
        elif rsi > config.indicators.rsi_overbought:
            score -= 1
            reasons.append(f"RSI overbought ({rsi:.1f})")

        # ─── Stochastic ─────────────────────────────────────────────
        stoch_k = latest["stoch_k"]
        if stoch_k < 20:
            score += 1
            reasons.append(f"Stochastic oversold ({stoch_k:.1f})")
        elif stoch_k > 80:
            score -= 1
            reasons.append(f"Stochastic overbought ({stoch_k:.1f})")

        # ─── CCI ────────────────────────────────────────────────────
        cci_val = latest["cci"]
        if cci_val < -200:
            score += 1
            reasons.append(f"CCI extreme low ({cci_val:.1f})")
        elif cci_val > 200:
            score -= 1
            reasons.append(f"CCI extreme high ({cci_val:.1f})")

        # ─── Candlestick Reversal Patterns ──────────────────────────
        if score > 0:
            if latest.get("pattern_hammer", 0) or latest.get("pattern_bullish_engulfing", 0) or latest.get("pattern_morning_star", 0):
                score += 1
                reasons.append("Bullish reversal candlestick")
        elif score < 0:
            if latest.get("pattern_bearish_engulfing", 0) or latest.get("pattern_evening_star", 0):
                score += -1
                reasons.append("Bearish reversal candlestick")

        # ─── Z-Score ────────────────────────────────────────────────
        zscore = (price - indicators["close"].rolling(20).mean().iloc[-1]) / \
                 indicators["close"].rolling(20).std().iloc[-1]
        if zscore < -2:
            score += 1
            reasons.append(f"Z-score extreme low ({zscore:.2f})")
        elif zscore > 2:
            score -= 1
            reasons.append(f"Z-score extreme high ({zscore:.2f})")

        # ─── Calculate Entry, SL, TP ────────────────────────────────
        atr = latest["atr"]
        if atr == 0 or np.isnan(atr):
            return self.hold_signal(symbol, "Cannot calculate ATR")

        bb_middle = latest["bb_middle"]

        if score >= 2:
            # BUY Signal (oversold reversion)
            entry = price
            sl = price - (atr * 1.5)
            tp = bb_middle  # Target the middle band
            # Enforce minimum R:R — never accept a sub-spread TP
            sl_dist = abs(entry - sl)
            min_tp_dist = sl_dist * config.risk.risk_reward_ratio
            if tp - entry < min_tp_dist:
                tp = entry + min_tp_dist
            confidence = min(abs(score) / 5.0, 0.85)

            return self._create_signal(
                SignalType.BUY, symbol, confidence, entry, sl, tp,
                " | ".join(reasons),
            )

        elif score <= -2:
            # SELL Signal (overbought reversion)
            entry = price
            sl = price + (atr * 1.5)
            tp = bb_middle
            sl_dist = abs(sl - entry)
            min_tp_dist = sl_dist * config.risk.risk_reward_ratio
            if entry - tp < min_tp_dist:
                tp = entry - min_tp_dist
            confidence = min(abs(score) / 5.0, 0.85)

            return self._create_signal(
                SignalType.SELL, symbol, confidence, entry, sl, tp,
                " | ".join(reasons),
            )

        return self.hold_signal(symbol, f"MR score insufficient: {score}")
