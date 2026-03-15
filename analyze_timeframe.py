"""
Analyze gold (XAUUSD) across multiple timeframes to find the best one.
Also check realistic profit potential for today.
"""
import MetaTrader5 as mt5
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.settings import config
from datetime import datetime, timedelta

mt5.initialize()

acct = mt5.account_info()
print("=" * 70)
print("CURRENT ACCOUNT STATUS")
print("=" * 70)
print(f"Balance: ${acct.balance:.2f} | Equity: ${acct.equity:.2f}")
print(f"Floating P&L: ${acct.profit:.2f}")

utc_now = datetime.utcnow()
hours_left = (23 - utc_now.hour) + (0 - utc_now.minute) / 60
print(f"Current UTC: {utc_now.strftime('%H:%M')} | Hours until 23:00 UTC: {hours_left:.1f}")
print(f"Prop Firm DD Limits: Daily 4% = ${acct.balance * 0.04:.0f} | Total 8% = ${5000 * 0.08:.0f}")

# ─── Analyze Gold on Multiple Timeframes ─────────────────────────────
print("\n" + "=" * 70)
print("GOLD (XAUUSD) TIMEFRAME ANALYSIS - Last 30 Days")
print("=" * 70)

symbol = "XAUUSDm"
mt5.symbol_select(symbol, True)

timeframes = {
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
}

results = {}

for tf_name, tf in timeframes.items():
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, 5000)
    if rates is None or len(rates) < 100:
        print(f"{tf_name}: Insufficient data")
        continue

    closes = np.array([r[4] for r in rates])
    highs = np.array([r[2] for r in rates])
    lows = np.array([r[3] for r in rates])
    opens = np.array([r[1] for r in rates])

    # ATR (14-period)
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1]))
    )
    atr_14 = np.mean(tr[-14:])

    # Average candle range (how much each candle moves)
    candle_range = np.mean(highs[-100:] - lows[-100:])

    # Average candle body (directional move)
    candle_body = np.mean(np.abs(closes[-100:] - opens[-100:]))

    # Body-to-range ratio (higher = more directional, less choppy)
    body_ratio = candle_body / candle_range if candle_range > 0 else 0

    # Trend strength: how often does price move in one direction for 3+ candles?
    direction = np.sign(closes[1:] - closes[:-1])
    trend_runs = 0
    run_length = 1
    run_lengths = []
    for i in range(1, len(direction)):
        if direction[i] == direction[i-1] and direction[i] != 0:
            run_length += 1
        else:
            run_lengths.append(run_length)
            if run_length >= 3:
                trend_runs += 1
            run_length = 1
    if run_length >= 3:
        trend_runs += 1
    run_lengths.append(run_length)

    avg_run = np.mean(run_lengths[-200:]) if run_lengths else 1
    max_run = max(run_lengths[-200:]) if run_lengths else 1

    # Win rate of simple MA crossover strategy (fast signal quality proxy)
    sma20 = np.convolve(closes, np.ones(20)/20, mode='valid')
    sma50 = np.convolve(closes, np.ones(50)/50, mode='valid')
    min_len = min(len(sma20), len(sma50))
    sma20 = sma20[-min_len:]
    sma50 = sma50[-min_len:]

    # Count crossover signals and their outcomes
    signal_wins = 0
    signal_losses = 0
    for i in range(1, min_len - 5):  # 5-candle lookahead
        # Bullish crossover
        if sma20[i] > sma50[i] and sma20[i-1] <= sma50[i-1]:
            future = closes[-min_len + i + 5] if (-min_len + i + 5) < len(closes) else closes[-1]
            current = closes[-min_len + i]
            if future > current:
                signal_wins += 1
            else:
                signal_losses += 1
        # Bearish crossover
        elif sma20[i] < sma50[i] and sma20[i-1] >= sma50[i-1]:
            future = closes[-min_len + i + 5] if (-min_len + i + 5) < len(closes) else closes[-1]
            current = closes[-min_len + i]
            if future < current:
                signal_wins += 1
            else:
                signal_losses += 1

    total_signals = signal_wins + signal_losses
    signal_wr = signal_wins / total_signals * 100 if total_signals > 0 else 0

    # Profit potential per candle (ATR * body ratio gives clean move size)
    profit_per_candle = atr_14 * body_ratio

    # How many candles fit in remaining hours?
    tf_minutes = {"M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240}
    candles_remaining = (hours_left * 60) / tf_minutes[tf_name]

    # Max theoretical profit at 0.01 lot with tick_value
    sym_info = mt5.symbol_info(symbol)
    tick_value = sym_info.trade_tick_value if sym_info else 1.0
    point = sym_info.point if sym_info else 0.001

    # Dollar move per 0.01 lot per ATR move
    atr_pips = atr_14 / (point * 10) if point > 0 else 0
    dollar_per_atr_min_lot = atr_pips * tick_value * 10 * 0.01

    results[tf_name] = {
        "atr": atr_14,
        "candle_range": candle_range,
        "candle_body": candle_body,
        "body_ratio": body_ratio,
        "avg_trend_run": avg_run,
        "max_trend_run": max_run,
        "signal_wr": signal_wr,
        "total_signals": total_signals,
        "profit_per_candle": profit_per_candle,
        "candles_remaining": candles_remaining,
        "dollar_per_atr": dollar_per_atr_min_lot,
    }

    print(f"\n{'─' * 50}")
    print(f"  {tf_name} TIMEFRAME")
    print(f"{'─' * 50}")
    print(f"  ATR(14):           ${atr_14:.2f}")
    print(f"  Avg Candle Range:  ${candle_range:.2f}")
    print(f"  Avg Candle Body:   ${candle_body:.2f}")
    print(f"  Body/Range Ratio:  {body_ratio:.2f} ({'Directional' if body_ratio > 0.45 else 'Choppy'})")
    print(f"  Avg Trend Run:     {avg_run:.1f} candles")
    print(f"  Max Trend Run:     {max_run} candles")
    print(f"  MA Cross WR:       {signal_wr:.0f}% ({total_signals} signals)")
    print(f"  Candles Left Today:{candles_remaining:.0f}")
    print(f"  $/ATR at 0.01 lot: ${dollar_per_atr_min_lot:.2f}")

# ─── Score and Rank Timeframes ────────────────────────────────────────
print("\n" + "=" * 70)
print("TIMEFRAME RANKING (Best for Gold Trading)")
print("=" * 70)

scores = {}
for tf_name, r in results.items():
    # Score factors (0-100 each):
    # 1. Body ratio (directional clarity) - higher is better
    body_score = min(r["body_ratio"] / 0.55 * 100, 100)

    # 2. Signal win rate - higher is better (baseline 50%)
    wr_score = max(0, (r["signal_wr"] - 40) / 30 * 100)

    # 3. Trend run length - longer runs = better for trend following
    run_score = min(r["avg_trend_run"] / 3.0 * 100, 100)

    # 4. Opportunity (enough candles remaining today)
    opp_score = min(r["candles_remaining"] / 10 * 100, 100)

    # 5. Dollar potential
    dollar_score = min(r["dollar_per_atr"] / 2.0 * 100, 100)

    # Weighted composite
    total_score = (
        body_score * 0.25 +
        wr_score * 0.30 +
        run_score * 0.20 +
        opp_score * 0.15 +
        dollar_score * 0.10
    )

    scores[tf_name] = total_score

# Sort by score
ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

for rank, (tf_name, score) in enumerate(ranked, 1):
    r = results[tf_name]
    medal = "🥇" if rank == 1 else ("🥈" if rank == 2 else "  ")
    print(f"  {medal} #{rank} {tf_name:4s} | Score: {score:.1f}/100 | "
          f"WR: {r['signal_wr']:.0f}% | Body: {r['body_ratio']:.2f} | "
          f"TrendRun: {r['avg_trend_run']:.1f} | Candles: {r['candles_remaining']:.0f}")

best_tf = ranked[0][0]
print(f"\n  BEST TIMEFRAME FOR GOLD: {best_tf}")

# ─── Realistic Profit Calculation ────────────────────────────────────
print("\n" + "=" * 70)
print("REALISTIC PROFIT ANALYSIS")
print("=" * 70)

# Current price and ATR
current_price = (mt5.symbol_info_tick(symbol).bid + mt5.symbol_info_tick(symbol).ask) / 2
best_r = results[best_tf]
atr = best_r["atr"]

print(f"  Gold Price:     ${current_price:.2f}")
print(f"  ATR ({best_tf}):      ${atr:.2f}")
print(f"  Hours Left:     {hours_left:.1f}")

# Max risk per trade (prop firm: 0.75% of $5000 = $37.50)
max_risk = acct.balance * 0.0075
print(f"  Max Risk/Trade: ${max_risk:.2f} (0.75% of ${acct.balance:.0f})")

# Lot size at 1.5 ATR stop-loss
sl_distance = atr * 1.5
sl_pips = sl_distance / (sym_info.point * 10)
lot_from_risk = max_risk / (sl_pips * tick_value * 10) if (sl_pips * tick_value * 10) > 0 else 0.01
lot_from_risk = max(0.01, min(lot_from_risk, 0.50))

# Potential profit per winning trade at 1:2 R:R
tp_distance = sl_distance * 2
win_amount = tp_distance / (sym_info.point * 10) * tick_value * 10 * lot_from_risk
loss_amount = max_risk

print(f"  Lot Size:       {lot_from_risk:.2f}")
print(f"  SL Distance:    ${sl_distance:.2f} ({sl_pips:.0f} pips)")
print(f"  Win Amount:     ${win_amount:.2f} per winning trade (1:2 R:R)")
print(f"  Loss Amount:    ${loss_amount:.2f} per losing trade")

# Scenario analysis
print(f"\n  SCENARIO ANALYSIS (at {lot_from_risk:.2f} lots):")
scenarios = [
    ("Conservative (2W 1L)", 2, 1),
    ("Good Day (3W 1L)", 3, 1),
    ("Great Day (4W 1L)", 4, 1),
    ("Perfect (5W 0L)", 5, 0),
]

for name, wins, losses in scenarios:
    pnl = (wins * win_amount) - (losses * loss_amount)
    print(f"    {name:25s}: ${pnl:+.2f}")

# How many wins needed for $500?
wins_for_500 = 500 / win_amount if win_amount > 0 else 99
no_loss_trades = int(np.ceil(wins_for_500))
print(f"\n  TO MAKE $500:")
print(f"    Need {no_loss_trades} consecutive wins with ZERO losses at {lot_from_risk:.2f} lots")
print(f"    OR need higher lot size (more risk)")

# At max lot (0.50)
max_win = tp_distance / (sym_info.point * 10) * tick_value * 10 * 0.50
max_loss = sl_distance / (sym_info.point * 10) * tick_value * 10 * 0.50
max_risk_pct = max_loss / acct.balance * 100
print(f"\n    At MAX lot 0.50: Win=${max_win:.2f}, Loss=${max_loss:.2f} (risk={max_risk_pct:.1f}% of balance)")
wins_at_max = int(np.ceil(500 / max_win)) if max_win > 0 else 99
print(f"    Would need {wins_at_max} wins at 0 losses")

# Daily DD limit check
dd_limit = acct.balance * 0.04
print(f"\n  RISK WARNING:")
print(f"    Daily DD limit (4%): ${dd_limit:.0f}")
print(f"    $500 target = {500/acct.balance*100:.1f}% of account in ONE day")
print(f"    This is {500/dd_limit:.1f}x your daily DD limit!")

mt5.shutdown()
