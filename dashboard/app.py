"""
=============================================================================
Web Dashboard
=============================================================================
Flask-based real-time monitoring dashboard for the trading bot.
Shows account status, open positions, trade history, AI predictions,
and technical analysis charts.
=============================================================================
"""

import json
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
import logging
import threading
from core.mt5_lock import mt5_safe as mt5

from config.settings import config

logger = logging.getLogger(__name__)


class Dashboard:
    """Web dashboard for monitoring the trading bot."""

    def __init__(self, bot=None):
        self.app = Flask(__name__, template_folder="templates")
        self.app.secret_key = config.dashboard.secret_key
        self.bot = bot
        self._setup_routes()

    def _setup_routes(self):
        """Register all dashboard routes."""

        @self.app.route("/")
        def index():
            return render_template("index.html")

        @self.app.route("/api/status")
        def api_status():
            """Get bot status and account info."""
            if self.bot is None:
                return jsonify({"error": "Bot not initialized"})

            try:
                account = self.bot.connector.get_account_info() or {}
                risk = self.bot.risk_manager.get_risk_summary() if self.bot.risk_manager else {}
                session = {}
                try:
                    from analysis.sentiment import SentimentAnalyzer
                    sa = SentimentAnalyzer()
                    session = sa.get_market_session()
                except:
                    pass

                return jsonify({
                    "account": account,
                    "risk": risk,
                    "session": session,
                    "bot_running": self.bot.running,
                    "mode": config.trading.mode.value,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as e:
                return jsonify({"error": str(e)})

        @self.app.route("/api/bot-performance")
        def api_bot_performance():
            """Get overall bot performance: total profit, ROI, trade stats."""
            if self.bot is None:
                return jsonify({"error": "Bot not initialized"})
            try:
                from collections import defaultdict

                account = self.bot.connector.get_account_info() or {}
                balance = account.get("balance", 0)
                equity = account.get("equity", 0)
                unrealized_pnl = account.get("profit", 0)  # open position P&L

                # All-time deals from MT5
                deals = self.bot.connector.get_history_deals(days=3650)  # ~10 years

                # Separate: realized P&L from closed trades, deposits/withdrawals
                realized_pnl = 0
                total_swaps = 0
                total_commission = 0
                total_closed = 0
                wins = 0
                losses = 0
                best_trade = 0
                worst_trade = 0
                deposits = 0
                withdrawals = 0
                symbol_pnl = defaultdict(lambda: {"profit": 0, "trades": 0, "wins": 0, "losses": 0})
                daily_equity = []

                for d in deals:
                    sym = d.get("symbol", "")
                    # Deposit/withdrawal (no symbol)
                    if not sym:
                        if d["profit"] > 0:
                            deposits += d["profit"]
                        elif d["profit"] < 0:
                            withdrawals += abs(d["profit"])
                        continue
                    # Skip zero-impact deals (entry side)
                    net = d["profit"] + d.get("swap", 0) + d.get("commission", 0)
                    if d["profit"] == 0 and d.get("swap", 0) == 0 and d.get("commission", 0) == 0:
                        continue
                    realized_pnl += net
                    total_swaps += d.get("swap", 0)
                    total_commission += d.get("commission", 0)
                    total_closed += 1
                    if net > 0:
                        wins += 1
                    elif net < 0:
                        losses += 1
                    best_trade = max(best_trade, net)
                    worst_trade = min(worst_trade, net)
                    symbol_pnl[sym]["profit"] += net
                    symbol_pnl[sym]["trades"] += 1
                    if net > 0:
                        symbol_pnl[sym]["wins"] += 1
                    elif net < 0:
                        symbol_pnl[sym]["losses"] += 1

                total_pnl = realized_pnl + unrealized_pnl
                starting_balance = deposits - withdrawals - realized_pnl
                if starting_balance <= 0:
                    starting_balance = deposits if deposits > 0 else balance
                roi = (total_pnl / starting_balance * 100) if starting_balance > 0 else 0
                win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
                profit_factor = (abs(sum(s["profit"] for s in symbol_pnl.values() if s["profit"] > 0)) /
                                 abs(sum(s["profit"] for s in symbol_pnl.values() if s["profit"] < 0)))\
                    if any(s["profit"] < 0 for s in symbol_pnl.values()) else 0

                # Open positions count & unrealized
                open_positions = []
                try:
                    pos = mt5.positions_get()
                    if pos:
                        for p in pos:
                            open_positions.append({
                                "symbol": p.symbol, "type": "BUY" if p.type == 0 else "SELL",
                                "volume": p.volume, "profit": round(p.profit, 2),
                                "swap": round(p.swap, 2),
                            })
                except Exception:
                    pass

                # Per-symbol breakdown
                sym_list = []
                for sym, info in sorted(symbol_pnl.items(), key=lambda x: x[1]["profit"], reverse=True):
                    wr = (info["wins"] / info["trades"] * 100) if info["trades"] > 0 else 0
                    sym_list.append({
                        "symbol": sym, "profit": round(info["profit"], 2),
                        "trades": info["trades"], "wins": info["wins"],
                        "losses": info["losses"], "win_rate": round(wr, 1),
                    })

                return jsonify({
                    "total_pnl": round(total_pnl, 2),
                    "realized_pnl": round(realized_pnl, 2),
                    "unrealized_pnl": round(unrealized_pnl, 2),
                    "total_swaps": round(total_swaps, 2),
                    "total_commission": round(total_commission, 2),
                    "balance": round(balance, 2),
                    "equity": round(equity, 2),
                    "starting_balance": round(starting_balance, 2),
                    "deposits": round(deposits, 2),
                    "roi_pct": round(roi, 2),
                    "total_closed_trades": total_closed,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": round(win_rate, 1),
                    "profit_factor": round(profit_factor, 2),
                    "best_trade": round(best_trade, 2),
                    "worst_trade": round(worst_trade, 2),
                    "open_positions": open_positions,
                    "open_count": len(open_positions),
                    "by_symbol": sym_list,
                })
            except Exception as e:
                logger.error(f"Bot performance API error: {e}", exc_info=True)
                return jsonify({"error": str(e)})

        @self.app.route("/api/positions")
        def api_positions():
            """Get open positions."""
            if self.bot is None:
                return jsonify([])
            try:
                positions = self.bot.connector.get_bot_positions()
                return jsonify(positions)
            except Exception as e:
                return jsonify({"error": str(e)})

        @self.app.route("/api/trades")
        def api_trades():
            """Get trade history enriched with P&L from MT5."""
            if self.bot is None:
                return jsonify([])
            try:
                trades = self.bot.trade_logger.get_trade_history()

                # Build lookup: ticket -> deal P&L from MT5 history
                deal_pnl = {}  # ticket -> {profit, swap, commission, status}
                try:
                    deals = self.bot.connector.get_history_deals(days=90)
                    for d in deals:
                        order_id = str(d.get("order", ""))
                        if order_id and d.get("symbol", ""):
                            net = d["profit"] + d.get("swap", 0) + d.get("commission", 0)
                            # Keep the closing-side deal (the one with profit != 0)
                            if net != 0 or d["profit"] != 0:
                                deal_pnl[order_id] = {
                                    "profit": round(d["profit"], 2),
                                    "net": round(net, 2),
                                    "swap": round(d.get("swap", 0), 2),
                                    "commission": round(d.get("commission", 0), 2),
                                    "status": "CLOSED",
                                }
                except Exception:
                    pass

                # Build lookup: ticket -> open position P&L
                open_pnl = {}
                try:
                    positions = mt5.positions_get()
                    if positions:
                        for p in positions:
                            open_pnl[str(p.ticket)] = {
                                "profit": round(p.profit, 2),
                                "net": round(p.profit + p.swap, 2),
                                "swap": round(p.swap, 2),
                                "commission": round(p.commission if hasattr(p, 'commission') else 0, 2),
                                "status": "OPEN",
                            }
                except Exception:
                    pass

                # Enrich trades with P&L
                enriched = []
                for t in trades:
                    ticket = str(t.get("ticket", ""))
                    pnl_info = deal_pnl.get(ticket) or open_pnl.get(ticket)
                    t["pnl"] = pnl_info["net"] if pnl_info else None
                    t["pnl_profit"] = pnl_info["profit"] if pnl_info else None
                    t["pnl_swap"] = pnl_info["swap"] if pnl_info else None
                    t["pnl_status"] = pnl_info["status"] if pnl_info else t.get("result", "")
                    enriched.append(t)

                return jsonify(enriched[-50:])
            except Exception as e:
                return jsonify({"error": str(e)})

        @self.app.route("/api/analysis/<symbol>")
        def api_analysis(symbol):
            """Get technical analysis for a symbol."""
            if self.bot is None:
                return jsonify({"error": "Bot not initialized"})
            try:
                from analysis.technical import TechnicalAnalyzer
                ta = TechnicalAnalyzer()
                df = self.bot.data_fetcher.get_ohlcv(symbol, count=200)
                if df is None:
                    return jsonify({"error": f"No data for {symbol}"})
                signal = ta.generate_signal(df)
                return jsonify({
                    "symbol": symbol,
                    "signal": signal,
                    "price": float(df["close"].iloc[-1]),
                    "prices": df["close"].tail(100).tolist(),
                    "timestamps": [t.isoformat() for t in df.tail(100).index],
                })
            except Exception as e:
                return jsonify({"error": str(e)})

        @self.app.route("/api/ai/<symbol>")
        def api_ai_prediction(symbol):
            """Get AI prediction for a symbol."""
            if self.bot is None:
                return jsonify({"error": "Bot not initialized"})
            try:
                df = self.bot.data_fetcher.get_ohlcv(symbol, count=500)
                if df is None:
                    return jsonify({"error": f"No data for {symbol}"})
                prediction = self.bot.ai_predictor.predict(df)
                return jsonify({"symbol": symbol, "prediction": prediction})
            except Exception as e:
                return jsonify({"error": str(e)})

        @self.app.route("/api/close/<int:ticket>", methods=["POST"])
        def api_close_position(ticket):
            """Close a specific position."""
            if self.bot is None:
                return jsonify({"error": "Bot not initialized"})
            try:
                result = self.bot.order_manager.close_position(ticket)
                return jsonify({"success": result, "ticket": ticket})
            except Exception as e:
                return jsonify({"error": str(e)})

        @self.app.route("/api/close-all", methods=["POST"])
        def api_close_all():
            """Close all positions."""
            if self.bot is None:
                return jsonify({"error": "Bot not initialized"})
            try:
                closed = self.bot.order_manager.close_all_positions()
                return jsonify({"closed": closed})
            except Exception as e:
                return jsonify({"error": str(e)})

        @self.app.route("/api/symbols")
        def api_symbols():
            """Get configured trading symbols."""
            return jsonify(config.trading.symbols)

        @self.app.route("/api/config")
        def api_config():
            """Get bot configuration (non-sensitive)."""
            return jsonify({
                "mode": config.trading.mode.value,
                "symbols": config.trading.symbols,
                "max_risk_per_trade": config.risk.max_risk_per_trade,
                "max_daily_risk": config.risk.max_daily_risk,
                "max_drawdown": config.risk.max_drawdown,
                "risk_reward_ratio": config.risk.risk_reward_ratio,
                "max_open_trades": config.trading.max_open_trades,
                "ai_confidence_threshold": config.ai.min_confidence,
            })

        @self.app.route("/api/news")
        def api_news():
            """Get economic calendar and news filter status."""
            if self.bot is None:
                return jsonify({"error": "Bot not initialized"})
            try:
                summary = self.bot.news_analyzer.get_calendar_summary()
                # Add per-symbol trade permission
                symbol_status = {}
                for sym in config.trading.symbols:
                    can_trade, reason, size_factor = self.bot.news_analyzer.should_trade(sym)
                    symbol_status[sym] = {
                        "can_trade": can_trade,
                        "reason": reason,
                        "size_factor": size_factor,
                    }
                summary["symbol_status"] = symbol_status
                return jsonify(summary)
            except Exception as e:
                return jsonify({"error": str(e)})

        @self.app.route("/api/news/sentiment/<symbol>")
        def api_news_sentiment(symbol):
            """Get news-based sentiment for a symbol."""
            if self.bot is None:
                return jsonify({"error": "Bot not initialized"})
            try:
                sentiment = self.bot.news_analyzer.get_news_sentiment(symbol)
                return jsonify({"symbol": symbol, "sentiment": sentiment})
            except Exception as e:
                return jsonify({"error": str(e)})

        # ─── Profit & Loss Summary API ────────────────────────────

        @self.app.route("/api/pnl")
        def api_pnl():
            """Get profit/loss breakdown by period with filter options.

            Query params:
                period  - day | week | month | year  (grouping granularity)
                days    - how many days of history to fetch (default 365)
                symbol  - optional symbol filter
            """
            if self.bot is None:
                return jsonify({"error": "Bot not initialized"})
            try:
                from datetime import datetime, timedelta
                from collections import defaultdict
                import calendar

                period = request.args.get("period", "day")
                days = int(request.args.get("days", 365))
                symbol_filter = request.args.get("symbol", None)

                # Fetch deal history from MT5
                deals = self.bot.connector.get_history_deals(days=days)

                # Filter: only exit deals (type 0=buy deal-in, 1=sell deal-in;
                # but profit!=0 indicates closing deals). We keep deals where
                # profit != 0 OR the deal type indicates close.
                # MT5 deal types: 0=BUY, 1=SELL.  Entry field: 0=IN, 1=OUT, 2=INOUT, 3=OUT_BY
                closed_deals = []
                for d in deals:
                    # Skip balance / credit / commission-only entries
                    if d.get("symbol", "") == "":
                        continue
                    # Keep deals that have actual P&L (closing side)
                    if d["profit"] == 0 and d["swap"] == 0 and d["commission"] == 0:
                        continue
                    if symbol_filter and d["symbol"] != symbol_filter:
                        continue
                    closed_deals.append(d)

                # --- Group by period ---
                def _period_key(dt, period):
                    if period == "day":
                        return dt.strftime("%Y-%m-%d")
                    elif period == "week":
                        iso = dt.isocalendar()
                        return f"{iso[0]}-W{iso[1]:02d}"
                    elif period == "month":
                        return dt.strftime("%Y-%m")
                    elif period == "year":
                        return dt.strftime("%Y")
                    return dt.strftime("%Y-%m-%d")

                groups = defaultdict(lambda: {"profit": 0, "swap": 0, "commission": 0,
                                              "trades": 0, "wins": 0, "losses": 0,
                                              "gross_profit": 0, "gross_loss": 0,
                                              "best": 0, "worst": 0})

                total_profit = 0
                total_trades = 0
                total_wins = 0
                total_losses = 0
                best_trade = 0
                worst_trade = 0

                for d in closed_deals:
                    dt = d["time"] if isinstance(d["time"], datetime) else datetime.fromtimestamp(d["time"])
                    key = _period_key(dt, period)
                    net = d["profit"] + d["swap"] + d["commission"]
                    g = groups[key]
                    g["profit"] += net
                    g["swap"] += d["swap"]
                    g["commission"] += d["commission"]
                    g["trades"] += 1
                    if net > 0:
                        g["wins"] += 1
                        g["gross_profit"] += net
                    elif net < 0:
                        g["losses"] += 1
                        g["gross_loss"] += net
                    g["best"] = max(g["best"], net)
                    g["worst"] = min(g["worst"], net)

                    total_profit += net
                    total_trades += 1
                    if net > 0:
                        total_wins += 1
                    elif net < 0:
                        total_losses += 1
                    best_trade = max(best_trade, net)
                    worst_trade = min(worst_trade, net)

                # Build sorted period list
                period_list = []
                for key in sorted(groups.keys(), reverse=True):
                    g = groups[key]
                    wr = (g["wins"] / g["trades"] * 100) if g["trades"] > 0 else 0
                    period_list.append({
                        "period": key,
                        "profit": round(g["profit"], 2),
                        "swap": round(g["swap"], 2),
                        "commission": round(g["commission"], 2),
                        "trades": g["trades"],
                        "wins": g["wins"],
                        "losses": g["losses"],
                        "win_rate": round(wr, 1),
                        "gross_profit": round(g["gross_profit"], 2),
                        "gross_loss": round(g["gross_loss"], 2),
                        "best": round(g["best"], 2),
                        "worst": round(g["worst"], 2),
                    })

                # Quick summaries for Today / This Week / This Month / This Year
                now = datetime.now()
                today_key = now.strftime("%Y-%m-%d")
                iso = now.isocalendar()
                week_key = f"{iso[0]}-W{iso[1]:02d}"
                month_key = now.strftime("%Y-%m")
                year_key = now.strftime("%Y")

                def _summary(key, grp):
                    g = grp.get(key)
                    if g is None:
                        return {"profit": 0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0}
                    wr = (g["wins"] / g["trades"] * 100) if g["trades"] > 0 else 0
                    return {"profit": round(g["profit"], 2), "trades": g["trades"],
                            "wins": g["wins"], "losses": g["losses"], "win_rate": round(wr, 1)}

                # Build day-groups, week-groups etc for summaries
                day_groups = defaultdict(lambda: {"profit": 0, "trades": 0, "wins": 0, "losses": 0})
                week_groups = defaultdict(lambda: {"profit": 0, "trades": 0, "wins": 0, "losses": 0})
                month_groups = defaultdict(lambda: {"profit": 0, "trades": 0, "wins": 0, "losses": 0})
                year_groups = defaultdict(lambda: {"profit": 0, "trades": 0, "wins": 0, "losses": 0})

                for d in closed_deals:
                    dt = d["time"] if isinstance(d["time"], datetime) else datetime.fromtimestamp(d["time"])
                    net = d["profit"] + d["swap"] + d["commission"]
                    for gmap, kfn in [(day_groups, lambda t: t.strftime("%Y-%m-%d")),
                                       (week_groups, lambda t: f"{t.isocalendar()[0]}-W{t.isocalendar()[1]:02d}"),
                                       (month_groups, lambda t: t.strftime("%Y-%m")),
                                       (year_groups, lambda t: t.strftime("%Y"))]:
                        k = kfn(dt)
                        gmap[k]["profit"] += net
                        gmap[k]["trades"] += 1
                        if net > 0:
                            gmap[k]["wins"] += 1
                        elif net < 0:
                            gmap[k]["losses"] += 1

                def _quick(key, gmap):
                    g = gmap.get(key)
                    if g is None:
                        return {"profit": 0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0}
                    wr = (g["wins"] / g["trades"] * 100) if g["trades"] > 0 else 0
                    return {"profit": round(g["profit"], 2), "trades": g["trades"],
                            "wins": g["wins"], "losses": g["losses"], "win_rate": round(wr, 1)}

                win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

                return jsonify({
                    "total_profit": round(total_profit, 2),
                    "total_trades": total_trades,
                    "total_wins": total_wins,
                    "total_losses": total_losses,
                    "win_rate": round(win_rate, 1),
                    "best_trade": round(best_trade, 2),
                    "worst_trade": round(worst_trade, 2),
                    "today": _quick(today_key, day_groups),
                    "this_week": _quick(week_key, week_groups),
                    "this_month": _quick(month_key, month_groups),
                    "this_year": _quick(year_key, year_groups),
                    "periods": period_list,
                    "filter": {"period": period, "days": days, "symbol": symbol_filter},
                })
            except Exception as e:
                logger.error(f"PnL API error: {e}", exc_info=True)
                return jsonify({"error": str(e)})

        # ─── Live Chart Page & API ───────────────────────────────

        @self.app.route("/chart")
        def chart_page():
            return render_template("chart.html")

        TIMEFRAME_LWC_MAP = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1,
        }

        @self.app.route("/api/chart/<symbol>")
        def api_chart_data(symbol):
            """Get OHLCV candles, trade markers, positions for the live chart."""
            if self.bot is None:
                return jsonify({"error": "Bot not initialized"})
            try:
                tf_str = request.args.get("tf", "H1").upper()
                mt5_tf = TIMEFRAME_LWC_MAP.get(tf_str, mt5.TIMEFRAME_H1)

                # Fetch OHLCV
                self.bot.connector.enable_symbol(symbol)
                rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, 500)
                if rates is None or len(rates) == 0:
                    return jsonify({"error": f"No data for {symbol}"})

                import pandas as pd
                df = pd.DataFrame(rates)

                # Build candle data for lightweight-charts (UTC timestamp)
                candles = []
                volumes = []
                for _, row in df.iterrows():
                    t = int(row["time"])
                    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
                    candles.append({"time": t, "open": o, "high": h, "low": l, "close": c})
                    vol_color = "rgba(0,212,170,0.35)" if c >= o else "rgba(255,71,87,0.35)"
                    volumes.append({"time": t, "value": float(row["tick_volume"]), "color": vol_color})

                # Current tick
                tick = mt5.symbol_info_tick(symbol)
                tick_data = None
                if tick:
                    tick_data = {
                        "bid": tick.bid,
                        "ask": tick.ask,
                        "spread": int(round((tick.ask - tick.bid) / mt5.symbol_info(symbol).point)) if mt5.symbol_info(symbol) else 0,
                    }

                # Day change %
                day_change = None
                if len(candles) >= 2:
                    prev_close = candles[-2]["close"]
                    cur_close = candles[-1]["close"]
                    if prev_close > 0:
                        day_change = ((cur_close - prev_close) / prev_close) * 100

                # ─── Trade markers from CSV history ────────────────
                trade_markers = []
                min_time = candles[0]["time"] if candles else 0
                max_time = candles[-1]["time"] if candles else 0
                try:
                    trades = self.bot.trade_logger.get_trade_history()
                    for t in trades:
                        if t.get("symbol") != symbol:
                            continue
                        ts_str = t.get("timestamp", "")
                        if not ts_str:
                            continue
                        try:
                            dt = datetime.fromisoformat(ts_str)
                            ts = int(dt.timestamp())
                        except:
                            continue
                        if ts < min_time or ts > max_time:
                            continue
                        # Snap to nearest candle time
                        closest_t = min(candles, key=lambda c: abs(c["time"] - ts))["time"]
                        trade_markers.append({
                            "time": closest_t,
                            "type": t.get("action", "BUY"),
                            "volume": t.get("volume", ""),
                            "price": float(t.get("entry_price", 0)),
                            "strategy": t.get("strategy", ""),
                            "confidence": float(t.get("confidence", 0)),
                            "ticket": t.get("ticket", ""),
                            "result": t.get("result", ""),
                        })
                except Exception as e:
                    logger.debug(f"Trade markers error: {e}")

                # ─── Open positions for this symbol ────────────────
                positions = []
                try:
                    all_pos = self.bot.connector.get_positions(symbol)
                    for p in all_pos:
                        positions.append({
                            "ticket": p["ticket"],
                            "type": p["type"],
                            "volume": p["volume"],
                            "price_open": p["price_open"],
                            "price_current": p["price_current"],
                            "sl": p["sl"],
                            "tp": p["tp"],
                            "profit": p["profit"],
                        })
                except Exception as e:
                    logger.debug(f"Positions error: {e}")

                # ─── Trade history for this symbol ─────────────────
                trade_history = []
                try:
                    all_trades = self.bot.trade_logger.get_trade_history()
                    trade_history = [t for t in all_trades if t.get("symbol") == symbol][-10:]
                except Exception:
                    pass

                return jsonify({
                    "symbol": symbol,
                    "timeframe": tf_str,
                    "candles": candles,
                    "volumes": volumes,
                    "tick": tick_data,
                    "day_change": day_change,
                    "trade_markers": trade_markers,
                    "positions": positions,
                    "trade_history": trade_history,
                })
            except Exception as e:
                logger.error(f"Chart API error: {e}", exc_info=True)
                return jsonify({"error": str(e)})

        @self.app.route("/api/tick/<symbol>")
        def api_tick(symbol):
            """Lightweight live tick endpoint — called every 1-2 s."""
            try:
                tick = mt5.symbol_info_tick(symbol)
                if tick is None:
                    return jsonify({"error": "No tick"})

                sym_info = mt5.symbol_info(symbol)
                point = sym_info.point if sym_info else 0.00001

                # Also send latest 1-min OHLCV so the last candle can update in real-time
                last_bar = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 1)
                bar = None
                if last_bar is not None and len(last_bar) > 0:
                    r = last_bar[0]
                    bar = {
                        "time": int(r["time"]),
                        "open": float(r["open"]),
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                        "volume": float(r["tick_volume"]),
                    }

                # Positions P&L snapshot
                positions = []
                try:
                    pos_list = mt5.positions_get(symbol=symbol)
                    if pos_list:
                        for p in pos_list:
                            positions.append({
                                "ticket": p.ticket,
                                "type": "BUY" if p.type == 0 else "SELL",
                                "volume": p.volume,
                                "profit": p.profit,
                                "price_current": p.price_current,
                            })
                except Exception:
                    pass

                return jsonify({
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "last": tick.last,
                    "time": int(tick.time),
                    "spread": int(round((tick.ask - tick.bid) / point)) if point > 0 else 0,
                    "bar": bar,
                    "positions": positions,
                })
            except Exception as e:
                return jsonify({"error": str(e)})

    def run(self, threaded: bool = True):
        """Start the dashboard server."""
        if threaded:
            thread = threading.Thread(
                target=self.app.run,
                kwargs={
                    "host": config.dashboard.host,
                    "port": config.dashboard.port,
                    "debug": False,
                    "use_reloader": False,
                },
                daemon=True,
            )
            thread.start()
            logger.info(f"Dashboard running at http://{config.dashboard.host}:{config.dashboard.port}")
        else:
            self.app.run(
                host=config.dashboard.host,
                port=config.dashboard.port,
                debug=config.dashboard.debug,
            )


def run_standalone_dashboard():
    """Run dashboard in standalone mode without MT5 connection (for preview)."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.logger import setup_logging
    setup_logging()

    dashboard = Dashboard(bot=None)

    # Add mock API responses for preview
    @dashboard.app.route("/api/status")
    def mock_status():
        from analysis.sentiment import SentimentAnalyzer
        sa = SentimentAnalyzer()
        session = sa.get_market_session()
        return jsonify({
            "account": {
                "login": 0,
                "server": "Not Connected",
                "balance": 10000.00,
                "equity": 10000.00,
                "margin": 0,
                "free_margin": 10000.00,
                "margin_level": 0,
                "profit": 0,
                "leverage": 100,
                "currency": "USD",
                "trade_allowed": False,
            },
            "risk": {
                "balance": 10000.00,
                "equity": 10000.00,
                "peak_equity": 10000.00,
                "drawdown": 0,
                "max_drawdown_limit": 15,
                "open_positions": 0,
                "max_positions": 5,
                "total_exposure_lots": 0,
                "unrealized_pnl": 0,
                "is_trading_hours": True,
                "daily_loss_exceeded": False,
                "drawdown_exceeded": False,
            },
            "session": session,
            "bot_running": False,
            "mode": "demo",
            "timestamp": datetime.now().isoformat(),
        })

    logger.info(f"Starting standalone dashboard at http://{config.dashboard.host}:{config.dashboard.port}")
    logger.info("NOTE: Running in preview mode without MT5 connection")
    logger.info("To connect to MT5, set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER environment variables and run: python main.py")
    dashboard.run(threaded=False)


if __name__ == "__main__":
    run_standalone_dashboard()
