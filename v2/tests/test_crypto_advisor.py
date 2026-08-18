import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crypto_advisor import (
    MAX_POSITIONS, MAX_STEP, MIN_STEP, _new_book, _step_for,
    apply_order, generate_orders,
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


def test_bear_market_halves_entry_size():
    frames = {
        "BTC/USD": make_frame(np.linspace(80_000, 50_000, 250), daily_range=0.03),
        "SOL/USD": make_frame(wavy_uptrend(), daily_range=0.06),
    }
    orders, _, view = generate_orders(frames, _new_book())
    assert view["market"]["label"] == "BEAR"
    buys = [o for o in orders if o["side"] == "buy"]
    assert buys and all(o["dollars"] == 62.0 for o in buys)


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
