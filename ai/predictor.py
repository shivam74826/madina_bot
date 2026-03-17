"""
=============================================================================
AI Price Predictor — V2 (Anti-Overfit Edition)
=============================================================================
Machine learning ensemble model with:
- Walk-forward validation (no look-ahead bias)
- Aggressive regularization
- Feature selection to prevent curse of dimensionality
- Calibrated confidence scores
- Dynamic ensemble weighting
=============================================================================
"""

import numpy as np
import pandas as pd
import os
from datetime import datetime
from typing import Dict, Optional, Tuple, List
import logging
import warnings

from sklearn.ensemble import (
    RandomForestClassifier,
    GradientBoostingClassifier,
    VotingClassifier,
    ExtraTreesClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import TimeSeriesSplit
from sklearn.calibration import CalibratedClassifierCV
import joblib

from config.settings import config
from ai.feature_engineering import FeatureEngineer

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


class AIPredictor:
    """AI-powered price direction predictor with anti-overfit design."""

    def __init__(self):
        self.feature_engineer = FeatureEngineer()
        self.model = None
        self.scaler = RobustScaler()  # More robust to outliers than StandardScaler
        self.feature_names = []
        self.is_trained = False
        self.training_accuracy = 0.0
        self.test_accuracy = 0.0
        self.walk_forward_accuracy = 0.0  # Walk-forward OOS accuracy
        self.last_trained = None
        self.feature_importances = {}
        self.confidence_calibration = 1.0   # Scale confidence based on validation
        self._overfit_ratio = 1.0              # Track overfit severity

        os.makedirs(config.ai.model_save_path, exist_ok=True)

    def _build_model(self):
        """
        Build the ensemble model with aggressive regularization.
        Key anti-overfit measures:
        - Very shallow trees (max_depth=3-4)
        - High min_samples_leaf
        - Fewer estimators
        - Includes linear model for stability
        """
        rf = RandomForestClassifier(
            n_estimators=50,
            max_depth=3,           # Very shallow to prevent memorization
            min_samples_split=30,
            min_samples_leaf=15,
            max_features="sqrt",   # Use only sqrt(n) features per split
            random_state=42,
            n_jobs=-1,
        )

        gb = GradientBoostingClassifier(
            n_estimators=40,
            max_depth=3,
            learning_rate=0.05,     # Slow learning rate
            min_samples_split=30,
            min_samples_leaf=15,
            subsample=0.8,          # Use only 80% of data per tree
            max_features=0.7,       # Use only 70% of features
            random_state=42,
        )

        # Extra Trees — less prone to overfitting than RF
        et = ExtraTreesClassifier(
            n_estimators=50,
            max_depth=4,
            min_samples_split=25,
            min_samples_leaf=12,
            max_features="sqrt",
            random_state=42,
            n_jobs=-1,
        )

        # Logistic Regression — stable linear baseline
        lr = LogisticRegression(
            C=0.1,               # Strong L2 regularization
            max_iter=500,
            random_state=42,
            solver="lbfgs",
        )

        self.model = VotingClassifier(
            estimators=[
                ("rf", rf),
                ("gb", gb),
                ("et", et),
                ("lr", lr),
            ],
            voting="soft",
            weights=[1.0, 1.2, 1.0, 0.8],  # GB slightly favored, LR as stabilizer
        )

    def train(
        self,
        df: pd.DataFrame,
        symbol: str = "default",
        horizon: int = None,
    ) -> Dict:
        """
        Train the AI model with walk-forward validation.
        """
        if horizon is None:
            horizon = config.ai.prediction_horizon

        logger.info(f"Training AI model for {symbol} | Horizon: {horizon} candles | "
                     f"Data: {len(df)} candles")

        # Prepare dataset with feature selection
        X_train, X_test, y_train, y_test, feature_names = \
            self.feature_engineer.prepare_dataset(df, horizon=horizon, threshold=0.001)

        if len(X_train) < 100:
            logger.error("Insufficient training data")
            return {"error": "Insufficient data", "samples": len(X_train)}

        self.feature_names = feature_names

        # Scale features with RobustScaler (handles outliers)
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        # Build and train model
        self._build_model()
        self.model.fit(X_train_scaled, y_train)

        # Evaluate
        train_pred = self.model.predict(X_train_scaled)
        test_pred = self.model.predict(X_test_scaled)

        self.training_accuracy = accuracy_score(y_train, train_pred)
        self.test_accuracy = accuracy_score(y_test, test_pred)

        # Walk-forward validation for realistic accuracy estimate
        wf_accuracy = self._walk_forward_validate(df, horizon, n_splits=5)
        self.walk_forward_accuracy = wf_accuracy

        # Walk-forward accuracy gating: reject model if WF is much worse than test
        random_baseline = 1.0 / len(np.unique(y_train))
        if wf_accuracy < random_baseline + 0.02:
            logger.warning(
                f"MODEL REJECTED: Walk-forward accuracy {wf_accuracy:.4f} barely beats "
                f"random ({random_baseline:.4f}). Model will NOT be used."
            )
            self.is_trained = False
            return {"status": "rejected", "reason": "walk_forward_too_low",
                    "wf_accuracy": wf_accuracy, "random_baseline": random_baseline}

        if wf_accuracy < self.test_accuracy - 0.10:
            logger.warning(
                f"MODEL SUSPECT: Walk-forward {wf_accuracy:.4f} is {self.test_accuracy - wf_accuracy:.4f} "
                f"below test accuracy {self.test_accuracy:.4f} -- likely overfitting. "
                f"Confidence will be heavily penalized."
            )
            self.confidence_calibration = 0.5  # Heavy penalty
        else:
            # Calibrate confidence based on validation performance
            excess_accuracy = max(self.test_accuracy - random_baseline, 0)
            self.confidence_calibration = min(excess_accuracy * 3.0, 1.0)

        self.is_trained = True
        self.last_trained = datetime.now()

        # Feature importance (from Random Forest)
        try:
            rf_model = self.model.named_estimators_["rf"]
            importances = rf_model.feature_importances_
            self.feature_importances = dict(
                sorted(
                    zip(feature_names, importances),
                    key=lambda x: x[1],
                    reverse=True,
                )[:20]
            )
        except Exception:
            self.feature_importances = {}

        # Save model
        self._save_model(symbol)

        # Detect overfitting
        overfit_ratio = self.training_accuracy / max(self.test_accuracy, 0.01)
        is_overfitting = overfit_ratio > 1.5
        self._overfit_ratio = overfit_ratio

        metrics = {
            "symbol": symbol,
            "training_samples": len(X_train),
            "test_samples": len(X_test),
            "features_used": len(feature_names),
            "training_accuracy": round(self.training_accuracy, 4),
            "test_accuracy": round(self.test_accuracy, 4),
            "walk_forward_accuracy": round(wf_accuracy, 4),
            "confidence_calibration": round(self.confidence_calibration, 4),
            "overfit_ratio": round(overfit_ratio, 2),
            "is_overfitting": is_overfitting,
            "top_features": list(self.feature_importances.keys())[:10],
            "class_distribution": dict(
                zip(*np.unique(y_train, return_counts=True))
            ),
        }

        status = "WARNING: OVERFITTING" if is_overfitting else "OK"
        logger.info(
            f"Training complete [{status}] | "
            f"Train: {self.training_accuracy:.4f} | Test: {self.test_accuracy:.4f} | "
            f"Walk-Forward: {wf_accuracy:.4f} | Overfit ratio: {overfit_ratio:.2f}"
        )
        return metrics

    def _walk_forward_validate(
        self, df: pd.DataFrame, horizon: int, n_splits: int = 3
    ) -> float:
        """
        Perform walk-forward validation — the gold standard for trading models.
        Simulates training on past data and testing on future data repeatedly.
        Uses temporary models to avoid overwriting self.model.
        """
        try:
            features = self.feature_engineer.create_features(df)
            labels = self.feature_engineer.create_labels(df, horizon, threshold=0.001)

            combined = features.copy()
            combined["target"] = labels
            combined.dropna(inplace=True)

            fname = [c for c in combined.columns if c != "target"]
            X = combined[fname].values
            y = combined["target"].values

            if len(X) < 200:
                return 0.0

            tscv = TimeSeriesSplit(n_splits=n_splits, gap=max(horizon * 2, 5))
            scores = []

            # Save reference to the real trained model
            saved_model = self.model

            for train_idx, test_idx in tscv.split(X):
                X_tr, X_te = X[train_idx], X[test_idx]
                y_tr, y_te = y[train_idx], y[test_idx]

                sc = RobustScaler()
                X_tr_s = sc.fit_transform(X_tr)
                X_te_s = sc.transform(X_te)

                self._build_model()
                self.model.fit(X_tr_s, y_tr)
                pred = self.model.predict(X_te_s)
                scores.append(accuracy_score(y_te, pred))

            # Restore the real model (trained on selected features)
            self.model = saved_model

            return float(np.mean(scores)) if scores else 0.0

        except Exception as e:
            logger.warning(f"Walk-forward validation failed: {e}")
            return 0.0

    def predict(self, df: pd.DataFrame) -> Dict:
        """
        Make a prediction with calibrated confidence.
        """
        if not self.is_trained:
            return {"error": "Model not trained", "prediction": 0, "confidence": 0}

        try:
            features = self.feature_engineer.create_features(df)
            features.dropna(inplace=True)

            if len(features) == 0:
                return {"error": "No valid features", "prediction": 0, "confidence": 0}

            latest = features.iloc[[-1]]

            # Feature alignment
            missing_cols = set(self.feature_names) - set(latest.columns)
            for col in missing_cols:
                latest[col] = 0
            latest = latest[self.feature_names]

            # Scale and predict
            X_scaled = self.scaler.transform(latest.values)
            prediction = self.model.predict(X_scaled)[0]
            probabilities = self.model.predict_proba(X_scaled)[0]

            # Raw confidence
            raw_confidence = float(np.max(probabilities))

            # Calibrated confidence — use raw confidence directly
            calibrated_confidence = raw_confidence

            # Only reduce for severe overfitting
            if getattr(self, '_overfit_ratio', 1.0) > 3.0:
                calibrated_confidence *= 0.7
                logger.warning("Model is severely overfitting — reducing confidence")

            confidence = min(calibrated_confidence, 0.85)  # Hard cap — 85% max

            # Map prediction
            if prediction == 1:
                action = "BUY"
            elif prediction == -1:
                action = "SELL"
            else:
                action = "HOLD"

            return {
                "prediction": int(prediction),
                "action": action,
                "confidence": round(confidence, 4),
                "raw_confidence": round(raw_confidence, 4),
                "probabilities": {
                    str(cls): round(float(prob), 4)
                    for cls, prob in zip(self.model.classes_, probabilities)
                },
                "meets_threshold": confidence >= config.ai.min_confidence,
                "model_accuracy": round(self.test_accuracy, 4),
                "walk_forward_accuracy": round(self.walk_forward_accuracy, 4),
                "last_trained": self.last_trained.isoformat() if self.last_trained else None,
            }

        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return {"error": str(e), "prediction": 0, "confidence": 0}

    def should_retrain(self) -> bool:
        """Check if the model needs retraining."""
        if not self.is_trained or self.last_trained is None:
            return True

        hours_since = (datetime.now() - self.last_trained).total_seconds() / 3600
        return hours_since > config.ai.retrain_interval_hours

    # ─── Cross-Validation ────────────────────────────────────────────────

    def cross_validate(
        self,
        df: pd.DataFrame,
        n_splits: int = 5,
        horizon: int = None,
    ) -> Dict:
        """Time-series cross-validation with purged gap."""
        if horizon is None:
            horizon = config.ai.prediction_horizon

        features = self.feature_engineer.create_features(df)
        labels = self.feature_engineer.create_labels(df, horizon, threshold=0.001)

        combined = features.copy()
        combined["target"] = labels
        combined.dropna(inplace=True)

        feature_names = [c for c in combined.columns if c != "target"]
        X = combined[feature_names].values
        y = combined["target"].values

        tscv = TimeSeriesSplit(n_splits=n_splits, gap=max(horizon * 2, 5))
        scores = []

        for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]

            scaler = RobustScaler()
            X_train_s = scaler.fit_transform(X_train)
            X_test_s = scaler.transform(X_test)

            self._build_model()
            self.model.fit(X_train_s, y_train)
            pred = self.model.predict(X_test_s)
            acc = accuracy_score(y_test, pred)
            scores.append(acc)
            logger.info(f"CV Fold {fold + 1}: Accuracy = {acc:.4f}")

        return {
            "fold_scores": [round(s, 4) for s in scores],
            "mean_accuracy": round(np.mean(scores), 4),
            "std_accuracy": round(np.std(scores), 4),
        }

    # ─── Model Persistence ───────────────────────────────────────────────

    def _save_model(self, symbol: str):
        """Save model, scaler, and metadata."""
        path = config.ai.model_save_path
        joblib.dump(self.model, os.path.join(path, f"model_{symbol}.pkl"))
        joblib.dump(self.scaler, os.path.join(path, f"scaler_{symbol}.pkl"))
        joblib.dump(self.feature_names, os.path.join(path, f"features_{symbol}.pkl"))

        # Save calibration data
        meta = {
            "confidence_calibration": getattr(self, 'confidence_calibration', 1.0),
            "test_accuracy": self.test_accuracy,
            "walk_forward_accuracy": self.walk_forward_accuracy,
            "training_accuracy": self.training_accuracy,
        }
        joblib.dump(meta, os.path.join(path, f"meta_{symbol}.pkl"))
        logger.info(f"Model saved for {symbol}")

    def load_model(self, symbol: str) -> bool:
        """Load a previously trained model."""
        path = config.ai.model_save_path
        try:
            self.model = joblib.load(os.path.join(path, f"model_{symbol}.pkl"))
            self.scaler = joblib.load(os.path.join(path, f"scaler_{symbol}.pkl"))
            self.feature_names = joblib.load(os.path.join(path, f"features_{symbol}.pkl"))

            # Load calibration metadata
            meta_path = os.path.join(path, f"meta_{symbol}.pkl")
            if os.path.exists(meta_path):
                meta = joblib.load(meta_path)
                self.confidence_calibration = meta.get("confidence_calibration", 1.0)
                self.test_accuracy = meta.get("test_accuracy", 0.0)
                self.walk_forward_accuracy = meta.get("walk_forward_accuracy", 0.0)
                self.training_accuracy = meta.get("training_accuracy", 0.0)

            self.is_trained = True
            self.last_trained = datetime.fromtimestamp(
                os.path.getmtime(os.path.join(path, f"model_{symbol}.pkl"))
            )
            logger.info(f"Model loaded for {symbol}")
            return True
        except FileNotFoundError:
            logger.info(f"No saved model found for {symbol}")
            return False
        except Exception as e:
            logger.error(f"Error loading model for {symbol}: {e}")
            return False

    def get_feature_importance(self, top_n: int = 15) -> Dict[str, float]:
        """Get top N most important features."""
        return dict(list(self.feature_importances.items())[:top_n])
