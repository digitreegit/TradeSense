import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crypto_advisor import (
    BEAR_SIZE, MAX_POSITIONS, MAX_STEP, MAX_UNITS, MAX_WEIGHT, MIN_STEP,
    TRIM_FRACTION, _new_book, _step_for, apply_order, generate_orders,
)


def make_frame(closes: np.ndarray, daily_range: float = 0.05) -> pd.DataFrame:
    idx = pd.date_range("2025-06-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * (1 + daily_range / 2),
            "low": closes * (1 - daily_range / 2),
            "close": closes,
        },
        index=idx,
    )


def wavy_uptrend(n: int = 250, lo: float = 100, hi: float = 200) -> np.ndarray:
    """Rising but oscillating, ending on a mild pullback so RSI(14) is not
    overbought while price stays above the 50EMA (trend still up)."""
    closes = np.linspace(lo, hi, n) * (1 + 0.03 * np.sin(np.arange(n) / 3))
    closes[-5:] = closes[-6] * np.array([0.995, 0.985, 0.99, 0.98, 0.985])
    return closes


def test_step_is_bounded():
    assert _step_for(0.001) == MIN_STEP
    assert _step_for(0.5) == MAX_STEP
    assert MIN_STEP <= _step_for(0.05) <= MAX_STEP


def test_uptrend_coin_gets_bought_and_downtrend_does_not():
    live = _new_book()
    frames = {
        "BTC/USD": make_frame(wavy_uptrend(), daily_range=0.03),
        "SOL/USD": make_frame(wavy_uptrend(), daily_range=0.06),
        "DOGE/USD": make_frame(np.linspace(200, 100, 250), daily_range=0.08),
    }
    orders, sim, view = generate_orders(frames, live)

    bought = {o["symbol"] for o in orders if o["side"] == "buy"}
    assert "SOL" in bought
    assert "DOGE" not in bought
    assert live["positions"] == {}          # not applied until confirm
    assert "SOL/USD" in sim["positions"]
    assert view["market"]["label"] in ("BULL", "CHOP")


def test_take_profit_sells_a_unit_and_ratchets_anchor():
    closes = wavy_uptrend()
    frames = {"SOL/USD": make_frame(closes, daily_range=0.06)}
    price = float(closes[-1])
    anchor = price / 1.10
    book = _new_book()
    book["cash"] = 875.0
    book["positions"]["SOL/USD"] = {
        "units": [{"dollars": 125.0, "price": anchor, "qty": 125.0 / anchor}],
        "anchor": anchor,
        "step": 0.05,
    }
    orders, sim, _ = generate_orders(frames, book)

    sells = [o for o in orders if o["side"] == "sell" and o["symbol"] == "SOL"]
    assert len(sells) == 1
    assert "익절" in sells[0]["reason"]
    assert "SOL/USD" in book["positions"]   # live book waits for confirm
    assert "SOL/USD" not in sim["positions"]


def test_dip_triggers_one_add_buy():
    closes = wavy_uptrend()
    frames = {"SOL/USD": make_frame(closes, daily_range=0.06)}
    price = float(closes[-1])
    anchor = price / 0.94
    book = _new_book()
    book["cash"] = 875.0
    book["positions"]["SOL/USD"] = {
        "units": [{"dollars": 125.0, "price": anchor, "qty": 125.0 / anchor}],
        "anchor": anchor,
        "step": 0.05,
    }
    orders, sim, _ = generate_orders(frames, book)

    adds = [o for o in orders if o["side"] == "buy" and o["symbol"] == "SOL"]
    assert len(adds) == 1
    assert "추가 매수" in adds[0]["reason"]
    assert len(book["positions"]["SOL/USD"]["units"]) == 1
    assert len(sim["positions"]["SOL/USD"]["units"]) == 2


def test_trend_break_liquidates_position():
    frames = {"SOL/USD": make_frame(np.linspace(200, 100, 250), daily_range=0.06)}
    book = _new_book()
    book["cash"] = 750.0
    book["positions"]["SOL/USD"] = {
        "units": [
            {"dollars": 125.0, "price": 180.0, "qty": 125.0 / 180.0},
            {"dollars": 125.0, "price": 150.0, "qty": 125.0 / 150.0},
        ],
        "anchor": 150.0,
        "step": 0.05,
    }
    orders, sim, _ = generate_orders(frames, book)

    sells = [o for o in orders if o["side"] == "sell" and o["symbol"] == "SOL"]
    assert len(sells) == 1
    assert "추세 이탈" in sells[0]["reason"]
    assert book["positions"] != {}
    assert sim["positions"] == {}
    assert sim["realized_pl"] < 0


def test_bear_market_reduces_entry_size():
    frames = {
        "BTC/USD": make_frame(np.linspace(80_000, 50_000, 250), daily_range=0.03),
        "SOL/USD": make_frame(wavy_uptrend(), daily_range=0.06),
    }
    orders, _, view = generate_orders(frames, _new_book())
    assert view["market"]["label"] == "BEAR"
    buys = [o for o in orders if o["side"] == "buy"]
    expected = round(1000 / MAX_POSITIONS / MAX_UNITS * BEAR_SIZE, 0)
    assert buys and all(o["dollars"] == expected for o in buys)


def test_daily_loss_circuit_breaker_blocks_new_buys():
    frames = {
        "BTC/USD": make_frame(wavy_uptrend(), daily_range=0.03),
        "SOL/USD": make_frame(wavy_uptrend(), daily_range=0.06),
    }
    book = _new_book()
    book["risk_day"] = {"date": "2026-08-25", "buy_halted": True}
    orders, _, _ = generate_orders(frames, book)
    assert not any(order["side"] == "buy" for order in orders)


def test_positions_capped_at_max():
    frames = {
        f"C{i}/USD": make_frame(wavy_uptrend(), daily_range=0.05)
        for i in range(6)
    }
    frames["BTC/USD"] = make_frame(wavy_uptrend(), daily_range=0.03)
    live = _new_book()
    orders, sim, _ = generate_orders(frames, live)
    assert live["positions"] == {}
    assert len(sim["positions"]) == MAX_POSITIONS
    assert len([o for o in orders if o["side"] == "buy"]) == MAX_POSITIONS


def test_oversized_position_gets_staged_trim_not_full_dump():
    """An 80%+ bag in a downtrend is trimmed in stages, never dumped."""
    closes = np.linspace(2.0, 1.0, 250)          # XRP-like downtrend
    frames = {"XRP/USD": make_frame(closes, daily_range=0.05)}
    price = float(closes[-1])
    qty = 5000.0
    book = _new_book()
    book["cash"] = 745.0
    book["budget"] = 745.0 + qty * price
    book["positions"]["XRP/USD"] = {
        "units": [{"dollars": qty * price, "price": price, "qty": qty}],
        "anchor": price, "step": 0.05, "avg_cost": 1.80,
    }
    orders, sim, _ = generate_orders(frames, book)

    sells = [o for o in orders if o["side"] == "sell" and o["symbol"] == "XRP"]
    assert len(sells) == 1
    assert sells[0]["kind"] == "trim"
    assert "축소" in sells[0]["reason"]
    value = qty * price
    total = 745.0 + value
    excess = value - MAX_WEIGHT * total
    expected = min(value * 0.50, max(value * TRIM_FRACTION, excess * 0.5))
    assert abs(sells[0]["dollars"] - expected) < 2
    remaining = sum(u["qty"] for u in sim["positions"]["XRP/USD"]["units"])
    assert 0 < remaining < qty
    # recovery: never buy more of the underwater bag
    assert not any(o["side"] == "buy" and o["symbol"] == "XRP" for o in orders)


def test_dust_position_is_consolidated():
    frames = {"SHIB/USD": make_frame(np.linspace(0.0001, 0.00005, 250))}
    price = 0.00005
    book = _new_book()
    book["cash"] = 950.0
    book["positions"]["SHIB/USD"] = {
        "units": [{"dollars": 4.0, "price": price, "qty": 4.0 / price}],
        "anchor": price, "step": 0.08,
    }
    orders, sim, _ = generate_orders(frames, book)
    sells = [o for o in orders if o["side"] == "sell" and o["symbol"] == "SHIB"]
    assert len(sells) == 1
    assert "소액 정리" in sells[0]["reason"]
    assert "SHIB/USD" not in sim["positions"]


def test_trim_apply_reduces_units_proportionally():
    book = _new_book()
    book["cash"] = 0.0
    book["positions"]["XRP/USD"] = {
        "units": [{"dollars": 5000.0, "price": 1.0, "qty": 5000.0}],
        "anchor": 1.0, "step": 0.05, "avg_cost": 1.80,
    }
    order = {"side": "sell", "symbol": "XRP", "pair": "XRP/USD",
             "price": 1.0, "kind": "trim", "step": 0.05}
    apply_order(book, order, 1500.0)
    pos = book["positions"]["XRP/USD"]
    assert abs(sum(u["qty"] for u in pos["units"]) - 3500.0) < 1e-6
    assert abs(book["cash"] - 1500.0) < 1e-6
    assert abs(book["realized_pl"]) < 1e-6      # MTM basis: no phantom P/L
    assert pos["avg_cost"] == 1.80              # display basis preserved


def test_live_hard_stop_beats_daily_strategy():
    closes = wavy_uptrend()
    frames = {"SOL/USD": make_frame(closes)}
    book = _new_book()
    book["cash"] = 100
    book["positions"]["SOL/USD"] = {
        "units": [{"dollars": 400, "price": 100, "qty": 4}],
        "anchor": 100, "step": 0.05, "avg_cost": 100, "peak_price": 100,
    }
    orders, _, _ = generate_orders(
        frames, book, live_prices={"SOL/USD": 91}, live_quote_fresh=True,
    )
    sells = [o for o in orders if o["symbol"] == "SOL" and o["side"] == "sell"]
    assert len(sells) == 1
    assert sells[0]["kind"] == "hard_stop"


def test_stale_quote_on_one_pair_does_not_block_other_risk():
    closes = wavy_uptrend()
    frames = {
        "SOL/USD": make_frame(closes),
        "SHIB/USD": make_frame(closes),
    }
    book = _new_book()
    book["cash"] = 100
    book["positions"]["SOL/USD"] = {
        "units": [{"dollars": 400, "price": 100, "qty": 4}],
        "anchor": 100, "step": 0.05, "avg_cost": 100, "peak_price": 100,
    }
    shib_px = float(closes[-1])
    book["positions"]["SHIB/USD"] = {
        "units": [{"dollars": 400, "price": shib_px, "qty": 400 / shib_px}],
        "anchor": shib_px, "step": 0.05, "avg_cost": shib_px, "peak_price": shib_px,
    }
    now = datetime.now(timezone.utc)
    orders, _, view = generate_orders(
        frames, book,
        live_prices={"SOL/USD": 91, "SHIB/USD": shib_px},
        quote_at_by_pair={
            "SOL/USD": now.isoformat(),
            "SHIB/USD": (now - timedelta(minutes=10)).isoformat(),
        },
    )
    sells = [o for o in orders if o["symbol"] == "SOL" and o["side"] == "sell"]
    assert len(sells) == 1
    assert sells[0]["kind"] == "hard_stop"
    assert any("SHIB" in r and "시세" in r for r in view["idle_reasons"])


def test_idle_reasons_cash_floor_and_full_slots():
    closes = wavy_uptrend()
    price = float(closes[-1])
    frames = {pair: make_frame(closes) for pair in (
        "SHIB/USD", "LTC/USD", "XRP/USD", "AVAX/USD",
    )}
    book = _new_book()
    book["cash"] = 800
    for pair in frames:
        book["positions"][pair] = {
            "units": [{"dollars": 1500, "price": price, "qty": 1500 / price}],
            "anchor": price, "step": 0.05, "avg_cost": price, "peak_price": price,
        }
    orders, _, view = generate_orders(frames, book)
    assert orders == []
    joined = " ".join(view["idle_reasons"])
    assert "바닥" in joined
    assert "4/4슬롯" in joined
    assert "35%" in joined


def test_profit_stage_apply_records_tier_and_sells_proportionally():
    book = _new_book()
    book["cash"] = 0
    book["positions"]["SOL/USD"] = {
        "units": [{"dollars": 400, "price": 100, "qty": 4}],
        "anchor": 100, "step": 0.05, "avg_cost": 100,
        "initial_risk_qty": 4, "profit_tiers_taken": [],
    }
    order = {
        "side": "sell", "symbol": "SOL", "pair": "SOL/USD",
        "price": 110, "kind": "profit_stage", "profit_tier": 0.10,
    }
    apply_order(book, order, 110)
    pos = book["positions"]["SOL/USD"]
    assert sum(u["qty"] for u in pos["units"]) == pytest.approx(3)
    assert pos["profit_tiers_taken"] == [0.10]


def test_auto_execution_orders_sells_first_and_limits_buys():
    from unittest.mock import patch
    from app.crypto_advisor import execute_pending_auto

    pending = [
        {"id": "b0", "side": "buy", "symbol": "SOL", "pair": "SOL/USD", "kind": "entry", "dollars": 100},
        {"id": "b1", "side": "buy", "symbol": "ETH", "pair": "ETH/USD", "kind": "entry", "dollars": 100},
        {"id": "s1", "side": "sell", "symbol": "SOL", "pair": "SOL/USD", "kind": "hard_stop", "dollars": 200},
        {"id": "b2", "side": "buy", "symbol": "BTC", "pair": "BTC/USD", "kind": "entry", "dollars": 100},
    ]
    with patch("app.crypto_advisor.store") as mock_store, \
         patch("app.robinhood_config.get_execution_mode", return_value="auto"), \
         patch("app.crypto_advisor.confirm_order", return_value={"ok": True, "orders": [], "order_history": []}) as confirm:
        mock_store.get.return_value = pending
        out = execute_pending_auto()
    assert [call.args[0] for call in confirm.call_args_list] == ["s1", "b1"]
    assert len(out) == 2


def test_auto_failure_locks_manual_and_stops():
    from unittest.mock import patch
    from app.crypto_advisor import execute_pending_auto

    pending = [
        {"id": "s1", "side": "sell", "symbol": "SOL", "pair": "SOL/USD", "kind": "hard_stop", "dollars": 200},
        {"id": "b1", "side": "buy", "symbol": "ETH", "pair": "ETH/USD", "kind": "entry", "dollars": 100},
    ]
    with patch("app.crypto_advisor.store") as mock_store, \
         patch("app.robinhood_config.get_execution_mode", return_value="auto"), \
         patch("app.robinhood_config.set_execution_mode") as set_mode, \
         patch("app.crypto_advisor.confirm_order", return_value={"ok": False, "error": "quote stale"}) as confirm, \
         patch("app.crypto_advisor.send"), patch("app.crypto_advisor.log_activity"):
        mock_store.get.return_value = pending
        out = execute_pending_auto()
    assert len(out) == 1
    confirm.assert_called_once()
    set_mode.assert_called_once_with("manual")


def test_unit_size_scales_with_real_book():
    """A $6,000 real book should size units off $6,000, not the $1,000 toy."""
    closes = wavy_uptrend()
    frames = {
        "BTC/USD": make_frame(closes, daily_range=0.03),
        "SOL/USD": make_frame(closes, daily_range=0.06),
    }
    book = _new_book()
    book["cash"] = 6000.0
    book["budget"] = 6000.0
    orders, _, _ = generate_orders(frames, book)
    buys = [o for o in orders if o["side"] == "buy"]
    assert buys and all(o["dollars"] == 750.0 for o in buys)


def test_no_average_down_when_deep_underwater():
    closes = wavy_uptrend()
    frames = {"SOL/USD": make_frame(closes, daily_range=0.06)}
    price = float(closes[-1])
    anchor = price / 0.94
    book = _new_book()
    book["cash"] = 875.0
    book["positions"]["SOL/USD"] = {
        "units": [{"dollars": 125.0, "price": anchor, "qty": 125.0 / anchor}],
        "anchor": anchor,
        "step": 0.05,
        "avg_cost": price * 1.5,
    }
    orders, _, _ = generate_orders(frames, book)
    assert not any(o["side"] == "buy" and o["symbol"] == "SOL" for o in orders)


def test_trim_proceeds_rotate_into_relative_strength():
    xrp = np.linspace(2.0, 1.0, 250)
    eth = wavy_uptrend()
    frames = {
        "XRP/USD": make_frame(xrp, daily_range=0.05),
        "ETH/USD": make_frame(eth, daily_range=0.04),
        "BTC/USD": make_frame(np.linspace(80_000, 50_000, 250), daily_range=0.03),
    }
    xrp_px = float(xrp[-1])
    eth_px = float(eth[-1])
    book = _new_book()
    book["cash"] = 745.0
    book["positions"]["XRP/USD"] = {
        "units": [{"dollars": 5000 * xrp_px, "price": xrp_px, "qty": 5000.0}],
        "anchor": xrp_px, "step": 0.05, "avg_cost": 1.80,
    }
    book["positions"]["ETH/USD"] = {
        "units": [{"dollars": 100.0, "price": eth_px, "qty": 100.0 / eth_px}],
        "anchor": eth_px, "step": 0.04, "avg_cost": eth_px,
    }
    book["budget"] = book["cash"] + 5000 * xrp_px + 100.0
    book["principal"] = 13500.0
    orders, _, view = generate_orders(frames, book)
    assert view["summary"]["principal"] == 13500.0
    assert view["summary"]["gap"] > 0
    assert any(o["kind"] == "trim" and o["symbol"] == "XRP" for o in orders)
    rotates = [o for o in orders if o["side"] == "buy" and o["symbol"] == "ETH"]
    assert rotates
    assert "재배치" in rotates[0]["reason"]
    assert not any(o["side"] == "buy" and o["symbol"] == "XRP" for o in orders)


def test_confirm_uses_actual_dollars_not_recommendation():
    live = _new_book()
    frames = {
        "BTC/USD": make_frame(wavy_uptrend(), daily_range=0.03),
        "SOL/USD": make_frame(wavy_uptrend(), daily_range=0.06),
    }
    orders, _, _ = generate_orders(frames, live)
    buy = next(o for o in orders if o["symbol"] == "SOL" and o["side"] == "buy")
    apply_order(live, buy, 100.0)
    pos = live["positions"]["SOL/USD"]
    assert pos["units"][0]["dollars"] == 100.0
    assert live["cash"] == live["budget"] - 100.0


def test_panel_splits_active_and_history():
    from app.crypto_advisor import _panel

    orders = [
        {"id": "1", "side": "sell", "symbol": "XRP", "dollars": 100, "status": "confirmed",
         "confirmed_at": "2026-08-19T12:00:00+00:00"},
        {"id": "2", "side": "buy", "symbol": "SOL", "dollars": 50},
    ]
    data = _panel(orders, {"summary": {}, "market": {"label": "CHOP"}})
    assert len(data["orders"]) == 1
    assert data["orders"][0]["symbol"] == "SOL"
    assert len(data["order_history"]) == 1
    assert data["order_history"][0]["symbol"] == "XRP"


def test_ensure_order_split_fixes_legacy_cache():
    from app.crypto_advisor import _ensure_order_split

    legacy = {
        "ok": True,
        "orders": [
            {"id": "1", "side": "sell", "symbol": "XRP", "dollars": 100, "status": "confirmed",
             "confirmed_at": "2026-08-19T12:00:00+00:00"},
            {"id": "2", "side": "buy", "symbol": "ETH", "dollars": 50},
        ],
    }
    fixed = _ensure_order_split(legacy)
    assert len(fixed["orders"]) == 1
    assert fixed["orders"][0]["symbol"] == "ETH"
    assert len(fixed["order_history"]) == 1


def test_merge_pending_does_not_reconfirm_fresh_proposal():
    from app.crypto_advisor import _merge_pending

    old = [{"id": "a", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
            "kind": "trim", "dollars": 100, "status": "confirmed",
            "confirmed_at": "2026-08-19T12:00:00+00:00"}]
    fresh = [{"id": "b", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
              "kind": "trim", "dollars": 120}]
    merged = _merge_pending(old, fresh)
    active = [o for o in merged if o.get("status") != "confirmed"]
    assert len(active) == 1
    assert active[0].get("status") != "confirmed"
    assert active[0]["dollars"] == 120


def test_notify_crypto_orders_skips_when_empty():
    from unittest.mock import patch
    from app.crypto_advisor import notify_crypto_orders

    with patch("app.crypto_advisor.send") as send:
        assert notify_crypto_orders({"ok": True, "orders": []}, "test") is True
        send.assert_not_called()


def test_notify_crypto_orders_quiet_hours():
    """No Telegram between midnight and 6 AM ET."""
    from datetime import datetime
    from unittest.mock import patch
    from zoneinfo import ZoneInfo
    from app.crypto_advisor import notify_crypto_orders
    from app.state import store

    store.set("crypto_notify_fp", None)
    data = {
        "ok": True,
        "orders": [{
            "id": "a1", "side": "buy", "symbol": "XRP",
            "dollars": 100, "price": 1.5, "reason": "test",
        }],
        "summary": {"total": 6000, "principal": 10000, "gap": 4000, "cash": 80},
        "market": {"label": "CHOP"},
    }
    quiet = datetime(2026, 8, 24, 2, 30, tzinfo=ZoneInfo("America/New_York"))
    with patch("app.crypto_advisor.send") as send, \
         patch("app.crypto_advisor._in_quiet_hours", return_value=True):
        assert notify_crypto_orders(data, "승인 요청", force=True) is True
        send.assert_not_called()
    awake = datetime(2026, 8, 24, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    with patch("app.crypto_advisor.send", return_value=True) as send, \
         patch("app.crypto_advisor._in_quiet_hours", return_value=False):
        assert notify_crypto_orders(data, "승인 요청", force=False) is True
        assert send.call_count == 1
        assert "승인 필요" in send.call_args[0][0] or "매수" in send.call_args[0][0]


def test_notify_crypto_orders_sends_when_actionable():
    from unittest.mock import patch
    from app.crypto_advisor import notify_crypto_orders
    from app.state import store

    store.set("crypto_notify_fp", None)
    data = {
        "ok": True,
        "orders": [{"id": "a", "side": "sell", "symbol": "XRP", "dollars": 100,
                    "price": 1.0, "reason": "trim"}],
        "summary": {"total": 6000, "principal": 10000, "gap": 4000, "cash": 80},
        "market": {"label": "CHOP"},
    }
    with patch("app.crypto_advisor.send", return_value=True) as send, \
         patch("app.crypto_advisor._in_quiet_hours", return_value=False):
        assert notify_crypto_orders(data, "스크린샷", force=True) is True
        assert send.call_count == 1
        assert "XRP" in send.call_args[0][0]


def test_collapse_actionable_keeps_one_sell_per_symbol():
    from app.crypto_advisor import _collapse_actionable

    orders = [
        {"id": "1", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
         "kind": "trim", "dollars": 500},
        {"id": "2", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
         "kind": "exit", "dollars": 1000},
        {"id": "3", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
         "kind": "take_profit", "dollars": 200, "status": "confirmed",
         "confirmed_at": "2026-08-19T12:00:00+00:00"},
    ]
    collapsed = _collapse_actionable(orders)
    pending = [o for o in collapsed if o.get("status") != "confirmed"]
    confirmed = [o for o in collapsed if o.get("status") == "confirmed"]
    assert len(pending) == 1
    assert pending[0]["kind"] == "exit"
    assert len(confirmed) == 1
    assert confirmed[0]["kind"] == "take_profit"


def test_collapse_actionable_keeps_one_buy_per_symbol():
    from app.crypto_advisor import _collapse_actionable

    orders = [
        {"id": "1", "side": "buy", "symbol": "ETH", "pair": "ETH/USD",
         "kind": "entry", "dollars": 125},
        {"id": "2", "side": "buy", "symbol": "ETH", "pair": "ETH/USD",
         "kind": "rotate", "dollars": 125},
    ]
    collapsed = _collapse_actionable(orders)
    assert len(collapsed) == 1
    assert collapsed[0]["kind"] == "rotate"


def test_confirm_removes_sibling_pending_orders():
    from unittest.mock import patch
    from app.crypto_advisor import confirm_order
    from app.state import store

    store.set("crypto_book", _new_book())
    pending = [
        {"id": "exit1", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
         "kind": "exit", "dollars": 1000, "price": 1.0, "step": 0.05,
         "status": "pending"},
        {"id": "trim1", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
         "kind": "trim", "dollars": 500, "price": 1.0, "step": 0.05,
         "status": "pending"},
        {"id": "buy1", "side": "buy", "symbol": "SOL", "pair": "SOL/USD",
         "kind": "entry", "dollars": 125, "price": 100.0, "step": 0.05,
         "status": "pending"},
    ]
    store.set("crypto_pending", pending)
    store.set("crypto_book", {
        **_new_book(),
        "positions": {
            "XRP/USD": {
                "units": [{"dollars": 1000.0, "price": 1.0, "qty": 1000.0}],
                "anchor": 1.0, "step": 0.05,
            },
        },
        "cash": 0.0,
    })
    with patch("app.crypto_advisor.advise_and_apply", return_value={"ok": True, "orders": [], "order_history": []}):
        result = confirm_order("exit1", actual_dollars=1000.0)
    assert result["ok"] is True
    remaining = store.get("crypto_pending") or []
    assert not any(o["id"] == "trim1" for o in remaining)
    assert any(o["id"] == "exit1" and o.get("status") == "confirmed" for o in remaining)
    assert any(o["id"] == "buy1" for o in remaining)


def test_deny_order_moves_to_history():
    from unittest.mock import patch
    from app.crypto_advisor import _panel, deny_order
    from app.state import store

    store.set("crypto_book", _new_book())
    pending = [
        {"id": "sell1", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
         "kind": "trim", "dollars": 1000, "price": 1.0, "step": 0.05,
         "reason": "축소", "status": "pending"},
    ]
    store.set("crypto_pending", pending)
    with patch("app.crypto_advisor.advise_and_apply", return_value={"ok": True, "orders": [], "order_history": []}):
        result = deny_order("sell1")
    assert result["ok"] is True
    remaining = store.get("crypto_pending") or []
    denied = next(o for o in remaining if o["id"] == "sell1")
    assert denied["status"] == "denied"
    assert denied.get("denied_at")
    panel = _panel(remaining, {})
    assert not panel["orders"]
    assert panel["order_history"][0]["id"] == "sell1"


def test_deny_removes_sibling_pending_orders():
    from unittest.mock import patch
    from app.crypto_advisor import deny_order
    from app.state import store

    store.set("crypto_book", _new_book())
    pending = [
        {"id": "exit1", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
         "kind": "exit", "dollars": 1000, "price": 1.0, "step": 0.05,
         "status": "pending"},
        {"id": "trim1", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
         "kind": "trim", "dollars": 500, "price": 1.0, "step": 0.05,
         "status": "pending"},
    ]
    store.set("crypto_pending", pending)
    with patch("app.crypto_advisor.advise_and_apply", return_value={"ok": True, "orders": [], "order_history": []}):
        deny_order("exit1")
    remaining = store.get("crypto_pending") or []
    assert not any(o["id"] == "trim1" for o in remaining)
    assert any(o["id"] == "exit1" and o["status"] == "denied" for o in remaining)


def test_set_principal_updates_book():
    from unittest.mock import patch
    from app.crypto_advisor import set_principal
    from app.state import store

    book = _new_book()
    book["principal"] = 10000.0
    store.set("crypto_book", book)
    with patch("app.crypto_advisor.advise_and_apply", return_value={"ok": True, "summary": {"principal": 11598.0}}):
        result = set_principal(11598.0)
    assert result["ok"] is True
    assert store.get("crypto_book")["principal"] == 11598.0


def test_merge_pending_skips_denied_fingerprint():
    from app.crypto_advisor import _merge_pending

    now = datetime.now(timezone.utc).isoformat()
    old = [{"id": "a", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
            "kind": "trim", "dollars": 100, "status": "denied",
            "denied_at": now}]
    fresh = [{"id": "b", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
              "kind": "trim", "dollars": 120}]
    merged = _merge_pending(old, fresh)
    active = [o for o in merged if o.get("status") not in ("confirmed", "denied")]
    assert active == []
    assert len([o for o in merged if o.get("status") == "denied"]) == 1


def test_merge_pending_requeues_denied_after_24h():
    from app.crypto_advisor import _merge_pending

    old = [{"id": "a", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
            "kind": "trim", "dollars": 100, "status": "denied",
            "denied_at": "2026-08-19T12:00:00+00:00"}]
    fresh = [{"id": "b", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
              "kind": "trim", "dollars": 120}]
    merged = _merge_pending(old, fresh)
    active = [o for o in merged if o.get("status") not in ("confirmed", "denied")]
    assert len(active) == 1
    assert active[0]["id"] != "a"
    assert any(o.get("status") == "denied" and o["id"] == "a" for o in merged)


def test_generate_orders_no_add_and_rotate_same_symbol():
    closes = wavy_uptrend()
    frames = {
        "SOL/USD": make_frame(closes, daily_range=0.06),
        "BTC/USD": make_frame(wavy_uptrend(), daily_range=0.03),
    }
    price = float(closes[-1])
    anchor = price / 0.94
    book = _new_book()
    book["cash"] = 875.0
    book["positions"]["SOL/USD"] = {
        "units": [{"dollars": 125.0, "price": anchor, "qty": 125.0 / anchor}],
        "anchor": anchor,
        "step": 0.05,
    }
    orders, _, _ = generate_orders(frames, book)
    sol_buys = [o for o in orders if o["side"] == "buy" and o["symbol"] == "SOL"]
    assert len(sol_buys) == 1
    assert sol_buys[0]["kind"] == "add"
