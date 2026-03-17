import sys; sys.path.insert(0, '.')
from core.mt5_lock import mt5_safe as mt5
mt5.initialize()
from core.mt5_connector import MT5Connector
from core.data_fetcher import DataFetcher
from analysis.technical import TechnicalAnalyzer
from analysis.sentiment import SentimentAnalyzer

c = MT5Connector(); c.connect()
f = DataFetcher(c)
ta = TechnicalAnalyzer()
sa = SentimentAnalyzer()
sym = 'XAUUSDm'
df = f.get_ohlcv(sym, count=100)
ind = ta.compute_all(df)
L = ind.iloc[-1]
P = ind.iloc[-2]
tick = mt5.symbol_info_tick(sym)
bid = tick.bid
ask = tick.ask
spread = ask - bid

last5 = df.tail(5)
print('=== LIVE MARKET: XAUUSD (Gold) ===')
print(f'Bid: {bid:.2f} | Ask: {ask:.2f} | Spread: {spread:.2f}')
print()

print('--- Last 5 M15 Candles ---')
for i, (_, r) in enumerate(last5.iterrows()):
    body = r['close'] - r['open']
    rng = r['high'] - r['low']
    direction = 'GREEN' if body > 0 else 'RED  '
    print(f'  {direction} O:{r["open"]:.2f} H:{r["high"]:.2f} L:{r["low"]:.2f} C:{r["close"]:.2f} | Body:{abs(body):.2f} Range:{rng:.2f}')

print()
print('--- Key Indicators ---')
rsi = L['rsi']
prev_rsi = P['rsi']
rsi_dir = 'rising' if rsi > prev_rsi else 'falling'
print(f'RSI(14):    {rsi:.1f} ({rsi_dir})')

macd = L['macd_hist']
prev_macd = P['macd_hist']
macd_dir = 'improving' if macd > prev_macd else 'worsening'
print(f'MACD Hist:  {macd:.3f} ({macd_dir})')

print(f'ADX:        {L["adx"]:.1f}')
ef = L['ema_fast']
es = L['ema_slow']
print(f'EMA 12:     {ef:.2f} | EMA 26: {es:.2f}')
print(f'SMA 20:     {L["sma_fast"]:.2f} | SMA 50: {L["sma_slow"]:.2f}')

bb_upper = L.get('bb_upper', None)
bb_lower = L.get('bb_lower', None)
if bb_upper and bb_lower:
    print(f'Bollinger:  Upper {bb_upper:.2f} | Lower {bb_lower:.2f}')

atr = L.get('atr', None)
if atr:
    print(f'ATR(14):    {atr:.2f}')

# Regime
try:
    regime = sa.analyze_market_regime(df)
    print()
    print(f'Regime: {regime.get("regime","?")} | Trend: {regime.get("trend","?")} | Volatility: {regime.get("volatility","?")}')
except:
    pass

# Price action
h1 = df['high'].tail(4).max()
l1 = df['low'].tail(4).min()
print()
print('--- Price Action (Last 1 Hour) ---')
print(f'Range: {l1:.2f} - {h1:.2f} (${h1-l1:.2f})')
move1h = bid - df['close'].iloc[-5]
print(f'1hr move: {move1h:+.2f}')

# Bias
bias_signals = []
if rsi < 30: bias_signals.append('OVERSOLD')
elif rsi > 70: bias_signals.append('OVERBOUGHT')
elif rsi < 50: bias_signals.append('bearish RSI')
else: bias_signals.append('bullish RSI')

if macd > 0: bias_signals.append('MACD positive')
elif macd > prev_macd: bias_signals.append('MACD improving')
else: bias_signals.append('MACD negative')

if ef > es: bias_signals.append('EMA bullish')
else: bias_signals.append('EMA bearish')

print()
print(f'Bias: {" | ".join(bias_signals)}')

# Open positions
positions = mt5.positions_get(symbol=sym)
print()
if positions:
    print(f'--- YOUR OPEN POSITIONS ({len(positions)}) ---')
    for p in positions:
        side = 'BUY' if p.type == 0 else 'SELL'
        pnl = p.profit
        dist_sl = abs(bid - p.sl) if p.sl else 0
        dist_tp = abs(p.tp - bid) if p.tp else 0
        print(f'  {side} {p.volume} @ {p.price_open:.2f} | Now: {bid:.2f} | P&L: ${pnl:+.2f}')
        print(f'  SL: {p.sl:.2f} (${dist_sl:.2f} away) | TP: {p.tp:.2f} (${dist_tp:.2f} away)')
else:
    print('--- NO OPEN POSITIONS ---')

c.disconnect()
