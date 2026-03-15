"""Verify configuration after M15 switch."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.settings import config
from ai.trade_journal import TradingJournal

print("Primary TF:", config.trading.primary_timeframe.value)
print("Analysis TFs:", [tf.value for tf in config.trading.analysis_timeframes])
print("Max trades/symbol:", config.trading.max_trades_per_symbol)
print("Max open trades:", config.trading.max_open_trades)
print("Trailing ATR mult:", config.risk.trailing_stop_atr_mult)
print("Break-even ATR mult:", config.risk.break_even_atr_mult)
print("Risk/trade:", config.risk.max_risk_per_trade)
print("Max lot:", config.risk.max_lot_size)
print()

j = TradingJournal()
print("Journal rules:")
for r in j.get_active_rules():
    print(f"  * {r}")

lessons = j.get_lessons()
print(f"Bad hours: {lessons.get('bad_hours_utc', [])}")
print(f"Max trades/day: {lessons.get('max_trades_per_day', 10)}")
