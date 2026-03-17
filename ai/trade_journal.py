"""
=============================================================================
TRADE JOURNAL & LEARNING SYSTEM
=============================================================================
Persistent learning engine that:
1. Records daily trading summaries after each session
2. Identifies recurring patterns (bad hours, bad strategies, overtrading)
3. Generates adaptive rules that the bot uses to filter future trades
4. Tracks what works and what doesn't over time

The bot reads these lessons before each trading cycle to avoid
repeating past mistakes.
=============================================================================
"""

import json
import os
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

JOURNAL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "journal")
LESSONS_FILE = os.path.join(JOURNAL_DIR, "lessons_learned.json")
DAILY_DIR = os.path.join(JOURNAL_DIR, "daily")


def _ensure_dirs():
    os.makedirs(JOURNAL_DIR, exist_ok=True)
    os.makedirs(DAILY_DIR, exist_ok=True)


class TradingJournal:
    """
    Persistent learning system. Saves daily analysis and distills
    actionable lessons that the bot reads every cycle.
    """

    def __init__(self):
        _ensure_dirs()
        self._lessons = self._load_lessons()
        # In-memory accumulators for current session
        self._session_trades: List[Dict] = []
        self._session_start = datetime.now()

    # ─── Lesson Persistence ──────────────────────────────────────────

    def _load_lessons(self) -> Dict:
        """Load accumulated lessons from disk."""
        if os.path.exists(LESSONS_FILE):
            try:
                with open(LESSONS_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "version": 1,
            "last_updated": None,
            "bad_hours_utc": [],          # Hours with consistently negative P&L
            "good_hours_utc": [],         # Hours with consistently positive P&L
            "max_trades_per_day": 10,     # Adaptive cap (starts conservative)
            "min_hold_minutes": 5,        # Minimum hold time before closing
            "avoid_direction": {},        # e.g. {"XAUUSD": "SELL"} if sells keep losing
            "strategy_penalties": {},     # Reduce weight for underperforming strategies
            "overtrading_threshold": 8,   # Trades/day that triggers overtrading warning
            "min_profit_to_close": 0.0,   # Minimum $ profit before trailing stop can close
            "consecutive_day_losses": 0,  # Days in a row with net loss
            "daily_summaries": [],        # Last 30 days summary
            "rules": [],                  # Human-readable rules derived from data
        }

    def _save_lessons(self):
        """Persist lessons to disk."""
        self._lessons["last_updated"] = datetime.now().isoformat()
        try:
            with open(LESSONS_FILE, "w") as f:
                json.dump(self._lessons, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save lessons: {e}")

    # ─── Recording ────────────────────────────────────────────────────

    def record_trade(self, trade_data: Dict):
        """Record a single trade result for end-of-day analysis."""
        self._session_trades.append({
            "time": datetime.now().isoformat(),
            "symbol": trade_data.get("symbol", ""),
            "direction": trade_data.get("direction", ""),
            "profit": trade_data.get("profit", 0),
            "hold_minutes": trade_data.get("hold_minutes", 0),
            "strategy": trade_data.get("strategy", ""),
            "entry_hour_utc": trade_data.get("entry_hour_utc", 0),
        })

    def save_daily_summary(self, analysis: Dict):
        """
        Save a daily performance summary and derive new lessons.
        Called at end of trading day or when bot stops.
        """
        today = date.today().isoformat()
        filepath = os.path.join(DAILY_DIR, f"{today}.json")

        # Save raw daily data
        try:
            with open(filepath, "w") as f:
                json.dump(analysis, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save daily summary: {e}")

        # Derive lessons from this day's data
        self._derive_lessons(analysis)
        self._save_lessons()

        logger.info(f"JOURNAL: Daily summary saved. Active rules: {len(self._lessons['rules'])}")

    def _derive_lessons(self, analysis: Dict):
        """
        Analyze a daily summary and update lessons.
        This is the 'learning' part — finds patterns and creates rules.
        """
        lessons = self._lessons

        # ─── 1. Bad/Good Hours ────────────────────────────────────
        hour_perf = analysis.get("hour_performance", {})
        bad_hours = set(lessons.get("bad_hours_utc", []))
        good_hours = set(lessons.get("good_hours_utc", []))

        for hour_str, stats in hour_perf.items():
            hour = int(hour_str)
            total = stats["wins"] + stats["losses"]
            if total >= 2:  # Need at least 2 trades to judge
                wr = stats["wins"] / total
                if wr <= 0.30 and stats["pnl"] < 0:
                    bad_hours.add(hour)
                    good_hours.discard(hour)
                elif wr >= 0.70 and stats["pnl"] > 0:
                    good_hours.add(hour)
                    bad_hours.discard(hour)

        lessons["bad_hours_utc"] = sorted(list(bad_hours))
        lessons["good_hours_utc"] = sorted(list(good_hours))

        # ─── 2. Overtrading Detection ────────────────────────────
        total_trades = analysis.get("total_trades", 0)
        net_profit = analysis.get("net_profit", 0)
        win_rate = analysis.get("win_rate", 50)

        if total_trades > 15 and win_rate < 50:
            # Too many trades with poor win rate = overtrading
            lessons["overtrading_threshold"] = max(
                2, lessons.get("overtrading_threshold", 8) - 1
            )
            lessons["max_trades_per_day"] = max(2, min(total_trades // 3, 6))

        # ─── 3. Direction Bias ────────────────────────────────────
        dir_perf = analysis.get("direction_performance", {})
        for direction, stats in dir_perf.items():
            total = stats["wins"] + stats["losses"]
            if total >= 3:
                wr = stats["wins"] / total
                if wr == 0 and stats["pnl"] < -10:
                    # This direction is pure loss — flag it
                    # Check which symbol (for now assume primary)
                    lessons["avoid_direction"] = lessons.get("avoid_direction", {})
                    # Only temporary avoidance (cleared on next profitable day)
                    lessons["avoid_direction"]["_last_bad"] = direction
                    lessons["avoid_direction"]["_bad_date"] = date.today().isoformat()

        # ─── 4. Strategy Performance ──────────────────────────────
        strat_perf = analysis.get("strategy_performance", {})
        penalties = lessons.get("strategy_penalties", {})
        for strat, stats in strat_perf.items():
            total = stats["wins"] + stats["losses"]
            if total >= 3:
                wr = stats["wins"] / total
                if wr < 0.35 and stats["pnl"] < 0:
                    penalties[strat] = min(
                        penalties.get(strat, 0) + 0.1, 0.5
                    )
                elif wr > 0.60 and stats["pnl"] > 0:
                    penalties[strat] = max(
                        penalties.get(strat, 0) - 0.1, 0.0
                    )
        lessons["strategy_penalties"] = penalties

        # ─── 5. Hold Time Analysis ────────────────────────────────
        avg_loss = abs(analysis.get("avg_loss", 0))
        avg_win = analysis.get("avg_win", 0)
        if avg_win > 0 and avg_loss > 0:
            if avg_win < avg_loss * 0.5:
                # Wins are way smaller than losses — holding winners too short
                lessons["min_hold_minutes"] = max(
                    lessons.get("min_hold_minutes", 5), 15
                )

        # ─── 6. Consecutive Loss Days ────────────────────────────
        if net_profit < 0:
            lessons["consecutive_day_losses"] = lessons.get("consecutive_day_losses", 0) + 1
        else:
            lessons["consecutive_day_losses"] = 0

        # ─── 7. Generate Human-Readable Rules ────────────────────
        rules = []
        if lessons["bad_hours_utc"]:
            hours_str = ", ".join(f"{h}:00" for h in lessons["bad_hours_utc"])
            rules.append(f"AVOID trading at UTC hours: {hours_str} (historically losing)")

        if lessons.get("overtrading_threshold", 8) < 8:
            rules.append(f"MAX {lessons['max_trades_per_day']} trades/day (overtrading detected)")

        bad_dir = lessons.get("avoid_direction", {}).get("_last_bad")
        if bad_dir:
            bad_date = lessons["avoid_direction"].get("_bad_date", "")
            rules.append(f"CAUTION: {bad_dir} direction had 0% WR on {bad_date}")

        for strat, penalty in lessons.get("strategy_penalties", {}).items():
            if penalty > 0.2:
                rules.append(f"PENALIZE strategy '{strat}' (weight -{penalty:.0%})")

        if lessons.get("consecutive_day_losses", 0) >= 2:
            rules.append(f"WARNING: {lessons['consecutive_day_losses']} consecutive losing days")

        if lessons.get("min_hold_minutes", 5) > 5:
            rules.append(f"HOLD trades minimum {lessons['min_hold_minutes']}min before closing")

        lessons["rules"] = rules

        # ─── 8. Keep rolling 30-day window ────────────────────────
        summary = {
            "date": date.today().isoformat(),
            "trades": total_trades,
            "win_rate": round(win_rate, 1),
            "net_profit": round(net_profit, 2),
        }
        summaries = lessons.get("daily_summaries", [])
        summaries.append(summary)
        lessons["daily_summaries"] = summaries[-30:]  # Keep last 30 days

    # ─── Query Methods (used by bot during trading) ──────────────────

    def get_lessons(self) -> Dict:
        """Return current lessons for the bot to use."""
        return self._lessons

    def is_bad_hour(self, hour_utc: int) -> bool:
        """Check if this hour has been historically bad."""
        return hour_utc in self._lessons.get("bad_hours_utc", [])

    def is_overtrading(self, trades_today: int) -> bool:
        """Check if we've exceeded the learned trade limit."""
        return trades_today >= self._lessons.get("max_trades_per_day", 10)

    def get_strategy_penalty(self, strategy_name: str) -> float:
        """Get penalty multiplier for a strategy (0.0 = no penalty, 0.5 = halve weight)."""
        return self._lessons.get("strategy_penalties", {}).get(strategy_name, 0.0)

    def should_avoid_direction(self, direction: str) -> bool:
        """Check if a direction should be avoided based on recent performance."""
        avoid = self._lessons.get("avoid_direction", {})
        bad_dir = avoid.get("_last_bad")
        bad_date = avoid.get("_bad_date", "")
        if bad_dir and bad_dir == direction:
            # Only avoid for 1 day after the bad day
            try:
                bad_dt = date.fromisoformat(bad_date)
                if (date.today() - bad_dt).days <= 1:
                    return True
            except Exception:
                pass
        return False

    def get_min_hold_minutes(self) -> int:
        """Get minimum hold time before allowing position close."""
        return self._lessons.get("min_hold_minutes", 5)

    def get_active_rules(self) -> List[str]:
        """Get all currently active rules as human-readable strings."""
        return self._lessons.get("rules", [])

    def log_rules(self):
        """Log all active rules to the bot logger."""
        rules = self.get_active_rules()
        if rules:
            logger.info("=" * 52)
            logger.info("       LESSONS FROM PAST TRADING")
            logger.info("=" * 52)
            for rule in rules:
                logger.info(f"  * {rule}")
            logger.info("=" * 52)
        else:
            logger.info("JOURNAL: No lessons learned yet — first trading day")
