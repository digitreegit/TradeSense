"""TradeSense v4 — grid engine: one tick every ~15 minutes for both venues.

Venue adapters hide the broker APIs; everything strategy-related lives in
`grid.py`. Per-venue lifecycle stored in `grid_book`:

    idle → liquidating → running
            (sell every API-tradable holding, then size the ladders from
             the freed cash and seed them)

Stocks (Alpaca) only act while the market is open; crypto (Robinhood) runs
around the clock. Symbols that Robinhood does not allow through the API are
left alone and listed as "manual" in the status view.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from . import grid
from .briefing import log_activity
from .config import settings
from .state import store

log = logging.getLogger(__name__)

SETTINGS_KEY = "grid_settings"
BOOK_KEY = "grid_book"
TRADES_KEY = "grid_trades"
TICK_KEY = "grid_last_tick"
MAX_TRADES_KEPT = 500
ORDER_WAIT_SECONDS = 20.0
# Resize the ladders upward when cash + cost basis exceeds the planned
# allocation by this factor (new deposits, app sales moved into the grid).
RESIZE_TRIGGER = 1.15


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def get_settings() -> dict:
    raw = store.get(SETTINGS_KEY) or {}
    return {
        "step": grid.clamp_step(raw.get("step", grid.DEFAULT_STEP)),
        "enabled": bool(raw.get("enabled", False)),
        "updated_at": raw.get("updated_at"),
    }


def _save_settings(**changes) -> dict:
    cur = get_settings()
    cur.update(changes)
    cur["updated_at"] = datetime.now(timezone.utc).isoformat()
    store.set(SETTINGS_KEY, cur)
    return cur


def set_step(step: float) -> dict:
    s = grid.clamp_step(step)
    out = _save_settings(step=s)
    log_activity("grid", f"그리드 간격을 {s:.1%}로 변경")
    return out


def set_enabled(enabled: bool) -> dict:
    out = _save_settings(enabled=bool(enabled))
    log_activity("grid", "그리드 자동매매 ON" if enabled else "그리드 자동매매 OFF (보유 유지)")
    return out


# --------------------------------------------------------------------------
# Venues
# --------------------------------------------------------------------------
class Venue(Protocol):
    name: str
    label: str
    universe: tuple[str, ...]

    def configured(self) -> bool: ...
    def ready(self) -> tuple[bool, str]: ...
    def cash(self) -> float: ...
    def prices(self, symbols: list[str]) -> dict[str, float]: ...
    def positions(self) -> dict[str, float]: ...
    def tradable(self, symbols: list[str]) -> list[str]: ...
    def buy(self, symbol: str, dollars: float, ref_price: float) -> dict: ...
    def sell(self, symbol: str, qty: float, ref_price: float) -> dict: ...


def _fail(error: str, *, transient: bool = False) -> dict:
    return {"ok": False, "error": str(error), "transient": transient}


def _fill(qty: float, price: float, dollars: float | None = None) -> dict:
    qty = float(qty)
    price = float(price)
    return {"ok": True, "qty": qty, "price": price,
            "dollars": round(float(dollars) if dollars else qty * price, 2)}


class AlpacaVenue:
    name = "alpaca"
    label = "주식 · Alpaca"
    universe = grid.STOCK_UNIVERSE
    no_same_day_round_trip = True

    def __init__(self) -> None:
        self._broker = None

    @property
    def broker(self):
        if self._broker is None:
            from .broker import Broker
            self._broker = Broker()
        return self._broker

    def configured(self) -> bool:
        from .alpaca_config import get_credentials, is_paper_key
        key, secret, _ = get_credentials()
        return bool(key and secret) and not is_paper_key(key)

    def ready(self) -> tuple[bool, str]:
        if not self.configured():
            return False, "Alpaca 키 미설정"
        if not self.broker.market_open_now():
            return False, "미국 장 마감 중"
        return True, ""

    def cash(self) -> float:
        acct = self.broker.trading.get_account()
        # Spendable cash. Alpaca margin-type accounts (the default, also under
        # $2k) can reuse same-day sale proceeds, so buying_power == cash right
        # after a liquidation; the min() only matters when BP is below cash.
        # (non_marginable_buying_power excluded unsettled proceeds and sized
        # the first ladders on 1/3 of the account — 2026-09-17.)
        cash = float(acct.cash or 0)
        bp = getattr(acct, "buying_power", None)
        if bp is not None:
            try:
                cash = min(cash, float(bp))
            except (TypeError, ValueError):
                pass
        return max(cash, 0.0)

    def equity(self) -> float | None:
        try:
            return float(self.broker.trading.get_account().equity)
        except Exception as exc:
            log.warning("alpaca equity failed: %s", exc)
            return None

    def prices(self, symbols: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for s in symbols:
            px = self.broker.latest_price(s)
            if px and px > 0:
                out[s] = float(px)
        return out

    def positions(self) -> dict[str, float]:
        return {sym: float(p["qty"]) for sym, p in self.broker.positions().items()}

    def tradable(self, symbols: list[str]) -> list[str]:
        out = []
        for s in symbols:
            try:
                asset = self.broker.trading.get_asset(s)
                if getattr(asset, "tradable", False) and getattr(asset, "fractionable", False):
                    out.append(s)
            except Exception as exc:
                log.warning("get_asset(%s) failed: %s", s, exc)
        return out

    def _settle(self, order: dict | None, side: str, symbol: str) -> dict:
        if not order:
            return _fail(f"{symbol} {side} 주문 응답 없음", transient=True)
        if order.get("error"):
            return _fail(order["error"], transient=True)
        oid = order.get("id")
        final = self.broker.wait_for_order(oid, timeout=ORDER_WAIT_SECONDS) if oid else order
        final = final or order
        status = str(final.get("status") or "")
        filled_qty = float(final.get("filled_qty") or 0)
        avg = float(final.get("filled_avg_price") or 0)
        if status == "filled" and filled_qty > 0 and avg > 0:
            return _fill(filled_qty, avg)
        # Marketable limits fill instantly or not at all: cancel and retry
        # next tick at a fresh quote rather than leaving a resting order.
        if oid and status not in ("filled", "canceled", "rejected", "expired"):
            self.broker.cancel_order(oid)
            final = self.broker.wait_for_order(oid, timeout=5.0) or final
            filled_qty = float(final.get("filled_qty") or 0)
            avg = float(final.get("filled_avg_price") or 0)
        if filled_qty > 0 and avg > 0:
            return _fill(filled_qty, avg)
        return _fail(f"{symbol} {side} 주문이 체결되지 않아 취소했습니다 (상태 {status or 'unknown'}).",
                     transient=True)

    def buy(self, symbol: str, dollars: float, ref_price: float) -> dict:
        try:
            limit = self.broker.marketable_limit_price(symbol, "buy", reference_price=ref_price)
            order = self.broker.buy_notional(
                symbol, round(float(dollars), 2),
                client_order_id=f"g4-{uuid.uuid4().hex[:20]}", limit_price=limit,
            )
            return self._settle(order, "buy", symbol)
        except Exception as exc:
            log.exception("alpaca buy %s failed", symbol)
            return _fail(str(exc), transient=True)

    def sell(self, symbol: str, qty: float, ref_price: float) -> dict:
        try:
            limit = self.broker.marketable_limit_price(symbol, "sell", reference_price=ref_price)
            order = self.broker.sell_all(
                symbol, qty=float(qty),
                client_order_id=f"g4-{uuid.uuid4().hex[:20]}", limit_price=limit,
            )
            return self._settle(order, "sell", symbol)
        except Exception as exc:
            log.exception("alpaca sell %s failed", symbol)
            return _fail(str(exc), transient=True)


class RobinhoodVenue:
    name = "robinhood"
    label = "크립토 · Robinhood"
    universe = grid.CRYPTO_UNIVERSE

    def __init__(self) -> None:
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from .robinhood_client import RobinhoodCryptoClient
            from .robinhood_config import get_credentials
            key, private = get_credentials()
            if not key or not private:
                raise RuntimeError("Robinhood API 키가 없습니다.")
            self._client = RobinhoodCryptoClient(key, private)
        return self._client

    @staticmethod
    def _rh(pair: str) -> str:
        return pair.replace("/USD", "-USD").upper()

    @staticmethod
    def _pair(code: str) -> str:
        return f"{str(code).upper().replace('-USD', '')}/USD"

    def configured(self) -> bool:
        from .robinhood_config import is_configured
        return is_configured()

    def ready(self) -> tuple[bool, str]:
        if not self.configured():
            return False, "Robinhood 키 미설정"
        return True, ""

    def cash(self) -> float:
        return float(self.client.get_account().get("buying_power") or 0)

    def equity(self) -> float | None:
        """Buying power + every crypto holding at live mid (manual coins too)."""
        try:
            positions = self.positions()
            prices = self.prices(list(positions)) if positions else {}
            return self.cash() + sum(q * prices.get(s, 0.0) for s, q in positions.items())
        except Exception as exc:
            log.warning("robinhood equity failed: %s", exc)
            return None

    def prices(self, symbols: list[str]) -> dict[str, float]:
        from .robinhood_live import _mid_from_quote
        if not symbols:
            return {}
        out: dict[str, float] = {}
        quotes = self.client.get_best_bid_ask(*[self._rh(s) for s in symbols])
        for row in quotes.get("results") or []:
            sym = str(row.get("symbol") or "")
            if not sym:
                continue
            px = _mid_from_quote(row)
            if px:
                out[self._pair(sym)] = float(px)
        return out

    def positions(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for row in self.client.get_all_holdings():
            code = str(row.get("asset_code") or "").upper()
            qty = float(row.get("total_quantity") or 0)
            if code and qty > 0:
                out[self._pair(code)] = out.get(self._pair(code), 0.0) + qty
        return out

    def tradable(self, symbols: list[str]) -> list[str]:
        if not symbols:
            return []
        codes = [s.split("/")[0] for s in symbols]
        ok_map = self.client.api_tradable_map(*codes)
        return [s for s in symbols if ok_map.get(s.split("/")[0]) is True]

    def _place(self, side: str, pair: str, dollars: float, ref_price: float) -> dict:
        from .robinhood_orders import place_market_dollars
        try:
            r = place_market_dollars(
                side=side, pair=pair, dollars=round(float(dollars), 2),
                client_order_id=str(uuid.uuid4()), fallback_price=ref_price,
                expected_price=ref_price,
            )
        except Exception as exc:
            log.exception("robinhood %s %s failed", side, pair)
            return _fail(str(exc), transient=True)
        if r.get("ok") and float(r.get("qty") or 0) > 0:
            return _fill(r["qty"], r.get("price") or ref_price, r.get("dollars"))
        return _fail(r.get("error") or "주문 실패",
                     transient=bool(r.get("transient") or r.get("retryable") or r.get("pending")))

    def buy(self, symbol: str, dollars: float, ref_price: float) -> dict:
        return self._place("buy", symbol, dollars, ref_price)

    def sell(self, symbol: str, qty: float, ref_price: float) -> dict:
        return self._place("sell", symbol, float(qty) * float(ref_price), ref_price)


_VENUES: list | None = None


def venues() -> list:
    global _VENUES
    if _VENUES is None:
        _VENUES = [RobinhoodVenue(), AlpacaVenue()]
    return _VENUES


def set_venues(items: list | None) -> None:
    """Test hook: inject fake venues (None restores the real ones)."""
    global _VENUES
    _VENUES = items


# --------------------------------------------------------------------------
# Book helpers
# --------------------------------------------------------------------------
def _empty_venue_book() -> dict:
    return {"phase": "idle", "ladders": {}, "manual": [], "unit_dollars": None,
            "note": None, "errors": [], "started_at": None, "updated_at": None,
            "cash": None, "grid_value": None, "account_total": None}


def _account_total(venue) -> float | None:
    fn = getattr(venue, "equity", None)
    if fn is None:
        return None
    try:
        v = fn()
        return round(float(v), 2) if v is not None else None
    except Exception as exc:
        log.warning("%s equity failed: %s", venue.name, exc)
        return None


def get_book() -> dict:
    book = store.get(BOOK_KEY) or {}
    for v in venues():
        book.setdefault(v.name, _empty_venue_book())
    return book


def _record_trade(trade: dict) -> None:
    trades = store.get(TRADES_KEY) or []
    trades.append(trade)
    store.set(TRADES_KEY, trades[-MAX_TRADES_KEPT:])


def recent_trades(limit: int = 100) -> list[dict]:
    trades = store.get(TRADES_KEY) or []
    return list(reversed(trades[-limit:]))


def _notify(text: str) -> None:
    try:
        from .notify import send
        send(text)
    except Exception:
        log.exception("telegram notify failed")


def _fmt_px(px: float) -> str:
    return f"{px:,.2f}" if px >= 1 else f"{px:.6g}"


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------
def start(*, run_now: bool = True) -> dict:
    """Liquidate everything API-tradable, then rebuild the ladders from cash."""
    book = get_book()
    for v in venues():
        vb = _empty_venue_book()
        vb["phase"] = "liquidating"
        vb["note"] = "보유 청산 후 사다리 구성 대기"
        book[v.name] = vb
    store.set(BOOK_KEY, book)
    store.set(TRADES_KEY, [])
    # Retire v3 state so old stop/pending logic can never act again.
    try:
        store.reset_trading_state()
    except Exception:
        log.exception("v3 state reset failed")
    _save_settings(enabled=True)
    log_activity("grid", "v4 그리드 시작 — 보유 청산 후 사다리 구성")
    _notify("[v4 그리드] 시작 — API로 팔 수 있는 보유를 정리한 뒤 사다리를 구성합니다.")
    if run_now:
        try:
            tick()
        except Exception:
            log.exception("initial grid tick failed")
    return status()


def stop() -> dict:
    set_enabled(False)
    _notify("[v4 그리드] 자동매매 OFF — 보유는 그대로 둡니다.")
    return status()


def resume() -> dict:
    set_enabled(True)
    _notify("[v4 그리드] 자동매매 ON")
    return status()


def tick(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    s = get_settings()
    out: dict = {"at": now.isoformat(), "enabled": s["enabled"], "step": s["step"], "venues": {}}
    if not s["enabled"]:
        out["skipped"] = "off"
        store.set(TICK_KEY, out)
        return out
    book = get_book()
    for v in venues():
        vb = book.setdefault(v.name, _empty_venue_book())
        try:
            out["venues"][v.name] = _tick_venue(v, vb, s["step"], now)
        except Exception as exc:
            log.exception("grid tick %s failed", v.name)
            vb["note"] = f"오류: {exc}"
            out["venues"][v.name] = {"error": str(exc)}
        vb["updated_at"] = now.isoformat()
        store.set(BOOK_KEY, book)  # persist per venue so one failure loses nothing
    store.set(TICK_KEY, out)
    return out


def _tick_venue(venue, vb: dict, step: float, now: datetime) -> dict:
    if not venue.configured():
        return {"skipped": "키 미설정"}
    phase = vb.get("phase") or "idle"
    if phase == "idle":
        return {"skipped": "시작 전"}
    ok, why = venue.ready()
    if not ok:
        return {"skipped": why}
    if phase == "liquidating":
        result = _liquidate(venue, vb, now)
        if vb.get("phase") != "running":
            return result
    return _run(venue, vb, step, now)


def _liquidate(venue, vb: dict, now: datetime) -> dict:
    positions = {s: q for s, q in venue.positions().items() if q > 0}
    tradable = set(venue.tradable(list(positions))) if positions else set()
    prices = venue.prices(list(positions)) if positions else {}
    sold, manual, errors = [], [], []
    for sym, qty in positions.items():
        if sym not in tradable:
            manual.append(sym)
            continue
        px = prices.get(sym)
        if not px:
            errors.append(f"{sym}: 시세 없음")
            continue
        r = venue.sell(sym, qty, px)
        if r.get("ok"):
            sold.append(sym)
            _record_trade({
                "at": now.isoformat(), "venue": venue.name, "symbol": sym, "side": "sell",
                "qty": r["qty"], "price": r["price"], "dollars": r["dollars"],
                "pl": None, "reason": "v4 시작 청산", "units_after": 0,
            })
            log_activity("grid", f"{venue.label} {sym} 청산 ${r['dollars']:,.2f}")
        else:
            errors.append(f"{sym}: {r.get('error')}")
            log_activity("grid", f"{venue.label} {sym} 청산 실패: {r.get('error')}")
    vb["manual"] = sorted(manual)
    vb["errors"] = errors
    vb["account_total"] = _account_total(venue)
    if sold or errors:
        vb["note"] = "청산 진행 중" + (f" · 오류 {len(errors)}건 — 다음 점검에서 재시도" if errors else "")
        return {"liquidated": sold, "errors": errors, "manual": manual}

    cash = venue.cash()
    syms = venue.tradable(list(venue.universe))
    if not syms:
        vb["note"] = "API로 자동 거래 가능한 종목이 없습니다."
        return {"skipped": vb["note"]}
    unit = grid.unit_size(cash, len(syms))
    if unit < grid.MIN_ORDER_DOLLARS:
        vb["note"] = f"현금 ${cash:,.2f}로는 {len(syms)}종목 사다리를 만들 수 없습니다."
        return {"skipped": vb["note"]}
    vb["ladders"] = {s: grid.new_ladder(s, venue.name, unit) for s in syms}
    vb["unit_dollars"] = unit
    vb["phase"] = "running"
    vb["started_at"] = now.isoformat()
    vb["note"] = None
    msg = (f"{venue.label} 사다리 구성: {', '.join(syms)} · 칸당 ${unit:,.2f} "
           f"× {grid.MAX_UNITS}칸 (현금 ${cash:,.2f})")
    log_activity("grid", msg)
    _notify(f"[v4 그리드] {msg}")
    return {"seeded": syms, "unit_dollars": unit, "manual": manual}


def _run(venue, vb: dict, step: float, now: datetime) -> dict:
    ladders: dict[str, dict] = vb.get("ladders") or {}
    if not ladders:
        vb["note"] = "사다리가 없습니다. 다시 시작하세요."
        return {"skipped": vb["note"]}
    syms = list(ladders)
    prices = venue.prices(syms)
    positions = venue.positions()
    cash = venue.cash()
    _maybe_resize(venue, vb, ladders, cash)
    actions: list[tuple[str, dict, float]] = []
    for sym, ladder in ladders.items():
        px = prices.get(sym)
        if not px:
            ladder["last_error"] = "시세 없음"
            continue
        if ladder.get("seeded"):
            note = grid.reconcile(ladder, positions.get(sym, 0.0), px)
            if note:
                log_activity("grid", note)
        grid.observe(ladder, px)
        if ladder.get("top_up"):
            deficit = grid.top_up_deficit(ladder)
            if deficit < grid.MIN_ORDER_DOLLARS:
                ladder.pop("top_up", None)
            else:
                actions.append((sym, {"side": "buy", "dollars": deficit, "n_units": 0,
                                      "top_up": True, "reason": "칸 크기 보충"}, px))
                continue
        action = grid.decide(ladder, px, step, cash)
        if not action:
            continue
        if action["side"] == "sell" and getattr(venue, "no_same_day_round_trip", False):
            # Under $25k a same-day buy→sell counts toward the pattern-day-trader
            # limit; hold the rung until the next session instead.
            tz = ZoneInfo(settings.timezone)
            if grid.top_unit_bought_on(ladder, now.astimezone(tz).date(), tz):
                ladder["last_error"] = "당일 매수 칸 — 다음 거래일부터 매도 (PDT 회피)"
                continue
        actions.append((sym, action, px))

    # Sells first so freed cash can fund this tick's buys.
    actions.sort(key=lambda a: 0 if a[1]["side"] == "sell" else 1)
    fills, errors = [], []
    for sym, action, px in actions:
        ladder = ladders[sym]
        if action["side"] == "buy":
            if cash < float(action["dollars"]) * 0.999:
                ladder["last_error"] = f"현금 부족 (${cash:,.2f})"
                continue
            r = venue.buy(sym, action["dollars"], px)
        else:
            r = venue.sell(sym, action["qty"], px)
        if not r.get("ok"):
            ladder["last_error"] = r.get("error")
            errors.append(f"{sym}: {r.get('error')}")
            log_activity("grid", f"{venue.label} {sym} {action['side']} 실패: {r.get('error')}")
            continue
        if action.get("top_up"):
            trade = grid.apply_top_up(ladder, qty=r["qty"], price=r["price"],
                                      dollars=r["dollars"], at=now)
        else:
            trade = grid.apply_fill(
                ladder, side=action["side"], qty=r["qty"], price=r["price"],
                dollars=r["dollars"], n_units=int(action.get("n_units") or 1), at=now,
            )
        trade["reason"] = action.get("reason")
        _record_trade(trade)
        cash += r["dollars"] if action["side"] == "sell" else -r["dollars"]
        fills.append(trade)
        side_ko = "매수" if action["side"] == "buy" else "매도"
        pl_txt = f" · 실현 {trade['pl']:+,.2f}" if trade.get("pl") is not None else ""
        line = (f"{venue.label} {sym} {side_ko} ${r['dollars']:,.2f} @ {_fmt_px(r['price'])} "
                f"({trade['units_after']}/{ladder['max_units']}칸){pl_txt}")
        log_activity("grid", line)
        _notify(f"[v4 그리드] {line}")

    vb["cash"] = round(cash, 2)
    vb["grid_value"] = round(sum(
        grid.held_qty(l) * prices.get(s, l.get("last_price") or 0) for s, l in ladders.items()
    ), 2)
    vb["errors"] = errors
    vb["account_total"] = _account_total(venue)
    vb["note"] = None if not errors else f"주문 오류 {len(errors)}건 — 다음 점검에서 재시도"
    return {"fills": len(fills), "errors": errors, "cash": vb["cash"]}


def _maybe_resize(venue, vb: dict, ladders: dict[str, dict], cash: float) -> str | None:
    """Grow the rungs when the venue holds materially more capital than the
    ladders were sized for (deposit, or an app sale moved into buying power).
    Never shrinks: losses must not quietly reduce the plan. Held units are
    topped up on the next tick so the rung count stays the same."""
    if not ladders:
        return None
    n = len(ladders)
    unit_old = float(vb.get("unit_dollars") or 0)
    basis = sum(grid.cost_basis(l) for l in ladders.values())
    capital = cash + basis
    planned = unit_old * grid.MAX_UNITS * n
    if unit_old <= 0 or capital < planned * RESIZE_TRIGGER:
        return None
    unit_new = grid.unit_size(capital, n)
    if unit_new <= unit_old:
        return None
    for l in ladders.values():
        l["unit_dollars"] = unit_new
        if l.get("units"):
            l["top_up"] = True
    vb["unit_dollars"] = unit_new
    msg = (f"{venue.label} 자본 ${capital:,.2f} 감지 — 칸당 ${unit_old:,.2f} → ${unit_new:,.2f}, "
           f"보유 칸 보충 매수")
    log_activity("grid", msg)
    _notify(f"[v4 그리드] {msg}")
    return msg


# --------------------------------------------------------------------------
# Status for the dashboard
# --------------------------------------------------------------------------
def status() -> dict:
    s = get_settings()
    book = get_book()
    out_venues = {}
    for v in venues():
        vb = book.get(v.name) or _empty_venue_book()
        ladders = vb.get("ladders") or {}
        rows = [grid.summary(l, s["step"]) for l in ladders.values()]
        realized = round(sum(r["realized_pl"] for r in rows), 2)
        unreal = [r["unrealized_pl"] for r in rows if r["unrealized_pl"] is not None]
        configured = False
        try:
            configured = v.configured()
        except Exception:
            pass
        # Account total and cash come straight from the broker on every
        # status read; the tick-time copies are only a fallback.
        account_total = vb.get("account_total")
        cash = vb.get("cash")
        if configured:
            live_total = _account_total(v)
            if live_total is not None:
                account_total = live_total
            try:
                cash = round(float(v.cash()), 2)
            except Exception as exc:
                log.warning("%s cash failed: %s", v.name, exc)
        out_venues[v.name] = {
            "label": v.label,
            "configured": configured,
            "phase": vb.get("phase") or "idle",
            "note": vb.get("note"),
            "errors": vb.get("errors") or [],
            "manual": vb.get("manual") or [],
            "unit_dollars": vb.get("unit_dollars"),
            "account_total": account_total,
            "cash": cash,
            "grid_value": vb.get("grid_value"),
            "realized_pl": realized,
            "unrealized_pl": round(sum(unreal), 2) if unreal else None,
            "started_at": vb.get("started_at"),
            "updated_at": vb.get("updated_at"),
            "ladders": rows,
            "universe": list(v.universe),
        }
    return {
        "version": "v4",
        "settings": s,
        "venues": out_venues,
        "trades": recent_trades(60),
        "last_tick": store.get(TICK_KEY),
        "activity": list(reversed((store.get("activity_log") or [])[-40:])),
    }
