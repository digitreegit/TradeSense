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
from app.engine import Engine


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
    def __init__(self, equity=1000.0, cash=1000.0, positions=None, fail_buys=()):
        self._equity = equity
        self._cash = cash
        self._positions = positions or {}
        self.fail_buys = set(fail_buys)
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
        self.sold.append(sym)
        self._positions.pop(sym, None)
        return True

    def wait_for_fills(self, timeout=30.0):
        pass


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
    eng._features = lambda syms: _features(*syms)
    return eng


def _buy(sym):
    return {"id": 1, "symbol": sym, "sleeve": "momentum", "side": "buy",
            "slot_weight": 0.3, "stop_mult": 3.0, "reason": "signal",
            "created_at": "2026-01-01T00:00:00+00:00"}


def test_hard_brake_at_open_cancels_buys_and_liquidates(monkeypatch):
    store = FakeStore()
    store.kv["brake"] = {"peak_equity": 1000.0, "halted": False}
    store.pending = [_buy("QQQ")]
    pos = {"SPY": {"qty": 1, "market_value": 700.0, "avg_entry": 100.0,
                   "current_price": 70.0, "unrealized_pl": -300.0}}
    broker = FakeBroker(equity=700.0, cash=0.0, positions=pos)  # 30% overnight dd
    eng = _make_engine(monkeypatch, broker, store)

    assert eng.job_execute_open() is True
    assert store.kv["brake"]["halted"] is True
    assert broker.sold == ["SPY"]           # liquidated, not bought
    assert broker.bought == []
    assert store.pending == []              # queued buys cancelled


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
