from datetime import datetime, timedelta, timezone

import pytest

from app import crypto_risk
from app.crypto_risk import (
    CRASH_30M_PCT,
    evaluate_position,
    fresh_pairs,
    quote_is_fresh,
    risk_levels,
    rolling_drop,
    stop_widths,
    sync_daily_risk,
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


def test_no_staged_profit_by_default_winners_ride():
    assert evaluate_position("SOL/USD", _pos(), 121) is None
    assert evaluate_position("SOL/USD", _pos(), 135) is None


def test_staged_profit_sells_initial_quarter_once(monkeypatch):
    monkeypatch.setattr(crypto_risk, "PROFIT_TIERS", (0.10, 0.20, 0.30))
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


def test_fresh_pairs_keeps_only_the_fresh_symbol():
    now = datetime.now(timezone.utc)
    live = {"SOL/USD": 100.0, "SHIB/USD": 0.00001}
    fresh = fresh_pairs(
        live,
        quote_at_by_pair={
            "SOL/USD": now.isoformat(),
            "SHIB/USD": (now - timedelta(minutes=10)).isoformat(),
        },
        now=now,
    )
    assert fresh == {"SOL/USD"}


def test_fresh_pairs_without_timestamps_honors_global_flag():
    live = {"SOL/USD": 100.0, "SHIB/USD": 0.00001}
    assert fresh_pairs(live, live_quote_fresh=True) == {"SOL/USD", "SHIB/USD"}
    assert fresh_pairs(live, live_quote_fresh=False) == set()


def test_update_tracking_skips_stale_pair_only():
    now = datetime.now(timezone.utc)
    book = {
        "cash": 0,
        "positions": {
            "SOL/USD": _pos(avg=100, qty=4, peak=100),
            "SHIB/USD": _pos(avg=1, qty=1000, peak=1),
        },
    }
    update_tracking(
        book,
        {"SOL/USD": 110, "SHIB/USD": 2},
        quote_at_by_pair={
            "SOL/USD": now.isoformat(),
            "SHIB/USD": (now - timedelta(minutes=10)).isoformat(),
        },
        now=now,
    )
    assert book["positions"]["SOL/USD"]["peak_price"] == pytest.approx(110)
    assert book["positions"]["SHIB/USD"]["peak_price"] == pytest.approx(1)


def test_risk_levels_show_next_untaken_tier(monkeypatch):
    monkeypatch.setattr(crypto_risk, "PROFIT_TIERS", (0.10, 0.20, 0.30))
    pos = _pos(peak=130)
    pos["profit_tiers_taken"] = [0.10]
    levels = risk_levels(pos)
    assert levels["hard_stop"] == pytest.approx(92)
    assert levels["trailing_stop"] == pytest.approx(120.9)
    assert levels["next_profit"] == pytest.approx(120)


def test_risk_levels_have_no_profit_target_by_default():
    levels = risk_levels(_pos(peak=130))
    assert levels["next_profit"] is None
    assert levels["hard_pct"] == pytest.approx(0.08)   # legacy pos without widths
    assert levels["trail_pct"] == pytest.approx(0.07)


def test_stop_widths_scale_with_coin_range_and_clamp():
    btc = stop_widths(0.032)
    assert btc["hard_pct"] == pytest.approx(0.096)
    assert btc["trail_pct"] == pytest.approx(0.128)
    alt = stop_widths(0.09)
    assert alt["hard_pct"] == pytest.approx(crypto_risk.HARD_STOP_MAX)
    assert alt["trail_pct"] == pytest.approx(crypto_risk.TRAILING_STOP_MAX)
    quiet = stop_widths(0.01)
    assert quiet["hard_pct"] == pytest.approx(crypto_risk.HARD_STOP_PCT)
    assert quiet["trail_pct"] == pytest.approx(crypto_risk.TRAILING_STOP_PCT)
    assert stop_widths(None) == {"hard_pct": 0.08, "trail_pct": 0.07}


def test_per_position_widths_override_module_defaults():
    pos = _pos(avg=100, peak=100)
    pos.update(hard_pct=0.15, trail_pct=0.20)
    assert evaluate_position("SOL/USD", pos, 90) is None       # -10%: inside 15% hard
    assert evaluate_position("SOL/USD", pos, 84.9)["kind"] == "hard_stop"


def test_trailing_from_daily_close_peak_ignores_intraday_spike():
    """A wick to 130 must not move the stop up; the close peak (110) does."""
    pos = _pos(avg=100, peak=130)
    sync_daily_risk(pos, range30=0.02, last_close=110)
    assert pos["peak_close"] == pytest.approx(110)
    assert pos["trail_pct"] == pytest.approx(0.08)   # 4 x 2%
    # 8% under the tick peak (130 -> 119.6) would have fired under the old rule
    assert evaluate_position("SOL/USD", pos, 119) is None
    assert evaluate_position("SOL/USD", pos, 101)["kind"] == "trailing_stop"


def test_sync_daily_risk_seeds_close_peak_from_cost_and_ratchets():
    pos = _pos(avg=100, peak=100)
    sync_daily_risk(pos, range30=0.05, last_close=95)
    assert pos["peak_close"] == pytest.approx(100)   # never below cost basis
    sync_daily_risk(pos, range30=0.05, last_close=120)
    assert pos["peak_close"] == pytest.approx(120)
    sync_daily_risk(pos, range30=0.05, last_close=110)
    assert pos["peak_close"] == pytest.approx(120)   # ratchets only up
    assert pos["hard_pct"] == pytest.approx(0.15)
    assert pos["trail_pct"] == pytest.approx(0.20)
