"""v4 grid: pure ladder logic + engine lifecycle with fake venues."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import grid, grid_engine


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
    assert st["settings"]["step"] == 0.05 and st["version"] == "v4"


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
