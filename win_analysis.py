import sys; sys.path.insert(0, '.')
from core.mt5_lock import mt5_safe as mt5
mt5.initialize()
from core.mt5_connector import MT5Connector
from core.data_fetcher import DataFetcher
from analysis.technical import TechnicalAnalyzer
from config.settings import TimeFrame

c = MT5Connector(); c.connect()
f = DataFetcher(c)
ta = TechnicalAnalyzer()
sym = 'XAUUSDm'

df_m15 = f.get_ohlcv(sym, count=200)
df_h1 = f.get_ohlcv(sym, timeframe=TimeFrame.H1, count=100)
df_h4 = f.get_ohlcv(sym, timeframe=TimeFrame.H4, count=50)

ind15 = ta.compute_all(df_m15)
ind_h1 = ta.compute_all(df_h1)
ind_h4 = ta.compute_all(df_h4)

tick = mt5.symbol_info_tick(sym)
bid = tick.bid
positions = mt5.positions_get(symbol=sym)

print('='*45)
print('   WIN PROBABILITY ANALYSIS')
print('='*45)
print()

for p in positions:
    entry = p.price_open
    sl = p.sl
    tp = p.tp
    pnl = p.profit
    risk = entry - sl
    reward = tp - entry
    rr = reward / risk if risk > 0 else 0
    dist_sl = bid - sl
    dist_tp = tp - bid
    dollar = "$"
    print(f'Trade: BUY @ {entry:.2f} | P&L: {dollar}{pnl:+.2f}')
    print(f'  SL: {sl:.2f} ({dist_sl:.2f} away) | TP: {tp:.2f} ({dist_tp:.2f} away)')
    print(f'  R:R = 1:{rr:.1f}')
    print()

L15 = ind15.iloc[-1]
P15 = ind15.iloc[-2]
Lh1 = ind_h1.iloc[-1]
Ph1 = ind_h1.iloc[-2]
Lh4 = ind_h4.iloc[-1]

print('--- Multi-Timeframe Scoring ---')
print()

score = 0
factors = []

# 1. RSI M15
rsi15 = L15['rsi']
if rsi15 < 30:
    score += 2; factors.append(f'M15 RSI {rsi15:.1f} OVERSOLD (+2)')
elif rsi15 < 40:
    score += 1; factors.append(f'M15 RSI {rsi15:.1f} near oversold (+1)')
elif rsi15 > 70:
    score -= 2; factors.append(f'M15 RSI {rsi15:.1f} OVERBOUGHT (-2)')
elif rsi15 > 60:
    score -= 1; factors.append(f'M15 RSI {rsi15:.1f} strong bearish (-1)')
else:
    factors.append(f'M15 RSI {rsi15:.1f} neutral (0)')

# 2. RSI H1
rsi_h1 = Lh1['rsi']
if rsi_h1 < 30:
    score += 2; factors.append(f'H1 RSI {rsi_h1:.1f} OVERSOLD (+2)')
elif rsi_h1 < 40:
    score += 1; factors.append(f'H1 RSI {rsi_h1:.1f} near oversold (+1)')
elif rsi_h1 > 60:
    score -= 1; factors.append(f'H1 RSI {rsi_h1:.1f} bearish (-1)')
else:
    factors.append(f'H1 RSI {rsi_h1:.1f} neutral (0)')

# 3. RSI H4
rsi_h4 = Lh4['rsi']
if rsi_h4 < 30:
    score += 2; factors.append(f'H4 RSI {rsi_h4:.1f} OVERSOLD (+2)')
elif rsi_h4 < 40:
    score += 1; factors.append(f'H4 RSI {rsi_h4:.1f} near oversold (+1)')
elif rsi_h4 > 60:
    score -= 1; factors.append(f'H4 RSI {rsi_h4:.1f} bearish (-1)')
else:
    factors.append(f'H4 RSI {rsi_h4:.1f} neutral (0)')

# 4. MACD M15 direction
macd15 = L15['macd_hist']
prev_macd15 = P15['macd_hist']
if macd15 > prev_macd15:
    score += 1; factors.append(f'M15 MACD improving ({macd15:.3f}) (+1)')
else:
    score -= 1; factors.append(f'M15 MACD worsening ({macd15:.3f}) (-1)')

# 5. MACD H1
macd_h1 = Lh1['macd_hist']
prev_macd_h1 = Ph1['macd_hist']
if macd_h1 > prev_macd_h1:
    score += 1; factors.append(f'H1 MACD improving (+1)')
else:
    score -= 1; factors.append(f'H1 MACD worsening (-1)')

# 6. Bollinger bands
bb_lower = L15.get('bb_lower', 0)
bb_upper = L15.get('bb_upper', 0)
if bb_lower and bid < bb_lower + 5:
    score += 2; factors.append(f'Price near BB lower {bb_lower:.2f} - bounce zone (+2)')
elif bb_upper and bid > bb_upper - 5:
    score -= 2; factors.append(f'Price near BB upper - reversal risk (-2)')
else:
    factors.append(f'Price between BB bands (0)')

# 7. Support from recent lows
recent_lows = df_m15['low'].tail(30).min()
if bid - recent_lows < 10:
    score += 1; factors.append(f'Near 30-bar support {recent_lows:.2f} (+1)')

# 8. Last 3 candles
last3 = sum(1 if df_m15['close'].iloc[-i] > df_m15['open'].iloc[-i] else -1 for i in range(1, 4))
if last3 <= -2:
    score -= 1; factors.append(f'3 consecutive red candles (-1)')
elif last3 >= 2:
    score += 1; factors.append(f'3 consecutive green candles (+1)')
else:
    factors.append(f'Mixed candle pattern (0)')

# 9. H4 EMA trend
ema_h4_fast = Lh4['ema_fast']
if bid > ema_h4_fast:
    score += 1; factors.append(f'Above H4 EMA12 {ema_h4_fast:.2f} (+1)')
else:
    score -= 1; factors.append(f'Below H4 EMA12 {ema_h4_fast:.2f} (-1)')

# 10. SL proximity vs ATR
atr = L15.get('atr', 13)
if atr:
    dist_to_sl_min = min(bid - p.sl for p in positions)
    if dist_to_sl_min < atr * 0.5:
        score -= 2; factors.append(f'SL DANGER: only {dist_to_sl_min:.1f} away vs ATR {atr:.1f} (-2)')
    elif dist_to_sl_min < atr:
        score -= 1; factors.append(f'SL tight: {dist_to_sl_min:.1f} away vs ATR {atr:.1f} (-1)')
    else:
        factors.append(f'SL safe: {dist_to_sl_min:.1f} away vs ATR {atr:.1f} (0)')

# 11. H1 candle pattern
h1_last3 = sum(1 if df_h1['close'].iloc[-i] > df_h1['open'].iloc[-i] else -1 for i in range(1, 4))
if h1_last3 <= -2:
    score -= 1; factors.append(f'H1: 3 red candles in a row (-1)')
elif h1_last3 >= 2:
    score += 1; factors.append(f'H1: 3 green candles in a row (+1)')

print('Factors:')
for fac in factors:
    print(f'  {fac}')

print()
print(f'Total Score: {score}')
print(f'  (range: -18 very bearish ... 0 neutral ... +18 very bullish)')

# Calculate probabilities
win_direction = max(5, min(95, 50 + score * 3.5))
lose_direction = 100 - win_direction

# TP reality check
best_entry = max(p.price_open for p in positions)
worst_entry = min(p.price_open for p in positions) 
avg_tp = sum(p.tp for p in positions) / len(positions)
avg_sl = max(p.sl for p in positions)
breakeven_need = best_entry - bid

print()
print('='*45)
print('   PROBABILITY BREAKDOWN')
print('='*45)
print()
print(f'  Price now:       {bid:.2f}')
print(f'  Breakeven needs: +{breakeven_need:.2f} move up')
print(f'  Nearest SL:      {avg_sl:.2f} ({bid - avg_sl:.2f} below)')
print(f'  TP target:       ~{avg_tp:.0f} ({avg_tp - bid:.0f} above)')
print()

# Scenarios
tp_pct = max(2, int(win_direction / 6))
breakeven_pct = max(5, int(win_direction * 0.5))
partial_pct = max(5, int(win_direction * 0.7))
one_sl_pct = int(lose_direction * 0.4)
both_sl_pct = int(lose_direction * 0.6)

d = "$"
print(f'  SCENARIO 1 - Both hit TP ({d}+165 each):    {tp_pct}%')
print(f'  SCENARIO 2 - Recover to breakeven:          {breakeven_pct}%')  
print(f'  SCENARIO 3 - Small recovery, partial loss:   {partial_pct - breakeven_pct}%')
print(f'  SCENARIO 4 - One SL hit, one survives:       {one_sl_pct}%')
print(f'  SCENARIO 5 - Both SL hit ({d}-30 total):     {both_sl_pct}%')
print()
print(f'  Direction goes UP (good for you):  {win_direction:.0f}%')
print(f'  Direction goes DOWN (bad for you): {lose_direction:.0f}%')

c.disconnect()
