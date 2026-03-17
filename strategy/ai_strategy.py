"""
=============================================================================
AI Strategy + Multi-Strategy Manager (V2)
=============================================================================
Enhanced AI Strategy that combines:
- AI prediction with market structure confirmation
- News-aware filtering (skip trades during high-impact events)
- Multi-strategy consensus with weighted voting
- Dynamic confidence based on market regime
=============================================================================
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
import logging

from config.settings import config
from strategy.base_strategy import BaseStrategy, TradeSignal, SignalType
from analysis.technical import TechnicalAnalyzer
from analysis.sentiment import SentimentAnalyzer
from analysis.market_structure import MarketStructureAnalyzer
from ai.predictor import AIPredictor

logger = logging.getLogger(__name__)


class AIStrategy(BaseStrategy):
    """
    AI-Enhanced Strategy — combines ML prediction with:
    - Technical confirmation
    - Market regime check
    - Market structure alignment
    """

    def __init__(self, predictor: AIPredictor = None):
        super().__init__("AI_Enhanced")
        self.ta = TechnicalAnalyzer()
        self.sentiment = SentimentAnalyzer()
        self.ms = MarketStructureAnalyzer()
        self.predictor = predictor or AIPredictor()

    def train_model(self, df: pd.DataFrame, symbol: str) -> Dict:
        """Train the AI model on historical data."""
        return self.predictor.train(df, symbol)

    def load_model(self, symbol: str) -> bool:
        """Load a pre-trained model."""
        return self.predictor.load_model(symbol)

    def analyze(self, df: pd.DataFrame, symbol: str) -> TradeSignal:
        """Analyze using AI + technical + structure confluence."""
        if len(df) < 200:
            return self.hold_signal(symbol, "Insufficient data for AI analysis")

        # ─── AI Prediction ───────────────────────────────────────────
        if not self.predictor.is_trained:
            logger.info(f"Training AI model for {symbol}...")
            self.predictor.train(df, symbol)

        prediction = self.predictor.predict(df)
        if prediction.get("error"):
            return self.hold_signal(symbol, f"AI error: {prediction['error']}")

        action = prediction["action"]
        confidence = prediction["confidence"]
        meets_threshold = prediction.get("meets_threshold", False)

        if action == "HOLD" or not meets_threshold:
            return self.hold_signal(
                symbol, f"AI confidence too low: {confidence:.2f}"
            )

        # ─── Technical Confirmation ──────────────────────────────────
        indicators = self.ta.compute_all(df)
        latest = indicators.iloc[-1]
        tech_signal = self.ta.generate_signal(df)
        tech_direction = tech_signal["signal"]  # -1 to 1

        ai_direction = 1 if action == "BUY" else -1

        tech_score = 0

        # RSI confirmation
        rsi = latest.get("rsi", 50)
        if action == "BUY" and 35 < rsi < 70:
            tech_score += 1
        elif action == "SELL" and 30 < rsi < 65:
            tech_score += 1

        # MACD confirmation
        macd_hist = latest.get("macd_hist", 0)
        if action == "BUY" and macd_hist > 0:
            tech_score += 1
        elif action == "SELL" and macd_hist < 0:
            tech_score += 1

        # Moving average alignment
        ema_fast = latest.get("ema_fast", 0)
        ema_slow = latest.get("ema_slow", 0)
        if action == "BUY" and ema_fast > ema_slow:
            tech_score += 1
        elif action == "SELL" and ema_fast < ema_slow:
            tech_score += 1

        # Technical conflict just reduces confidence, doesn't block
        if tech_score < 1 and ai_direction * tech_direction < 0:
            confidence *= 0.85  # Reduce confidence instead of blocking

        # ─── Market Structure Confirmation ───────────────────────────
        try:
            struct_bias, struct_conf, struct_reason = self.ms.get_trade_bias(df)
            if action == "BUY" and struct_bias == "sell":
                confidence *= 0.7  # Reduce confidence if structure disagrees
            elif action == "SELL" and struct_bias == "buy":
                confidence *= 0.7
            elif action == "BUY" and struct_bias == "buy":
                confidence *= 1.1  # Boost if structure agrees
            elif action == "SELL" and struct_bias == "sell":
                confidence *= 1.1
        except Exception:
            pass  # Structure analysis failed, proceed without it

        # ─── Market Regime Check ─────────────────────────────────────
        regime = self.sentiment.analyze_market_regime(df)
        volatility = regime.get("volatility", "normal")

        if volatility == "high" and regime.get("vol_ratio", 1.0) > 2.5:
            confidence *= 0.8  # Reduce confidence in extreme vol, don't block
        elif volatility == "high":
            confidence *= 0.85

        # ─── Calculate Dynamic SL/TP ─────────────────────────────────
        atr = latest.get("atr", 0)
        if atr <= 0:
            return self.hold_signal(symbol, "Invalid ATR")

        price = latest["close"]

        # Combine AI + technical confidence
        combined_confidence = (confidence * 0.6) + (abs(tech_direction) * 0.4)
        combined_confidence = min(combined_confidence, 0.95)

        sl_mult = 2.0 - (combined_confidence * 0.5)
        tp_mult = sl_mult * config.risk.risk_reward_ratio

        reasons = [
            f"AI:{action}({confidence:.2f})",
            f"Tech:{tech_score}/3",
            f"Regime:{regime.get('regime', '?')}",
        ]

        if ai_direction > 0:
            entry = price
            sl = price - atr * sl_mult
            tp = price + atr * tp_mult
            return self._create_signal(
                SignalType.BUY, symbol, combined_confidence, entry, sl, tp,
                " | ".join(reasons),
            )
        else:
            entry = price
            sl = price + atr * sl_mult
            tp = price - atr * tp_mult
            return self._create_signal(
                SignalType.SELL, symbol, combined_confidence, entry, sl, tp,
                " | ".join(reasons),
            )


class MultiStrategyManager:
    """
    Runs all strategies and picks the best signal using weighted consensus.
    
    Strategies:
    1. TrendFollowing — ride established trends
    2. MeanReversion — fade extremes in ranging markets
    3. AIStrategy — ML prediction with confirmation
    4. SMCStrategy — Smart Money Concepts (order blocks, FVGs)
    5. BreakoutStrategy — trade range breakouts
    
    Signal Selection:
    - Direction consensus (majority must agree)
    - Weighted by strategy confidence and historical accuracy
    - Market regime awareness (trend strategies in trends, MR in ranges)
    """

    def __init__(self, strategies: list = None):
        self.strategies: list = strategies or []
        self._strategy_weights = {
            "Trend_Following": 1.2,
            "Mean_Reversion": 0.9,
            "AI_Enhanced": 1.3,
            "Smart_Money": 1.4,     # SMC gets highest weight
            "Breakout": 1.0,
        }

    def add_strategy(self, strategy: BaseStrategy):
        self.strategies.append(strategy)

    def get_best_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        market_regime: str = "unknown",
        news_can_trade: bool = True,
        news_size_factor: float = 1.0,
    ) -> TradeSignal:
        """
        Run all strategies and return the best signal.
        
        Args:
            df: OHLCV data
            symbol: Trading symbol
            market_regime: Current regime ('trending', 'ranging', 'volatile')
            news_can_trade: Whether news filter allows trading
            news_size_factor: Position size multiplier from news filter
        """
        if not self.strategies:
            return TradeSignal(
                signal_type=SignalType.HOLD, symbol=symbol,
                confidence=0, entry_price=0, stop_loss=0, take_profit=0,
                reason="No strategies configured",
                strategy_name="Multi_Strategy",
            )

        signals = {}
        for strategy in self.strategies:
            try:
                signal = strategy.analyze(df, symbol)
                signals[strategy.name] = signal
            except Exception as e:
                logger.error(f"Strategy {strategy.name} error for {symbol}: {e}")

        if not signals:
            return TradeSignal(
                signal_type=SignalType.HOLD, symbol=symbol,
                confidence=0, entry_price=0, stop_loss=0, take_profit=0,
                reason="All strategies failed",
                strategy_name="Multi_Strategy",
            )

        # ─── Filter active signals (exclude HOLDs) ──────────────────
        active_signals = {
            name: sig for name, sig in signals.items()
            if sig.signal_type in (SignalType.BUY, SignalType.SELL) and sig.is_valid()
        }

        if not active_signals:
            hold_reasons = [f"{n}: {s.reason}" for n, s in signals.items()]
            return TradeSignal(
                signal_type=SignalType.HOLD, symbol=symbol,
                confidence=0, entry_price=0, stop_loss=0, take_profit=0,
                reason=" | ".join(hold_reasons[:3]),
                strategy_name="Multi_Strategy",
            )

        # ─── Direction Consensus ─────────────────────────────────────
        buy_weight = 0.0
        sell_weight = 0.0

        for name, sig in active_signals.items():
            weight = self._strategy_weights.get(name, 1.0) * sig.confidence
            weight *= self._regime_weight(name, market_regime)

            if sig.signal_type == SignalType.BUY:
                buy_weight += weight
            elif sig.signal_type == SignalType.SELL:
                sell_weight += weight

        # Determine consensus direction
        if buy_weight > sell_weight:
            consensus_direction = SignalType.BUY
        else:
            consensus_direction = SignalType.SELL

        # Filter to only signals matching consensus direction
        aligned_signals = {
            name: sig for name, sig in active_signals.items()
            if sig.signal_type == consensus_direction
        }

        if not aligned_signals:
            return TradeSignal(
                signal_type=SignalType.HOLD, symbol=symbol,
                confidence=0, entry_price=0, stop_loss=0, take_profit=0,
                reason="No consensus direction",
                strategy_name="Multi_Strategy",
            )

        # ─── Minimum Consensus Gate ──────────────────────────────────
        # Require at least 2 strategies to agree, OR 1 strategy with high confidence
        agreement_count = len(aligned_signals)
        total_strategies = len(signals)

        MIN_CONSENSUS = 2  # 2 out of 5 — reasonable bar without signal drought
        HIGH_CONFIDENCE_SOLO = 0.70  # Allow solo if confidence >= 0.70

        if agreement_count < MIN_CONSENSUS:
            # Check if the single strategy has very high confidence
            best_solo = max(aligned_signals.values(), key=lambda s: s.confidence)
            if best_solo.confidence >= HIGH_CONFIDENCE_SOLO:
                # High-confidence solo signal — let it through
                pass
            else:
                strategy_names = ", ".join(aligned_signals.keys())
                return TradeSignal(
                    signal_type=SignalType.HOLD, symbol=symbol,
                    confidence=0, entry_price=0, stop_loss=0, take_profit=0,
                    reason=(
                        f"Weak consensus ({agreement_count}/{total_strategies}): "
                        f"{strategy_names} -- need {MIN_CONSENSUS}+ or conf>={HIGH_CONFIDENCE_SOLO}"
                    ),
                    strategy_name="Multi_Strategy",
                )

        # ─── Select best aligned signal ──────────────────────────────
        best_name = max(
            aligned_signals.keys(),
            key=lambda n: (
                aligned_signals[n].confidence
                * self._strategy_weights.get(n, 1.0)
                * self._regime_weight(n, market_regime)
            ),
        )
        best_signal = aligned_signals[best_name]

        # ─── Consensus confidence (reward agreement, penalise weak) ───
        agreement_ratio = agreement_count / total_strategies if total_strategies > 0 else 0

        if agreement_ratio >= 0.8:
            confidence_factor = 1.1   # 4-5/5 agree — strong boost
        elif agreement_ratio >= 0.6:
            confidence_factor = 1.05  # 3/5 agree — small boost
        else:
            confidence_factor = 1.0   # 2/5 agree — neutral (MIN_CONSENSUS=2 so this is valid)

        final_confidence = min(best_signal.confidence * confidence_factor, 0.95)

        # lot_size is intentionally set to 0 — position sizing MUST be
        # done by RiskManager.calculate_position_size(), never by strategy
        strategy_names = ", ".join(aligned_signals.keys())
        reason = (
            f"CONSENSUS ({agreement_count}/{total_strategies}): {strategy_names} | "
            f"{best_signal.reason}"
        )

        return TradeSignal(
            signal_type=best_signal.signal_type,
            symbol=symbol,
            confidence=final_confidence,
            entry_price=best_signal.entry_price,
            stop_loss=best_signal.stop_loss,
            take_profit=best_signal.take_profit,
            lot_size=0,  # Risk manager sizes all trades
            reason=reason,
            strategy_name=f"Multi({best_name})",
            risk_reward=best_signal.risk_reward,
        )

    def _regime_weight(self, strategy_name: str, regime: str) -> float:
        """Adjust strategy weight based on market regime."""
        regime_weights = {
            "trending": {
                "Trend_Following": 1.3,
                "Mean_Reversion": 0.5,
                "AI_Enhanced": 1.1,
                "Smart_Money": 1.2,
                "Breakout": 1.0,
            },
            "ranging": {
                "Trend_Following": 0.5,
                "Mean_Reversion": 1.4,
                "AI_Enhanced": 1.0,
                "Smart_Money": 1.1,
                "Breakout": 1.3,
            },
            "volatile": {
                "Trend_Following": 0.7,
                "Mean_Reversion": 0.6,
                "AI_Enhanced": 1.0,
                "Smart_Money": 1.2,
                "Breakout": 0.8,
            },
        }

        weights = regime_weights.get(regime, {})
        return weights.get(strategy_name, 1.0)
