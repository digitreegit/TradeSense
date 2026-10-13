"""v6.3 — paper ("테스트") trading venue.

Wraps a real venue: real prices, real universe, real market hours — but
cash, positions and resting orders live in the store, and nothing reaches
the broker. The engine cannot tell the difference, so the same rules run
with the same bugs, which is the point: test with play money first.

Fill model matches scripts/dip_replay.py (conservative): marketable buys
pay the quote plus a taker cost, sells receive the quote minus it; a
resting limit fills only once the live quote has crossed it, at the limit.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from .state import store

log = logging.getLogger(__name__)

MODES = ("paper", "live")
DEFAULT_MODE = "paper"
DEFAULT_CASH = {"robinhood": 7000.0, "alpaca": 1050.0}
MIN_CASH = 100.0
MAX_CASH = 10_000_000.0
COST = {"robinhood": 0.005, "alpaca": 0.0005}  # per side


def clamp_cash(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return MIN_CASH
    return round(max(MIN_CASH, min(MAX_CASH, v)), 2)


def book_key(venue_name: str) -> str:
    return f"paper_book:{venue_name}"


def fresh_book(start_cash: float, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {"cash": float(start_cash), "start_cash": float(start_cash), "positions": {},
            "orders": {}, "started_at": now.isoformat()}


class PaperVenue:
    paper = True

    def __init__(self, real, start_cash: float | None = None):
        self.real = real
        self.name = real.name
        self.label = f"{real.label} · 테스트"
        self.universe = real.universe
        self.strategy = getattr(real, "strategy", "grid")
        self.resting_limits = bool(getattr(real, "resting_limits", False))
        self.no_same_day_round_trip = bool(getattr(real, "no_same_day_round_trip", False))
        self.cost = COST.get(real.name, 0.005)
        self._start_cash = float(start_cash if start_cash is not None else DEFAULT_CASH.get(real.name, 1000.0))

    # ---- state -------------------------------------------------------------
    def _book(self) -> dict:
        b = store.get(book_key(self.name))
        if not b:
            b = fresh_book(self._start_cash)
            store.set(book_key(self.name), b)
        return b

    def _save(self, b: dict) -> None:
        store.set(book_key(self.name), b)

    def reset(self, start_cash: float, now: datetime | None = None) -> dict:
        b = fresh_book(start_cash, now)
        self._save(b)
        return b

    # ---- venue protocol ----------------------------------------------------
    def configured(self) -> bool:
        return self.real.configured()

    def ready(self) -> tuple[bool, str]:
        return self.real.ready()

    def cash(self) -> float:
        return float(self._book()["cash"])

    def positions(self) -> dict[str, float]:
        return {s: float(q) for s, q in self._book()["positions"].items() if float(q) > 0}

    def prices(self, symbols: list[str]) -> dict[str, float]:
        return self.real.prices(symbols)

    def tradable(self, symbols: list[str]) -> list[str]:
        return self.real.tradable(symbols)

    def equity(self) -> float | None:
        b = self._book()
        pos = {s: float(q) for s, q in b["positions"].items() if float(q) > 0}
        prices = self.prices(list(pos)) if pos else {}
        locked = sum(float(o.get("dollars") or 0) for o in b["orders"].values()
                     if o["state"] == "open" and o["side"] == "buy")
        return round(float(b["cash"]) + locked + sum(q * prices.get(s, 0.0) for s, q in pos.items()), 2)

    def __getattr__(self, item):
        # market_universe, recent_hourly_highs, ... — read-only helpers of the real venue.
        if item in ("market_universe", "recent_hourly_highs"):
            return getattr(self.real, item)
        raise AttributeError(item)

    # ---- fills -------------------------------------------------------------
    def buy(self, symbol: str, dollars: float, ref_price: float) -> dict:
        b = self._book()
        dollars = round(float(dollars), 2)
        if dollars <= 0 or not ref_price or ref_price <= 0:
            return {"ok": False, "error": "잘못된 주문"}
        if dollars > float(b["cash"]) + 1e-9:
            return {"ok": False, "error": f"테스트 현금 부족 (${b['cash']:,.2f} < ${dollars:,.2f})"}
        px = float(ref_price) * (1.0 + self.cost)
        qty = dollars / px
        b["cash"] = round(float(b["cash"]) - dollars, 2)
        b["positions"][symbol] = float(b["positions"].get(symbol, 0.0)) + qty
        self._save(b)
        return {"ok": True, "qty": qty, "price": px, "dollars": dollars}

    def sell(self, symbol: str, qty: float, ref_price: float) -> dict:
        b = self._book()
        held = float(b["positions"].get(symbol, 0.0))
        locked = sum(float(o.get("qty") or 0) for o in b["orders"].values()
                     if o["state"] == "open" and o["side"] == "sell" and o["symbol"] == symbol)
        avail = held - locked
        qty = min(float(qty), avail)
        if qty <= 0 or not ref_price or ref_price <= 0:
            return {"ok": False, "transient": True,
                    "error": f"{symbol} 매도 가능 수량이 없습니다 (보유 {held:g}, 대기 주문 {locked:g})"}
        px = float(ref_price) * (1.0 - self.cost)
        dollars = round(qty * px, 2)
        b["positions"][symbol] = held - qty
        if b["positions"][symbol] <= 1e-12:
            b["positions"].pop(symbol, None)
        b["cash"] = round(float(b["cash"]) + dollars, 2)
        self._save(b)
        return {"ok": True, "qty": qty, "price": px, "dollars": dollars}

    # ---- resting limits ------------------------------------------------------
    def place_resting(self, side: str, symbol: str, *, limit_price: float,
                      qty: float | None = None, dollars: float | None = None) -> dict:
        b = self._book()
        limit_price = float(limit_price)
        if side == "buy":
            dollars = round(float(dollars if dollars is not None else (qty or 0) * limit_price), 2)
            if dollars <= 0:
                return {"ok": False, "error": "잘못된 주문"}
            if dollars > float(b["cash"]) + 1e-9:
                return {"ok": False, "error": f"테스트 현금 부족 (${b['cash']:,.2f})"}
            qty = dollars / limit_price
            b["cash"] = round(float(b["cash"]) - dollars, 2)  # locked until fill/cancel
        else:
            qty = float(qty if qty is not None else (dollars or 0) / limit_price)
            held = float(b["positions"].get(symbol, 0.0))
            locked = sum(float(o.get("qty") or 0) for o in b["orders"].values()
                         if o["state"] == "open" and o["side"] == "sell" and o["symbol"] == symbol)
            if qty > held - locked + 1e-12:
                return {"ok": False, "transient": True,
                        "error": f"{symbol} 매도 가능 수량이 없습니다 (보유 {held:g}, 대기 {locked:g})"}
            dollars = round(qty * limit_price, 2)
        oid = f"paper-{uuid.uuid4().hex[:12]}"
        b["orders"][oid] = {"id": oid, "side": side, "symbol": symbol, "limit_price": limit_price,
                            "qty": float(qty), "dollars": dollars, "state": "open",
                            "at": datetime.now(timezone.utc).isoformat()}
        self._save(b)
        return {"ok": True, "rh_order_id": oid, "rh_api_version": "paper",
                "limit_price": limit_price, "qty": float(qty), "dollars": dollars}

    def _try_fill(self, b: dict, o: dict) -> None:
        if o["state"] != "open":
            return
        px = self.prices([o["symbol"]]).get(o["symbol"])
        if not px:
            return
        if o["side"] == "sell" and px >= o["limit_price"]:
            held = float(b["positions"].get(o["symbol"], 0.0))
            qty = min(float(o["qty"]), held)
            b["positions"][o["symbol"]] = held - qty
            if b["positions"][o["symbol"]] <= 1e-12:
                b["positions"].pop(o["symbol"], None)
            o["dollars"] = round(qty * o["limit_price"], 2)
            o["qty"] = qty
            b["cash"] = round(float(b["cash"]) + o["dollars"], 2)
            o["state"] = "filled"
        elif o["side"] == "buy" and px <= o["limit_price"]:
            b["positions"][o["symbol"]] = float(b["positions"].get(o["symbol"], 0.0)) + float(o["qty"])
            o["state"] = "filled"  # cash was locked at placement

    def resting_status(self, meta: dict) -> dict:
        b = self._book()
        o = b["orders"].get(str(meta.get("id")))
        if not o:
            return {"ok": True, "state": "canceled", "terminal": True, "pending": False,
                    "filled": False, "qty": 0, "price": 0, "dollars": 0}
        self._try_fill(b, o)
        self._save(b)
        filled = o["state"] == "filled"
        return {"ok": True, "state": o["state"], "filled": filled, "pending": o["state"] == "open",
                "terminal": o["state"] in ("filled", "canceled"),
                "qty": float(o["qty"]) if filled else 0.0,
                "price": float(o["limit_price"]) if filled else 0.0,
                "dollars": float(o["dollars"]) if filled else 0.0}

    def cancel_resting(self, meta: dict) -> dict:
        b = self._book()
        o = b["orders"].get(str(meta.get("id")))
        if o and o["state"] == "open":
            if o["side"] == "buy":
                b["cash"] = round(float(b["cash"]) + float(o["dollars"]), 2)
            o["state"] = "canceled"
            self._save(b)
        return {"ok": True, "state": "canceled"}
