"""Deep analysis of today's trading performance."""
import MetaTrader5 as mt5
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.settings import config
from datetime import datetime, timedelta
import json

mt5.initialize()

# Get ALL deals from today and yesterday
now = datetime.now()
start = datetime(now.year, now.month, now.day) - timedelta(days=2)
deals = mt5.history_deals_get(start, now)

if not deals:
    print("No deals found!")
    mt5.shutdown()
    exit(1)

# Filter bot deals with actual P&L
bot_deals = [d for d in deals if d.magic == config.trading.magic_number]

print("=" * 80)
print("FULL TRADE ANALYSIS - March 11, 2026")
print("=" * 80)

# Separate entry and exit deals
entries = [d for d in bot_deals if d.entry == 0]  # DEAL_ENTRY_IN
exits = [d for d in bot_deals if d.entry == 1]    # DEAL_ENTRY_OUT
profit_deals = [d for d in bot_deals if d.profit != 0]

print(f"\nTotal bot deals: {len(bot_deals)}")
print(f"Entries: {len(entries)} | Exits: {len(profit_deals)}")

# Detailed trade results
print("\n" + "=" * 80)
print("DETAILED TRADE RESULTS (P&L deals)")
print("=" * 80)

wins = []
losses = []
total_profit = 0
total_commission = 0
total_swap = 0

for d in sorted(profit_deals, key=lambda x: x.time):
    ts = datetime.fromtimestamp(d.time)
    side = "BUY" if d.type in [0, 2] else "SELL"
    net = d.profit + d.swap + d.commission
    total_profit += d.profit
    total_commission += d.commission
    total_swap += d.swap
    
    result = "WIN" if d.profit > 0 else "LOSS"
    if d.profit > 0:
        wins.append(d)
    else:
        losses.append(d)
    
    # Calculate hold time by finding matching entry
    entry_deal = None
    for e in entries:
        if e.position_id == d.position_id:
            entry_deal = e
            break
    
    hold_mins = 0
    entry_price = 0
    if entry_deal:
        hold_mins = (d.time - entry_deal.time) / 60
        entry_price = entry_deal.price
    
    sl_distance = abs(entry_price - d.price) if entry_price else 0
    
    print(f"  {ts.strftime('%H:%M')} | {d.symbol:10s} | {side:4s} | "
          f"Vol={d.volume:.2f} | Entry={entry_price:.2f} -> Exit={d.price:.2f} | "
          f"P&L=${d.profit:+.2f} | Comm=${d.commission:.2f} | "
          f"Hold={hold_mins:.0f}min | {result} | Comment: {d.comment}")

print(f"\n{'='*80}")
print(f"SUMMARY")
print(f"{'='*80}")
print(f"  Total trades closed: {len(profit_deals)}")
print(f"  Wins:  {len(wins)} ({len(wins)/len(profit_deals)*100:.0f}%)" if profit_deals else "")
print(f"  Losses: {len(losses)} ({len(losses)/len(profit_deals)*100:.0f}%)" if profit_deals else "")
print(f"  Gross Profit:  ${sum(d.profit for d in wins):.2f}")
print(f"  Gross Loss:    ${sum(d.profit for d in losses):.2f}")
print(f"  Net Profit:    ${total_profit:.2f}")
print(f"  Commission:    ${total_commission:.2f}")
print(f"  Swap:          ${total_swap:.2f}")
print(f"  Net After Costs: ${total_profit + total_commission + total_swap:.2f}")

# Analyze patterns
print(f"\n{'='*80}")
print(f"PATTERN ANALYSIS")
print(f"{'='*80}")

# Average win vs average loss
if wins:
    avg_win = sum(d.profit for d in wins) / len(wins)
    print(f"  Avg Win:  ${avg_win:.2f}")
if losses:
    avg_loss = sum(d.profit for d in losses) / len(losses)
    print(f"  Avg Loss: ${avg_loss:.2f}")
if wins and losses:
    print(f"  Win/Loss Ratio: {avg_win/abs(avg_loss):.2f}")

# Hold time analysis
print(f"\n  HOLD TIME ANALYSIS:")
for d in sorted(profit_deals, key=lambda x: x.time):
    entry_deal = None
    for e in entries:
        if e.position_id == d.position_id:
            entry_deal = e
            break
    if entry_deal:
        hold_mins = (d.time - entry_deal.time) / 60
        result = "WIN" if d.profit > 0 else "LOSS"
        print(f"    {result}: held {hold_mins:.0f}min -> ${d.profit:+.2f}")

# Strategy performance
print(f"\n  STRATEGY BREAKDOWN:")
strategy_stats = {}
for d in profit_deals:
    strat = d.comment.replace("AI_", "") if d.comment else "Unknown"
    if strat not in strategy_stats:
        strategy_stats[strat] = {"wins": 0, "losses": 0, "pnl": 0.0}
    strategy_stats[strat]["pnl"] += d.profit
    if d.profit > 0:
        strategy_stats[strat]["wins"] += 1
    else:
        strategy_stats[strat]["losses"] += 1

for strat, stats in strategy_stats.items():
    total = stats["wins"] + stats["losses"]
    wr = stats["wins"] / total * 100 if total > 0 else 0
    print(f"    {strat:30s} | W:{stats['wins']} L:{stats['losses']} | "
          f"WR:{wr:.0f}% | P&L: ${stats['pnl']:+.2f}")

# Time-of-day analysis
print(f"\n  TIME-OF-DAY ANALYSIS:")
hour_stats = {}
for d in profit_deals:
    entry_deal = None
    for e in entries:
        if e.position_id == d.position_id:
            entry_deal = e
            break
    if entry_deal:
        hour = datetime.fromtimestamp(entry_deal.time).hour
        if hour not in hour_stats:
            hour_stats[hour] = {"wins": 0, "losses": 0, "pnl": 0.0}
        hour_stats[hour]["pnl"] += d.profit
        if d.profit > 0:
            hour_stats[hour]["wins"] += 1
        else:
            hour_stats[hour]["losses"] += 1

for hour in sorted(hour_stats.keys()):
    stats = hour_stats[hour]
    total = stats["wins"] + stats["losses"]
    wr = stats["wins"] / total * 100 if total > 0 else 0
    print(f"    {hour:02d}:00 UTC | W:{stats['wins']} L:{stats['losses']} | "
          f"WR:{wr:.0f}% | P&L: ${stats['pnl']:+.2f}")

# Direction analysis
print(f"\n  DIRECTION ANALYSIS:")
dir_stats = {"BUY": {"wins": 0, "losses": 0, "pnl": 0.0}, "SELL": {"wins": 0, "losses": 0, "pnl": 0.0}}
for d in profit_deals:
    side = "BUY" if d.type in [0, 2] else "SELL"
    # For exit deals, the type is reversed
    # Actually for DEAL_ENTRY_OUT, type 0=BUY means closing a SELL, type 1=SELL means closing a BUY
    # Let's use the entry deal type instead
    entry_deal = None
    for e in entries:
        if e.position_id == d.position_id:
            entry_deal = e
            break
    if entry_deal:
        orig_side = "BUY" if entry_deal.type == 0 else "SELL"
    else:
        orig_side = side
    
    dir_stats[orig_side]["pnl"] += d.profit
    if d.profit > 0:
        dir_stats[orig_side]["wins"] += 1
    else:
        dir_stats[orig_side]["losses"] += 1

for direction, stats in dir_stats.items():
    total = stats["wins"] + stats["losses"]
    wr = stats["wins"] / total * 100 if total > 0 else 0
    print(f"    {direction}: W:{stats['wins']} L:{stats['losses']} | WR:{wr:.0f}% | P&L: ${stats['pnl']:+.2f}")

# Consecutive loss streaks
print(f"\n  LOSS STREAKS:")
streak = 0
max_streak = 0
streaks = []
for d in sorted(profit_deals, key=lambda x: x.time):
    if d.profit < 0:
        streak += 1
        max_streak = max(max_streak, streak)
    else:
        if streak > 0:
            streaks.append(streak)
        streak = 0
if streak > 0:
    streaks.append(streak)
print(f"    Max consecutive losses: {max_streak}")
print(f"    Loss streaks: {streaks}")

# Commission impact
print(f"\n  COST IMPACT:")
print(f"    Gross P&L:    ${total_profit:.2f}")
print(f"    Commissions:  ${total_commission:.2f}")
print(f"    Swaps:        ${total_swap:.2f}")
print(f"    Cost % of gross: {abs(total_commission + total_swap) / max(abs(total_profit), 0.01) * 100:.1f}%")

# Volume analysis - overtrading check
print(f"\n  OVERTRADING CHECK:")
print(f"    Total trades: {len(profit_deals)}")
print(f"    Trades per hour: {len(profit_deals) / 21:.1f} (21 trading hours)")
if len(profit_deals) > 10:
    print(f"    >>> HIGH FREQUENCY: {len(profit_deals)} trades may indicate overtrading!")

# Save analysis to JSON for the learning system
analysis = {
    "date": now.strftime("%Y-%m-%d"),
    "total_trades": len(profit_deals),
    "wins": len(wins),
    "losses": len(losses),
    "win_rate": len(wins) / len(profit_deals) * 100 if profit_deals else 0,
    "gross_profit": round(total_profit, 2),
    "commissions": round(total_commission, 2),
    "net_profit": round(total_profit + total_commission + total_swap, 2),
    "avg_win": round(sum(d.profit for d in wins) / len(wins), 2) if wins else 0,
    "avg_loss": round(sum(d.profit for d in losses) / len(losses), 2) if losses else 0,
    "max_streak_losses": max_streak,
    "strategy_performance": {k: {"wins": v["wins"], "losses": v["losses"], "pnl": round(v["pnl"], 2)} for k, v in strategy_stats.items()},
    "hour_performance": {str(k): {"wins": v["wins"], "losses": v["losses"], "pnl": round(v["pnl"], 2)} for k, v in hour_stats.items()},
    "direction_performance": {k: {"wins": v["wins"], "losses": v["losses"], "pnl": round(v["pnl"], 2)} for k, v in dir_stats.items()},
}

with open("logs/daily_analysis.json", "w") as f:
    json.dump(analysis, f, indent=2)
print(f"\nAnalysis saved to logs/daily_analysis.json")

mt5.shutdown()
