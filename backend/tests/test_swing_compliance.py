"""Swing policy helpers: rolling weekday window + buy-fill budget."""
from __future__ import annotations

from datetime import date

import pytest

from app.services.compliance_service import (
    ComplianceService,
    rolling_weekday_sessions_ending,
)


def test_rolling_weekday_sessions_friday_anchor():
    # 2026-05-08 is Friday
    anchor = date(2026, 5, 8)
    win = rolling_weekday_sessions_ending(anchor, 5)
    assert anchor in win
    assert date(2026, 5, 7) in win  # Thu
    assert date(2026, 5, 6) in win  # Wed
    assert date(2026, 5, 5) in win  # Tue
    assert date(2026, 5, 4) in win  # Mon
    assert len(win) == 5
    assert date(2026, 5, 3) not in win  # prior Sunday


def test_swing_buy_cap_per_5_sessions(tmp_path, monkeypatch):
    from app.services import compliance_service as cs_mod

    monkeypatch.setattr(cs_mod, "_today_et", lambda: date(2026, 5, 11))  # Monday

    svc = ComplianceService(log_dir=tmp_path)
    assert svc.swing_can_open_new_position(3) is True
    svc.record_buy("A", 1, 10.0, settled_before=50_000.0)
    svc.record_buy("B", 1, 10.0, settled_before=50_000.0)
    svc.record_buy("C", 1, 10.0, settled_before=50_000.0)
    assert svc.swing_buy_fills_in_last_n_sessions(5) == 3
    assert svc.swing_can_open_new_position(3) is False
    assert svc.swing_entry_slots_remaining(3) == 0


def test_earliest_open_lot_bought_on(tmp_path, monkeypatch):
    from app.services import compliance_service as cs_mod

    monkeypatch.setattr(cs_mod, "_today_et", lambda: date(2026, 5, 11))
    svc = ComplianceService(log_dir=tmp_path)
    assert svc.earliest_open_lot_bought_on("ZZZ") is None
    svc.record_buy("X", 2, 100.0, settled_before=50_000.0)
    assert svc.earliest_open_lot_bought_on("X") == date(2026, 5, 11)
