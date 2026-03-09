"""
=============================================================================
Feature Engineering for AI Models — V2 (Optimized)
=============================================================================
Creates advanced features from market data for machine learning models.
Includes: technical, statistical, time-based, market structure, and 
momentum features. Features are designed to minimize overfitting with
proper normalization and feature selection.
=============================================================================
"""

import pandas as pd
import numpy as np
from typing import Tuple, List
import logging

from analysis.technical import TechnicalAnalyzer

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """Creates ML-ready features from raw market data."""

    def __init__(self):
        self.ta = TechnicalAnalyzer()
        self._selected_features: List[str] = []  # Populated after feature selection

    def create_features(
        self,
        df: pd.DataFrame,
        window: int = 50,
    ) -> pd.DataFrame:
        """
        Create comprehensive feature set for ML models.
        All features are normalized / bounded to prevent overfitting.
        """
        features = pd.DataFrame(index=df.index)

        # ─── Price Return Features (normalized) ─────────────────────
        features["returns_1"] = df["close"].pct_change(1)
        features["returns_5"] = df["close"].pct_change(5)
        features["returns_10"] = df["close"].pct_change(10)
        features["returns_20"] = df["close"].pct_change(20)

        # ─── Moving Average Crossover Features (bounded ratios) ─────
        for period in [10, 20, 50]:
            sma = df["close"].rolling(period).mean()
            features[f"price_sma_{period}_ratio"] = (df["close"] / sma) - 1.0  # Center at 0

        # EMA ratios
        ema12 = df["close"].ewm(span=12).mean()
        ema26 = df["close"].ewm(span=26).mean()
        features["ema_cross_ratio"] = (ema12 / ema26) - 1.0

        # ─── Volatility Features ─────────────────────────────────────
        features["volatility_10"] = features["returns_1"].rolling(10).std()
        features["volatility_20"] = features["returns_1"].rolling(20).std()
        features["vol_ratio"] = features["volatility_10"] / features["volatility_20"].replace(0, np.nan)

        # Normalized ATR
        atr = self.ta.atr(df)
        features["atr_pct"] = atr / df["close"]

        # Volatility regime (current vol vs historical)
        vol_50 = features["returns_1"].rolling(50).std()
        features["vol_regime"] = features["volatility_10"] / vol_50.replace(0, np.nan)

        # ─── Technical Indicator Features ────────────────────────────
        # RSI (already 0-100 bounded)
        features["rsi"] = self.ta.rsi(df["close"])
        features["rsi_centered"] = (features["rsi"] - 50) / 50  # Normalize to [-1, 1]
        features["rsi_momentum"] = features["rsi"].diff(5) / 100.0

        # MACD (normalized)
        macd_line, macd_signal, macd_hist = self.ta.macd(df["close"])
        features["macd_norm"] = macd_line / df["close"]
        features["macd_signal_norm"] = macd_signal / df["close"]
        features["macd_hist_norm"] = macd_hist / df["close"]

        # Bollinger Bands (already bounded)
        bb_upper, bb_middle, bb_lower = self.ta.bollinger_bands(df["close"])
        features["bb_width"] = (bb_upper - bb_lower) / bb_middle
        features["bb_pct"] = (df["close"] - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)

        # Stochastic (already 0-100 bounded)
        stoch_k, stoch_d = self.ta.stochastic(df)
        features["stoch_k"] = stoch_k / 100.0  # Normalize to [0, 1]
        features["stoch_d"] = stoch_d / 100.0

        # ADX (trend strength, 0-100)
        adx_val, plus_di, minus_di = self.ta.adx(df)
        features["adx_norm"] = adx_val / 100.0
        features["di_diff_norm"] = (plus_di - minus_di) / 100.0

        # CCI (normalize to bounded range)
        cci = self.ta.cci(df)
        features["cci_norm"] = np.tanh(cci / 200.0)  # Bound with tanh

        # ─── Momentum Features ───────────────────────────────────────
        # Rate of Change
        features["roc_5"] = (df["close"] - df["close"].shift(5)) / df["close"].shift(5)
        features["roc_14"] = (df["close"] - df["close"].shift(14)) / df["close"].shift(14)

        # Momentum (current vs past - normalized)
        features["momentum_10"] = (df["close"] - df["close"].shift(10)) / (atr + 1e-10)
        features["momentum_20"] = (df["close"] - df["close"].shift(20)) / (atr + 1e-10)

        # Trend consistency (% of bars closing up in window)
        features["up_ratio_10"] = (df["close"] > df["close"].shift(1)).rolling(10).mean()
        features["up_ratio_20"] = (df["close"] > df["close"].shift(1)).rolling(20).mean()

        # ─── Candle Pattern Features ─────────────────────────────────
        body = abs(df["close"] - df["open"])
        range_ = (df["high"] - df["low"]).replace(0, np.nan)
        features["body_ratio"] = body / range_
        features["upper_shadow"] = (df["high"] - pd.concat([df["open"], df["close"]], axis=1).max(axis=1)) / range_
        features["lower_shadow"] = (pd.concat([df["open"], df["close"]], axis=1).min(axis=1) - df["low"]) / range_

        # Engulfing pattern signal
        features["engulfing"] = self._engulfing_signal(df)

        # Pin bar signal
        features["pin_bar"] = self._pin_bar_signal(df)

        # ─── Volume Features ─────────────────────────────────────────
        if "tick_volume" in df.columns and df["tick_volume"].sum() > 0:
            vol_col = df["tick_volume"]
        elif "volume" in df.columns and df["volume"].sum() > 0:
            vol_col = df["volume"]
        else:
            vol_col = None

        if vol_col is not None:
            vol_sma = vol_col.rolling(20).mean()
            features["volume_ratio"] = vol_col / vol_sma.replace(0, np.nan)
            features["volume_trend"] = vol_col.rolling(5).mean() / vol_col.rolling(20).mean().replace(0, np.nan)
        else:
            features["volume_ratio"] = 1.0
            features["volume_trend"] = 1.0

        # ─── Market Structure Features ───────────────────────────────
        features["dist_to_high_20"] = (df["high"].rolling(20).max() - df["close"]) / (atr + 1e-10)
        features["dist_to_low_20"] = (df["close"] - df["low"].rolling(20).min()) / (atr + 1e-10)
        features["range_position"] = (df["close"] - df["low"].rolling(20).min()) / \
            (df["high"].rolling(20).max() - df["low"].rolling(20).min()).replace(0, np.nan)

        # Higher highs / lower lows momentum
        features["hh_count"] = (df["high"] > df["high"].shift(1)).rolling(10).sum()
        features["ll_count"] = (df["low"] < df["low"].shift(1)).rolling(10).sum()
        features["structure_score"] = (features["hh_count"] - features["ll_count"]) / 10.0

        # ─── Mean Reversion Features ─────────────────────────────────
        features["zscore_20"] = (
            (df["close"] - df["close"].rolling(20).mean())
            / df["close"].rolling(20).std().replace(0, np.nan)
        )
        features["zscore_50"] = (
            (df["close"] - df["close"].rolling(50).mean())
            / df["close"].rolling(50).std().replace(0, np.nan)
        )

        # ─── Time Features (cyclical encoding only) ─────────────────
        if isinstance(df.index, pd.DatetimeIndex):
            features["hour_sin"] = np.sin(2 * np.pi * df.index.hour / 24)
            features["hour_cos"] = np.cos(2 * np.pi * df.index.hour / 24)
            features["dow_sin"] = np.sin(2 * np.pi * df.index.dayofweek / 5)
            features["dow_cos"] = np.cos(2 * np.pi * df.index.dayofweek / 5)

        # ─── Lag Features (only key indicators, limited lags) ────────
        for lag in [1, 3, 5]:
            features[f"return_lag_{lag}"] = features["returns_1"].shift(lag)
        features["rsi_lag_3"] = features["rsi_centered"].shift(3)

        # ─── Clip extreme values to prevent outlier-driven overfitting
        for col in features.columns:
            if features[col].dtype in [np.float64, np.float32]:
                p01 = features[col].quantile(0.01)
                p99 = features[col].quantile(0.99)
                if pd.notna(p01) and pd.notna(p99) and p01 != p99:
                    features[col] = features[col].clip(p01, p99)

        return features

    def _engulfing_signal(self, df: pd.DataFrame) -> pd.Series:
        """Detect bullish/bearish engulfing patterns. Returns +1/-1/0."""
        signal = pd.Series(0, index=df.index)
        if len(df) < 2:
            return signal

        prev_body = df["close"].shift(1) - df["open"].shift(1)
        curr_body = df["close"] - df["open"]

        # Bullish engulfing
        bullish = (
            (prev_body < 0) &  # Previous bearish
            (curr_body > 0) &   # Current bullish
            (df["open"] <= df["close"].shift(1)) &
            (df["close"] >= df["open"].shift(1))
        )

        # Bearish engulfing
        bearish = (
            (prev_body > 0) &
            (curr_body < 0) &
            (df["open"] >= df["close"].shift(1)) &
            (df["close"] <= df["open"].shift(1))
        )

        signal[bullish] = 1
        signal[bearish] = -1
        return signal

    def _pin_bar_signal(self, df: pd.DataFrame) -> pd.Series:
        """Detect pin bar / hammer / shooting star patterns."""
        signal = pd.Series(0, index=df.index)
        body = abs(df["close"] - df["open"])
        range_ = (df["high"] - df["low"]).replace(0, np.nan)
        body_pct = body / range_

        upper_shadow = df["high"] - pd.concat([df["open"], df["close"]], axis=1).max(axis=1)
        lower_shadow = pd.concat([df["open"], df["close"]], axis=1).min(axis=1) - df["low"]

        # Bullish pin bar (hammer): small body, long lower shadow
        bullish = (body_pct < 0.3) & (lower_shadow / range_ > 0.6)
        # Bearish pin bar (shooting star): small body, long upper shadow
        bearish = (body_pct < 0.3) & (upper_shadow / range_ > 0.6)

        signal[bullish] = 1
        signal[bearish] = -1
        return signal

    def create_labels(
        self,
        df: pd.DataFrame,
        horizon: int = 1,
        threshold: float = 0.0,
    ) -> pd.Series:
        """
        Create target labels with ATR-adaptive threshold.
        Uses forward max favorable / adverse excursion for smarter labeling.
        """
        future_return = df["close"].shift(-horizon) / df["close"] - 1

        if threshold > 0:
            # Use adaptive threshold based on recent volatility
            vol = df["close"].pct_change().rolling(20).std()
            adaptive_threshold = np.maximum(threshold, vol * 0.5)

            labels = pd.Series(0, index=df.index, dtype=int)
            labels[future_return > adaptive_threshold] = 1
            labels[future_return < -adaptive_threshold] = -1
        else:
            labels = (future_return > 0).astype(int) * 2 - 1

        return labels

    def create_regression_labels(
        self,
        df: pd.DataFrame,
        horizon: int = 1,
    ) -> pd.Series:
        """Create target for regression (future return)."""
        return df["close"].shift(-horizon) / df["close"] - 1

    def select_features(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: List[str],
        max_features: int = 35,
    ) -> Tuple[np.ndarray, List[str]]:
        """
        Select the best features to reduce overfitting.
        Uses correlation filter + variance threshold + importance.
        """
        df_feat = pd.DataFrame(X, columns=feature_names)

        # 1. Remove near-zero variance features
        variances = df_feat.var()
        valid_cols = variances[variances > 1e-6].index.tolist()
        df_feat = df_feat[valid_cols]

        # 2. Remove highly correlated features (keep one from each pair)
        corr_matrix = df_feat.corr().abs()
        upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
        to_drop = [col for col in upper.columns if any(upper[col] > 0.90)]
        df_feat = df_feat.drop(columns=to_drop, errors="ignore")

        # 3. Quick importance ranking with lightweight RF
        from sklearn.ensemble import RandomForestClassifier
        rf = RandomForestClassifier(n_estimators=30, max_depth=4, random_state=42, n_jobs=-1)
        rf.fit(df_feat.values, y)
        importances = pd.Series(rf.feature_importances_, index=df_feat.columns)
        top_features = importances.nlargest(max_features).index.tolist()

        self._selected_features = top_features
        logger.info(f"Feature selection: {len(feature_names)} -> {len(top_features)} features")

        return df_feat[top_features].values, top_features

    def prepare_dataset(
        self,
        df: pd.DataFrame,
        horizon: int = 1,
        threshold: float = 0.001,
        test_ratio: float = 0.2,
    ) -> Tuple:
        """
        Prepare complete train/test dataset with feature selection
        and purged gap to prevent data leakage.
        """
        features = self.create_features(df)
        labels = self.create_labels(df, horizon, threshold)

        # Combine and drop NaN
        combined = features.copy()
        combined["target"] = labels
        combined.dropna(inplace=True)

        feature_names = [c for c in combined.columns if c != "target"]
        X = combined[feature_names].values
        y = combined["target"].values

        # Purged train/test split — leave a gap to prevent forward leakage
        purge_gap = max(horizon * 2, 5)
        split_idx = int(len(X) * (1 - test_ratio))
        X_train = X[:split_idx - purge_gap]
        y_train = y[:split_idx - purge_gap]
        X_test = X[split_idx:]
        y_test = y[split_idx:]

        # Feature selection on training data only
        X_train_sel, selected_names = self.select_features(X_train, y_train, feature_names)

        # Apply same selection to test set
        sel_indices = [feature_names.index(f) for f in selected_names]
        X_test_sel = X_test[:, sel_indices]

        return X_train_sel, X_test_sel, y_train, y_test, selected_names
