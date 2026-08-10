import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, regime, strategy
from app.decisions import CRYPTO, DEFENSIVE, DIP, MOMENTUM, PosMeta, decide
from app.indicators import atr, rsi, sma
from app.risk import DrawdownBrake, position_dollars


def make_df(closes, highs=None, lows=None):
    closes = np.asarray(closes, dtype=float)
    idx = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame({
        "open": closes,
        "high": highs if highs is not None else closes * 1.01,
        "low": lows if lows is not None else closes * 0.99,
        "close": closes,
        "volume": 1e6,
    }, index=idx)


# -- indicators --------------------------------------------------------------

def test_rsi_bounds():
    up = make_df(np.linspace(100, 200, 50))
    r = rsi(up["close"], 14)
    assert r.iloc[-1] > 70
    down = make_df(np.linspace(200, 100, 50))
    assert rsi(down["close"], 14).iloc[-1] < 30


def test_atr_positive():
    df = make_df(100 + np.random.RandomState(0).randn(100).cumsum())
    assert (atr(df, 14).dropna() > 0).all()


# -- regime -------------------------------------------------------------------

def test_regime_bull_and_bear():
    bull = make_df(np.linspace(100, 300, 300))
    assert regime.classify(bull) == regime.BULL
    bear = make_df(np.linspace(300, 100, 300))
    assert regime.classify(bear) == regime.BEAR
    short = make_df(np.linspace(100, 110, 50))
    assert regime.classify(short) == regime.CHOP  # insufficient history


# -- strategy ------------------------------------------------------------------

def test_momentum_selection_requires_positive_return():
    strong = strategy.compute_features(make_df(np.linspace(100, 160, 120))).iloc[-1]
    weak = strategy.compute_features(make_df(np.linspace(160, 100, 120))).iloc[-1]
    picks = strategy.select_momentum({"STRONG": strong, "WEAK": weak}, top_n=2)
    assert picks == ["STRONG"]


def test_dip_entry_needs_uptrend_and_oversold():
    rs = np.random.RandomState(1)
    trend = np.linspace(100, 200, 260) + rs.randn(260)
    trend[-3:] = trend[-4] * np.array([0.97, 0.94, 0.92])  # 3-day sharp dip
    row = strategy.compute_features(make_df(trend)).iloc[-1]
    assert row["rsi2"] < config.DIP_RSI_ENTRY
    assert strategy.dip_entry(row)

    downtrend = np.linspace(200, 100, 260)
    row2 = strategy.compute_features(make_df(downtrend)).iloc[-1]
    assert not strategy.dip_entry(row2)  # below 200SMA: no knife catching


def test_dip_entry_requires_normal_volume():
    row = strategy.compute_features(make_df(np.linspace(100, 160, 260))).iloc[-1].copy()
    row["rsi2"] = 5.0
    row["volume_ratio"] = config.DIP_ENTRY_MIN_VOLUME_RATIO - 0.01
    assert not strategy.dip_entry(row)


def test_trailing_stop_only_ratchets_up():
    ts = strategy.TrailingStop.initial(close=100, atr_value=2, mult=3)
    assert ts.level == 94
    ts.update(close=110, atr_value=2, mult=3)
    assert ts.level == 104
    ts.update(close=100, atr_value=2, mult=3)  # price falls: stop must not fall
    assert ts.level == 104
    assert ts.hit(103)


# -- risk -----------------------------------------------------------------------

def test_position_dollars_risk_budget_caps_size():
    # wide stop (high ATR) -> risk budget binds below the slot allocation
    d = position_dollars(equity=3000, slot_weight=0.30, price=100, atr_value=8, stop_mult=3.0)
    assert d == pytest.approx(3000 * 0.02 / 0.24, rel=1e-6)
    # tight stop -> slot allocation binds
    d2 = position_dollars(equity=3000, slot_weight=0.30, price=100, atr_value=1, stop_mult=3.0)
    assert d2 == pytest.approx(900, rel=1e-6)


def test_drawdown_brake_hysteresis():
    b = DrawdownBrake(peak_equity=1000)
    b.update(900)
    assert not b.halted and b.scale(900) == 1.0
    b.update(840)  # dd 16% -> soft
    assert b.scale(840) == 0.5
    b.update(700)  # dd 30% -> hard
    assert b.halted and b.scale(700) == 0.0
    b.update(790)  # dd 21% -> still halted (hysteresis)
    assert b.halted
    b.update(810)  # dd 19% -> resumes
    assert not b.halted


# -- decisions -------------------------------------------------------------------

def _rows():
    strong = strategy.compute_features(make_df(np.linspace(100, 160, 260))).iloc[-1]
    return {"SPY": strong, "QQQ": strong, "BTC/USD": strong}


def test_decide_sells_on_stop_breach():
    rows = _rows()
    positions = {"SPY": PosMeta("SPY", MOMENTUM, held_days=5, stop_level=999999.0)}
    orders = decide(rows, positions, ["SPY", "QQQ"], ["BTC/USD"], regime.BULL, week_rollover=False)
    sells = [o for o in orders if o.side == "sell" and o.symbol == "SPY"]
    assert sells and sells[0].reason == "stop"


def test_dip_profit_target_exits_at_four_percent():
    rows = _rows()
    rows["SPY"] = rows["SPY"].copy()
    entry = float(rows["SPY"]["close"]) / (1 + config.DIP_PROFIT_TARGET)
    positions = {
        "SPY": PosMeta(
            "SPY", DIP, held_days=2, stop_level=None, entry_price=entry
        )
    }
    orders = decide(
        rows, positions, ["SPY"], [], regime.BULL, week_rollover=False
    )
    assert any(o.symbol == "SPY" and o.reason == "profit-target" for o in orders)


def test_distribution_exit_needs_extreme_volume_and_upper_wick():
    row = _rows()["SPY"].copy()
    row["volume_ratio"] = config.DISTRIBUTION_MIN_VOLUME_RATIO
    row["upper_wick"] = config.DISTRIBUTION_MIN_UPPER_WICK
    assert strategy.distribution_exit(row)
    row["volume_ratio"] -= 0.01
    assert not strategy.distribution_exit(row)


def test_decide_buys_momentum_on_rollover():
    orders = decide(_rows(), {}, ["SPY", "QQQ"], [], regime.BULL, week_rollover=True)
    buys = {o.symbol for o in orders if o.side == "buy" and o.sleeve == MOMENTUM}
    assert buys == {"SPY", "QQQ"}


def test_single_stocks_get_half_slot():
    # Earnings-gap control: an ETF and a single stock with identical momentum
    # must NOT get identical dollar slots — the single name takes half.
    rows = _rows()
    strong = strategy.compute_features(make_df(np.linspace(100, 160, 260))).iloc[-1]
    rows["AAPL"] = strong
    orders = decide(rows, {}, ["SPY", "QQQ", "AAPL"], [], regime.BULL, week_rollover=True)
    slots = {o.symbol: o.slot_weight for o in orders if o.side == "buy" and o.sleeve == MOMENTUM}
    assert "AAPL" in slots and "SPY" in slots
    assert slots["AAPL"] == pytest.approx(slots["SPY"] * config.SINGLE_NAME_SCALE)


def test_one_symbol_cannot_be_queued_by_multiple_sleeves():
    rows = _rows()
    gld = strategy.compute_features(make_df(np.linspace(100, 180, 260))).iloc[-1]
    rows["GLD"] = gld
    orders = decide(
        rows, {}, ["SPY", "QQQ", "GLD"], [], regime.BULL,
        week_rollover=True, defensive_syms=["GLD"],
    )
    gld_buys = [o for o in orders if o.symbol == "GLD" and o.side == "buy"]
    assert len(gld_buys) == 1


def test_decide_crypto_trend_on():
    orders = decide(_rows(), {}, [], ["BTC/USD"], regime.BEAR, week_rollover=False)
    assert any(o.symbol == "BTC/USD" and o.side == "buy" and o.sleeve == CRYPTO for o in orders)


def test_decide_defensive_when_no_crypto():
    rows = _rows()
    gld = strategy.compute_features(make_df(np.linspace(100, 160, 260))).iloc[-1]
    rows["GLD"] = gld
    orders = decide(rows, {}, [], [], regime.BEAR, week_rollover=False,
                    defensive_syms=["GLD", "TLT"])
    assert any(o.symbol == "GLD" and o.side == "buy" and o.sleeve == DEFENSIVE for o in orders)
