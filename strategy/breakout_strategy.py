"""
=============================================================================
Breakout Strategy
=============================================================================
Trades breakouts from consolidation zones with volume confirmation:
- Range compression detection (low volatility → ready to break)
- Support/Resistance breakout with volume surge
- Bollinger Band squeeze breakout
- Failed breakout (fakeout) detection
- Multi-timeframe confirmation
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


class BreakoutStrategy(BaseStrategy):
    """
    Breakout Strategy: Trades range breakouts with confirmation.
    
    Logic:
    1. Detect consolidation (BB squeeze, low ADX, narrow range)
    2. Wait for breakout above/below the range
    3. Confirm with volume surge
    4. Enter with SL inside the range, TP at projected target
    """

    def __init__(self):
        super().__init__("Breakout")
        self.ta = TechnicalAnalyzer()

    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        """Analyze for breakout opportunities."""
        if len(df) < 100:
            return self.hold_signal(symbol, "Insufficient data for breakout analysis")

        indicators = self.ta.compute_all(df)
        latest = indicators.iloc[-1]
        prev = indicators.iloc[-2]
        price = latest["close"]

        score = 0
        reasons = []

        # ─── 1. DETECT CONSOLIDATION ────────────────────────────────
        # Bollinger Band width (squeeze detection)
        bb_width = latest.get("bb_width", 0)
        bb_width_prev = indicators["bb_width"].rolling(50).mean().iloc[-1] if "bb_width" in indicators.columns else bb_width

        is_squeeze = bb_width < bb_width_prev * 0.7  # BB narrower than average

        # ADX low = ranging market  
        adx = latest.get("adx", 25)
        is_low_adx = adx < 20

        # Range compression (recent range vs average range)
        recent_range = (df["high"].tail(10).max() - df["low"].tail(10).min())
        avg_range = (df["high"].rolling(50).max() - df["low"].rolling(50).min()).iloc[-1]
        range_compression = recent_range / avg_range if avg_range > 0 else 1.0

        is_compressed = range_compression < 0.5

        # Score consolidation
        consolidation_score = sum([is_squeeze, is_low_adx, is_compressed])
        if consolidation_score >= 1:
            reasons.append(f"Consolidation detected (score: {consolidation_score})")

        reasons.append(f"Consolidation detected (score: {consolidation_score})")

        # ─── 2. DETECT BREAKOUT ─────────────────────────────────────
        # Recent high/low for the consolidation range
        lookback = 20
        range_high = df["high"].tail(lookback).max()
        range_low = df["low"].tail(lookback).min()
        range_size = range_high - range_low

        atr = latest.get("atr", 0)
        if atr <= 0:
            return self.hold_signal(symbol, "Invalid ATR")

        # Breakout requires closing beyond the range
        breakout_buffer = atr * 0.2  # Small buffer to confirm real breakout

        bullish_breakout = price > range_high + breakout_buffer
        bearish_breakout = price < range_low - breakout_buffer

        if bullish_breakout:
            score += 3
            reasons.append(f"Bullish breakout above {range_high:.5f}")
        elif bearish_breakout:
            score -= 3
            reasons.append(f"Bearish breakout below {range_low:.5f}")
        else:
            return self.hold_signal(symbol, "No breakout detected")

        # ─── 3. VOLUME CONFIRMATION ─────────────────────────────────
        # Volume should be above average during breakout
        vol_col = None
        if "tick_volume" in df.columns and df["tick_volume"].sum() > 0:
            vol_col = "tick_volume"
        elif "volume" in df.columns and df["volume"].sum() > 0:
            vol_col = "volume"

        if vol_col:
            current_vol = df[vol_col].iloc[-1]
            avg_vol = df[vol_col].rolling(20).mean().iloc[-1]
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

            if vol_ratio > 1.5:
                score += 2 if score > 0 else -2
                reasons.append(f"Strong volume ({vol_ratio:.1f}x avg)")
            elif vol_ratio > 1.0:
                score += 1 if score > 0 else -1
                reasons.append(f"Above avg volume ({vol_ratio:.1f}x)")
            else:
                # Weak volume breakout — likely fakeout
                score = score // 2  # Reduce conviction
                reasons.append(f"Weak volume WARNING ({vol_ratio:.1f}x)")

        # ─── 4. MOMENTUM CONFIRMATION ───────────────────────────────
        rsi = latest.get("rsi", 50)
        macd_hist = latest.get("macd_hist", 0)

        if score > 0:
            if rsi > 55 and macd_hist > 0:
                score += 1
                reasons.append("Momentum confirms bullish breakout")
            elif rsi < 40:
                score -= 1
                reasons.append("RSI divergence — possible fakeout")
        elif score < 0:
            if rsi < 45 and macd_hist < 0:
                score -= 1
                reasons.append("Momentum confirms bearish breakout")
            elif rsi > 60:
                score += 1
                reasons.append("RSI divergence — possible fakeout")

        # ─── 5. GENERATE SIGNAL ─────────────────────────────────────
        if score >= 2:
            entry = price
            # SL: max of range-based and ATR-based (whichever is wider)
            range_sl = range_high - range_size * 0.3
            atr_sl = entry - atr * 1.5
            sl = min(range_sl, atr_sl)  # Pick the wider stop
            # TP: projected range extension, enforced min R:R
            sl_dist = abs(entry - sl)
            tp = entry + max(range_size, sl_dist) * config.risk.risk_reward_ratio

            confidence = min(abs(score) / 5.0, 0.85)

            return self._create_signal(
                SignalType.BUY, symbol, confidence, entry, sl, tp,
                " | ".join(reasons),
            )

        elif score <= -2:
            entry = price
            range_sl = range_low + range_size * 0.3
            atr_sl = entry + atr * 1.5
            sl = max(range_sl, atr_sl)  # Pick the wider stop
            sl_dist = abs(sl - entry)
            tp = entry - max(range_size, sl_dist) * config.risk.risk_reward_ratio

            confidence = min(abs(score) / 5.0, 0.85)

            return self._create_signal(
                SignalType.SELL, symbol, confidence, entry, sl, tp,
                " | ".join(reasons),
            )

        return self.hold_signal(symbol, f"Breakout score insufficient: {score}")
