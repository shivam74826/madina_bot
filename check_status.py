"""Quick diagnostic script to check why bot isn't trading."""
import MetaTrader5 as mt5
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.settings import config
from datetime import datetime, timedelta

mt5.initialize()
acct = mt5.account_info()
if not acct:
    print("ERROR: Cannot connect to MT5!")
    mt5.shutdown()
    exit(1)

print("=" * 60)
print("ACCOUNT STATUS")
print("=" * 60)
print(f"Balance:      ${acct.balance:.2f}")
print(f"Equity:       ${acct.equity:.2f}")
print(f"Free Margin:  ${acct.margin_free:.2f}")
print(f"Margin Level: {acct.margin_level:.1f}%" if acct.margin_level else "Margin Level: N/A")
print(f"Floating P&L: ${acct.profit:.2f}")

# Prop firm DD calculation
if config.prop_firm.enabled:
    acct_size = config.prop_firm.account_size
    total_dd = (acct_size - acct.equity) / acct_size if acct.equity < acct_size else 0
    print(f"\nPROP FIRM STATUS:")
    print(f"  Account Size:  ${acct_size:.0f}")
    print(f"  Total DD:      {total_dd*100:.2f}% (buffer: {config.prop_firm.max_drawdown_buffer*100:.0f}%, limit: {config.prop_firm.max_drawdown_limit*100:.0f}%)")
    print(f"  DD Halted?     {'YES - THIS IS BLOCKING!' if total_dd >= config.prop_firm.max_drawdown_buffer else 'No'}")
    print(f"  Emergency?     {'YES!' if total_dd >= config.prop_firm.emergency_close_at_dd_pct else 'No'}")

# Check open positions  
print("\n" + "=" * 60)
print("OPEN POSITIONS")
print("=" * 60)
positions = mt5.positions_get()
if positions:
    bot_positions = [p for p in positions if p.magic == config.trading.magic_number]
    other_positions = [p for p in positions if p.magic != config.trading.magic_number]
    print(f"Total open: {len(positions)} (Bot: {len(bot_positions)}, Other: {len(other_positions)})")
    print(f"Max allowed: {config.trading.max_open_trades}")
    if len(bot_positions) >= config.trading.max_open_trades:
        print(f">>> BLOCKING: Max open trades reached ({len(bot_positions)}/{config.trading.max_open_trades})!")
    
    for p in positions:
        side = "BUY" if p.type == 0 else "SELL"
        print(f"  [{p.ticket}] {p.symbol} {side} vol={p.volume} P&L={p.profit:.2f} comment={p.comment}")
    
    # Per-symbol check
    symbols_count = {}
    for p in bot_positions:
        symbols_count[p.symbol] = symbols_count.get(p.symbol, 0) + 1
    for sym, cnt in symbols_count.items():
        if cnt >= config.trading.max_trades_per_symbol:
            print(f">>> BLOCKING: Max trades for {sym} reached ({cnt}/{config.trading.max_trades_per_symbol})!")
else:
    print("No open positions")

# Check daily P&L
print("\n" + "=" * 60)
print("TODAY'S CLOSED DEALS")
print("=" * 60)
deals = mt5.history_deals_get(datetime.now() - timedelta(days=1), datetime.now())
if deals:
    bot_deals = [d for d in deals if d.magic == config.trading.magic_number and d.profit != 0]
    if bot_deals:
        total_pnl = sum(d.profit + d.swap + d.commission for d in bot_deals)
        losses = [d for d in bot_deals if d.profit < 0]
        wins = [d for d in bot_deals if d.profit > 0]
        consecutive_losses = 0
        for d in sorted(bot_deals, key=lambda x: x.time, reverse=True):
            if d.profit < 0:
                consecutive_losses += 1
            else:
                break
        print(f"Closed deals: {len(bot_deals)} | Wins: {len(wins)} | Losses: {len(losses)}")
        print(f"Total P&L: ${total_pnl:.2f}")
        print(f"Recent consecutive losses: {consecutive_losses}")
        if consecutive_losses >= config.risk.max_consecutive_losses:
            print(f">>> BLOCKING: Circuit breaker triggered ({consecutive_losses} >= {config.risk.max_consecutive_losses})!")
        
        max_daily_loss = acct.balance * config.risk.max_daily_risk
        unrealized = acct.profit
        total_daily = total_pnl + unrealized
        print(f"Daily risk used: ${abs(total_daily):.2f} / ${max_daily_loss:.2f}")
        if total_daily < -max_daily_loss:
            print(f">>> BLOCKING: Daily loss limit exceeded!")
    else:
        print("No bot deals closed recently")
else:
    print("No deals found")

# Trading hours check
print("\n" + "=" * 60)
print("TRADING HOURS")
print("=" * 60)
now = datetime.utcnow()
print(f"Current UTC: {now.strftime('%A %H:%M')}")
print(f"Allowed: {config.trading.trading_hours_start}:00 - {config.trading.trading_hours_end}:00 UTC")
if now.weekday() >= 5:
    print(">>> BLOCKING: Weekend!")
elif not (config.trading.trading_hours_start <= now.hour <= config.trading.trading_hours_end):
    print(">>> BLOCKING: Outside trading hours!")
else:
    print("Trading hours: OK")

print("\n" + "=" * 60)
mt5.shutdown()
