"""Diagnostic: trace why the bot sees HOLD every cycle."""
import sys, os
sys.path.insert(0, '.')

from core.mt5_lock import mt5_safe as mt5
mt5.initialize()

from config.settings import config
from core.data_fetcher import DataFetcher
from core.mt5_connector import MT5Connector
from core.order_manager import OrderManager
from strategy.ai_strategy import MultiStrategyManager
from ai.predictor import AIPredictor
from analysis.news_analyzer import NewsAnalyzer
from analysis.sentiment import SentimentAnalyzer
from ai.trade_journal import TradingJournal
from risk.risk_manager import RiskManager
from datetime import datetime as _dt

connector = MT5Connector()
connector.connect()

symbol = config.trading.symbols[0] if config.trading.symbols else 'XAUUSDm'
print(f"Symbol: {symbol}")

# 1. Trading hours
om = OrderManager(connector)
rm = RiskManager(connector, om)
rm.initialize()
hours_ok = rm._is_trading_hours(symbol)
u = _dt.utcnow()
print(f"1. Trading hours OK: {hours_ok}  (UTC {u:%H:%M %A})")
if not hours_ok:
    print("   BLOCKED: Outside trading hours")
    connector.disconnect()
    sys.exit()

# 2. Journal guards
journal = TradingJournal()
lessons = journal.get_lessons()
print(f"2. Journal lessons: {lessons}")
print(f"   Overtrading (0 trades): {journal.is_overtrading(0)}")
utc_hour = u.hour
print(f"   Bad hour ({utc_hour}): {journal.is_bad_hour(utc_hour)}")
print(f"   Avoid BUY: {journal.should_avoid_direction('BUY')}")
print(f"   Avoid SELL: {journal.should_avoid_direction('SELL')}")

# 3. News check
na = NewsAnalyzer()
can_trade, reason, size_factor = na.should_trade(symbol)
print(f"3. News: can_trade={can_trade}, reason={reason}, size={size_factor}")
if not can_trade:
    print("   BLOCKED: News filter")
    connector.disconnect()
    sys.exit()

# 4. Data fetch
fetcher = DataFetcher(connector)
df = fetcher.get_ohlcv(symbol, count=500)
n = len(df) if df is not None else 0
print(f"4. Data: {n} candles")
if df is None or n < 200:
    print("   BLOCKED: Not enough data")
    connector.disconnect()
    sys.exit()

# 5. Market regime
sa = SentimentAnalyzer()
regime_info = sa.analyze_market_regime(df)
regime = regime_info.get('regime', 'unknown')
print(f"5. Market regime: {regime} | details: {regime_info}")

# 6. Strategy signal
from strategy.trend_following import TrendFollowingStrategy
from strategy.mean_reversion import MeanReversionStrategy
from strategy.smc_strategy import SMCStrategy
from strategy.breakout_strategy import BreakoutStrategy
from strategy.ai_strategy import AIStrategy

predictor = AIPredictor()
try:
    predictor.load_model(symbol)
    print("6a. AI model loaded from file")
except Exception as e:
    print(f"6a. AI model load failed ({e}), training fresh...")
    predictor.train(fetcher.get_ohlcv(symbol, count=5000), symbol)

mgr = MultiStrategyManager()
mgr.add_strategy(TrendFollowingStrategy())
mgr.add_strategy(MeanReversionStrategy())
mgr.add_strategy(AIStrategy(predictor))
mgr.add_strategy(SMCStrategy())
mgr.add_strategy(BreakoutStrategy())
signal = mgr.get_best_signal(
    df, symbol,
    market_regime=regime,
    news_can_trade=True,
    news_size_factor=size_factor,
)
print(f"6b. FINAL Signal: {signal.signal_type.value} | Confidence: {signal.confidence:.3f} | Strategy: {signal.strategy_name}")
print(f"    Reason: {signal.reason}")

# 7. Show individual strategy results regardless
from strategy.trend_following import TrendFollowingStrategy
from strategy.mean_reversion import MeanReversionStrategy
from strategy.smc_strategy import SMCStrategy
from strategy.breakout_strategy import BreakoutStrategy
from strategy.ai_strategy import AIStrategy as AIEnhancedStrategy

strategies = [
    ('TrendFollowing', TrendFollowingStrategy()),
    ('MeanReversion', MeanReversionStrategy()),
    ('SMC', SMCStrategy()),
    ('Breakout', BreakoutStrategy()),
    ('AI', AIEnhancedStrategy(predictor)),
]
print("\n--- Individual Strategy Signals ---")
for name, strat in strategies:
    try:
        s = strat.generate_signal(df, symbol)
        print(f"  {name:20s}: {s.signal_type.value:4s} conf={s.confidence:.3f}  SL={s.stop_loss:.2f}  TP={s.take_profit:.2f}  reason={s.reason[:100]}")
    except Exception as e:
        print(f"  {name:20s}: ERROR - {e}")

# 8. If not HOLD, check risk validation
if signal.signal_type.value != 'HOLD':
    validation = rm.validate_trade(signal)
    print(f"\n7. Risk validation: approved={validation['approved']}")
    if not validation['approved']:
        print(f"   Rejection reasons: {validation['reasons']}")

connector.disconnect()
print("\nDone.")
