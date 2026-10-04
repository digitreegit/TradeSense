"""v4 grid: pure ladder logic + engine lifecycle with fake venues."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import dip, grid, grid_engine


# --------------------------------------------------------------------------
# grid.py
# --------------------------------------------------------------------------
def _ladder(unit=100.0):
    return grid.new_ladder("BTC/USD", "robinhood", unit)


def _seed(ladder, price=100.0):
    a = grid.decide(ladder, price, 0.05, cash=10_000)
    assert a["side"] == "buy" and a["n_units"] == grid.START_UNITS
    grid.apply_fill(ladder, side="buy", qty=a["dollars"] / price, price=price,
                    dollars=a["dollars"], n_units=a["n_units"])
    return ladder


def test_seed_buys_start_units_then_anchors_at_fill():
    l = _seed(_ladder())
    assert len(l["units"]) == grid.START_UNITS
    assert l["anchor"] == 100.0 and l["seeded"]
    assert grid.decide(l, 100.0, 0.05, cash=10_000) is None


def test_sell_one_unit_at_plus_step_and_reanchor():
    l = _seed(_ladder())
    assert grid.decide(l, 104.9, 0.05, cash=10_000) is None
    a = grid.decide(l, 105.0, 0.05, cash=10_000)
    assert a["side"] == "sell" and a["n_units"] == 1
    assert a["qty"] == pytest.approx(1.0)  # $100 unit bought at 100
    t = grid.apply_fill(l, side="sell", qty=a["qty"], price=105.0, dollars=105.0)
    assert len(l["units"]) == 2 and l["anchor"] == 105.0
    assert t["pl"] == pytest.approx(5.0)
    assert l["realized_pl"] == pytest.approx(5.0)
    # Next sell is +5% above the new anchor, next buy -5% below it.
    lv = grid.levels(l, 0.05)
    assert lv["sell_at"] == pytest.approx(110.25)
    assert lv["buy_at"] == pytest.approx(99.75)


def test_buy_one_unit_at_minus_step_up_to_max():
    l = _seed(_ladder())
    a = grid.decide(l, 95.0, 0.05, cash=10_000)
    assert a["side"] == "buy" and a["dollars"] == 100.0
    grid.apply_fill(l, side="buy", qty=100 / 95, price=95.0, dollars=100.0)
    a = grid.decide(l, 90.25, 0.05, cash=10_000)
    assert a["side"] == "buy"
    grid.apply_fill(l, side="buy", qty=100 / 90.25, price=90.25, dollars=100.0)
    assert len(l["units"]) == grid.MAX_UNITS
    # Full ladder: no more buys however far it falls.
    assert grid.decide(l, 50.0, 0.05, cash=10_000) is None
    assert grid.levels(l, 0.05)["buy_at"] is None


def test_no_buy_without_cash():
    l = _seed(_ladder())
    assert grid.decide(l, 95.0, 0.05, cash=50.0) is None


def _sell_out(l):
    for px in (105.0, 110.25, 115.7625):
        a = grid.decide(l, px, 0.05, cash=10_000)
        assert a and a["side"] == "sell"
        grid.apply_fill(l, side="sell", qty=a["qty"], price=px, dollars=a["qty"] * px)
    assert not l["units"] and l["hwm"] == pytest.approx(115.7625)
    return l


def test_sell_out_waits_at_last_sale_price_by_default():
    assert grid.FOLLOW_HIGH is False
    l = _sell_out(_seed(_ladder()))
    # Price runs away: the reference stays at the last sale, we stay in cash.
    grid.observe(l, 150.0)
    grid.observe(l, 160.0)
    assert l["hwm"] == pytest.approx(115.7625)
    assert grid.levels(l, 0.05)["buy_at"] == pytest.approx(115.7625 * 0.95)
    assert grid.decide(l, 152.0, 0.05, cash=10_000) is None
    a = grid.decide(l, 109.0, 0.05, cash=10_000)
    assert a and a["side"] == "buy" and a["n_units"] == 1


def test_sell_out_can_follow_the_high_when_enabled(monkeypatch):
    monkeypatch.setattr(grid, "FOLLOW_HIGH", True)
    l = _sell_out(_seed(_ladder()))
    grid.observe(l, 150.0)
    assert grid.decide(l, 150.0, 0.05, cash=10_000) is None
    grid.observe(l, 160.0)
    assert grid.levels(l, 0.05)["buy_at"] == pytest.approx(152.0)
    assert grid.decide(l, 153.0, 0.05, cash=10_000) is None
    a = grid.decide(l, 152.0, 0.05, cash=10_000)
    assert a and a["side"] == "buy" and a["n_units"] == 1


def test_partial_sell_fill_leaves_smaller_top_unit():
    l = _seed(_ladder())
    grid.apply_fill(l, side="sell", qty=0.4, price=105.0, dollars=42.0)
    assert len(l["units"]) == 3
    assert l["units"][-1]["qty"] == pytest.approx(0.6)
    assert l["units"][-1]["dollars"] == pytest.approx(60.0)
    assert l["realized_pl"] == pytest.approx(2.0)


def test_reconcile_trims_after_manual_sell_and_adopts_manual_buy():
    l = _seed(_ladder())
    note = grid.reconcile(l, broker_qty=2.0, price=100.0)
    assert note and len(l["units"]) == 2
    assert grid.reconcile(l, broker_qty=2.0, price=100.0) is None
    note = grid.reconcile(l, broker_qty=3.0, price=120.0)
    assert note and len(l["units"]) == 3
    assert l["units"][-1]["price"] == 120.0 and l["anchor"] == 120.0


def test_reconcile_ignores_dust_differences():
    l = _seed(_ladder())
    assert grid.reconcile(l, broker_qty=3.0 - 1e-6, price=100.0) is None


def test_unit_size_and_step_clamp():
    assert grid.unit_size(1000.0, 2) == pytest.approx(1000 * grid.CASH_USE / 2 / grid.MAX_UNITS)
    assert grid.unit_size(0.0, 3) == 0.0
    assert grid.clamp_step(0.001) == grid.MIN_STEP
    assert grid.clamp_step(5) == grid.MAX_STEP
    assert grid.clamp_step("x") == grid.DEFAULT_STEP


def test_tiny_unit_never_trades():
    l = grid.new_ladder("AMD", "alpaca", 2.0)
    assert grid.decide(l, 100.0, 0.05, cash=1000) is None


# --------------------------------------------------------------------------
# grid_engine.py with fake store + venues
# --------------------------------------------------------------------------
class FakeStore:
    def __init__(self):
        self.kv: dict = {}
        self.resets = 0

    def get(self, key, default=None):
        return self.kv.get(key, default)

    def set(self, key, value):
        self.kv[key] = value

    def reset_trading_state(self):
        self.resets += 1


class FakeVenue:
    def __init__(self, name, universe, *, prices, positions=None, cash=1000.0,
                 tradable=None, open_=True, configured=True):
        self.name = name
        self.label = name
        self.universe = tuple(universe)
        self._prices = dict(prices)
        self._positions = dict(positions or {})
        self._cash = cash
        self._tradable = set(tradable if tradable is not None else list(universe) + list(self._positions))
        self.open = open_
        self._configured = configured
        self.orders: list[tuple] = []
        self.fail_next: dict | None = None

    def configured(self):
        return self._configured

    def ready(self):
        return (True, "") if self.open else (False, "장 마감")

    def cash(self):
        return self._cash

    def prices(self, symbols):
        return {s: self._prices[s] for s in symbols if s in self._prices}

    def positions(self):
        return {s: q for s, q in self._positions.items() if q > 0}

    def tradable(self, symbols):
        return [s for s in symbols if s in self._tradable]

    def buy(self, symbol, dollars, ref_price):
        self.orders.append(("buy", symbol, dollars))
        if self.fail_next:
            f, self.fail_next = self.fail_next, None
            return f
        qty = dollars / ref_price
        self._positions[symbol] = self._positions.get(symbol, 0.0) + qty
        self._cash -= dollars
        return {"ok": True, "qty": qty, "price": ref_price, "dollars": dollars}

    def sell(self, symbol, qty, ref_price):
        self.orders.append(("sell", symbol, qty))
        if self.fail_next:
            f, self.fail_next = self.fail_next, None
            return f
        qty = min(qty, self._positions.get(symbol, 0.0))
        self._positions[symbol] = self._positions.get(symbol, 0.0) - qty
        self._cash += qty * ref_price
        return {"ok": True, "qty": qty, "price": ref_price, "dollars": qty * ref_price}


class RestingFakeVenue(FakeVenue):
    """Crypto-style venue: seed is marketable, then GTC limits sit until filled."""

    resting_limits = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._resting: dict[str, dict] = {}  # id -> order
        self._id = 0

    def place_resting(self, side, symbol, *, limit_price, qty=None, dollars=None):
        self._id += 1
        oid = f"r{self._id}"
        if side == "buy":
            q = float(dollars) / float(limit_price)
            d = float(dollars)
            self._cash -= d  # lock buying power
        else:
            q = float(qty)
            d = q * float(limit_price)
            # lock qty by reducing available — simplify: leave total, track reserved
            if self._positions.get(symbol, 0) < q * 0.999:
                return {"ok": False, "error": "수량 부족"}
        order = {
            "id": oid, "side": side, "symbol": symbol,
            "limit_price": float(limit_price), "qty": q, "dollars": d,
            "state": "open", "filled_qty": 0.0, "avg": 0.0,
        }
        self._resting[oid] = order
        self.orders.append(("resting", side, symbol, float(limit_price), q))
        return {
            "ok": True, "resting": True, "qty": q, "price": float(limit_price),
            "limit_price": float(limit_price), "dollars": d,
            "rh_order_id": oid, "rh_api_version": "v1", "state": "open",
        }

    def resting_status(self, meta):
        o = self._resting.get(meta["id"])
        if not o:
            return {"ok": True, "state": "canceled", "terminal": True, "pending": False,
                    "filled": False, "qty": 0, "price": 0, "dollars": 0}
        return {
            "ok": True, "state": o["state"],
            "filled": o["state"] == "filled",
            "pending": o["state"] == "open",
            "terminal": o["state"] in ("filled", "canceled"),
            "qty": o["filled_qty"], "price": o["avg"],
            "dollars": round(o["filled_qty"] * o["avg"], 2) if o["avg"] else 0,
        }

    def cancel_resting(self, meta):
        o = self._resting.pop(meta["id"], None)
        if o and o["state"] == "open" and o["side"] == "buy":
            self._cash += o["dollars"]  # unlock
        if o:
            o["state"] = "canceled"
        return {"ok": True, "state": "canceled"}

    def fill_resting(self, order_id, *, price=None):
        o = self._resting[order_id]
        px = float(price if price is not None else o["limit_price"])
        o["state"] = "filled"
        o["filled_qty"] = o["qty"]
        o["avg"] = px
        if o["side"] == "buy":
            self._positions[o["symbol"]] = self._positions.get(o["symbol"], 0.0) + o["qty"]
            # cash already deducted when placed
        else:
            self._positions[o["symbol"]] = self._positions.get(o["symbol"], 0.0) - o["qty"]
            self._cash += o["qty"] * px
        return o


@pytest.fixture
def env(monkeypatch):
    st = FakeStore()
    monkeypatch.setattr(grid_engine, "store", st)
    monkeypatch.setattr(grid_engine, "log_activity", lambda *a, **k: None)
    monkeypatch.setattr(grid_engine, "_notify", lambda *a, **k: None)
    grid_engine.set_venues(None)
    yield st
    grid_engine.set_venues(None)


NOW = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)


def test_start_liquidates_then_seeds_only_api_tradable_symbols(env):
    rh = FakeVenue(
        "robinhood", ["BTC/USD", "ETH/USD", "SOL/USD"],
        prices={"BTC/USD": 100.0, "ETH/USD": 10.0, "SOL/USD": 1.0, "XRP/USD": 2.0, "DOGE/USD": 0.1},
        positions={"XRP/USD": 500.0, "DOGE/USD": 1000.0},
        cash=900.0,
        tradable=["BTC/USD", "ETH/USD", "DOGE/USD"],  # SOL & XRP app-only
    )
    grid_engine.set_venues([rh])
    grid_engine.start(run_now=False)
    assert env.resets == 1 and grid_engine.get_settings()["enabled"]
    assert env.kv[grid_engine.BOOK_KEY]["robinhood"]["phase"] == "liquidating"

    # Tick 1: DOGE is sold, XRP stays (manual), nothing seeded yet.
    r1 = grid_engine.tick(NOW)["venues"]["robinhood"]
    assert r1["liquidated"] == ["DOGE/USD"] and r1["manual"] == ["XRP/USD"]
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    assert vb["phase"] == "liquidating" and vb["manual"] == ["XRP/USD"]
    assert rh._cash == pytest.approx(1000.0)

    # Tick 2: cash is free → ladders for BTC/ETH only, seeded at once.
    grid_engine.tick(NOW)
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    assert vb["phase"] == "running"
    assert sorted(vb["ladders"]) == ["BTC/USD", "ETH/USD"]
    unit = grid.unit_size(1000.0, 2)
    assert vb["unit_dollars"] == pytest.approx(unit)
    for l in vb["ladders"].values():
        assert l["seeded"] and len(l["units"]) == grid.START_UNITS
    seeds = [o for o in rh.orders if o[0] == "buy"]
    assert len(seeds) == 2 and all(o[2] == pytest.approx(unit * grid.START_UNITS) for o in seeds)


def _running_book(env, venue, step=0.05):
    grid_engine.set_venues([venue])
    grid_engine.start(run_now=False)
    grid_engine.set_step(step)
    grid_engine.tick(NOW)  # nothing to liquidate → seeds
    return env.kv[grid_engine.BOOK_KEY][venue.name]


def test_running_tick_sells_at_plus_step_and_buys_at_minus_step(env):
    v = FakeVenue("alpaca", ["AMD", "COIN"], prices={"AMD": 100.0, "COIN": 50.0}, cash=1000.0)
    vb = _running_book(env, v)
    unit = vb["unit_dollars"]
    v.orders.clear()

    v._prices["AMD"] = 105.0   # +5% → sell one unit
    v._prices["COIN"] = 47.5   # -5% → buy one unit
    r = grid_engine.tick(NOW)["venues"]["alpaca"]
    assert r["fills"] == 2 and not r["errors"]
    assert [o[:2] for o in v.orders] == [("sell", "AMD"), ("buy", "COIN")]  # sells first
    vb = env.kv[grid_engine.BOOK_KEY]["alpaca"]
    assert len(vb["ladders"]["AMD"]["units"]) == 2
    assert len(vb["ladders"]["COIN"]["units"]) == 4
    assert vb["ladders"]["AMD"]["realized_pl"] == pytest.approx(unit * 0.05)
    trades = env.kv[grid_engine.TRADES_KEY]
    assert [t["side"] for t in trades[-2:]] == ["sell", "buy"]
    assert trades[-2]["pl"] == pytest.approx(unit * 0.05)


def test_failed_order_is_recorded_and_retried_next_tick(env):
    v = FakeVenue("alpaca", ["AMD"], prices={"AMD": 100.0}, cash=1000.0)
    _running_book(env, v)
    v._prices["AMD"] = 105.0
    v.fail_next = {"ok": False, "error": "체결 안 됨", "transient": True}
    r = grid_engine.tick(NOW)["venues"]["alpaca"]
    assert r["fills"] == 0 and r["errors"]
    vb = env.kv[grid_engine.BOOK_KEY]["alpaca"]
    assert vb["ladders"]["AMD"]["last_error"] == "체결 안 됨"
    assert len(vb["ladders"]["AMD"]["units"]) == 3
    r = grid_engine.tick(NOW)["venues"]["alpaca"]
    assert r["fills"] == 1
    assert env.kv[grid_engine.BOOK_KEY]["alpaca"]["ladders"]["AMD"]["last_error"] is None


def test_stock_venue_holds_same_day_rungs_to_avoid_pdt(env):
    from datetime import timedelta
    v = FakeVenue("alpaca", ["AMD"], prices={"AMD": 100.0}, cash=1000.0)
    v.no_same_day_round_trip = True
    _running_book(env, v)  # seeded at NOW
    v._prices["AMD"] = 105.0
    v.orders.clear()
    r = grid_engine.tick(NOW + timedelta(hours=2))["venues"]["alpaca"]
    assert r["fills"] == 0 and not v.orders
    assert "PDT" in env.kv[grid_engine.BOOK_KEY]["alpaca"]["ladders"]["AMD"]["last_error"]
    r = grid_engine.tick(NOW + timedelta(days=1))["venues"]["alpaca"]
    assert r["fills"] == 1 and v.orders[0][:2] == ("sell", "AMD")
    # Buys are never delayed by the guard.
    v._prices["AMD"] = 99.0
    assert grid_engine.tick(NOW + timedelta(days=1, hours=1))["venues"]["alpaca"]["fills"] == 1


def test_stock_venue_waits_for_market_open(env):
    v = FakeVenue("alpaca", ["AMD"], prices={"AMD": 100.0}, cash=1000.0, open_=False)
    grid_engine.set_venues([v])
    grid_engine.start(run_now=False)
    r = grid_engine.tick(NOW)["venues"]["alpaca"]
    assert r == {"skipped": "장 마감"}
    assert not v.orders
    v.open = True
    grid_engine.tick(NOW)
    assert env.kv[grid_engine.BOOK_KEY]["alpaca"]["phase"] == "running"


def test_disabled_grid_does_nothing_and_resume_continues(env):
    v = FakeVenue("alpaca", ["AMD"], prices={"AMD": 100.0}, cash=1000.0)
    _running_book(env, v)
    grid_engine.stop()
    v._prices["AMD"] = 105.0
    v.orders.clear()
    assert grid_engine.tick(NOW)["skipped"] == "off"
    assert not v.orders
    grid_engine.resume()
    assert grid_engine.tick(NOW)["venues"]["alpaca"]["fills"] == 1


def test_manual_app_sell_shrinks_ladder_before_deciding(env):
    v = FakeVenue("robinhood", ["BTC/USD"], prices={"BTC/USD": 100.0}, cash=1000.0)
    vb = _running_book(env, v)
    # User sold two units in the app.
    v._positions["BTC/USD"] = vb["ladders"]["BTC/USD"]["units"][0]["qty"]
    grid_engine.tick(NOW)
    assert len(env.kv[grid_engine.BOOK_KEY]["robinhood"]["ladders"]["BTC/USD"]["units"]) == 1


def test_one_venue_failure_does_not_block_the_other(env):
    class Broken(FakeVenue):
        def prices(self, symbols):
            raise RuntimeError("api down")

    rh = Broken("robinhood", ["BTC/USD"], prices={"BTC/USD": 100.0}, cash=1000.0)
    al = FakeVenue("alpaca", ["AMD"], prices={"AMD": 100.0}, cash=1000.0)
    grid_engine.set_venues([rh, al])
    grid_engine.start(run_now=False)
    out = grid_engine.tick(NOW)["venues"]
    assert "error" in out["robinhood"]
    assert env.kv[grid_engine.BOOK_KEY]["alpaca"]["phase"] == "running"


def test_new_cash_grows_rungs_and_tops_up_held_units_without_selling(env):
    v = FakeVenue("robinhood", ["BTC/USD", "ETH/USD"], prices={"BTC/USD": 100.0, "ETH/USD": 10.0}, cash=1000.0)
    vb = _running_book(env, v)
    unit_old = vb["unit_dollars"]
    assert unit_old == pytest.approx(grid.unit_size(1000.0, 2))
    # Small drift does not resize.
    v._cash += 50.0
    grid_engine.tick(NOW)
    assert env.kv[grid_engine.BOOK_KEY]["robinhood"]["unit_dollars"] == pytest.approx(unit_old)
    # User sells XRP in the app → +$2000 buying power.
    v._cash += 2000.0
    v.orders.clear()
    r = grid_engine.tick(NOW)["venues"]["robinhood"]
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    capital = 3050.0 - 6 * unit_old + 6 * unit_old  # cash + basis = 3050
    unit_new = grid.unit_size(capital, 2)
    assert vb["unit_dollars"] == pytest.approx(unit_new)
    assert r["fills"] == 2 and all(o[0] == "buy" for o in v.orders)
    for l in vb["ladders"].values():
        assert len(l["units"]) == grid.START_UNITS            # rung count unchanged
        assert grid.cost_basis(l) == pytest.approx(3 * unit_new, rel=1e-6)
        assert not l.get("top_up")
    trades = env.kv[grid_engine.TRADES_KEY]
    assert trades[-1]["reason"] == "칸 크기 보충"
    # Losing cash never shrinks the plan.
    v._cash -= 1500.0
    grid_engine.tick(NOW)
    assert env.kv[grid_engine.BOOK_KEY]["robinhood"]["unit_dollars"] == pytest.approx(unit_new)


def test_liquidation_errors_are_kept_for_the_dashboard(env):
    v = FakeVenue("robinhood", ["BTC/USD"], prices={"BTC/USD": 100.0, "SHIB/USD": 0.00001},
                  positions={"SHIB/USD": 1000.0}, cash=500.0, tradable=["BTC/USD", "SHIB/USD"])
    v.fail_next = {"ok": False, "error": "SHIB 매도 가능 수량이 없습니다.", "transient": True}
    grid_engine.set_venues([v])
    grid_engine.start(run_now=False)
    grid_engine.tick(NOW)
    st = grid_engine.status()["venues"]["robinhood"]
    assert st["phase"] == "liquidating"
    assert st["errors"] == ["SHIB/USD: SHIB 매도 가능 수량이 없습니다."]


def test_status_reports_account_total_when_venue_has_equity(env):
    v = FakeVenue("alpaca", ["AMD"], prices={"AMD": 100.0}, cash=1000.0)
    v.equity = lambda: 1234.5
    _running_book(env, v)
    assert grid_engine.status()["venues"]["alpaca"]["account_total"] == 1234.5


def test_alpaca_cash_uses_buying_power_not_settled_only():
    class Acct:
        cash = "504.83"
        buying_power = "504.83"
        non_marginable_buying_power = "170.00"

    class Trading:
        def get_account(self):
            return Acct()

    class Broker:
        trading = Trading()

    venue = grid_engine.AlpacaVenue()
    venue._broker = Broker()
    assert venue.cash() == pytest.approx(504.83)


def test_status_exposes_levels_and_pl(env):
    v = FakeVenue("alpaca", ["AMD"], prices={"AMD": 100.0}, cash=1000.0)
    _running_book(env, v)
    st = grid_engine.status()
    row = st["venues"]["alpaca"]["ladders"][0]
    assert row["symbol"] == "AMD" and row["units"] == 3
    assert row["sell_at"] == pytest.approx(105.0)
    assert row["buy_at"] == pytest.approx(95.0)
    assert st["settings"]["step"] == 0.05 and st["version"] == "v5"


def test_equity_history_keeps_one_point_per_day_and_carries_missing_venues(env):
    day1 = datetime(2026, 9, 18, 14, 0, tzinfo=timezone.utc)   # 10:00 ET
    grid_engine.record_equity({"robinhood": 8000.0, "alpaca": 500.0}, day1)
    grid_engine.record_equity({"robinhood": 8100.0, "alpaca": None}, day1 + timedelta(hours=5))
    h = grid_engine.equity_history()
    assert len(h) == 1
    assert h[0]["date"] == "2026-09-18"
    assert h[0]["robinhood"] == 8100.0 and h[0]["alpaca"] == 500.0 and h[0]["total"] == 8600.0

    # 23:30 ET on the 18th is still the 18th locally even though it is the 19th in UTC.
    grid_engine.record_equity({"robinhood": 8200.0, "alpaca": 510.0},
                              datetime(2026, 9, 19, 3, 30, tzinfo=timezone.utc))
    assert len(grid_engine.equity_history()) == 1
    grid_engine.record_equity({"robinhood": 8300.0, "alpaca": 520.0}, day1 + timedelta(days=1))
    h = grid_engine.equity_history()
    assert [p["date"] for p in h] == ["2026-09-18", "2026-09-19"]
    assert h[-1]["total"] == 8820.0

    # status() records the live totals of configured venues and returns the series.
    v = FakeVenue("alpaca", ["AMD"], prices={"AMD": 100.0}, cash=1000.0)
    v.equity = lambda: 1234.5
    grid_engine.set_venues([v])
    st = grid_engine.status()
    assert st["history"][-1]["alpaca"] == 1234.5
    assert st["venues"]["alpaca"]["account_total"] == 1234.5


def test_step_is_set_per_venue_and_legacy_single_step_is_the_fallback(env):
    rh = FakeVenue("robinhood", ["BTC/USD"], prices={"BTC/USD": 100.0}, cash=1000.0)
    al = FakeVenue("alpaca", ["AMD"], prices={"AMD": 100.0}, cash=1000.0)
    grid_engine.set_venues([rh, al])
    # A pre-v4.1 settings blob only carries one step: both venues inherit it.
    env.kv[grid_engine.SETTINGS_KEY] = {"step": 0.03, "enabled": True}
    s = grid_engine.get_settings()
    assert s["steps"] == {"robinhood": 0.03, "alpaca": 0.03}

    grid_engine.set_step(0.08, venue="robinhood")
    s = grid_engine.get_settings()
    assert s["steps"] == {"robinhood": 0.08, "alpaca": 0.03}
    assert grid_engine.step_for(s, "robinhood") == 0.08
    assert grid_engine.step_for(s, "alpaca") == 0.03
    with pytest.raises(ValueError):
        grid_engine.set_step(0.05, venue="nasdaq")

    # Each venue's ladders are judged with its own step.
    grid_engine.start(run_now=False)
    grid_engine.tick(NOW)
    st = grid_engine.status()
    assert st["venues"]["robinhood"]["step"] == 0.08
    assert st["venues"]["robinhood"]["ladders"][0]["sell_at"] == pytest.approx(108.0)
    assert st["venues"]["alpaca"]["step"] == 0.03
    assert st["venues"]["alpaca"]["ladders"][0]["sell_at"] == pytest.approx(103.0)

    rh._prices["BTC/USD"] = 104.0   # +4%: below crypto's 8%, nothing sells
    al._prices["AMD"] = 104.0       # +4%: above stocks' 3%, one rung sells
    grid_engine.tick(NOW + timedelta(days=1))
    assert not [o for o in rh.orders if o[0] == "sell"]
    assert len([o for o in al.orders if o[0] == "sell"]) == 1

    # venue=None sets every venue at once (the old single-step behaviour).
    grid_engine.set_step(0.05)
    assert grid_engine.get_settings()["steps"] == {"robinhood": 0.05, "alpaca": 0.05}


def test_crypto_resting_limits_sit_until_filled_then_reanchor(env):
    v = RestingFakeVenue("robinhood", ["BTC/USD"], prices={"BTC/USD": 100.0}, cash=1000.0)
    grid_engine.set_venues([v])
    grid_engine.start(run_now=False)
    grid_engine.set_step(0.05, venue="robinhood")
    r = grid_engine.tick(NOW)["venues"]["robinhood"]
    assert r.get("seeded") or r.get("fills", 0) >= 0
    # Second tick: seed completes on first liquidate→seed path; ensure running.
    if env.kv[grid_engine.BOOK_KEY]["robinhood"]["phase"] != "running":
        grid_engine.tick(NOW)
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    assert vb["phase"] == "running"
    ladder = vb["ladders"]["BTC/USD"]
    assert ladder["seeded"] and len(ladder["units"]) == 3
    # Resting buy + sell should now be on the book at ±5%.
    grid_engine.tick(NOW)
    ladder = env.kv[grid_engine.BOOK_KEY]["robinhood"]["ladders"]["BTC/USD"]
    oo = ladder["open_orders"]
    assert "buy" in oo and "sell" in oo
    assert oo["sell"]["limit_price"] == pytest.approx(105.0, rel=1e-4)
    assert oo["buy"]["limit_price"] == pytest.approx(95.0, rel=1e-4)
    pending = env.kv[grid_engine.BOOK_KEY]["robinhood"]["pending_buy"]
    assert pending == pytest.approx(oo["buy"]["dollars"])
    # Price moving to 104 must NOT market-fill; only the resting sell does.
    before_units = len(ladder["units"])
    v._prices["BTC/USD"] = 104.0
    grid_engine.tick(NOW + timedelta(minutes=15))
    assert len(env.kv[grid_engine.BOOK_KEY]["robinhood"]["ladders"]["BTC/USD"]["units"]) == before_units
    # Fill the resting sell → one rung gone, orders cleared then replaced.
    sell_id = oo["sell"]["id"]
    v.fill_resting(sell_id, price=105.0)
    grid_engine.tick(NOW + timedelta(minutes=30))
    ladder = env.kv[grid_engine.BOOK_KEY]["robinhood"]["ladders"]["BTC/USD"]
    assert len(ladder["units"]) == before_units - 1
    assert ladder["anchor"] == pytest.approx(105.0)
    assert "buy" in ladder["open_orders"] and "sell" in ladder["open_orders"]
    # New sell level is 5% above the new anchor.
    assert ladder["open_orders"]["sell"]["limit_price"] == pytest.approx(110.25, rel=1e-3)
    # OFF cancels resting limits and unlocks the buy reservation.
    cash_before_stop = v._cash
    locked = ladder["open_orders"]["buy"]["dollars"]
    grid_engine.stop()
    assert not env.kv[grid_engine.BOOK_KEY]["robinhood"]["ladders"]["BTC/USD"]["open_orders"]
    assert v._cash == pytest.approx(cash_before_stop + locked)


# --------------------------------------------------------------------------
# v5 crypto: 24h dip buyer
# --------------------------------------------------------------------------
class DipFakeVenue(RestingFakeVenue):
    strategy = "dip"

    def __init__(self, *a, market=None, **kw):
        super().__init__(*a, **kw)
        self._market = list(market if market is not None else self.universe)
        self.bootstrap: dict = {}

    def market_universe(self):
        return list(self._market)

    def recent_hourly_highs(self, symbols):
        return {s: list(self.bootstrap[s]) for s in symbols if s in self.bootstrap}


def _dip_settings(pct=0.05, dollars=100.0):
    grid_engine.set_dip(pct=pct, order_dollars=dollars)


def test_dip_settings_have_defaults_and_clamp(env):
    s = grid_engine.get_settings()
    assert s["dip"] == {"pct": 0.05, "order_dollars": 1000.0}
    grid_engine.set_dip(pct=0.5, order_dollars=1)
    s = grid_engine.get_settings()
    assert s["dip"]["pct"] == dip.MAX_DIP and s["dip"]["order_dollars"] == dip.MIN_ORDER_DOLLARS
    grid_engine.set_dip(pct=0.08)
    assert grid_engine.get_settings()["dip"] == {"pct": 0.08, "order_dollars": dip.MIN_ORDER_DOLLARS}


def test_dip_buys_whole_market_coin_after_24h_drop_then_sells_at_target(env):
    v = DipFakeVenue(
        "robinhood", ["BTC/USD"], market=["BTC/USD", "AAVE/USD", "LINK/USD"],
        prices={"BTC/USD": 100.0, "AAVE/USD": 200.0, "LINK/USD": 20.0}, cash=1000.0,
    )
    grid_engine.set_venues([v])
    _dip_settings(0.05, 100.0)
    grid_engine.start(run_now=False)
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    assert vb["phase"] == "adopting"

    # Tick 1: nothing held, no history → just watching, no orders.
    r = grid_engine.tick(NOW)["venues"]["robinhood"]
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    assert vb["phase"] == "running" and r["watch"] == 3 and r["fills"] == []
    assert v.orders == []
    hist = env.kv[grid_engine.PRICES_KEY]
    assert set(hist) == {"BTC/USD", "AAVE/USD", "LINK/USD"}

    # AAVE drops 6% from its 24h high (which is the sample we just took).
    v._prices["AAVE/USD"] = 188.0
    v._prices["LINK/USD"] = 19.5   # -2.5%: not enough
    t1 = NOW + timedelta(hours=1)
    r = grid_engine.tick(t1)["venues"]["robinhood"]
    assert [f["symbol"] for f in r["fills"]] == ["AAVE/USD"]
    buys = [o for o in v.orders if o[0] == "buy"]
    assert buys == [("buy", "AAVE/USD", 100.0)]
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    lot = vb["lots"]["AAVE/USD"]
    assert lot["price"] == pytest.approx(188.0) and lot["dollars"] == pytest.approx(100.0)
    # A GTC sell is parked 5% above the fill.
    so = lot["sell_order"]
    assert so and so["limit_price"] == pytest.approx(188.0 * 1.05) and so["qty"] == pytest.approx(lot["qty"])
    assert v._cash == pytest.approx(900.0)

    # Falling further does NOT buy again (one lot per coin).
    v._prices["AAVE/USD"] = 170.0
    r = grid_engine.tick(t1 + timedelta(minutes=15))["venues"]["robinhood"]
    assert r["fills"] == [] and len([o for o in v.orders if o[0] == "buy"]) == 1

    # Fill the resting sell → lot closed with +5% realized, cash back.
    v.fill_resting(so["id"])
    t2 = t1 + timedelta(hours=2)
    v._prices["AAVE/USD"] = 198.0
    r = grid_engine.tick(t2)["venues"]["robinhood"]
    assert [f["side"] for f in r["fills"]] == ["sell"]
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    assert "AAVE/USD" not in vb["lots"]
    assert vb["realized_pl"] == pytest.approx(5.0)
    trades = env.kv[grid_engine.TRADES_KEY]
    assert trades[-1]["side"] == "sell" and trades[-1]["pl"] == pytest.approx(5.0)

    # Status exposes the v5 shape for the dashboard.
    st = grid_engine.status()["venues"]["robinhood"]
    assert st["strategy"] == "dip" and st["dip"]["pct"] == 0.05
    assert st["lots"] == [] and st["realized_pl"] == pytest.approx(5.0)
    watch = {w["symbol"]: w for w in st["watch"]}
    assert watch["AAVE/USD"]["high_24h"] == pytest.approx(200.0)
    assert watch["AAVE/USD"]["trigger_at"] == pytest.approx(190.0)
    assert watch["AAVE/USD"]["change"] == pytest.approx(198 / 200 - 1)


def test_dip_rearms_after_sell_and_uses_rolling_24h_high(env):
    v = DipFakeVenue("robinhood", ["SOL/USD"], market=["SOL/USD"],
                     prices={"SOL/USD": 100.0}, cash=1000.0)
    grid_engine.set_venues([v])
    _dip_settings(0.05, 100.0)
    grid_engine.start(run_now=False)
    grid_engine.tick(NOW)
    v._prices["SOL/USD"] = 94.0
    grid_engine.tick(NOW + timedelta(hours=1))
    lots = env.kv[grid_engine.BOOK_KEY]["robinhood"]["lots"]
    so = lots["SOL/USD"]["sell_order"]
    v.fill_resting(so["id"])
    v._prices["SOL/USD"] = 99.0
    grid_engine.tick(NOW + timedelta(hours=2))
    assert env.kv[grid_engine.BOOK_KEY]["robinhood"]["lots"] == {}
    # Old 100 high ages out after 24h; new high is 99 → trigger at 94.05.
    v._prices["SOL/USD"] = 95.0
    r = grid_engine.tick(NOW + timedelta(hours=25))["venues"]["robinhood"]
    assert r["fills"] == []
    v._prices["SOL/USD"] = 94.0
    r = grid_engine.tick(NOW + timedelta(hours=25, minutes=15))["venues"]["robinhood"]
    assert [f["symbol"] for f in r["fills"]] == ["SOL/USD"]


def test_dip_bootstraps_24h_high_from_hourly_bars(env):
    v = DipFakeVenue("robinhood", ["ETH/USD"], market=["ETH/USD"],
                     prices={"ETH/USD": 94.0}, cash=1000.0)
    v.bootstrap = {"ETH/USD": [[(NOW - timedelta(hours=h)).isoformat(), 100.0] for h in range(1, 6)]}
    grid_engine.set_venues([v])
    _dip_settings(0.05, 100.0)
    grid_engine.start(run_now=False)
    r = grid_engine.tick(NOW)["venues"]["robinhood"]
    # Already 6% under the bootstrapped high on the very first tick.
    assert [f["symbol"] for f in r["fills"]] == ["ETH/USD"]


def test_dip_respects_cash_and_per_tick_cap(env):
    syms = [f"C{i}/USD" for i in range(6)]
    v = DipFakeVenue("robinhood", syms, market=syms, prices={s: 100.0 for s in syms}, cash=250.0)
    grid_engine.set_venues([v])
    _dip_settings(0.05, 100.0)
    grid_engine.start(run_now=False)
    grid_engine.tick(NOW)
    for s in syms:
        v._prices[s] = 90.0
    r = grid_engine.tick(NOW + timedelta(hours=1))["venues"]["robinhood"]
    # $250 buys two $100 lots; third is blocked by cash.
    assert len(r["fills"]) == 2
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    assert "현금 부족" in vb["note"]
    v._cash = 10_000.0
    r = grid_engine.tick(NOW + timedelta(hours=1, minutes=15))["venues"]["robinhood"]
    assert len(r["fills"]) == grid_engine.MAX_DIP_BUYS_PER_TICK


def test_dip_adopts_v4_ladders_with_cost_basis_and_stop_cancels_sells(env):
    v = DipFakeVenue("robinhood", ["BTC/USD"], market=["BTC/USD"],
                     prices={"BTC/USD": 100.0}, positions={"BTC/USD": 2.0}, cash=500.0)
    grid_engine.set_venues([v])
    _dip_settings(0.05, 100.0)
    # Pretend a v4 ladder is on the book: 2 units bought for $90 each.
    ladder = grid.new_ladder("BTC/USD", "robinhood", 90.0)
    grid.apply_fill(ladder, side="buy", qty=2.0, price=90.0, dollars=180.0, n_units=2, at=NOW)
    ladder["open_orders"] = {"buy": {"id": "old", "limit_price": 85.0, "qty": 1, "dollars": 85.0}}
    book = grid_engine.get_book()
    book["robinhood"]["phase"] = "running"
    book["robinhood"]["ladders"] = {"BTC/USD": ladder}
    env.set(grid_engine.BOOK_KEY, book)
    grid_engine._save_settings(enabled=True)

    grid_engine.tick(NOW)
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    assert vb["ladders"] == {}
    lot = vb["lots"]["BTC/USD"]
    assert lot["source"] == "adopted" and lot["qty"] == pytest.approx(2.0)
    assert lot["dollars"] == pytest.approx(180.0) and lot["price"] == pytest.approx(90.0)
    # Sell parked at +5% over the *cost basis*, not the current price.
    assert lot["sell_order"]["limit_price"] == pytest.approx(94.5)
    assert v.orders == [("resting", "sell", "BTC/USD", 94.5, 2.0)]

    grid_engine.stop()
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    assert vb["lots"]["BTC/USD"]["sell_order"] is None
    assert v._resting == {}


def test_dip_pure_helpers():
    assert dip.is_stable("USDC/USD") and not dip.is_stable("BTC/USD")
    hist = {"X/USD": [[(NOW - timedelta(hours=30)).isoformat(), 500.0],
                      [(NOW - timedelta(hours=3)).isoformat(), 100.0]]}
    assert dip.high_24h(hist["X/USD"], NOW) == 100.0
    assert dip.should_buy(95.0, 100.0, 0.05) and not dip.should_buy(95.5, 100.0, 0.05)
    assert dip.sell_target(188.0, 0.05) == pytest.approx(197.4)
    trimmed = dip.append_samples(hist, {"X/USD": 97.0}, NOW)
    assert len(trimmed["X/USD"]) == 2 and trimmed["X/USD"][-1][1] == 97.0


def test_dip_ignores_dust_leftovers_instead_of_erroring(env):
    # $0.02 of BTC and $0.19 of SOL left over from old ladders: below the API
    # minimum, so they must be skipped on adoption and purged if already a lot.
    v = DipFakeVenue("robinhood", ["BTC/USD"], market=["BTC/USD", "SOL/USD", "LIT/USD"],
                     prices={"BTC/USD": 85000.0, "SOL/USD": 120.0, "LIT/USD": 3.5},
                     positions={"BTC/USD": 0.02 / 85000.0, "SOL/USD": 0.19 / 120.0, "LIT/USD": 285.0},
                     cash=7000.0)
    grid_engine.set_venues([v])
    _dip_settings(0.05, 1000.0)
    grid_engine.start(run_now=False)
    grid_engine.tick(NOW)
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    assert list(vb["lots"]) == ["LIT/USD"]
    assert vb["dust"] == ["BTC/USD", "SOL/USD"]
    assert vb["errors"] == []
    assert [o for o in v.orders if o[2] != "LIT/USD"] == []
    # A lot that decays into dust (partial manual sell) is purged too.
    vb["lots"]["LIT/USD"]["qty"] = 0.1
    v._positions["LIT/USD"] = 0.1
    env.set(grid_engine.BOOK_KEY, env.kv[grid_engine.BOOK_KEY])
    grid_engine.tick(NOW + timedelta(minutes=15))
    vb = env.kv[grid_engine.BOOK_KEY]["robinhood"]
    assert vb["lots"] == {} and "LIT/USD" in vb["dust"]
    assert grid_engine.status()["venues"]["robinhood"]["dust"] == vb["dust"]
