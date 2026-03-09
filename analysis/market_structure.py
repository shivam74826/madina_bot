"""
=============================================================================
Market Structure Analyzer
=============================================================================
Advanced price action and market structure analysis:
- Support & Resistance levels (swing highs/lows)
- Supply & Demand zones
- Order Blocks (Smart Money Concepts)
- Fair Value Gaps (FVG / Imbalances)
- Break of Structure (BOS) and Change of Character (CHoCH)
- Liquidity pools (equal highs/lows)
- Fibonacci retracement levels
=============================================================================
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class Zone:
    """Represents a price zone (support/resistance/supply/demand)."""
    zone_type: str          # 'support', 'resistance', 'supply', 'demand', 'order_block'
    price_high: float
    price_low: float
    strength: int           # Number of touches / confirmations
    created_bar: int        # Bar index where zone was created
    last_tested_bar: int = 0
    is_broken: bool = False
    volume_at_creation: float = 0.0

    @property
    def mid_price(self) -> float:
        return (self.price_high + self.price_low) / 2.0

    @property
    def zone_width(self) -> float:
        return self.price_high - self.price_low


@dataclass
class FairValueGap:
    """Represents a Fair Value Gap (FVG / Imbalance)."""
    direction: str          # 'bullish' or 'bearish'
    high: float
    low: float
    bar_index: int
    is_filled: bool = False
    fill_percentage: float = 0.0

    @property
    def gap_size(self) -> float:
        return self.high - self.low


@dataclass 
class StructureBreak:
    """Represents a Break of Structure (BOS) or Change of Character (CHoCH)."""
    break_type: str         # 'BOS' or 'CHoCH'
    direction: str          # 'bullish' or 'bearish'
    price: float
    bar_index: int
    strength: float = 0.0   # How decisive the break was


class MarketStructureAnalyzer:
    """
    Analyzes market structure using Smart Money Concepts (SMC).
    
    Identifies:
    - Market structure shifts (BOS/CHoCH)
    - Order blocks (institutional entry zones)
    - Fair value gaps (price imbalances)
    - Liquidity pools
    - Supply/Demand zones
    """

    def __init__(self, swing_lookback: int = 10, zone_tolerance: float = 0.001):
        """
        Args:
            swing_lookback: Bars to look back for swing point identification
            zone_tolerance: Tolerance for zone proximity (as % of price)
        """
        self.swing_lookback = swing_lookback
        self.zone_tolerance = zone_tolerance

    # ─── SWING POINTS ────────────────────────────────────────────────────

    def find_swing_highs(self, df: pd.DataFrame, lookback: int = None) -> List[Tuple[int, float]]:
        """Find swing highs (local maxima)."""
        lb = lookback or self.swing_lookback
        highs = df["high"].values
        swings = []

        for i in range(lb, len(highs) - lb):
            if highs[i] == max(highs[i - lb:i + lb + 1]):
                swings.append((i, highs[i]))

        return swings

    def find_swing_lows(self, df: pd.DataFrame, lookback: int = None) -> List[Tuple[int, float]]:
        """Find swing lows (local minima)."""
        lb = lookback or self.swing_lookback
        lows = df["low"].values
        swings = []

        for i in range(lb, len(lows) - lb):
            if lows[i] == min(lows[i - lb:i + lb + 1]):
                swings.append((i, lows[i]))

        return swings

    # ─── SUPPORT & RESISTANCE ────────────────────────────────────────────

    def find_support_resistance(
        self, df: pd.DataFrame, num_levels: int = 5
    ) -> Dict[str, List[Zone]]:
        """
        Identify key support and resistance levels.
        
        Uses swing highs/lows with clustering to find significant levels.
        """
        swing_highs = self.find_swing_highs(df)
        swing_lows = self.find_swing_lows(df)

        current_price = df["close"].iloc[-1]
        atr = self._calculate_atr(df)

        # Cluster nearby price levels
        all_levels = []
        for idx, price in swing_highs:
            all_levels.append(("resistance", idx, price))
        for idx, price in swing_lows:
            all_levels.append(("support", idx, price))

        # Group nearby levels
        supports = []
        resistances = []

        support_prices = sorted([p for _, _, p in all_levels if p < current_price], reverse=True)
        resistance_prices = sorted([p for _, _, p in all_levels if p >= current_price])

        # Cluster support levels
        clustered_supports = self._cluster_levels(support_prices, atr * 0.5)
        for cluster in clustered_supports[:num_levels]:
            mid = np.mean(cluster)
            supports.append(Zone(
                zone_type="support",
                price_high=max(cluster),
                price_low=min(cluster),
                strength=len(cluster),
                created_bar=len(df) - 1,
            ))

        # Cluster resistance levels
        clustered_resistances = self._cluster_levels(resistance_prices, atr * 0.5)
        for cluster in clustered_resistances[:num_levels]:
            mid = np.mean(cluster)
            resistances.append(Zone(
                zone_type="resistance",
                price_high=max(cluster),
                price_low=min(cluster),
                strength=len(cluster),
                created_bar=len(df) - 1,
            ))

        return {"supports": supports, "resistances": resistances}

    def _cluster_levels(self, prices: List[float], tolerance: float) -> List[List[float]]:
        """Cluster nearby price levels together."""
        if not prices:
            return []

        clusters = [[prices[0]]]
        for price in prices[1:]:
            if abs(price - np.mean(clusters[-1])) <= tolerance:
                clusters[-1].append(price)
            else:
                clusters.append([price])

        # Sort by cluster size (most touches = strongest)
        clusters.sort(key=len, reverse=True)
        return clusters

    # ─── ORDER BLOCKS ────────────────────────────────────────────────────

    def find_order_blocks(self, df: pd.DataFrame, max_blocks: int = 5) -> List[Zone]:
        """
        Identify Order Blocks — the last opposing candle before a strong move.
        
        Bullish OB: Last bearish candle before a strong bullish move
        Bearish OB: Last bullish candle before a strong bearish move
        """
        if len(df) < 20:
            return []

        order_blocks = []
        opens = df["open"].values
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        volumes = df["tick_volume"].values if "tick_volume" in df.columns else np.ones(len(df))

        atr = self._calculate_atr(df)

        for i in range(3, len(df) - 1):
            # Check for strong move (at least 2x ATR)
            move = abs(closes[i] - opens[i])
            if move < atr * 1.5:
                continue

            # Bullish Order Block: bearish candle before bullish move
            if closes[i] > opens[i]:  # Current candle is bullish
                # Look for last bearish candle before this move
                for j in range(i - 1, max(i - 4, 0), -1):
                    if closes[j] < opens[j]:  # Bearish candle = potential OB
                        ob = Zone(
                            zone_type="order_block_bullish",
                            price_high=highs[j],
                            price_low=lows[j],
                            strength=1,
                            created_bar=j,
                            volume_at_creation=float(volumes[j]),
                        )
                        order_blocks.append(ob)
                        break

            # Bearish Order Block: bullish candle before bearish move
            elif closes[i] < opens[i]:  # Current candle is bearish
                for j in range(i - 1, max(i - 4, 0), -1):
                    if closes[j] > opens[j]:  # Bullish candle = potential OB
                        ob = Zone(
                            zone_type="order_block_bearish",
                            price_high=highs[j],
                            price_low=lows[j],
                            strength=1,
                            created_bar=j,
                            volume_at_creation=float(volumes[j]),
                        )
                        order_blocks.append(ob)
                        break

        # Check if order blocks have been broken (mitigated)
        current_price = closes[-1]
        valid_blocks = []
        for ob in order_blocks:
            if "bullish" in ob.zone_type:
                if current_price < ob.price_low:
                    ob.is_broken = True
                else:
                    valid_blocks.append(ob)
            else:
                if current_price > ob.price_high:
                    ob.is_broken = True
                else:
                    valid_blocks.append(ob)

        # Return most recent unbroken blocks
        valid_blocks.sort(key=lambda x: x.created_bar, reverse=True)
        return valid_blocks[:max_blocks]

    # ─── FAIR VALUE GAPS ─────────────────────────────────────────────────

    def find_fair_value_gaps(self, df: pd.DataFrame, max_gaps: int = 5) -> List[FairValueGap]:
        """
        Identify Fair Value Gaps (FVG) — 3-candle patterns with price imbalance.
        
        Bullish FVG: Gap between candle 1 high and candle 3 low (price moved up too fast)
        Bearish FVG: Gap between candle 1 low and candle 3 high (price moved down too fast)
        """
        if len(df) < 5:
            return []

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        fvgs = []
        atr = self._calculate_atr(df)
        min_gap = atr * 0.2  # Minimum gap size

        for i in range(2, len(df)):
            # Bullish FVG: candle3_low > candle1_high
            if lows[i] > highs[i - 2] and (lows[i] - highs[i - 2]) > min_gap:
                fvg = FairValueGap(
                    direction="bullish",
                    high=lows[i],
                    low=highs[i - 2],
                    bar_index=i - 1,
                )
                # Check if gap has been filled
                if i < len(df) - 1:
                    future_lows = lows[i + 1:] if i + 1 < len(df) else []
                    if len(future_lows) > 0:
                        min_future = np.min(future_lows)
                        if min_future <= fvg.low:
                            fvg.is_filled = True
                            fvg.fill_percentage = 1.0
                        elif min_future < fvg.high:
                            fvg.fill_percentage = (fvg.high - min_future) / fvg.gap_size
                fvgs.append(fvg)

            # Bearish FVG: candle3_high < candle1_low  
            if highs[i] < lows[i - 2] and (lows[i - 2] - highs[i]) > min_gap:
                fvg = FairValueGap(
                    direction="bearish",
                    high=lows[i - 2],
                    low=highs[i],
                    bar_index=i - 1,
                )
                if i < len(df) - 1:
                    future_highs = highs[i + 1:] if i + 1 < len(df) else []
                    if len(future_highs) > 0:
                        max_future = np.max(future_highs)
                        if max_future >= fvg.high:
                            fvg.is_filled = True
                            fvg.fill_percentage = 1.0
                        elif max_future > fvg.low:
                            fvg.fill_percentage = (max_future - fvg.low) / fvg.gap_size
                fvgs.append(fvg)

        # Return unfilled gaps (most recent first)
        unfilled = [f for f in fvgs if not f.is_filled]
        unfilled.sort(key=lambda x: x.bar_index, reverse=True)
        return unfilled[:max_gaps]

    # ─── BREAK OF STRUCTURE ──────────────────────────────────────────────

    def detect_structure_breaks(self, df: pd.DataFrame) -> List[StructureBreak]:
        """
        Detect Break of Structure (BOS) and Change of Character (CHoCH).
        
        BOS: Price breaks a swing point in the same direction as the trend
        CHoCH: Price breaks a swing point against the trend (trend reversal signal)
        """
        if len(df) < 50:
            return []

        swing_highs = self.find_swing_highs(df, lookback=5)
        swing_lows = self.find_swing_lows(df, lookback=5)

        breaks = []
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        # Determine current trend using recent structure
        recent_sh = swing_highs[-3:] if len(swing_highs) >= 3 else swing_highs
        recent_sl = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows

        if len(recent_sh) >= 2 and len(recent_sl) >= 2:
            # Higher highs + higher lows = uptrend
            hh = recent_sh[-1][1] > recent_sh[-2][1] if len(recent_sh) >= 2 else False
            hl = recent_sl[-1][1] > recent_sl[-2][1] if len(recent_sl) >= 2 else False
            # Lower highs + lower lows = downtrend
            lh = recent_sh[-1][1] < recent_sh[-2][1] if len(recent_sh) >= 2 else False
            ll = recent_sl[-1][1] < recent_sl[-2][1] if len(recent_sl) >= 2 else False

            current_trend = "up" if (hh and hl) else ("down" if (lh and ll) else "neutral")
        else:
            current_trend = "neutral"

        # Check for recent breaks
        current_price = closes[-1]
        current_bar = len(df) - 1

        # Check if current price broke above last swing high
        if swing_highs:
            last_sh_idx, last_sh_price = swing_highs[-1]
            if current_price > last_sh_price:
                if current_trend == "up":
                    breaks.append(StructureBreak(
                        break_type="BOS", direction="bullish",
                        price=last_sh_price, bar_index=current_bar,
                        strength=(current_price - last_sh_price) / last_sh_price
                    ))
                elif current_trend == "down":
                    breaks.append(StructureBreak(
                        break_type="CHoCH", direction="bullish",
                        price=last_sh_price, bar_index=current_bar,
                        strength=(current_price - last_sh_price) / last_sh_price
                    ))

        # Check if current price broke below last swing low
        if swing_lows:
            last_sl_idx, last_sl_price = swing_lows[-1]
            if current_price < last_sl_price:
                if current_trend == "down":
                    breaks.append(StructureBreak(
                        break_type="BOS", direction="bearish",
                        price=last_sl_price, bar_index=current_bar,
                        strength=(last_sl_price - current_price) / last_sl_price
                    ))
                elif current_trend == "up":
                    breaks.append(StructureBreak(
                        break_type="CHoCH", direction="bearish",
                        price=last_sl_price, bar_index=current_bar,
                        strength=(last_sl_price - current_price) / last_sl_price
                    ))

        return breaks

    # ─── LIQUIDITY ANALYSIS ──────────────────────────────────────────────

    def find_liquidity_pools(self, df: pd.DataFrame) -> Dict:
        """
        Identify liquidity pools — areas where stop losses likely cluster.
        
        - Equal highs: Sell-side liquidity (stops above)
        - Equal lows: Buy-side liquidity (stops below)
        - Recent swing highs/lows: Obvious SL placement areas
        """
        if len(df) < 30:
            return {"buy_side": [], "sell_side": []}

        highs = df["high"].values
        lows = df["low"].values
        atr = self._calculate_atr(df)
        tolerance = atr * 0.3

        buy_side = []   # Liquidity above price (sell-side stops)
        sell_side = []   # Liquidity below price (buy-side stops)

        swing_highs = self.find_swing_highs(df, lookback=5)
        swing_lows = self.find_swing_lows(df, lookback=5)

        # Find equal highs (clustered at similar prices)
        for i in range(len(swing_highs)):
            count = 1
            for j in range(i + 1, len(swing_highs)):
                if abs(swing_highs[i][1] - swing_highs[j][1]) <= tolerance:
                    count += 1
            if count >= 2:
                buy_side.append({
                    "price": swing_highs[i][1],
                    "touches": count,
                    "type": "equal_highs",
                })

        # Find equal lows
        for i in range(len(swing_lows)):
            count = 1
            for j in range(i + 1, len(swing_lows)):
                if abs(swing_lows[i][1] - swing_lows[j][1]) <= tolerance:
                    count += 1
            if count >= 2:
                sell_side.append({
                    "price": swing_lows[i][1],
                    "touches": count,
                    "type": "equal_lows",
                })

        # Sort by proximity to current price
        current = df["close"].iloc[-1]
        buy_side.sort(key=lambda x: abs(x["price"] - current))
        sell_side.sort(key=lambda x: abs(x["price"] - current))

        return {
            "buy_side": buy_side[:5],
            "sell_side": sell_side[:5],
        }

    # ─── FIBONACCI LEVELS ────────────────────────────────────────────────

    def calculate_fibonacci_levels(self, df: pd.DataFrame, lookback: int = 100) -> Dict:
        """
        Calculate Fibonacci retracement levels from recent swing.
        """
        recent = df.tail(lookback)
        swing_high = recent["high"].max()
        swing_low = recent["low"].min()
        high_idx = recent["high"].idxmax()
        low_idx = recent["low"].idxmin()

        diff = swing_high - swing_low

        # Determine if the latest swing is up or down
        if high_idx > low_idx:
            # Upswing — fib levels are retracements down
            direction = "up"
            levels = {
                "0.0": swing_high,
                "0.236": swing_high - diff * 0.236,
                "0.382": swing_high - diff * 0.382,
                "0.5": swing_high - diff * 0.5,
                "0.618": swing_high - diff * 0.618,
                "0.786": swing_high - diff * 0.786,
                "1.0": swing_low,
            }
        else:
            # Downswing — fib levels are retracements up
            direction = "down"
            levels = {
                "0.0": swing_low,
                "0.236": swing_low + diff * 0.236,
                "0.382": swing_low + diff * 0.382,
                "0.5": swing_low + diff * 0.5,
                "0.618": swing_low + diff * 0.618,
                "0.786": swing_low + diff * 0.786,
                "1.0": swing_high,
            }

        return {
            "direction": direction,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "levels": levels,
        }

    # ─── COMPREHENSIVE ANALYSIS ──────────────────────────────────────────

    def analyze(self, df: pd.DataFrame) -> Dict:
        """
        Perform full market structure analysis.
        
        Returns comprehensive dict with all structure data.
        """
        if len(df) < 50:
            return {"error": "Insufficient data for market structure analysis"}

        sr_levels = self.find_support_resistance(df)
        order_blocks = self.find_order_blocks(df)
        fvgs = self.find_fair_value_gaps(df)
        structure_breaks = self.detect_structure_breaks(df)
        liquidity = self.find_liquidity_pools(df)
        fib = self.calculate_fibonacci_levels(df)

        current_price = df["close"].iloc[-1]
        atr = self._calculate_atr(df)

        # Determine bias from structure
        bias = self._determine_structural_bias(
            current_price, sr_levels, order_blocks, fvgs, structure_breaks, fib
        )

        return {
            "current_price": current_price,
            "atr": atr,
            "supports": [{"price": z.mid_price, "strength": z.strength}
                        for z in sr_levels["supports"]],
            "resistances": [{"price": z.mid_price, "strength": z.strength}
                           for z in sr_levels["resistances"]],
            "order_blocks": [
                {"type": ob.zone_type, "high": ob.price_high, "low": ob.price_low,
                 "bar": ob.created_bar}
                for ob in order_blocks
            ],
            "fair_value_gaps": [
                {"direction": f.direction, "high": f.high, "low": f.low,
                 "filled_pct": round(f.fill_percentage * 100)}
                for f in fvgs
            ],
            "structure_breaks": [
                {"type": b.break_type, "direction": b.direction,
                 "price": b.price, "strength": round(b.strength, 4)}
                for b in structure_breaks
            ],
            "liquidity": liquidity,
            "fibonacci": fib,
            "structural_bias": bias,
        }

    def _determine_structural_bias(
        self, price, sr_levels, order_blocks, fvgs, breaks, fib
    ) -> Dict:
        """Determine the overall structural bias."""
        bullish_score = 0
        bearish_score = 0
        reasons = []

        # Structure breaks
        for b in breaks:
            if b.direction == "bullish":
                bullish_score += 2 if b.break_type == "CHoCH" else 1
                reasons.append(f"Bullish {b.break_type}")
            else:
                bearish_score += 2 if b.break_type == "CHoCH" else 1
                reasons.append(f"Bearish {b.break_type}")

        # Order blocks
        bullish_obs = [ob for ob in order_blocks if "bullish" in ob.zone_type
                       and ob.price_low <= price <= ob.price_high * 1.01]
        bearish_obs = [ob for ob in order_blocks if "bearish" in ob.zone_type
                       and ob.price_low * 0.99 <= price <= ob.price_high]

        if bullish_obs:
            bullish_score += len(bullish_obs)
            reasons.append(f"At bullish OB")
        if bearish_obs:
            bearish_score += len(bearish_obs)
            reasons.append(f"At bearish OB")

        # FVGs
        for fvg in fvgs:
            if fvg.direction == "bullish" and fvg.low <= price <= fvg.high:
                bullish_score += 1
                reasons.append("In bullish FVG")
            elif fvg.direction == "bearish" and fvg.low <= price <= fvg.high:
                bearish_score += 1
                reasons.append("In bearish FVG")

        # Fibonacci confluence
        fib_levels = fib.get("levels", {})
        for level_name, level_price in fib_levels.items():
            if abs(price - level_price) / price < 0.002:  # Within 0.2%
                if level_name in ("0.618", "0.5"):
                    reasons.append(f"At Fib {level_name} level")
                    if fib["direction"] == "up":
                        bullish_score += 1  # Retracement in uptrend
                    else:
                        bearish_score += 1

        net = bullish_score - bearish_score
        if net > 1:
            bias = "strongly_bullish"
        elif net > 0:
            bias = "bullish"
        elif net < -1:
            bias = "strongly_bearish"
        elif net < 0:
            bias = "bearish"
        else:
            bias = "neutral"

        return {
            "bias": bias,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
            "net_score": net,
            "reasons": reasons,
        }

    # ─── TRADING SIGNALS FROM STRUCTURE ──────────────────────────────────

    def get_trade_bias(self, df: pd.DataFrame) -> Tuple[str, float, str]:
        """
        Get a simple trade bias from market structure.
        
        Returns:
            (direction, confidence, reason)
            direction: 'buy', 'sell', or 'neutral'
        """
        analysis = self.analyze(df)
        bias = analysis.get("structural_bias", {})

        bias_str = bias.get("bias", "neutral")
        net_score = bias.get("net_score", 0)
        reasons = bias.get("reasons", [])

        confidence = min(abs(net_score) / 5.0, 0.9)

        if "strongly_bullish" in bias_str or bias_str == "bullish":
            return ("buy", confidence, " | ".join(reasons) if reasons else "Bullish structure")
        elif "strongly_bearish" in bias_str or bias_str == "bearish":
            return ("sell", confidence, " | ".join(reasons) if reasons else "Bearish structure")
        else:
            return ("neutral", 0.0, "No clear structural bias")

    # ─── UTILITY ─────────────────────────────────────────────────────────

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range."""
        if len(df) < period + 1:
            return abs(df["high"].iloc[-1] - df["low"].iloc[-1])

        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                abs(high[1:] - close[:-1]),
                abs(low[1:] - close[:-1])
            )
        )

        return float(np.mean(tr[-period:]))
