"""
=============================================================================
Data Fetcher
=============================================================================
High-level data retrieval and preparation for analysis and AI models.
Multi-timeframe data aggregation and preprocessing.
=============================================================================
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

from config.settings import config, TimeFrame
from core.mt5_connector import MT5Connector

logger = logging.getLogger(__name__)


class DataFetcher:
    """Fetches and prepares market data for analysis."""

    def __init__(self, connector: MT5Connector):
        self.connector = connector
        self._cache = {}
        self._cache_time = {}
        self._cache_ttl = 60  # Cache TTL in seconds

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: TimeFrame = None,
        count: int = 500,
        use_cache: bool = True,
    ) -> Optional[pd.DataFrame]:
        """Get OHLCV data with caching."""
        if timeframe is None:
            timeframe = config.trading.primary_timeframe

        cache_key = f"{symbol}_{timeframe.value}_{count}"

        # Check cache
        if use_cache and cache_key in self._cache:
            elapsed = (datetime.now() - self._cache_time[cache_key]).total_seconds()
            # Invalidate stale cache: after weekends or gaps > 2 min of TTL
            cached_df = self._cache[cache_key]
            stale = False
            if elapsed >= self._cache_ttl:
                stale = True
            elif cached_df is not None and len(cached_df) > 0 and 'time' in cached_df.columns:
                last_bar = cached_df['time'].iloc[-1]
                if hasattr(last_bar, 'weekday') and last_bar.weekday() <= 4:
                    # If today is Monday and last bar is from Friday/earlier, force refresh
                    now = datetime.now()
                    if now.weekday() == 0 and last_bar.weekday() == 4:
                        stale = True
            if not stale:
                return cached_df.copy()

        # Fetch fresh data with retry
        df = None
        for attempt in range(3):
            df = self.connector.get_rates(symbol, timeframe, count)
            if df is not None:
                break
            import time as _time
            _time.sleep(1 * (attempt + 1))

        # Validate OHLCV data
        if df is not None and len(df) > 0:
            try:
                bad_rows = (
                    (df['high'] < df['low']) |
                    (df['close'] > df['high']) |
                    (df['close'] < df['low'])
                )
                if bad_rows.any():
                    n_bad = bad_rows.sum()
                    logger.warning(f"DATA QUALITY: {n_bad} bad OHLCV rows for {symbol} — dropping them")
                    df = df[~bad_rows].reset_index(drop=True)
            except Exception:
                pass  # Don't break on validation failure

            self._cache[cache_key] = df
            self._cache_time[cache_key] = datetime.now()

        return df

    def get_multi_timeframe_data(
        self,
        symbol: str,
        count: int = 500,
    ) -> Dict[TimeFrame, pd.DataFrame]:
        """Get data across all analysis timeframes."""
        data = {}
        for tf in config.trading.analysis_timeframes:
            df = self.get_ohlcv(symbol, tf, count)
            if df is not None:
                data[tf] = df
        return data

    def get_all_symbols_data(
        self,
        timeframe: TimeFrame = None,
        count: int = 500,
    ) -> Dict[str, pd.DataFrame]:
        """Get data for all configured trading symbols."""
        data = {}
        for symbol in config.trading.symbols:
            self.connector.enable_symbol(symbol)
            df = self.get_ohlcv(symbol, timeframe, count)
            if df is not None:
                data[symbol] = df
        return data

    def get_correlation_matrix(
        self,
        timeframe: TimeFrame = None,
        count: int = 200,
    ) -> Optional[pd.DataFrame]:
        """Calculate correlation matrix between all trading pairs."""
        data = self.get_all_symbols_data(timeframe, count)
        if not data:
            return None

        closes = pd.DataFrame()
        for symbol, df in data.items():
            closes[symbol] = df["close"].pct_change()

        return closes.corr()

    def get_training_data(
        self,
        symbol: str,
        timeframe: TimeFrame = None,
        days: int = None,
    ) -> Optional[pd.DataFrame]:
        """Get extended historical data for AI model training."""
        if days is None:
            days = config.ai.training_lookback_days
        if timeframe is None:
            timeframe = config.trading.primary_timeframe

        date_from = datetime.now() - timedelta(days=days)
        date_to = datetime.now()

        return self.connector.get_rates_range(symbol, timeframe, date_from, date_to)

    def prepare_features_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add basic derived columns useful for analysis."""
        result = df.copy()

        # Price changes
        result["returns"] = result["close"].pct_change()
        result["log_returns"] = np.log(result["close"] / result["close"].shift(1))

        # Candle patterns
        result["body"] = result["close"] - result["open"]
        result["body_pct"] = result["body"] / result["open"] * 100
        result["upper_shadow"] = result["high"] - result[["open", "close"]].max(axis=1)
        result["lower_shadow"] = result[["open", "close"]].min(axis=1) - result["low"]
        result["range"] = result["high"] - result["low"]

        # Volume
        if "volume" in result.columns:
            result["volume_sma"] = result["volume"].rolling(20).mean()
            result["volume_ratio"] = result["volume"] / result["volume_sma"]

        # Volatility
        result["volatility"] = result["returns"].rolling(20).std() * np.sqrt(252)

        return result

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        self._cache_time.clear()
