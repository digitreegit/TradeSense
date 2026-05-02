"""Event calendar: opening/closing auctions, FOMC ± window, earnings filter."""
from __future__ import annotations

from datetime import datetime

import pytz

from app.services.event_calendar import (
    is_blackout,
    symbol_is_earnings_today,
)

ET = pytz.timezone("America/New_York")


def _et(year, month, day, hour, minute):
    return ET.localize(datetime(year, month, day, hour, minute))


def test_opening_auction_blackout():
    blackout, reason = is_blackout(_et(2026, 5, 1, 9, 32), window_minutes=30)
    assert blackout is True
    assert "Opening auction" in reason


def test_closing_auction_blackout():
    blackout, reason = is_blackout(_et(2026, 5, 1, 15, 59), window_minutes=30)
    assert blackout is True
    assert "Closing auction" in reason


def test_fomc_window_blocks_within_30m():
    # 2026-04-29 14:00 ET FOMC. ±30m window.
    blackout, reason = is_blackout(_et(2026, 4, 29, 13, 45), window_minutes=30)
    assert blackout is True
    assert "FOMC" in reason


def test_fomc_window_clears_outside_window():
    blackout, _reason = is_blackout(_et(2026, 4, 29, 12, 0), window_minutes=30)
    assert blackout is False


def test_symbol_is_earnings_today_empty_dict_no_match():
    assert symbol_is_earnings_today("AAPL", {}) is False


def test_symbol_is_earnings_today_uppercase_match():
    today = ET.localize(datetime.now()).strftime("%Y-%m-%d")
    assert symbol_is_earnings_today("aapl", {"AAPL": [today]}) is True
