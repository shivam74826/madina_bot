"""
=============================================================================
Smart Money Concepts (SMC) Strategy
=============================================================================
Institutional-grade strategy based on Smart Money Concepts:
- Order Block entries (institutional accumulation/distribution zones)
- Fair Value Gap fills (price imbalance trades)
- Break of Structure confirmation
- Liquidity sweep entries
- Multi-timeframe confluence
=============================================================================
"""

import pandas as pd
import numpy as np
from typing import Dict
import logging

from config.settings import config
from strategy.base_strategy import BaseStrategy, TradeSignal, SignalType
from analysis.technical import TechnicalAnalyzer
from analysis.market_structure import MarketStructureAnalyzer

logger = logging.getLogger(__name__)


class SMCStrategy(BaseStrategy):
    """
    Smart Money Concepts Strategy.
    
    Trades based on institutional order flow concepts:
    1. Identify market structure (trend direction via BOS/CHoCH)
    2. Wait for price to retrace to an Order Block or FVG
    3. Enter with structure confirmation
    4. Target opposing liquidity pool
    """

    def __init__(self):
        super().__init__("Smart_Money")
        self.ta = TechnicalAnalyzer()
        self.ms = MarketStructureAnalyzer(swing_lookback=8)

    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        """Analyze using Smart Money Concepts."""
        if len(df) < 100:
            return self.hold_signal(symbol, "Insufficient data for SMC analysis")

        try:
            structure = self.ms.analyze(df)
        except Exception as e:
            logger.warning(f"SMC analysis error for {symbol}: {e}")
            return self.hold_signal(symbol, f"Structure analysis failed: {e}")

        current_price = structure["current_price"]
        atr = structure["atr"]

        if atr <= 0:
            return self.hold_signal(symbol, "Invalid ATR")

        bias = structure.get("structural_bias", {})
        bias_direction = bias.get("bias", "neutral")
        bias_score = bias.get("net_score", 0)
        bias_reasons = bias.get("reasons", [])

        score = 0
        reasons = []

        # ─── 1. MARKET STRUCTURE DIRECTION ───────────────────────────
        # Only trade in the direction of structure
        structure_breaks = structure.get("structure_breaks", [])

        has_bullish_break = any(
            b["direction"] == "bullish" for b in structure_breaks
        )
        has_bearish_break = any(
            b["direction"] == "bearish" for b in structure_breaks
        )

        # CHoCH (Change of Character) is a stronger signal
        has_bullish_choch = any(
            b["direction"] == "bullish" and b["type"] == "CHoCH"
            for b in structure_breaks
        )
        has_bearish_choch = any(
            b["direction"] == "bearish" and b["type"] == "CHoCH"
            for b in structure_breaks
        )

        if has_bullish_break:
            score += 2 if has_bullish_choch else 1
            reasons.append("Bullish BOS" + (" + CHoCH" if has_bullish_choch else ""))
        if has_bearish_break:
            score -= 2 if has_bearish_choch else 1
            reasons.append("Bearish BOS" + (" + CHoCH" if has_bearish_choch else ""))

        # Structural bias
        if "bullish" in bias_direction:
            score += 1
            reasons.append(f"Bullish structure (score: {bias_score})")
        elif "bearish" in bias_direction:
            score -= 1
            reasons.append(f"Bearish structure (score: {bias_score})")

        # ─── 2. ORDER BLOCK PROXIMITY ────────────────────────────────
        order_blocks = structure.get("order_blocks", [])

        for ob in order_blocks:
            ob_high = ob["high"]
            ob_low = ob["low"]
            ob_type = ob["type"]

            # Check if price is at/near the order block
            if ob_low <= current_price <= ob_high:
                if "bullish" in ob_type:
                    score += 2
                    reasons.append("At bullish Order Block")
                elif "bearish" in ob_type:
                    score -= 2
                    reasons.append("At bearish Order Block")
            elif "bullish" in ob_type and 0 < (current_price - ob_high) < atr * 0.5:
                score += 1
                reasons.append("Near bullish Order Block")
            elif "bearish" in ob_type and 0 < (ob_low - current_price) < atr * 0.5:
                score -= 1
                reasons.append("Near bearish Order Block")

        # ─── 3. FAIR VALUE GAP ──────────────────────────────────────
        fvgs = structure.get("fair_value_gaps", [])

        for fvg in fvgs:
            fvg_high = fvg["high"]
            fvg_low = fvg["low"]

            if fvg_low <= current_price <= fvg_high:
                if fvg["direction"] == "bullish":
                    score += 1
                    reasons.append("In bullish FVG (expect fill & bounce)")
                elif fvg["direction"] == "bearish":
                    score -= 1
                    reasons.append("In bearish FVG (expect fill & drop)")

        # ─── 4. FIBONACCI CONFLUENCE ─────────────────────────────────
        fib = structure.get("fibonacci", {})
        fib_levels = fib.get("levels", {})
        fib_direction = fib.get("direction", "")

        for level_name, level_price in fib_levels.items():
            if abs(current_price - level_price) / current_price < 0.002:
                if level_name in ("0.618", "0.5", "0.382"):
                    if fib_direction == "up" and score > 0:
                        score += 1
                        reasons.append(f"Bullish Fib {level_name} retracement")
                    elif fib_direction == "down" and score < 0:
                        score -= 1
                        reasons.append(f"Bearish Fib {level_name} retracement")

        # ─── 5. TECHNICAL CONFIRMATION ───────────────────────────────
        indicators = self.ta.compute_all(df)
        latest = indicators.iloc[-1]

        rsi = latest.get("rsi", 50)
        if score > 0 and rsi < 65:  # Not overbought
            score += 1
            reasons.append(f"RSI confirms buy ({rsi:.0f})")
        elif score < 0 and rsi > 35:  # Not oversold
            score -= 1
            reasons.append(f"RSI confirms sell ({rsi:.0f})")

        # ─── GENERATE SIGNAL ─────────────────────────────────────────
        if score >= 2:
            entry = current_price
            sl = current_price - atr * 1.5
            tp = current_price + atr * 1.5 * config.risk.risk_reward_ratio

            # If there's a nearby resistance, use it as a more realistic TP
            resistances = structure.get("resistances", [])
            for res in resistances:
                if res["price"] > entry + atr:
                    candidate_tp = res["price"]
                    # Only use S/R TP if it maintains minimum R:R
                    if abs(candidate_tp - entry) / abs(entry - sl) >= config.risk.risk_reward_ratio:
                        tp = candidate_tp
                    break

            confidence = min(abs(score) / 5.0, 0.85)

            return self._create_signal(
                SignalType.BUY, symbol, confidence, entry, sl, tp,
                " | ".join(reasons),
            )

        elif score <= -2:
            entry = current_price
            sl = current_price + atr * 1.5
            tp = current_price - atr * 1.5 * config.risk.risk_reward_ratio

            # Use nearby support for more realistic TP
            supports = structure.get("supports", [])
            for sup in supports:
                if sup["price"] < entry - atr:
                    candidate_tp = sup["price"]
                    # Only use S/R TP if it maintains minimum R:R
                    if abs(entry - candidate_tp) / abs(sl - entry) >= config.risk.risk_reward_ratio:
                        tp = candidate_tp
                    break

            confidence = min(abs(score) / 5.0, 0.85)

            return self._create_signal(
                SignalType.SELL, symbol, confidence, entry, sl, tp,
                " | ".join(reasons),
            )

        return self.hold_signal(
            symbol,
            f"SMC score insufficient ({score}) - {' | '.join(reasons) if reasons else 'No setup'}"
        )
