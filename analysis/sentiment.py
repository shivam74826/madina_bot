"""
=============================================================================
Market Sentiment Analyzer
=============================================================================
Analyzes overall market sentiment using multiple data sources:
- Currency strength analysis
- Volatility regime detection
- Market session analysis
- Inter-market correlations
=============================================================================
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Optional
import logging

from config.settings import config

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """Analyzes market sentiment and conditions."""

    def __init__(self):
        self._currency_strength = {}

    def analyze_market_regime(self, df: pd.DataFrame) -> Dict:
        """
        Determine the current market regime.
        
        Returns:
            Dict with regime type, volatility state, and trend info
        """
        if len(df) < 50:
            return {"regime": "unknown", "volatility": "unknown", "trend": "unknown"}

        returns = df["close"].pct_change().dropna()

        # Volatility regime
        current_vol = returns.tail(20).std()
        long_vol = returns.std()
        vol_ratio = current_vol / long_vol if long_vol > 0 else 1.0

        if vol_ratio > 1.5:
            volatility = "high"
        elif vol_ratio < 0.5:
            volatility = "low"
        else:
            volatility = "normal"

        # Trend detection
        sma_20 = df["close"].rolling(20).mean().iloc[-1]
        sma_50 = df["close"].rolling(50).mean().iloc[-1]
        current_price = df["close"].iloc[-1]

        if current_price > sma_20 > sma_50:
            trend = "bullish"
        elif current_price < sma_20 < sma_50:
            trend = "bearish"
        else:
            trend = "ranging"

        # Regime classification
        if trend != "ranging" and volatility != "high":
            regime = "trending"
        elif trend == "ranging" and volatility == "low":
            regime = "ranging"
        elif volatility == "high":
            regime = "volatile"
        else:
            regime = "transitioning"

        return {
            "regime": regime,
            "volatility": volatility,
            "vol_ratio": round(vol_ratio, 2),
            "trend": trend,
            "current_price": round(current_price, 5),
        }

    def calculate_currency_strength(
        self, pair_data: Dict[str, pd.DataFrame], period: int = 20
    ) -> Dict[str, float]:
        """
        Calculate individual currency strength scores.
        
        Args:
            pair_data: Dict of symbol -> DataFrame with OHLCV data
            period: Lookback period for strength calculation
            
        Returns:
            Dict of currency -> strength score (-100 to 100)
        """
        currencies = {}

        for symbol, df in pair_data.items():
            if len(df) < period:
                continue

            change = (df["close"].iloc[-1] / df["close"].iloc[-period] - 1) * 100

            base = symbol[:3]
            quote = symbol[3:6]

            currencies.setdefault(base, [])
            currencies.setdefault(quote, [])

            currencies[base].append(change)
            currencies[quote].append(-change)  # Inverse for quote currency

        # Average strength
        strength = {}
        for currency, changes in currencies.items():
            if changes:
                strength[currency] = round(np.mean(changes), 3)

        # Normalize to -100 to 100
        if strength:
            max_abs = max(abs(v) for v in strength.values())
            if max_abs > 0:
                for k in strength:
                    strength[k] = round(strength[k] / max_abs * 100, 2)

        self._currency_strength = strength
        return strength

    def get_market_session(self) -> Dict:
        """
        Determine the current active trading session.
        
        Returns:
            Dict with session info and expected volatility
        """
        utc_now = datetime.now(timezone.utc)
        hour = utc_now.hour

        sessions = {
            "sydney": (21, 6),
            "tokyo": (0, 9),
            "london": (7, 16),
            "new_york": (12, 21),
        }

        active_sessions = []
        for session, (start, end) in sessions.items():
            if start < end:
                if start <= hour < end:
                    active_sessions.append(session)
            else:  # Wraps around midnight
                if hour >= start or hour < end:
                    active_sessions.append(session)

        # Overlap detection (highest volatility)
        is_overlap = len(active_sessions) > 1
        overlap_type = None
        if "london" in active_sessions and "new_york" in active_sessions:
            overlap_type = "london_newyork"
        elif "tokyo" in active_sessions and "london" in active_sessions:
            overlap_type = "tokyo_london"

        # Volatility expectation
        if overlap_type == "london_newyork":
            expected_vol = "very_high"
        elif overlap_type == "tokyo_london":
            expected_vol = "high"
        elif "london" in active_sessions or "new_york" in active_sessions:
            expected_vol = "medium_high"
        elif "tokyo" in active_sessions:
            expected_vol = "medium"
        else:
            expected_vol = "low"

        # Best pairs for session
        session_pairs = {
            "sydney": ["AUDUSD", "NZDUSD", "AUDJPY"],
            "tokyo": ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY"],
            "london": ["EURUSD", "GBPUSD", "EURGBP", "USDCHF"],
            "new_york": ["EURUSD", "GBPUSD", "USDCAD", "USDJPY"],
        }

        recommended_pairs = set()
        for session in active_sessions:
            recommended_pairs.update(session_pairs.get(session, []))

        return {
            "active_sessions": active_sessions,
            "is_overlap": is_overlap,
            "overlap_type": overlap_type,
            "expected_volatility": expected_vol,
            "recommended_pairs": list(recommended_pairs),
            "utc_hour": hour,
        }

    def detect_divergence(
        self, price: pd.Series, indicator: pd.Series, lookback: int = 20
    ) -> Optional[str]:
        """
        Detect bullish or bearish divergence between price and indicator.
        
        Returns:
            'bullish_divergence', 'bearish_divergence', or None
        """
        if len(price) < lookback or len(indicator) < lookback:
            return None

        price_tail = price.tail(lookback)
        ind_tail = indicator.tail(lookback)

        # Find recent swing lows and highs
        price_making_lower_low = price_tail.iloc[-1] < price_tail.min() * 1.001
        price_making_higher_high = price_tail.iloc[-1] > price_tail.max() * 0.999

        ind_making_higher_low = ind_tail.iloc[-1] > ind_tail.min()
        ind_making_lower_high = ind_tail.iloc[-1] < ind_tail.max()

        # Bullish divergence: price lower low, indicator higher low
        if price_making_lower_low and ind_making_higher_low:
            return "bullish_divergence"

        # Bearish divergence: price higher high, indicator lower high
        if price_making_higher_high and ind_making_lower_high:
            return "bearish_divergence"

        return None

    def get_sentiment_summary(
        self, df: pd.DataFrame, all_pairs_data: Dict[str, pd.DataFrame] = None
    ) -> Dict:
        """Get a complete sentiment summary."""
        regime = self.analyze_market_regime(df)
        session = self.get_market_session()

        summary = {
            "regime": regime,
            "session": session,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if all_pairs_data:
            summary["currency_strength"] = self.calculate_currency_strength(all_pairs_data)

        return summary
