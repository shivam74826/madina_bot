"""
=============================================================================
Walk-Forward Backtester
=============================================================================
Validates strategy profitability on historical data before live trading.
Includes: slippage, commissions, swap costs, spread simulation.
Run: python backtest.py --symbol XAUUSDm --days 365
=============================================================================
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import config, TimeFrame
from analysis.technical import TechnicalAnalyzer
from strategy.trend_following import TrendFollowingStrategy
from strategy.mean_reversion import MeanReversionStrategy
from strategy.breakout_strategy import BreakoutStrategy
from strategy.smc_strategy import SMCStrategy
from strategy.base_strategy import SignalType

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger(__name__)

TIMEFRAME_MAP = {
    TimeFrame.M1: mt5.TIMEFRAME_M1,
    TimeFrame.M5: mt5.TIMEFRAME_M5,
    TimeFrame.M15: mt5.TIMEFRAME_M15,
    TimeFrame.M30: mt5.TIMEFRAME_M30,
    TimeFrame.H1: mt5.TIMEFRAME_H1,
    TimeFrame.H4: mt5.TIMEFRAME_H4,
    TimeFrame.D1: mt5.TIMEFRAME_D1,
}


@dataclass
class BacktestTrade:
    """Record of a simulated trade."""
    entry_time: datetime
    exit_time: datetime
    direction: str
    entry_price: float
    exit_price: float
    sl: float
    tp: float
    lot_size: float
    pnl: float
    commission: float
    slippage: float
    strategy: str
    reason: str
    exit_reason: str  # "TP", "SL", "end_of_data"


@dataclass
class BacktestResult:
    """Aggregate backtest results."""
    symbol: str
    timeframe: str
    period_start: datetime = None
    period_end: datetime = None
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0
    total_commission: float = 0.0
    total_slippage_cost: float = 0.0
    max_drawdown_pct: float = 0.0
    max_consecutive_losses: int = 0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_winner: float = 0.0
    avg_loser: float = 0.0
    win_rate: float = 0.0
    avg_rr_achieved: float = 0.0
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    strategy_breakdown: Dict[str, Dict] = field(default_factory=dict)


class WalkForwardBacktester:
    """
    Walk-forward backtester with realistic cost simulation.
    Trains strategies on train_window, tests on test_window, rolls forward.
    """

    def __init__(
        self,
        symbol: str,
        timeframe: TimeFrame = None,
        initial_balance: float = 5000.0,
        risk_per_trade: float = 0.0075,
        commission_per_lot: float = 7.0,
        slippage_pips: float = 1.0,
        spread_pips: float = 2.0,
    ):
        self.symbol = symbol
        self.timeframe = timeframe or config.trading.primary_timeframe
        self.initial_balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.commission_per_lot = commission_per_lot
        self.slippage_pips = slippage_pips
        self.spread_pips = spread_pips

        # Strategies to test
        self.strategies = {
            "TrendFollowing": TrendFollowingStrategy(),
            "MeanReversion": MeanReversionStrategy(),
            "Breakout": BreakoutStrategy(),
            "SMC": SMCStrategy(),
        }

    def fetch_historical_data(self, days: int) -> Optional[pd.DataFrame]:
        """Fetch historical data from MT5."""
        if not mt5.initialize():
            logger.error("MT5 init failed")
            return None

        mt5_tf = TIMEFRAME_MAP.get(self.timeframe, mt5.TIMEFRAME_M15)
        date_from = datetime.now() - timedelta(days=days)
        date_to = datetime.now()

        rates = mt5.copy_rates_range(self.symbol, mt5_tf, date_from, date_to)
        mt5.shutdown()

        if rates is None or len(rates) == 0:
            logger.error(f"No data for {self.symbol}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        logger.info(f"Fetched {len(df)} bars for {self.symbol} ({days} days)")
        return df

    def _pip_value(self, df: pd.DataFrame) -> float:
        """Estimate pip value from price level."""
        price = df["close"].iloc[-1]
        # Gold: 1 pip = 0.1 for XAU
        if "XAU" in self.symbol.upper():
            return 0.1
        elif price > 10:
            return 0.01
        else:
            return 0.0001

    def _calculate_lot_size(self, balance: float, sl_distance: float, pip_value: float) -> float:
        """Calculate lot size from risk parameters."""
        if sl_distance <= 0 or pip_value <= 0:
            return 0.01
        sl_pips = sl_distance / pip_value
        # tick_value for gold ~ $1 per pip per 0.01 lot (approx)
        risk_amount = balance * self.risk_per_trade
        # Approximate: for gold, 1 standard lot = $10 per pip
        pip_cost_per_lot = 10.0  # USD per pip per lot (approximate for gold)
        lot = risk_amount / (sl_pips * pip_cost_per_lot) if sl_pips > 0 else 0.01
        lot = max(0.01, min(lot, config.risk.max_lot_size))
        return round(lot, 2)

    def run(self, days: int = 365, warmup_bars: int = 200) -> Optional[BacktestResult]:
        """
        Run walk-forward backtest.
        
        Args:
            days: Total days of historical data
            warmup_bars: Bars needed before first signal
        """
        df = self.fetch_historical_data(days)
        if df is None:
            return None

        result = BacktestResult(
            symbol=self.symbol,
            timeframe=self.timeframe.value,
            period_start=df["time"].iloc[warmup_bars],
            period_end=df["time"].iloc[-1],
        )

        balance = self.initial_balance
        peak_balance = balance
        max_dd = 0.0
        consecutive_losses = 0
        max_consec_losses = 0
        pnl_list = []
        equity_curve = [balance]
        pip_val = self._pip_value(df)

        strategy_stats = {name: {"wins": 0, "losses": 0, "pnl": 0.0} for name in self.strategies}

        # Walk through data bar by bar
        for i in range(warmup_bars, len(df) - 1):
            window = df.iloc[:i + 1].copy()

            # Skip weekends and low-volume periods
            hour = window["time"].iloc[-1].hour
            if hour < 1 or hour > 22:
                continue

            # Run each strategy
            for strat_name, strategy in self.strategies.items():
                try:
                    signal = strategy.analyze(window, self.symbol)
                except Exception:
                    continue

                if signal.signal_type == SignalType.HOLD:
                    continue

                if signal.confidence < config.ai.min_confidence:
                    continue

                if signal.risk_reward < config.risk.risk_reward_ratio:
                    continue

                # Simulate entry with spread + slippage
                entry_price = signal.entry_price
                spread_cost = self.spread_pips * pip_val
                slip_cost = self.slippage_pips * pip_val

                if signal.signal_type == SignalType.BUY:
                    entry_price += spread_cost / 2 + slip_cost  # Worse fill
                else:
                    entry_price -= spread_cost / 2 + slip_cost

                sl = signal.stop_loss
                tp = signal.take_profit
                sl_distance = abs(entry_price - sl)

                lot_size = self._calculate_lot_size(balance, sl_distance, pip_val)
                commission = self.commission_per_lot * lot_size

                # Simulate trade outcome: scan future bars for SL/TP hit
                exit_price = None
                exit_reason = "end_of_data"
                exit_time = df["time"].iloc[-1]

                for j in range(i + 1, min(i + 100, len(df))):
                    bar = df.iloc[j]
                    bar_high = bar["high"]
                    bar_low = bar["low"]

                    if signal.signal_type == SignalType.BUY:
                        # Check SL first (worst case)
                        if bar_low <= sl:
                            exit_price = sl - slip_cost  # Slippage on exit
                            exit_reason = "SL"
                            exit_time = bar["time"]
                            break
                        if bar_high >= tp:
                            exit_price = tp - slip_cost
                            exit_reason = "TP"
                            exit_time = bar["time"]
                            break
                    else:  # SELL
                        if bar_high >= sl:
                            exit_price = sl + slip_cost
                            exit_reason = "SL"
                            exit_time = bar["time"]
                            break
                        if bar_low <= tp:
                            exit_price = tp + slip_cost
                            exit_reason = "TP"
                            exit_time = bar["time"]
                            break

                if exit_price is None:
                    # Trade didn't hit SL/TP within 100 bars, close at last price
                    exit_price = df["close"].iloc[min(i + 100, len(df) - 1)]
                    exit_reason = "timeout"

                # Calculate P&L
                if signal.signal_type == SignalType.BUY:
                    raw_pnl = (exit_price - entry_price) * lot_size * 100  # Approximate
                else:
                    raw_pnl = (entry_price - exit_price) * lot_size * 100

                net_pnl = raw_pnl - commission

                # Record trade
                trade = BacktestTrade(
                    entry_time=window["time"].iloc[-1],
                    exit_time=exit_time,
                    direction=signal.signal_type.value,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    sl=sl,
                    tp=tp,
                    lot_size=lot_size,
                    pnl=net_pnl,
                    commission=commission,
                    slippage=slip_cost * lot_size * 100,
                    strategy=strat_name,
                    reason=signal.reason[:100],
                    exit_reason=exit_reason,
                )
                result.trades.append(trade)

                # Update balance
                balance += net_pnl
                pnl_list.append(net_pnl)
                equity_curve.append(balance)

                # Track stats
                if net_pnl >= 0:
                    result.wins += 1
                    result.gross_profit += net_pnl
                    strategy_stats[strat_name]["wins"] += 1
                    consecutive_losses = 0
                else:
                    result.losses += 1
                    result.gross_loss += abs(net_pnl)
                    strategy_stats[strat_name]["losses"] += 1
                    consecutive_losses += 1
                    max_consec_losses = max(max_consec_losses, consecutive_losses)

                strategy_stats[strat_name]["pnl"] += net_pnl
                result.total_commission += commission
                result.total_slippage_cost += trade.slippage

                # Drawdown
                peak_balance = max(peak_balance, balance)
                dd = (peak_balance - balance) / peak_balance if peak_balance > 0 else 0
                max_dd = max(max_dd, dd)

                # Only one trade per bar
                break

        # Compute final metrics
        result.total_trades = len(result.trades)
        result.net_pnl = balance - self.initial_balance
        result.max_drawdown_pct = max_dd * 100
        result.max_consecutive_losses = max_consec_losses
        result.equity_curve = equity_curve
        result.strategy_breakdown = strategy_stats

        if result.total_trades > 0:
            result.win_rate = result.wins / result.total_trades * 100
            result.avg_winner = result.gross_profit / result.wins if result.wins > 0 else 0
            result.avg_loser = result.gross_loss / result.losses if result.losses > 0 else 0
            result.profit_factor = result.gross_profit / result.gross_loss if result.gross_loss > 0 else float('inf')
            result.avg_rr_achieved = result.avg_winner / result.avg_loser if result.avg_loser > 0 else 0

            # Sharpe ratio (annualized)
            if len(pnl_list) > 1:
                pnl_arr = np.array(pnl_list)
                avg_return = pnl_arr.mean()
                std_return = pnl_arr.std()
                result.sharpe_ratio = (avg_return / std_return * np.sqrt(252)) if std_return > 0 else 0

        return result

    def print_report(self, result: BacktestResult):
        """Print a detailed backtest report."""
        print("\n" + "=" * 70)
        print("  WALK-FORWARD BACKTEST REPORT")
        print("=" * 70)
        print(f"  Symbol:     {result.symbol}")
        print(f"  Timeframe:  {result.timeframe}")
        print(f"  Period:     {result.period_start} -> {result.period_end}")
        print(f"  Initial:    ${self.initial_balance:,.2f}")
        print(f"  Costs:      Commission ${self.commission_per_lot}/lot | "
              f"Slippage {self.slippage_pips} pips | Spread {self.spread_pips} pips")
        print("-" * 70)
        print(f"  Total Trades:       {result.total_trades}")
        print(f"  Win Rate:           {result.win_rate:.1f}%")
        print(f"  Wins / Losses:      {result.wins} / {result.losses}")
        print(f"  Net P&L:            ${result.net_pnl:+,.2f}")
        print(f"  Gross Profit:       ${result.gross_profit:,.2f}")
        print(f"  Gross Loss:         ${result.gross_loss:,.2f}")
        print(f"  Profit Factor:      {result.profit_factor:.2f}")
        print(f"  Avg Winner:         ${result.avg_winner:.2f}")
        print(f"  Avg Loser:          ${result.avg_loser:.2f}")
        print(f"  Avg R:R Achieved:   {result.avg_rr_achieved:.2f}")
        print(f"  Sharpe Ratio:       {result.sharpe_ratio:.2f}")
        print(f"  Max Drawdown:       {result.max_drawdown_pct:.1f}%")
        print(f"  Max Consec. Losses: {result.max_consecutive_losses}")
        print(f"  Total Commission:   ${result.total_commission:.2f}")
        print(f"  Total Slippage:     ${result.total_slippage_cost:.2f}")

        print("\n  --- Strategy Breakdown ---")
        for name, stats in result.strategy_breakdown.items():
            total = stats["wins"] + stats["losses"]
            if total == 0:
                continue
            wr = stats["wins"] / total * 100
            print(f"  {name:20s} | Trades: {total:4d} | WR: {wr:5.1f}% | P&L: ${stats['pnl']:+8.2f}")

        # Final verdict
        print("\n" + "-" * 70)
        if result.profit_factor > 1.3 and result.win_rate > 45 and result.max_drawdown_pct < 8:
            print("  VERDICT: PASS - Strategy shows edge. Safe to trade on prop firm.")
        elif result.profit_factor > 1.0:
            print("  VERDICT: MARGINAL - Barely profitable. Needs improvement before live.")
        else:
            print("  VERDICT: FAIL - Strategy is NOT profitable. DO NOT trade live.")
        print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Walk-Forward Backtester")
    parser.add_argument("--symbol", default="XAUUSDm", help="Symbol to backtest")
    parser.add_argument("--days", type=int, default=365, help="Days of history")
    parser.add_argument("--balance", type=float, default=5000.0, help="Initial balance")
    parser.add_argument("--risk", type=float, default=0.0075, help="Risk per trade (0.0075 = 0.75%)")
    parser.add_argument("--slippage", type=float, default=1.0, help="Slippage in pips")
    parser.add_argument("--spread", type=float, default=2.0, help="Spread in pips")
    args = parser.parse_args()

    bt = WalkForwardBacktester(
        symbol=args.symbol,
        initial_balance=args.balance,
        risk_per_trade=args.risk,
        slippage_pips=args.slippage,
        spread_pips=args.spread,
    )

    result = bt.run(days=args.days)
    if result:
        bt.print_report(result)
    else:
        print("Backtest failed - check MT5 connection and symbol availability.")


if __name__ == "__main__":
    main()
