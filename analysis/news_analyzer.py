"""
=============================================================================
News & Economic Calendar Analyzer
=============================================================================
Fetches and analyzes economic news events to:
- Avoid trading during HIGH-impact news releases
- Adjust position sizes around medium-impact news
- Trade WITH the news direction when possible
- Track central bank decisions, NFP, CPI, GDP events

Data Sources:
- ForexFactory economic calendar (free JSON API)
- Fallback: Built-in high-impact event schedule
=============================================================================
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# Try importing requests; fall back to urllib if unavailable
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False


class NewsImpact(Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    HOLIDAY = "Holiday"


@dataclass
class EconomicEvent:
    """Represents a single economic calendar event."""
    title: str
    country: str
    currency: str
    impact: NewsImpact
    datetime_utc: datetime
    forecast: str = ""
    previous: str = ""
    actual: str = ""

    @property
    def is_high_impact(self) -> bool:
        return self.impact == NewsImpact.HIGH

    @property
    def minutes_until(self) -> float:
        now = datetime.now(timezone.utc)
        dt = self.datetime_utc if self.datetime_utc.tzinfo else self.datetime_utc.replace(tzinfo=timezone.utc)
        return (dt - now).total_seconds() / 60.0


@dataclass
class NewsFilter:
    """Configuration for news-based trade filtering."""
    # Don't open trades this many minutes before HIGH impact news
    high_impact_freeze_minutes: int = 30
    # Don't open trades this many minutes after HIGH impact news
    high_impact_cooldown_minutes: int = 15
    # Reduce position size this many minutes before MEDIUM impact
    medium_impact_freeze_minutes: int = 15
    # Position size reduction factor during medium impact (0.5 = half size)
    medium_impact_size_factor: float = 0.5
    # Close positions before these ultra-high events
    close_before_events: List[str] = field(default_factory=lambda: [
        "Non-Farm Employment Change",
        "Nonfarm Payrolls",
        "FOMC Statement",
        "Fed Interest Rate Decision",
        "ECB Interest Rate Decision",
        "BOE Interest Rate Decision",
        "BOJ Interest Rate Decision",
        "CPI y/y",
        "Core CPI m/m",
        "GDP q/q",
    ])


# ─── CURRENCY MAPPING ────────────────────────────────────────────────────
# Maps trading symbols to affected currencies for news filtering
SYMBOL_CURRENCIES = {
    "EURUSDm": ["EUR", "USD"],
    "GBPUSDm": ["GBP", "USD"],
    "USDJPYm": ["USD", "JPY"],
    "XAUUSDm": ["USD", "XAU"],  # Gold reacts to USD news
    "BTCUSDm": ["USD"],          # BTC reacts to USD macro
    "USDCHFm": ["USD", "CHF"],
    "AUDUSDm": ["AUD", "USD"],
    "NZDUSDm": ["NZD", "USD"],
    "USDCADm": ["USD", "CAD"],
    "EURJPYm": ["EUR", "JPY"],
    "GBPJPYm": ["GBP", "JPY"],
    "EURGBPm": ["EUR", "GBP"],
    # Also support lookups without 'm' suffix
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "USDJPY": ["USD", "JPY"],
    "XAUUSD": ["USD", "XAU"],
    "BTCUSD": ["USD"],
}

# ─── HIGH-IMPACT EVENT KEYWORDS ──────────────────────────────────────────
HIGH_IMPACT_KEYWORDS = [
    "non-farm", "nonfarm", "NFP",
    "interest rate", "rate decision",
    "FOMC", "Fed Chair", "ECB President",
    "CPI ", "Consumer Price Index",
    "GDP ", "Gross Domestic Product",
    "employment change", "unemployment rate",
    "PMI ", "ISM Manufacturing",
    "retail sales",
    "central bank",
    "monetary policy",
    "trade balance",
    "inflation",
]


class NewsAnalyzer:
    """
    Fetches and analyzes economic news to make trading decisions.
    
    Key features:
    - Fetches ForexFactory economic calendar
    - Identifies high-impact events for each currency
    - Provides trade filtering (avoid/reduce during news)
    - Assigns directional bias based on actual vs forecast
    """

    # ForexFactory free calendar endpoint
    FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    def __init__(self, news_filter: NewsFilter = None):
        self.filter_config = news_filter or NewsFilter()
        self.events: List[EconomicEvent] = []
        self._last_fetch_time: Optional[datetime] = None
        self._fetch_interval_minutes = 60  # Refresh every hour
        self._cache_dir = Path("cache")
        self._cache_dir.mkdir(exist_ok=True)
        self._cache_file = self._cache_dir / "news_cache.json"

    # ─── DATA FETCHING ───────────────────────────────────────────────────

    def fetch_calendar(self, force: bool = False) -> bool:
        """
        Fetch the economic calendar from ForexFactory.
        Returns True if successful.
        """
        now = datetime.now(timezone.utc)

        # Don't refetch too frequently
        if not force and self._last_fetch_time:
            elapsed = (now - self._last_fetch_time).total_seconds() / 60.0
            if elapsed < self._fetch_interval_minutes and len(self.events) > 0:
                return True

        try:
            raw_events = self._fetch_from_api()
            if raw_events:
                self.events = self._parse_events(raw_events)
                self._last_fetch_time = now
                self._save_cache(raw_events)
                logger.info(f"Fetched {len(self.events)} economic events "
                           f"({sum(1 for e in self.events if e.is_high_impact)} high-impact)")
                return True
        except Exception as e:
            logger.warning(f"Failed to fetch calendar from API: {e}")

        # Try loading from cache
        cached = self._load_cache()
        if cached:
            self.events = self._parse_events(cached)
            self._last_fetch_time = now
            logger.info(f"Loaded {len(self.events)} events from cache")
            return True

        # Use built-in fallback schedule
        self.events = self._get_fallback_events()
        self._last_fetch_time = now
        logger.warning("Using fallback event schedule")
        return False

    def _fetch_from_api(self) -> Optional[List[Dict]]:
        """Fetch raw event data from ForexFactory API."""
        if HAS_REQUESTS:
            resp = requests.get(self.FF_CALENDAR_URL, timeout=10,
                              headers={"User-Agent": "ForexBot/1.0"})
            resp.raise_for_status()
            return resp.json()
        else:
            req = urllib.request.Request(
                self.FF_CALENDAR_URL,
                headers={"User-Agent": "ForexBot/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())

    def _parse_events(self, raw: List[Dict]) -> List[EconomicEvent]:
        """Parse raw ForexFactory JSON into EconomicEvent objects."""
        events = []
        for item in raw:
            try:
                # Parse datetime
                date_str = item.get("date", "")
                if not date_str:
                    continue
                try:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    try:
                        dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S%z")
                    except ValueError:
                        continue

                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)

                # Parse impact
                impact_str = item.get("impact", "Low")
                try:
                    impact = NewsImpact(impact_str)
                except ValueError:
                    if "high" in impact_str.lower():
                        impact = NewsImpact.HIGH
                    elif "medium" in impact_str.lower():
                        impact = NewsImpact.MEDIUM
                    elif "holiday" in impact_str.lower():
                        impact = NewsImpact.HOLIDAY
                    else:
                        impact = NewsImpact.LOW

                event = EconomicEvent(
                    title=item.get("title", "Unknown Event"),
                    country=item.get("country", ""),
                    currency=item.get("country", "").upper()[:3],
                    impact=impact,
                    datetime_utc=dt,
                    forecast=str(item.get("forecast", "")),
                    previous=str(item.get("previous", "")),
                    actual=str(item.get("actual", "")),
                )
                events.append(event)

            except Exception as e:
                logger.debug(f"Skipping event parse error: {e}")
                continue

        # Sort by datetime
        events.sort(key=lambda e: e.datetime_utc)
        return events

    def _save_cache(self, raw_events: List[Dict]):
        """Cache events to disk."""
        try:
            with open(self._cache_file, "w") as f:
                json.dump(raw_events, f)
        except Exception as e:
            logger.debug(f"Cache save failed: {e}")

    def _load_cache(self) -> Optional[List[Dict]]:
        """Load cached events from disk."""
        try:
            if self._cache_file.exists():
                age = time.time() - self._cache_file.stat().st_mtime
                if age < 86400:  # Less than 24 hours old
                    with open(self._cache_file) as f:
                        return json.load(f)
        except Exception:
            pass
        return None

    def _get_fallback_events(self) -> List[EconomicEvent]:
        """
        Generate fallback high-impact events based on known schedule.
        Major recurring events by day of week.
        """
        events = []
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Common recurring high-impact times (UTC)
        # Monday-Friday typical major event windows
        major_windows = [
            (8, 30, "EUR", "European Economic Data"),
            (12, 30, "USD", "US Economic Data"),
            (13, 0, "USD", "US Economic Data"),
            (14, 0, "USD", "US Economic Data / Fed"),
            (18, 0, "USD", "FOMC / Fed Speakers"),
        ]

        for day_offset in range(7):
            d = today + timedelta(days=day_offset)
            if d.weekday() >= 5:
                continue
            for hour, minute, currency, title in major_windows:
                events.append(EconomicEvent(
                    title=f"[Scheduled] {title}",
                    country=currency,
                    currency=currency,
                    impact=NewsImpact.MEDIUM,
                    datetime_utc=d.replace(hour=hour, minute=minute),
                ))

        return events

    # ─── NEWS ANALYSIS ───────────────────────────────────────────────────

    def get_upcoming_events(
        self,
        currency: str = None,
        minutes_ahead: int = 120,
        min_impact: NewsImpact = NewsImpact.MEDIUM,
    ) -> List[EconomicEvent]:
        """
        Get upcoming economic events within the time window.
        
        Args:
            currency: Filter by currency (e.g., 'USD', 'EUR')
            minutes_ahead: Look-ahead window in minutes
            min_impact: Minimum impact level to include
        """
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(minutes=minutes_ahead)
        impact_priority = {NewsImpact.LOW: 0, NewsImpact.MEDIUM: 1,
                          NewsImpact.HIGH: 2, NewsImpact.HOLIDAY: 1}
        min_priority = impact_priority.get(min_impact, 1)

        results = []
        for event in self.events:
            dt = event.datetime_utc
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            if dt < now - timedelta(minutes=30):
                continue
            if dt > cutoff:
                continue

            if impact_priority.get(event.impact, 0) < min_priority:
                continue

            if currency and event.currency != currency.upper():
                continue

            results.append(event)

        return results

    def should_trade(self, symbol: str) -> Tuple[bool, str, float]:
        """
        Determine if it's safe to trade a symbol right now based on news.
        
        Returns:
            Tuple of (can_trade: bool, reason: str, size_factor: float)
            size_factor: 1.0 = full size, 0.5 = half, 0.0 = don't trade
        """
        # Refresh calendar if needed
        self.fetch_calendar()

        currencies = SYMBOL_CURRENCIES.get(symbol, ["USD"])
        now = datetime.now(timezone.utc)

        for currency in currencies:
            # Check HIGH impact events
            high_events = self.get_upcoming_events(
                currency=currency,
                minutes_ahead=self.filter_config.high_impact_freeze_minutes,
                min_impact=NewsImpact.HIGH,
            )

            for event in high_events:
                mins_until = event.minutes_until

                # Event is coming soon — freeze trading
                if 0 < mins_until <= self.filter_config.high_impact_freeze_minutes:
                    return (
                        False,
                        f"HIGH-impact {event.title} ({event.currency}) in {mins_until:.0f}min",
                        0.0,
                    )

                # Event just happened — cooldown period
                if -self.filter_config.high_impact_cooldown_minutes <= mins_until <= 0:
                    return (
                        False,
                        f"HIGH-impact {event.title} ({event.currency}) cooldown ({-mins_until:.0f}min ago)",
                        0.0,
                    )

                # Check if we should close positions before ultra-high events
                if self._is_ultra_high_event(event) and 0 < mins_until <= 60:
                    return (
                        False,
                        f"CRITICAL event {event.title} in {mins_until:.0f}min — avoid new trades",
                        0.0,
                    )

            # Check MEDIUM impact events
            med_events = self.get_upcoming_events(
                currency=currency,
                minutes_ahead=self.filter_config.medium_impact_freeze_minutes,
                min_impact=NewsImpact.MEDIUM,
            )

            medium_nearby = [
                e for e in med_events
                if e.impact == NewsImpact.MEDIUM
                and 0 < e.minutes_until <= self.filter_config.medium_impact_freeze_minutes
            ]

            if medium_nearby:
                event = medium_nearby[0]
                return (
                    True,
                    f"MEDIUM-impact {event.title} ({event.currency}) in {event.minutes_until:.0f}min — reduced size",
                    self.filter_config.medium_impact_size_factor,
                )

        return (True, "No significant news events nearby", 1.0)

    def _is_ultra_high_event(self, event: EconomicEvent) -> bool:
        """Check if event is in the ultra-high-impact list."""
        title_lower = event.title.lower()
        for keyword in self.filter_config.close_before_events:
            if keyword.lower() in title_lower:
                return True
        return False

    def get_news_sentiment(self, symbol: str) -> Dict:
        """
        Analyze recent news/events to determine directional bias.
        
        Uses actual vs forecast to determine if data was better/worse
        than expected, which can inform trading direction.
        
        Returns:
            Dict with bias ('bullish', 'bearish', 'neutral'), strength, details
        """
        currencies = SYMBOL_CURRENCIES.get(symbol, ["USD"])
        self.fetch_calendar()

        bullish_score = 0.0
        bearish_score = 0.0
        details = []

        for currency in currencies:
            recent_events = self._get_recent_events_with_data(currency, hours_back=24)

            for event in recent_events:
                direction, strength = self._analyze_event_outcome(event, currency, symbol)
                if direction > 0:
                    bullish_score += strength
                    details.append(f"Bullish: {event.title} ({event.currency})")
                elif direction < 0:
                    bearish_score += strength
                    details.append(f"Bearish: {event.title} ({event.currency})")

        # Determine overall bias
        net_score = bullish_score - bearish_score
        if net_score > 0.5:
            bias = "bullish"
        elif net_score < -0.5:
            bias = "bearish"
        else:
            bias = "neutral"

        return {
            "bias": bias,
            "bullish_score": round(bullish_score, 2),
            "bearish_score": round(bearish_score, 2),
            "net_score": round(net_score, 2),
            "details": details,
            "events_analyzed": len(details),
        }

    def _get_recent_events_with_data(self, currency: str, hours_back: int = 24) -> List[EconomicEvent]:
        """Get recent events that have actual data (already released)."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours_back)
        results = []
        for event in self.events:
            dt = event.datetime_utc
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if cutoff <= dt <= now and event.actual:
                if event.currency == currency.upper():
                    results.append(event)
        return results

    def _analyze_event_outcome(
        self,
        event: EconomicEvent,
        currency: str,
        symbol: str,
    ) -> Tuple[float, float]:
        """
        Analyze if event outcome is bullish or bearish for the symbol.
        
        Returns:
            (direction, strength) where direction is +1 (bullish), -1 (bearish), 0 (neutral)
            and strength is 0.0 to 1.0
        """
        try:
            actual = self._parse_numeric(event.actual)
            forecast = self._parse_numeric(event.forecast)
            previous = self._parse_numeric(event.previous)
        except (ValueError, TypeError):
            return (0, 0.0)

        if actual is None or forecast is None:
            return (0, 0.0)

        # Beat or miss expectations
        surprise = actual - forecast
        if previous is not None and previous != 0:
            surprise_pct = abs(surprise / previous) if previous != 0 else 0
        else:
            surprise_pct = 0

        # Determine direction
        title_lower = event.title.lower()

        # Events where HIGHER = stronger currency
        positive_events = [
            "gdp", "employment", "retail sales", "pmi",
            "manufacturing", "interest rate", "trade balance",
            "consumer confidence", "industrial production",
            "housing starts", "building permits",
        ]

        # Events where HIGHER = weaker currency (e.g., unemployment, CPI can be mixed)
        negative_events = [
            "unemployment", "jobless claims",
        ]

        # Determine if this event beating expectations is good for currency
        is_positive = any(kw in title_lower for kw in positive_events)
        is_negative = any(kw in title_lower for kw in negative_events)

        if is_negative:
            surprise = -surprise  # Flip for negative events

        if surprise > 0 and (is_positive or is_negative):
            currency_direction = 1  # Currency strengthens
        elif surprise < 0 and (is_positive or is_negative):
            currency_direction = -1  # Currency weakens
        else:
            return (0, 0.0)

        # Convert currency direction to symbol direction
        # For pairs like EURUSD: if USD strengthens → EURUSD falls (bearish)
        # Base currency strengthening → bullish, Quote currency strengthening → bearish
        base_ccy = symbol[:3] if len(symbol) >= 6 else ""
        if currency == base_ccy:
            symbol_direction = currency_direction
        else:
            symbol_direction = -currency_direction

        # Special handling for XAUUSD (Gold)
        if symbol == "XAUUSD" and currency == "USD":
            symbol_direction = -currency_direction  # USD strong = Gold weak

        strength = min(abs(surprise_pct) * 2, 1.0) if surprise_pct > 0 else 0.3
        if event.is_high_impact:
            strength *= 1.5

        return (symbol_direction, min(strength, 1.0))

    def _parse_numeric(self, value: str) -> Optional[float]:
        """Parse a numeric string, handling %, K, M suffixes."""
        if not value or value.strip() == "":
            return None
        value = value.strip().replace(",", "")
        multiplier = 1.0
        if value.endswith("%"):
            value = value[:-1]
        elif value.upper().endswith("K"):
            value = value[:-1]
            multiplier = 1000
        elif value.upper().endswith("M"):
            value = value[:-1]
            multiplier = 1_000_000
        elif value.upper().endswith("B"):
            value = value[:-1]
            multiplier = 1_000_000_000
        try:
            return float(value) * multiplier
        except ValueError:
            return None

    # ─── SUMMARY & DASHBOARD ─────────────────────────────────────────────

    def get_calendar_summary(self) -> Dict:
        """Get a summary of today's and upcoming events for the dashboard."""
        self.fetch_calendar()
        now = datetime.now(timezone.utc)
        today = now.date()

        today_events = []
        upcoming_high = []

        for event in self.events:
            dt = event.datetime_utc
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            if dt.date() == today:
                today_events.append({
                    "time": dt.strftime("%H:%M UTC"),
                    "currency": event.currency,
                    "title": event.title,
                    "impact": event.impact.value,
                    "forecast": event.forecast,
                    "previous": event.previous,
                    "actual": event.actual,
                    "minutes_until": round(event.minutes_until),
                    "status": "released" if event.actual else (
                        "upcoming" if event.minutes_until > 0 else "pending"
                    ),
                })

            if event.is_high_impact and event.minutes_until > 0:
                upcoming_high.append({
                    "time": dt.strftime("%Y-%m-%d %H:%M UTC"),
                    "currency": event.currency,
                    "title": event.title,
                    "minutes_until": round(event.minutes_until),
                })

        return {
            "today_count": len(today_events),
            "today_high_impact": sum(1 for e in today_events if e["impact"] == "High"),
            "today_events": today_events[:20],  # Limit for dashboard
            "upcoming_high_impact": upcoming_high[:10],
            "last_updated": self._last_fetch_time.isoformat() if self._last_fetch_time else None,
        }

    def get_trading_status_for_all_symbols(self, symbols: List[str]) -> Dict:
        """Get news-based trading status for all configured symbols."""
        result = {}
        for symbol in symbols:
            can_trade, reason, size_factor = self.should_trade(symbol)
            result[symbol] = {
                "can_trade": can_trade,
                "reason": reason,
                "size_factor": size_factor,
            }
        return result
