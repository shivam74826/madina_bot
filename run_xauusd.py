"""Quick launcher: Run XAUUSD trading on demo mode.
Cleans stale AI models to avoid feature-mismatch errors after restarts.
"""
import sys
import os
import glob
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── Step 1: Clean stale model files to force fresh training ──
models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
if os.path.exists(models_dir):
    stale = glob.glob(os.path.join(models_dir, "*.pkl"))
    if stale:
        print(f"Cleaning {len(stale)} stale model files to avoid feature mismatch...")
        for f in stale:
            os.remove(f)
        print("Model cache cleared. Fresh models will be trained on startup.")

from config.settings import config, TradingMode
from utils.logger import setup_logging

# ── Step 2: Configure ──
setup_logging()
config.trading.mode = TradingMode.DEMO

# Try XAUUSD first; the bot will auto-detect the correct symbol on connect
config.trading.symbols = ["XAUUSD"]

# Create and start bot
from main import ForexAIBot
import signal
import MetaTrader5 as mt5

bot = ForexAIBot()

def signal_handler(sig, frame):
    bot.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ── Step 3: Pre-check MT5 connection and find correct gold symbol ──
print("=" * 60)
print("  PRE-FLIGHT CHECK")
print("=" * 60)

if mt5.initialize(
    path=config.mt5.path,
    login=config.mt5.login,
    password=config.mt5.password,
    server=config.mt5.server,
    timeout=config.mt5.timeout,
):
    info = mt5.account_info()
    print(f"  MT5 Connected: Account {info.login} | Balance: {info.balance} {info.currency}")

    # Find the correct gold symbol
    gold_symbol = None
    for candidate in ["XAUUSD", "XAUUSDm", "XAUUSD.pro", "XAUUSD.raw", "GOLD"]:
        sym_info = mt5.symbol_info(candidate)
        if sym_info is not None:
            gold_symbol = candidate
            mt5.symbol_select(candidate, True)
            tick = mt5.symbol_info_tick(candidate)
            price = tick.ask if tick else "N/A"
            print(f"  Gold symbol found: {candidate} (price: {price})")
            break

    mt5.shutdown()

    if gold_symbol:
        config.trading.symbols = [gold_symbol]
        # Also update the bot's internal symbol list
        print(f"  Trading symbol set to: {gold_symbol}")
    else:
        print("  WARNING: No gold symbol found! Listing available symbols with 'XAU':")
        mt5.initialize(path=config.mt5.path, login=config.mt5.login,
                       password=config.mt5.password, server=config.mt5.server)
        syms = mt5.symbols_get(group="*XAU*,*GOLD*")
        if syms:
            for s in syms:
                print(f"    {s.name}")
        mt5.shutdown()
else:
    err = mt5.last_error()
    print(f"  MT5 connection failed: {err}")
    print("  Make sure MetaTrader 5 is running and logged in!")
    sys.exit(1)

print()
print("=" * 60)
print(f"  STARTING XAUUSD TRADING BOT (Demo Mode)")
print(f"  Symbol: {config.trading.symbols[0]}")
print(f"  Dashboard: http://127.0.0.1:5000")
print("=" * 60)
print()

bot.start(with_dashboard=True)
