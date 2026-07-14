"""
Macro-event blackout calendar.

Single-purpose helper that answers: "should we pause new entries right now?"
Data sources are local (hard-coded FOMC / CPI / NFP dates) so the bot keeps
working even when external APIs are down. Widen / replace with a live feed
later without touching callers.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, List, Optional, Tuple

import pytz

ET = pytz.timezone("America/New_York")


# (date, HH:MM ET, label). Keep times in ET to match the market clock.
# Sources: FOMC statement schedule, BLS CPI/PPI, BLS NFP. Update yearly.
_HARD_CODED_EVENTS: List[Tuple[date, time, str]] = [
    # --- 2026 FOMC ---
    (date(2026, 1, 28), time(14, 0), "FOMC"),
    (date(2026, 3, 18), time(14, 0), "FOMC"),
    (date(2026, 4, 29), time(14, 0), "FOMC"),
    (date(2026, 6, 17), time(14, 0), "FOMC"),
    (date(2026, 7, 29), time(14, 0), "FOMC"),
    (date(2026, 9, 16), time(14, 0), "FOMC"),
    (date(2026, 10, 28), time(14, 0), "FOMC"),
    (date(2026, 12, 9), time(14, 0), "FOMC"),
    # --- 2026 CPI / PPI / NFP (approximate release times in ET) ---
    (date(2026, 1, 13), time(8, 30), "CPI"),
    (date(2026, 2, 11), time(8, 30), "CPI"),
    (date(2026, 3, 11), time(8, 30), "CPI"),
    (date(2026, 4, 14), time(8, 30), "CPI"),
    (date(2026, 5, 12), time(8, 30), "CPI"),
    (date(2026, 6, 10), time(8, 30), "CPI"),
    (date(2026, 1, 9), time(8, 30), "NFP"),
    (date(2026, 2, 6), time(8, 30), "NFP"),
    (date(2026, 3, 6), time(8, 30), "NFP"),
    (date(2026, 4, 3), time(8, 30), "NFP"),
    (date(2026, 5, 1), time(8, 30), "NFP"),
    (date(2026, 6, 5), time(8, 30), "NFP"),
]


def _combine_et(d: date, t: time) -> datetime:
    return ET.localize(datetime.combine(d, t))


def upcoming_events(now_et: Optional[datetime] = None, window_days: int = 7) -> List[dict]:
    """Return events within ``window_days`` forward of ``now_et``."""
    now_et = now_et or datetime.now(ET)
    out = []
    for d, t, label in _HARD_CODED_EVENTS:
        when = _combine_et(d, t)
        if 0 <= (when - now_et).total_seconds() <= window_days * 86400:
            out.append({"time": when.isoformat(), "label": label})
    return sorted(out, key=lambda e: e["time"])


def is_blackout(
    now_et: Optional[datetime] = None,
    window_minutes: int = 30,
    earnings_symbols: Optional[Iterable[str]] = None,
) -> Tuple[bool, str]:
    """
    Decide if we should pause *new* buys right now.

    Returns (blackout, reason). ``reason`` is human-readable for UI / logs.

    - First 5 minutes (9:30–9:35 ET): opening auction noise.
    - Last 2 minutes (15:58–16:00): closing auction drift.
    - ``window_minutes >= 9999``: treat the whole macro-event day as blackout
      (conservative preset).
    - Otherwise: ± ``window_minutes`` around each event time.
    """
    now_et = now_et or datetime.now(ET)
    t = now_et.time()

    if time(9, 30) <= t < time(9, 35):
        return True, "Opening auction (9:30–9:35 ET)"
    if time(15, 58) <= t <= time(16, 0):
        return True, "Closing auction (15:58–16:00 ET)"

    today = now_et.date()
    for d, ev_t, label in _HARD_CODED_EVENTS:
        if d != today:
            continue
        if window_minutes >= 9999:
            return True, f"{label} day — conservative whole-day blackout"
        event_dt = _combine_et(d, ev_t)
        delta = abs((now_et - event_dt).total_seconds()) / 60.0
        if delta <= window_minutes:
            return True, f"{label} ±{window_minutes}m window"

    if earnings_symbols:
        return False, ""  # filtering by symbol happens at the playbook level

    return False, ""


def symbol_is_earnings_today(symbol: str, earnings_dates: dict) -> bool:
    """Return True if ``symbol`` reports earnings today (ET).

    ``earnings_dates`` is a mapping ``{symbol: [YYYY-MM-DD, ...]}``. Callers
    typically maintain this in-memory and refresh from an external source.
    """
    if not earnings_dates:
        return False
    today = datetime.now(ET).strftime("%Y-%m-%d")
    return today in (earnings_dates.get(symbol.upper()) or [])
