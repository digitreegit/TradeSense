from datetime import datetime, timedelta, timezone

import pytest

from app.crypto_risk import (
    CRASH_30M_PCT,
    evaluate_position,
    quote_is_fresh,
    risk_levels,
    rolling_drop,
    update_tracking,
)


def _pos(avg=100.0, qty=4.0, peak=100.0):
    return {
        "units": [{"qty": qty, "dollars": avg * qty, "price": avg}],
        "avg_cost": avg,
        "peak_price": peak,
        "initial_risk_qty": qty,
        "profit_tiers_taken": [],
    }


def test_hard_stop_has_priority_over_crash():
    action = evaluate_position("SOL/USD", _pos(), 91.9, recent_drop=-0.10)
    assert action["kind"] == "hard_stop"
    assert action["sell_all"] is True


def test_trailing_stop_uses_ratcheted_peak():
    action = evaluate_position("SOL/USD", _pos(avg=80, peak=120), 111.5)
    assert action["kind"] == "trailing_stop"


def test_staged_profit_sells_initial_quarter_once():
    pos = _pos()
    action = evaluate_position("SOL/USD", pos, 121)
    assert action["kind"] == "profit_stage"
    assert action["profit_tier"] == pytest.approx(0.10)
    assert action["dollars"] == pytest.approx(121)
    pos["profit_tiers_taken"] = [0.10]
    action = evaluate_position("SOL/USD", pos, 121)
    assert action["profit_tier"] == pytest.approx(0.20)


def test_tracking_detects_rolling_crash_and_daily_buy_halt():
    now = datetime.now(timezone.utc)
    book = {"cash": 0, "positions": {"SOL/USD": _pos()}}
    update_tracking(book, {"SOL/USD": 100}, quote_at=(now - timedelta(minutes=15)).isoformat(), now=now - timedelta(minutes=15))
    update_tracking(book, {"SOL/USD": 94}, quote_at=now.isoformat(), now=now)
    assert rolling_drop(book, "SOL/USD", 94) <= -CRASH_30M_PCT
    assert book["risk_day"]["buy_halted"] is True


def test_quote_freshness_fails_closed():
    now = datetime.now(timezone.utc)
    assert quote_is_fresh(now.isoformat(), now)
    assert not quote_is_fresh((now - timedelta(minutes=3)).isoformat(), now)
    assert not quote_is_fresh(None, now)


def test_risk_levels_show_next_untaken_tier():
    pos = _pos(peak=130)
    pos["profit_tiers_taken"] = [0.10]
    levels = risk_levels(pos)
    assert levels["hard_stop"] == pytest.approx(92)
    assert levels["trailing_stop"] == pytest.approx(120.9)
    assert levels["next_profit"] == pytest.approx(120)
