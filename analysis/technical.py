"""
=============================================================================
Technical Analysis Engine
=============================================================================
Comprehensive technical indicator calculations including:
- Moving Averages (SMA, EMA, WMA)
- RSI, MACD, Stochastic, ADX, CCI
- Bollinger Bands, ATR, Ichimoku Cloud
- Support/Resistance, Candlestick Patterns
- Custom composite signals
=============================================================================
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
import logging

from config.settings import config

logger = logging.getLogger(__name__)


class TechnicalAnalyzer:
    """Calculates technical indicators and generates signals."""

    def __init__(self):
        self.cfg = config.indicators

    # ─── Moving Averages ─────────────────────────────────────────────────

    def sma(self, series: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average."""
        return series.rolling(window=period).mean()

    def ema(self, series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean()

    def wma(self, series: pd.Series, period: int) -> pd.Series:
        """Weighted Moving Average."""
        weights = np.arange(1, period + 1)
        return series.rolling(window=period).apply(
            lambda x: np.dot(x, weights) / weights.sum(), raw=True
        )

    def vwap(self, df: pd.DataFrame) -> pd.Series:
        """Volume Weighted Average Price."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        return (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()

    # ─── Oscillators ─────────────────────────────────────────────────────

    def rsi(self, series: pd.Series, period: int = None) -> pd.Series:
        """Relative Strength Index."""
        if period is None:
            period = self.cfg.rsi_period

        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def macd(
        self, series: pd.Series
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        MACD (Moving Average Convergence Divergence).
        
        Returns: (macd_line, signal_line, histogram)
        """
        fast_ema = self.ema(series, self.cfg.macd_fast)
        slow_ema = self.ema(series, self.cfg.macd_slow)
        macd_line = fast_ema - slow_ema
        signal_line = self.ema(macd_line, self.cfg.macd_signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def stochastic(
        self, df: pd.DataFrame
    ) -> Tuple[pd.Series, pd.Series]:
        """
        Stochastic Oscillator.
        
        Returns: (%K, %D)
        """
        k_period = self.cfg.stoch_k
        d_period = self.cfg.stoch_d
        smooth = self.cfg.stoch_smooth

        low_min = df["low"].rolling(window=k_period).min()
        high_max = df["high"].rolling(window=k_period).max()

        fast_k = 100 * (df["close"] - low_min) / (high_max - low_min)
        k = fast_k.rolling(window=smooth).mean()
        d = k.rolling(window=d_period).mean()
        return k, d

    def cci(self, df: pd.DataFrame, period: int = 20) -> pd.Series:
        """Commodity Channel Index."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        sma = typical_price.rolling(window=period).mean()
        mad = typical_price.rolling(window=period).apply(
            lambda x: np.abs(x - x.mean()).mean(), raw=True
        )
        return (typical_price - sma) / (0.015 * mad)

    def williams_r(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Williams %R."""
        high_max = df["high"].rolling(window=period).max()
        low_min = df["low"].rolling(window=period).min()
        return -100 * (high_max - df["close"]) / (high_max - low_min)

    # ─── Trend Indicators ────────────────────────────────────────────────

    def adx(self, df: pd.DataFrame, period: int = None) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Average Directional Index.
        
        Returns: (ADX, +DI, -DI)
        """
        if period is None:
            period = self.cfg.adx_period

        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr = self._true_range(df)
        atr = tr.ewm(alpha=1 / period, min_periods=period).mean()

        plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr)

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.ewm(alpha=1 / period, min_periods=period).mean()

        return adx, plus_di, minus_di

    def ichimoku(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """
        Ichimoku Cloud indicator.
        
        Returns: dict with tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b, chikou_span
        """
        tenkan_period = self.cfg.ichimoku_tenkan
        kijun_period = self.cfg.ichimoku_kijun
        senkou_period = self.cfg.ichimoku_senkou

        high = df["high"]
        low = df["low"]
        close = df["close"]

        tenkan_sen = (high.rolling(tenkan_period).max() + low.rolling(tenkan_period).min()) / 2
        kijun_sen = (high.rolling(kijun_period).max() + low.rolling(kijun_period).min()) / 2
        senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun_period)
        senkou_span_b = ((high.rolling(senkou_period).max() + low.rolling(senkou_period).min()) / 2).shift(kijun_period)
        chikou_span = close.shift(-kijun_period)

        return {
            "tenkan_sen": tenkan_sen,
            "kijun_sen": kijun_sen,
            "senkou_span_a": senkou_span_a,
            "senkou_span_b": senkou_span_b,
            "chikou_span": chikou_span,
        }

    def parabolic_sar(self, df: pd.DataFrame, af_start: float = 0.02, af_max: float = 0.2) -> pd.Series:
        """Parabolic SAR."""
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        n = len(close)

        sar = np.zeros(n)
        ep = np.zeros(n)
        af = np.zeros(n)
        trend = np.ones(n)  # 1 = up, -1 = down

        sar[0] = low[0]
        ep[0] = high[0]
        af[0] = af_start

        for i in range(1, n):
            sar[i] = sar[i - 1] + af[i - 1] * (ep[i - 1] - sar[i - 1])

            if trend[i - 1] == 1:
                if low[i] < sar[i]:
                    trend[i] = -1
                    sar[i] = ep[i - 1]
                    ep[i] = low[i]
                    af[i] = af_start
                else:
                    trend[i] = 1
                    if high[i] > ep[i - 1]:
                        ep[i] = high[i]
                        af[i] = min(af[i - 1] + af_start, af_max)
                    else:
                        ep[i] = ep[i - 1]
                        af[i] = af[i - 1]
            else:
                if high[i] > sar[i]:
                    trend[i] = 1
                    sar[i] = ep[i - 1]
                    ep[i] = high[i]
                    af[i] = af_start
                else:
                    trend[i] = -1
                    if low[i] < ep[i - 1]:
                        ep[i] = low[i]
                        af[i] = min(af[i - 1] + af_start, af_max)
                    else:
                        ep[i] = ep[i - 1]
                        af[i] = af[i - 1]

        return pd.Series(sar, index=df.index, name="sar")

    # ─── Volatility Indicators ───────────────────────────────────────────

    def bollinger_bands(
        self, series: pd.Series
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Bollinger Bands.
        
        Returns: (upper_band, middle_band, lower_band)
        """
        middle = self.sma(series, self.cfg.bb_period)
        std = series.rolling(window=self.cfg.bb_period).std()
        upper = middle + (self.cfg.bb_std * std)
        lower = middle - (self.cfg.bb_std * std)
        return upper, middle, lower

    def atr(self, df: pd.DataFrame, period: int = None) -> pd.Series:
        """Average True Range."""
        if period is None:
            period = self.cfg.atr_period
        tr = self._true_range(df)
        return tr.ewm(alpha=1 / period, min_periods=period).mean()

    def _true_range(self, df: pd.DataFrame) -> pd.Series:
        """Calculate True Range."""
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        return pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    def keltner_channels(
        self, df: pd.DataFrame, ema_period: int = 20, atr_mult: float = 2.0
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Keltner Channels. Returns (upper, middle, lower)."""
        middle = self.ema(df["close"], ema_period)
        atr_val = self.atr(df)
        upper = middle + atr_mult * atr_val
        lower = middle - atr_mult * atr_val
        return upper, middle, lower

    # ─── Volume Indicators ───────────────────────────────────────────────

    def obv(self, df: pd.DataFrame) -> pd.Series:
        """On-Balance Volume."""
        obv = np.where(
            df["close"] > df["close"].shift(1),
            df["volume"],
            np.where(df["close"] < df["close"].shift(1), -df["volume"], 0),
        )
        return pd.Series(np.cumsum(obv), index=df.index, name="obv")

    def mfi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Money Flow Index."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        money_flow = typical_price * df["volume"]

        positive_flow = money_flow.where(typical_price > typical_price.shift(1), 0)
        negative_flow = money_flow.where(typical_price < typical_price.shift(1), 0)

        pos_sum = positive_flow.rolling(window=period).sum()
        neg_sum = negative_flow.rolling(window=period).sum()

        mfi = 100 - (100 / (1 + pos_sum / neg_sum))
        return mfi

    # ─── Support / Resistance ────────────────────────────────────────────

    def find_support_resistance(
        self, df: pd.DataFrame, lookback: int = 50, num_levels: int = 5
    ) -> Dict[str, list]:
        """Find support and resistance levels using pivot points."""
        highs = df["high"].tail(lookback)
        lows = df["low"].tail(lookback)

        # Find local maxima and minima
        resistance_levels = []
        support_levels = []

        for i in range(2, len(highs) - 2):
            if highs.iloc[i] > highs.iloc[i - 1] and highs.iloc[i] > highs.iloc[i - 2] \
               and highs.iloc[i] > highs.iloc[i + 1] and highs.iloc[i] > highs.iloc[i + 2]:
                resistance_levels.append(highs.iloc[i])

            if lows.iloc[i] < lows.iloc[i - 1] and lows.iloc[i] < lows.iloc[i - 2] \
               and lows.iloc[i] < lows.iloc[i + 1] and lows.iloc[i] < lows.iloc[i + 2]:
                support_levels.append(lows.iloc[i])

        # Cluster nearby levels
        resistance_levels = self._cluster_levels(resistance_levels, num_levels)
        support_levels = self._cluster_levels(support_levels, num_levels)

        return {"support": support_levels, "resistance": resistance_levels}

    def _cluster_levels(self, levels: list, n: int) -> list:
        """Cluster nearby price levels together."""
        if not levels:
            return []
        levels = sorted(levels)
        clustered = []
        current_cluster = [levels[0]]

        for i in range(1, len(levels)):
            if abs(levels[i] - current_cluster[-1]) / current_cluster[-1] < 0.001:
                current_cluster.append(levels[i])
            else:
                clustered.append(np.mean(current_cluster))
                current_cluster = [levels[i]]
        clustered.append(np.mean(current_cluster))

        # Return top N strongest levels
        return sorted(clustered)[-n:] if len(clustered) > n else clustered

    # ─── Candlestick Patterns ────────────────────────────────────────────

    def detect_candlestick_patterns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Detect major candlestick patterns."""
        result = pd.DataFrame(index=df.index)
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        body = abs(c - o)
        range_ = h - l

        # Doji
        result["doji"] = (body / range_ < 0.1).astype(int)

        # Hammer / Hanging Man
        lower_shadow = pd.concat([o, c], axis=1).min(axis=1) - l
        upper_shadow = h - pd.concat([o, c], axis=1).max(axis=1)
        result["hammer"] = ((lower_shadow > 2 * body) & (upper_shadow < body * 0.5)).astype(int)

        # Engulfing
        prev_body = body.shift(1)
        bullish_engulf = (c > o) & (c.shift(1) < o.shift(1)) & (body > prev_body)
        bearish_engulf = (c < o) & (c.shift(1) > o.shift(1)) & (body > prev_body)
        result["bullish_engulfing"] = bullish_engulf.astype(int)
        result["bearish_engulfing"] = bearish_engulf.astype(int)

        # Morning / Evening Star (3-candle)
        small_body_1 = body.shift(1) < body.shift(2) * 0.3
        morning_star = (c.shift(2) < o.shift(2)) & small_body_1 & (c > o) & (c > (o.shift(2) + c.shift(2)) / 2)
        evening_star = (c.shift(2) > o.shift(2)) & small_body_1 & (c < o) & (c < (o.shift(2) + c.shift(2)) / 2)
        result["morning_star"] = morning_star.astype(int)
        result["evening_star"] = evening_star.astype(int)

        # Three White Soldiers / Black Crows
        bull_candle = c > o
        bear_candle = c < o
        three_white = bull_candle & bull_candle.shift(1) & bull_candle.shift(2) & \
                      (c > c.shift(1)) & (c.shift(1) > c.shift(2))
        three_black = bear_candle & bear_candle.shift(1) & bear_candle.shift(2) & \
                      (c < c.shift(1)) & (c.shift(1) < c.shift(2))
        result["three_white_soldiers"] = three_white.astype(int)
        result["three_black_crows"] = three_black.astype(int)

        return result

    # ─── Compute All Indicators ──────────────────────────────────────────

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all technical indicators and add them to the DataFrame.
        This is the main method used by strategies and AI models.
        """
        result = df.copy()

        # Moving Averages
        result["sma_fast"] = self.sma(result["close"], self.cfg.sma_fast)
        result["sma_slow"] = self.sma(result["close"], self.cfg.sma_slow)
        result["sma_trend"] = self.sma(result["close"], self.cfg.sma_trend)
        result["ema_fast"] = self.ema(result["close"], self.cfg.ema_fast)
        result["ema_slow"] = self.ema(result["close"], self.cfg.ema_slow)

        # RSI
        result["rsi"] = self.rsi(result["close"])

        # MACD
        result["macd"], result["macd_signal"], result["macd_hist"] = self.macd(result["close"])

        # Bollinger Bands
        result["bb_upper"], result["bb_middle"], result["bb_lower"] = self.bollinger_bands(result["close"])
        result["bb_width"] = (result["bb_upper"] - result["bb_lower"]) / result["bb_middle"]
        result["bb_pct"] = (result["close"] - result["bb_lower"]) / (result["bb_upper"] - result["bb_lower"])

        # ATR
        result["atr"] = self.atr(result)

        # Stochastic
        result["stoch_k"], result["stoch_d"] = self.stochastic(result)

        # ADX
        result["adx"], result["plus_di"], result["minus_di"] = self.adx(result)

        # CCI
        result["cci"] = self.cci(result)

        # Williams %R
        result["williams_r"] = self.williams_r(result)

        # OBV
        result["obv"] = self.obv(result)

        # MFI
        result["mfi"] = self.mfi(result)

        # Ichimoku
        ichimoku_data = self.ichimoku(result)
        for key, value in ichimoku_data.items():
            result[f"ichi_{key}"] = value

        # Parabolic SAR
        result["psar"] = self.parabolic_sar(result)

        # Candlestick Patterns
        patterns = self.detect_candlestick_patterns(result)
        for col in patterns.columns:
            result[f"pattern_{col}"] = patterns[col]

        return result

    # ─── Signal Generation ───────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame) -> Dict:
        """
        Generate a composite trading signal from all indicators.
        
        Returns:
            Dict with 'signal' (-1 to 1), 'strength', 'reasons'
        """
        if len(df) < 200:
            return {"signal": 0, "strength": 0, "reasons": ["Insufficient data"]}

        indicators = self.compute_all(df)
        latest = indicators.iloc[-1]
        signals = []
        reasons = []

        # Trend (Moving Averages)
        if latest["sma_fast"] > latest["sma_slow"] > latest["sma_trend"]:
            signals.append(1)
            reasons.append("Strong uptrend (SMA alignment)")
        elif latest["sma_fast"] < latest["sma_slow"] < latest["sma_trend"]:
            signals.append(-1)
            reasons.append("Strong downtrend (SMA alignment)")
        else:
            signals.append(0)

        # RSI
        if latest["rsi"] < self.cfg.rsi_oversold:
            signals.append(1)
            reasons.append(f"RSI oversold ({latest['rsi']:.1f})")
        elif latest["rsi"] > self.cfg.rsi_overbought:
            signals.append(-1)
            reasons.append(f"RSI overbought ({latest['rsi']:.1f})")
        else:
            signals.append(0)

        # MACD
        if latest["macd_hist"] > 0 and indicators["macd_hist"].iloc[-2] <= 0:
            signals.append(1)
            reasons.append("MACD bullish crossover")
        elif latest["macd_hist"] < 0 and indicators["macd_hist"].iloc[-2] >= 0:
            signals.append(-1)
            reasons.append("MACD bearish crossover")
        else:
            signals.append(0.5 if latest["macd_hist"] > 0 else -0.5)

        # Bollinger Bands
        if latest["close"] < latest["bb_lower"]:
            signals.append(1)
            reasons.append("Price below lower Bollinger Band")
        elif latest["close"] > latest["bb_upper"]:
            signals.append(-1)
            reasons.append("Price above upper Bollinger Band")
        else:
            signals.append(0)

        # ADX + DI
        if latest["adx"] > self.cfg.adx_threshold:
            if latest["plus_di"] > latest["minus_di"]:
                signals.append(0.5)
                reasons.append(f"Strong bullish trend (ADX: {latest['adx']:.1f})")
            else:
                signals.append(-0.5)
                reasons.append(f"Strong bearish trend (ADX: {latest['adx']:.1f})")

        # Stochastic
        if latest["stoch_k"] < 20 and latest["stoch_d"] < 20:
            signals.append(0.5)
            reasons.append("Stochastic oversold")
        elif latest["stoch_k"] > 80 and latest["stoch_d"] > 80:
            signals.append(-0.5)
            reasons.append("Stochastic overbought")

        # Ichimoku Cloud
        if latest["close"] > latest.get("ichi_senkou_span_a", 0) and \
           latest["close"] > latest.get("ichi_senkou_span_b", 0):
            signals.append(0.5)
            reasons.append("Price above Ichimoku cloud")
        elif latest["close"] < latest.get("ichi_senkou_span_a", float("inf")) and \
             latest["close"] < latest.get("ichi_senkou_span_b", float("inf")):
            signals.append(-0.5)
            reasons.append("Price below Ichimoku cloud")

        # Candlestick Patterns
        if latest.get("pattern_bullish_engulfing", 0) or latest.get("pattern_morning_star", 0) or latest.get("pattern_three_white_soldiers", 0):
            signals.append(0.5)
            reasons.append("Bullish candlestick pattern")
        if latest.get("pattern_bearish_engulfing", 0) or latest.get("pattern_evening_star", 0) or latest.get("pattern_three_black_crows", 0):
            signals.append(-0.5)
            reasons.append("Bearish candlestick pattern")

        # Composite signal
        if signals:
            avg_signal = np.mean(signals)
            strength = abs(avg_signal)
        else:
            avg_signal = 0
            strength = 0

        return {
            "signal": round(avg_signal, 3),
            "strength": round(strength, 3),
            "reasons": reasons if reasons else ["No clear signal"],
            "indicators": {
                "rsi": round(latest["rsi"], 2) if not np.isnan(latest["rsi"]) else 0,
                "macd_hist": round(latest["macd_hist"], 6) if not np.isnan(latest["macd_hist"]) else 0,
                "adx": round(latest["adx"], 2) if not np.isnan(latest["adx"]) else 0,
                "bb_pct": round(latest["bb_pct"], 3) if not np.isnan(latest["bb_pct"]) else 0,
                "stoch_k": round(latest["stoch_k"], 2) if not np.isnan(latest["stoch_k"]) else 0,
                "atr": round(latest["atr"], 6) if not np.isnan(latest["atr"]) else 0,
            },
        }
