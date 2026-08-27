"""Open-execution scenarios with a fake broker/store.

Covers the two live-money bugs found in QA:
- overnight gap past the hard drawdown brake must cancel queued buys
- one failed order must not wipe the rest of the pending queue
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import engine as engine_mod
from app.engine import Engine, _carry_unexecuted_sells
from app.decisions import PendingOrder


class FakeStore:
    def __init__(self):
        self.kv = {}
        self.pending = []
        self.pos_meta = {}
        self.trades = []

    def get(self, key, default=None):
        return self.kv.get(key, default)

    def set(self, key, value):
        self.kv[key] = value

    def pending_all(self):
        return [dict(o) for o in self.pending]

    def pending_clear(self):
        self.pending = []

    def pending_replace_dicts(self, orders):
        self.pending = [dict(o) for o in orders]

    def pending_replace(self, orders):
        self.pending = [
            {
                "symbol": o.symbol, "sleeve": o.sleeve, "side": o.side,
                "slot_weight": o.slot_weight, "stop_mult": o.stop_mult,
                "reason": o.reason, "created_at": "2026-01-01T00:00:00+00:00",
            }
            for o in orders
        ]

    def pos_meta_all(self):
        return {k: dict(v) for k, v in self.pos_meta.items()}

    def pos_meta_upsert(self, symbol, sleeve, stop_level, stop_mult, entry_date, held_days=0):
        self.pos_meta[symbol] = {
            "symbol": symbol, "sleeve": sleeve, "stop_level": stop_level,
            "stop_mult": stop_mult, "entry_date": entry_date, "held_days": held_days,
        }

    def pos_meta_delete(self, symbol):
        self.pos_meta.pop(symbol, None)

    def log_trade(self, symbol, sleeve, side, notional, reason, detail=""):
        self.trades.append({"symbol": symbol, "side": side, "notional": notional,
                            "reason": reason})

    def log_equity(self, equity, cash, reg):
        pass


class FakeBroker:
    def __init__(
        self, equity=1000.0, cash=1000.0, positions=None,
        fail_buys=(), fail_sells=(),
    ):
        self._equity = equity
        self._cash = cash
        self._positions = positions or {}
        self.fail_buys = set(fail_buys)
        self.fail_sells = set(fail_sells)
        self.bought = []
        self.sold = []

    def market_open_now(self):
        return True

    def equity(self):
        return self._equity

    def cash(self):
        return self._cash

    def positions(self):
        return dict(self._positions)

    def latest_price(self, sym):
        return 100.0

    def buy_notional(self, sym, dollars):
        if sym in self.fail_buys:
            return None
        self.bought.append((sym, dollars))
        return "order"

    def sell_all(self, sym):
        if sym in self.fail_sells:
            return False
        self.sold.append(sym)
        self._positions.pop(sym, None)
        return True

    def wait_for_fills(self, timeout=30.0):
        return True


def _features(*syms):
    df = pd.DataFrame({"close": [100.0, 100.0], "atr": [2.0, 2.0]})
    return {s: df for s in syms}


def _make_engine(monkeypatch, broker, store):
    monkeypatch.setattr(engine_mod, "store", store)
    monkeypatch.setattr(engine_mod, "send", lambda *a, **k: None)
    monkeypatch.setattr(engine_mod, "log_activity", lambda *a, **k: None)
    monkeypatch.setattr(engine_mod.news_overlay, "current",
                        lambda: {"avoid": [], "tilt": 1.0})
    eng = Engine()
    eng._broker = broker
    eng._features = lambda syms, **kwargs: _features(*syms)
    return eng


def _buy(sym):
    return {"id": 1, "symbol": sym, "sleeve": "momentum", "side": "buy",
            "slot_weight": 0.3, "stop_mult": 3.0, "reason": "signal",
            "created_at": "2026-01-01T00:00:00+00:00"}


def _sell(sym):
    order = _buy(sym)
    order.update({"side": "sell", "slot_weight": 0.0, "reason": "rotate"})
    return order


def test_hard_brake_at_open_cancels_buys_and_liquidates(monkeypatch):
    store = FakeStore()
    store.kv["brake"] = {"peak_equity": 1000.0, "halted": False}
    store.pending = [_buy("QQQ")]
    store.pos_meta["SPY"] = {
        "symbol": "SPY", "sleeve": "momentum", "stop_level": 80.0,
        "stop_mult": 3.0, "entry_date": "2026-01-01", "held_days": 2,
    }
    pos = {"SPY": {"qty": 1, "market_value": 700.0, "avg_entry": 100.0,
                   "current_price": 70.0, "unrealized_pl": -300.0}}
    broker = FakeBroker(equity=700.0, cash=0.0, positions=pos)  # 30% overnight dd
    eng = _make_engine(monkeypatch, broker, store)

    assert eng.job_execute_open() is True
    assert store.kv["brake"]["halted"] is True
    assert broker.sold == ["SPY"]           # liquidated, not bought
    assert broker.bought == []
    assert store.pending == []              # queued buys cancelled


def test_manual_holding_is_visible_to_broker_but_not_adopted(monkeypatch):
    store = FakeStore()
    pos = {"AAPL": {"qty": 1, "market_value": 100.0, "avg_entry": 100.0,
                    "current_price": 100.0, "unrealized_pl": 0.0}}
    eng = _make_engine(monkeypatch, FakeBroker(positions=pos), store)
    assert eng._pos_metas(pos) == {}
    assert store.pos_meta == {}


class PendingBuyBroker(FakeBroker):
    def __init__(self):
        super().__init__(equity=1000.0, cash=1000.0)
        self.client_ids = []
        self.fill_on_call = 2

    def buy_notional(self, sym, dollars, *, client_order_id):
        self.client_ids.append(client_order_id)
        if len(self.client_ids) < self.fill_on_call:
            return {
                "id": "alpaca-buy-1", "client_order_id": client_order_id,
                "status": "accepted", "filled_qty": 0, "filled_avg_price": 0,
            }
        self._positions[sym] = {
            "qty": 2, "market_value": 200.0, "avg_entry": 100.0,
            "current_price": 100.0, "unrealized_pl": 0.0,
        }
        return {
            "id": "alpaca-buy-1", "client_order_id": client_order_id,
            "status": "filled", "filled_qty": 2, "filled_avg_price": 100,
        }

    def wait_for_order(self, order_id, timeout=12):
        return {
            "id": order_id, "client_order_id": self.client_ids[-1],
            "status": "accepted", "filled_qty": 0, "filled_avg_price": 0,
        }


def test_accepted_buy_keeps_queue_and_reuses_client_id_until_fill(monkeypatch):
    store = FakeStore()
    store.kv["brake"] = {"peak_equity": 1000.0, "halted": False}
    store.pending = [_buy("SPY")]
    broker = PendingBuyBroker()
    eng = _make_engine(monkeypatch, broker, store)

    assert eng.job_execute_open() is False
    assert store.pending and store.pending[0]["symbol"] == "SPY"
    assert "SPY" not in store.pos_meta
    assert store.trades == []

    # Simulate the accepted order filling between cron ticks. The next run must
    # reconcile the saved client id even though cash is now reserved/zero and
    # the position already appears at Alpaca.
    broker._cash = 0.0
    broker._positions["SPY"] = {
        "qty": 2, "market_value": 200.0, "avg_entry": 100.0,
        "current_price": 100.0, "unrealized_pl": 0.0,
    }
    assert eng.job_execute_open() is True
    assert broker.client_ids[0] == broker.client_ids[1]
    assert store.pending == []
    assert "SPY" in store.pos_meta
    assert len(store.trades) == 1


class PendingSellBroker(FakeBroker):
    def sell_all(self, sym, *, qty, client_order_id):
        self.sold.append((sym, client_order_id))
        return {
            "id": "alpaca-sell-1", "client_order_id": client_order_id,
            "status": "accepted", "filled_qty": 0, "filled_avg_price": 0,
        }

    def wait_for_order(self, order_id, timeout=12):
        return {"id": order_id, "status": "accepted"}


def test_hard_brake_keeps_unconfirmed_liquidation_for_retry(monkeypatch):
    store = FakeStore()
    store.kv["brake"] = {"peak_equity": 1000.0, "halted": False}
    store.pending = [_buy("QQQ")]
    store.pos_meta["SPY"] = {
        "symbol": "SPY", "sleeve": "momentum", "stop_level": 80.0,
        "stop_mult": 3.0, "entry_date": "2026-01-01", "held_days": 2,
    }
    pos = {"SPY": {"qty": 1, "market_value": 700.0, "avg_entry": 100.0,
                   "current_price": 70.0, "unrealized_pl": -300.0}}
    broker = PendingSellBroker(equity=700.0, cash=0.0, positions=pos)
    eng = _make_engine(monkeypatch, broker, store)

    assert eng.job_execute_open() is False
    assert [(o["side"], o["symbol"]) for o in store.pending] == [("sell", "SPY")]
    assert "SPY" in store.pos_meta


def test_partial_buy_failure_keeps_only_failed_orders(monkeypatch):
    store = FakeStore()
    store.kv["brake"] = {"peak_equity": 1000.0, "halted": False}
    store.pending = [_buy("SPY"), _buy("QQQ")]
    broker = FakeBroker(equity=1000.0, cash=1000.0, fail_buys={"QQQ"})
    eng = _make_engine(monkeypatch, broker, store)

    assert eng.job_execute_open() is False  # retry next tick
    assert [s for s, _ in broker.bought] == ["SPY"]
    assert [o["symbol"] for o in store.pending] == ["QQQ"]  # only the failure kept

    # next tick: broker recovers, retry succeeds and queue empties
    broker.fail_buys = set()
    assert eng.job_execute_open() is True
    assert [s for s, _ in broker.bought] == ["SPY", "QQQ"]
    assert store.pending == []


def test_all_orders_succeed_clears_queue(monkeypatch):
    store = FakeStore()
    store.kv["brake"] = {"peak_equity": 1000.0, "halted": False}
    store.pending = [_buy("SPY")]
    broker = FakeBroker(equity=1000.0, cash=1000.0)
    eng = _make_engine(monkeypatch, broker, store)

    assert eng.job_execute_open() is True
    assert [s for s, _ in broker.bought] == ["SPY"]
    assert store.pending == []
    assert "SPY" in store.pos_meta          # stop metadata recorded


def test_opening_stop_runs_even_without_pending_orders(monkeypatch):
    store = FakeStore()
    store.kv["brake"] = {"peak_equity": 1000.0, "halted": False}
    store.pos_meta["AAPL"] = {
        "symbol": "AAPL", "sleeve": "momentum", "stop_level": 95.0,
        "stop_mult": 3.0, "entry_date": "2026-01-01", "held_days": 3,
    }
    pos = {"AAPL": {"qty": 1, "market_value": 90.0, "avg_entry": 100.0,
                    "current_price": 90.0, "unrealized_pl": -10.0}}
    broker = FakeBroker(equity=990.0, cash=900.0, positions=pos)
    eng = _make_engine(monkeypatch, broker, store)

    assert eng.job_execute_open() is True
    assert broker.sold == ["AAPL"]
    assert "AAPL" not in store.pos_meta


def test_failed_sell_defers_all_buys(monkeypatch):
    store = FakeStore()
    store.kv["brake"] = {"peak_equity": 1000.0, "halted": False}
    store.pending = [_sell("AAPL"), _buy("QQQ")]
    pos = {"AAPL": {"qty": 1, "market_value": 100.0, "avg_entry": 100.0,
                    "current_price": 100.0, "unrealized_pl": 0.0}}
    broker = FakeBroker(
        equity=1000.0, cash=100.0, positions=pos, fail_sells={"AAPL"}
    )
    eng = _make_engine(monkeypatch, broker, store)

    assert eng.job_execute_open() is False
    assert broker.bought == []
    assert [(o["side"], o["symbol"]) for o in store.pending] == [
        ("sell", "AAPL"), ("buy", "QQQ")
    ]


def test_close_decision_carries_only_unexecuted_held_sells():
    old = [
        {"symbol": "AAPL", "sleeve": "dip", "side": "sell", "reason": "dip-exit"},
        {"symbol": "QQQ", "sleeve": "momentum", "side": "buy", "reason": ""},
        {"symbol": "MSFT", "sleeve": "momentum", "side": "sell", "reason": "stop"},
    ]
    fresh = [PendingOrder("XLK", "momentum", "buy", 0.3, 3.0)]
    held = {"AAPL": {}, "XLK": {}}

    merged = _carry_unexecuted_sells(fresh, old, held)
    assert [(o.side, o.symbol) for o in merged] == [
        ("sell", "AAPL"), ("buy", "XLK")
    ]
