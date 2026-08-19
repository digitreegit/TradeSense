"""Crypto advisor — the bot tells the user exactly what to buy or sell
on Robinhood. Primary objective: recover original principal.

Alpaca cannot trade crypto in this account's state, so no real orders are
ever placed here. Proposed orders stay pending until the user confirms
(optionally with the actual Robinhood fill size). The book is updated only
on confirm. Checks run 09:00 / 12:00 / 21:00 ET.

Recovery playbook: do not average down a concentrated bag (XRP). Trim
overweight names, dump dust, and redeploy proceeds into relative-strength
uptrends. A naked grid still bleeds in downtrends, so entries require
price > 50EMA and 20EMA >= 50EMA.
"""
from __future__ import annotations

import copy
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd

from .briefing import log_activity
from .indicators import ema, rsi, sma
from .notify import send
from .state import store

log = logging.getLogger(__name__)

# Alpaca crypto data pairs that Robinhood also lists (manual execution venue).
CANDIDATES = [
    "BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "XRP/USD",
    "AVAX/USD", "LINK/USD", "LTC/USD", "UNI/USD", "SHIB/USD",
    "BCH/USD", "AAVE/USD",
]

BUDGET = 1000.0
MAX_POSITIONS = 4
MAX_UNITS = 2          # per coin: initial entry + one add on the dip
BOOK_KEY = "crypto_book"
PENDING_KEY = "crypto_pending"
CACHE_KEY = "crypto_advice"
CACHE_TTL = 900.0      # panel refresh window; scheduled runs bypass it

MIN_STEP = 0.04        # never advise a step tighter than 4%
MAX_STEP = 0.12
MAX_WEIGHT = 0.35      # one coin above this share of the book gets trimmed
TRIM_FRACTION = 0.45   # downtrend bags: unstick capital faster (was 30%)
TRIM_FRACTION_UP = 0.20
MAX_TRIM = 0.50        # never dump more than half a bag in one check
DUST_MIN = 50.0        # positions below this are consolidated when not trending up
MIN_UNIT = 25.0
BEAR_SIZE = 0.75       # recovery: deploy 75% size in a bear, not half
CASH_FLOOR = 0.15      # keep 15% cash; the rest can work
RSI_MAX = 75.0         # skip only clearly overbought strength
NO_AVERAGEDOWN = 0.15  # never add if price is >15% below original avg cost
SCHEDULE = "매일 09:00 · 12:00 · 21:00 (ET)"


def fetch_bars(days: int = 400) -> dict[str, pd.DataFrame]:
    """Public Alpaca crypto data — works without API keys."""
    from alpaca.data.historical import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = CryptoHistoricalDataClient()
    req = CryptoBarsRequest(
        symbol_or_symbols=CANDIDATES,
        timeframe=TimeFrame.Day,
        start=datetime.now(timezone.utc) - timedelta(days=days),
    )
    data = client.get_crypto_bars(req).data
    out: dict[str, pd.DataFrame] = {}
    for sym in CANDIDATES:
        bars = data.get(sym)
        if not bars:
            continue
        df = pd.DataFrame(
            {
                "date": [b.timestamp for b in bars],
                "open": [b.open for b in bars],
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
            }
        ).set_index("date")
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        out[sym] = df
    return out


def _coin_metrics(df: pd.DataFrame) -> dict | None:
    if len(df) < 60:
        return None
    close = df["close"]
    price = float(close.iloc[-1])
    ema20 = float(ema(close, 20).iloc[-1])
    ema50 = float(ema(close, 50).iloc[-1])
    range30 = float(((df["high"] - df["low"]) / df["close"]).tail(30).mean())
    if price > ema50 and ema20 >= ema50:
        trend = "up"
    elif price < ema50 and ema20 < ema50:
        trend = "down"
    else:
        trend = "side"
    return {
        "price": price,
        "trend": trend,
        "ema50": ema50,
        "range30": range30,
        "rsi14": float(rsi(close, 14).iloc[-1]),
        "ret30": float(price / close.iloc[-31] - 1) if len(close) > 31 else 0.0,
    }


def _step_for(range30: float) -> float:
    """RuleFive step sized to the coin's own daily range (~1.5 average days)."""
    return round(min(MAX_STEP, max(MIN_STEP, range30 * 1.5)), 2)


def _new_book() -> dict:
    return {
        "budget": BUDGET, "cash": BUDGET, "positions": {},
        "realized_pl": 0.0, "principal": BUDGET,
    }


def _underwater(pos: dict, price: float) -> bool:
    """True when adding would be averaging down a deep original loss."""
    avg = pos.get("avg_cost")
    return bool(avg) and avg > 0 and price < avg * (1 - NO_AVERAGEDOWN)


def _market_state(metrics: dict[str, dict]) -> tuple[str, str]:
    btc = metrics.get("BTC/USD")
    ups = sum(1 for m in metrics.values() if m["trend"] == "up")
    breadth = ups / len(metrics) if metrics else 0.0
    if btc and btc["trend"] == "up" and breadth >= 0.5:
        return "BULL", "강세 — BTC 상승 추세, 시장 폭 양호"
    if (btc and btc["trend"] == "down") or breadth < 0.25:
        return "BEAR", "약세 — 물타기 금지, 하락 편중은 축소, 강세 상대강도로만 재배치"
    return "CHOP", "혼조 — 상승 추세 코인만 제한적으로"


def generate_orders(
    frames: dict[str, pd.DataFrame], book: dict
) -> tuple[list[dict], dict, dict]:
    """Propose orders against a *copy* of the book. The caller's book is
    left unchanged — fills land only via confirm_order()."""
    metrics = {}
    for sym, df in frames.items():
        m = _coin_metrics(df)
        if m is not None:
            metrics[sym] = m

    label, comment = _market_state(metrics)
    bear = label == "BEAR"
    orders: list[dict] = []
    sim = copy.deepcopy(book)

    def _pos_value(pos: dict, sym: str) -> float:
        m = metrics.get(sym)
        px = m["price"] if m else pos["units"][-1]["price"]
        return sum(u["qty"] for u in pos["units"]) * px

    # size units off the whole book (real holdings + cash), not a fixed $1000
    total_value = sim["cash"] + sum(
        _pos_value(p, s) for s, p in sim["positions"].items()
    )
    unit = max(MIN_UNIT, round(total_value / MAX_POSITIONS / MAX_UNITS, 0))
    if bear:
        unit = max(MIN_UNIT, round(unit * BEAR_SIZE, 0))
    floor = CASH_FLOOR * total_value

    def _order(side: str, sym: str, dollars: float, price: float,
               reason: str, kind: str, step: float):
        orders.append({
            "id": uuid.uuid4().hex[:12],
            "side": side, "symbol": sym.split("/")[0], "pair": sym,
            "dollars": round(dollars, 0), "price": price, "reason": reason,
            "kind": kind, "step": step,
            "status": "pending", "actual_dollars": None,
        })

    sold_this_run: set[str] = set()
    for sym in list(sim["positions"]):
        m = metrics.get(sym)
        pos = sim["positions"][sym]
        if m is None:
            continue
        price, step = m["price"], pos["step"]
        value = sum(u["qty"] for u in pos["units"]) * price
        weight = value / total_value if total_value > 0 else 0.0

        # 0) dust that is not trending up: consolidate into cash
        if value < DUST_MIN and m["trend"] != "up":
            _order("sell", sym, value, price, "소액 정리 — 회복 기여 없음", "exit", step)
            apply_order(sim, orders[-1], value)
            sold_this_run.add(sym)
            continue

        # 1) oversized position: staged trim. Recovery wants capital unstuck
        # faster than a 30% drip, but never a full dump in one check.
        if weight > MAX_WEIGHT:
            frac = TRIM_FRACTION if m["trend"] == "down" else TRIM_FRACTION_UP
            excess = value - MAX_WEIGHT * total_value
            trim = min(value * MAX_TRIM, max(value * frac, excess * 0.5))
            why = ("하락 추세" if m["trend"] == "down" else "추세 무관") + \
                f" · 비중 {weight:.0%} — 원금 회복용 축소"
            _order("sell", sym, trim, price, why, "trim", step)
            apply_order(sim, orders[-1], trim)
            sold_this_run.add(sym)
            continue

        if m["trend"] == "down" or price < m["ema50"]:
            _order("sell", sym, value, price, "추세 이탈 — 전량 매도", "exit", step)
            apply_order(sim, orders[-1], value)
            sold_this_run.add(sym)
        elif price >= pos["anchor"] * (1 + step):
            u = pos["units"][-1]
            got = u["qty"] * price
            _order("sell", sym, got, price, f"익절 +{step:.0%}", "take_profit", step)
            apply_order(sim, orders[-1], got)
            sold_this_run.add(sym)
        elif (
            price <= pos["anchor"] * (1 - step)
            and len(pos["units"]) < MAX_UNITS
            and sim["cash"] - floor >= unit
            and not _underwater(pos, price)
        ):
            _order("buy", sym, unit, price, f"−{step:.0%} 추가 매수", "add", step)
            apply_order(sim, orders[-1], unit)

    def _can_deploy(new_slot: bool) -> bool:
        if sim["cash"] - floor < unit:
            return False
        if new_slot and len(sim["positions"]) >= MAX_POSITIONS:
            return False
        return True

    def _fits_cap(sym: str, dollars: float) -> bool:
        value = _pos_value(sim["positions"][sym], sym) if sym in sim["positions"] else 0.0
        return total_value <= 0 or (value + dollars) / total_value <= MAX_WEIGHT + 1e-9

    # Put trim proceeds to work in relative strength — don't let cash sit.
    # Rank by 30-day return (what's actually going up), not raw range.
    held_rs = sorted(
        (
            (sym, metrics[sym]) for sym in sim["positions"]
            if metrics.get(sym)
            and metrics[sym]["trend"] == "up"
            and metrics[sym]["rsi14"] < RSI_MAX
            and sym not in sold_this_run
            and not _underwater(sim["positions"][sym], metrics[sym]["price"])
            and len(sim["positions"][sym]["units"]) < MAX_UNITS
        ),
        key=lambda x: x[1]["ret30"], reverse=True,
    )
    for sym, m in held_rs:
        if not _can_deploy(new_slot=False) or not _fits_cap(sym, unit):
            continue
        step = sim["positions"][sym]["step"]
        _order("buy", sym, unit, m["price"],
               "원금 회복 — 상대강도 재배치", "rotate", step)
        apply_order(sim, orders[-1], unit)

    candidates = sorted(
        (
            (sym, m) for sym, m in metrics.items()
            if sym not in sim["positions"] and sym not in sold_this_run
            and m["trend"] == "up" and m["rsi14"] < RSI_MAX
        ),
        key=lambda x: x[1]["ret30"], reverse=True,
    )
    for sym, m in candidates:
        if not _can_deploy(new_slot=True):
            break
        step = _step_for(m["range30"])
        why = "원금 회복 — 상승 추세 진입"
        if bear:
            why += " · 약세장 축소 크기"
        _order("buy", sym, unit, m["price"], why, "entry", step)
        apply_order(sim, orders[-1], unit)

    sim["updated_at"] = datetime.now(timezone.utc).isoformat()
    market = {
        "label": label, "comment": comment,
        "btc_price": metrics.get("BTC/USD", {}).get("price"),
        "btc_ret30": metrics.get("BTC/USD", {}).get("ret30"),
    }
    # Panel P/L is the *confirmed* book, not the simulated fills.
    view = {"market": market, "summary": _summary(book, metrics)}
    return orders, sim, view


def apply_order(book: dict, order: dict, dollars: float) -> None:
    """Apply one fill to the book at `order['price']` for `dollars` notional."""
    dollars = float(dollars)
    if dollars <= 0:
        raise ValueError("금액은 0보다 커야 합니다")
    pair = order["pair"]
    price = float(order["price"])
    kind = order.get("kind") or ("buy" if order["side"] == "buy" else "exit")
    step = float(order.get("step") or MIN_STEP)

    if order["side"] == "buy":
        qty = dollars / price
        if pair not in book["positions"]:
            book["positions"][pair] = {
                "units": [], "anchor": price, "step": step,
            }
        pos = book["positions"][pair]
        pos["units"].append({"dollars": dollars, "price": price, "qty": qty})
        if kind == "add":
            pos["anchor"] = pos["anchor"] * (1 - pos["step"])
        book["cash"] -= dollars
        return

    pos = book["positions"].get(pair)
    if not pos or not pos["units"]:
        raise ValueError(f"{order['symbol']} 보유가 없어 매도할 수 없습니다")
    invested = sum(u["dollars"] for u in pos["units"])
    if kind == "take_profit":
        u = pos["units"].pop()
        book["cash"] += dollars
        book["realized_pl"] += dollars - u["dollars"]
        pos["anchor"] = pos["anchor"] * (1 + pos["step"])
        if not pos["units"]:
            del book["positions"][pair]
        return
    if kind == "trim":
        # partial sell: reduce every unit proportionally, anchor unchanged
        total_qty = sum(u["qty"] for u in pos["units"])
        ratio = min(1.0, (dollars / price) / total_qty) if total_qty > 0 else 1.0
        removed_cost = invested * ratio
        for u in pos["units"]:
            u["qty"] *= (1 - ratio)
            u["dollars"] *= (1 - ratio)
        book["cash"] += dollars
        book["realized_pl"] += dollars - removed_cost
        if ratio >= 0.999:
            del book["positions"][pair]
        return
    # full exit
    book["cash"] += dollars
    book["realized_pl"] += dollars - invested
    del book["positions"][pair]


def _summary(book: dict, metrics: dict[str, dict]) -> dict:
    positions_view = []
    total = book["cash"]
    for sym, pos in book["positions"].items():
        m = metrics.get(sym)
        price = m["price"] if m else pos["units"][-1]["price"]
        qty = sum(u["qty"] for u in pos["units"])
        invested = sum(u["dollars"] for u in pos["units"])
        value = qty * price
        total += value
        avg_cost = pos.get("avg_cost")
        positions_view.append({
            "symbol": sym.split("/")[0],
            "price": price,
            "invested": invested,
            "value": value,
            "pl": value - invested,
            "units": len(pos["units"]),
            "qty": qty,
            "avg_cost": avg_cost,
            "total_return": (price / avg_cost - 1) if avg_cost else None,
            "sell_at": pos["anchor"] * (1 + pos["step"]),
            "add_at": pos["anchor"] * (1 - pos["step"]) if len(pos["units"]) < MAX_UNITS else None,
            "exit_at": m["ema50"] if m else None,
        })
    principal = float(book.get("principal") or book.get("budget") or BUDGET)
    gap = max(0.0, principal - total)
    return {
        "cash": book["cash"],
        "total": total,
        "pl": total - book["budget"],
        "realized_pl": book["realized_pl"],
        "budget": book["budget"],
        "principal": principal,
        "gap": gap,
        "recovered_pct": (total / principal) if principal else 0.0,
        "positions": positions_view,
    }


def _fp(o: dict) -> tuple:
    return (o["side"], o["pair"], o.get("kind", ""))


def _merge_pending(old: list[dict], fresh: list[dict]) -> list[dict]:
    """Keep confirmation state when the same action is re-proposed."""
    by_fp = {_fp(o): o for o in old}
    out: list[dict] = []
    seen: set[tuple] = set()
    for o in fresh:
        prev = by_fp.get(_fp(o))
        if prev and prev.get("status") == "confirmed":
            o = {**o, "id": prev["id"], "status": "confirmed",
                 "actual_dollars": prev.get("actual_dollars")}
        elif prev:
            o = {**o, "id": prev["id"]}
        seen.add(_fp(o))
        out.append(o)
    for o in old:
        if o.get("status") == "confirmed" and _fp(o) not in seen:
            out.append(o)
    return out


def _panel(orders: list[dict], view: dict) -> dict:
    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schedule": SCHEDULE,
        "orders": orders,
        **view,
    }


def advise_and_apply(force: bool = False) -> dict:
    """Propose orders. Confirmed book is not touched until confirm_order()."""
    if not force:
        cached = store.get(CACHE_KEY)
        if cached and time.time() - cached.get("cached_at", 0) < CACHE_TTL:
            return cached["data"]
    try:
        frames = fetch_bars()
        if not frames:
            raise RuntimeError("no crypto bars returned")
        book = store.get(BOOK_KEY) or _new_book()
        orders, _, view = generate_orders(frames, book)
        orders = _merge_pending(store.get(PENDING_KEY) or [], orders)
        store.set(PENDING_KEY, orders)
    except Exception as exc:
        log.exception("crypto advice failed")
        return {"ok": False, "error": f"크립토 분석 실패: {exc}"}
    data = _panel(orders, view)
    store.set(CACHE_KEY, {"cached_at": time.time(), "data": data})
    return data


def confirm_order(order_id: str, actual_dollars: float | None = None) -> dict:
    """Mark a pending order executed and size the book to the real fill."""
    pending = store.get(PENDING_KEY) or []
    order = next((o for o in pending if o.get("id") == order_id), None)
    if order is None:
        return {"ok": False, "error": "해당 주문을 찾을 수 없습니다. 패널을 새로고침하세요."}
    if order.get("status") == "confirmed":
        cached = store.get(CACHE_KEY)
        return (cached or {}).get("data") or {"ok": True, "orders": pending}
    dollars = float(actual_dollars) if actual_dollars is not None else float(order["dollars"])
    book = store.get(BOOK_KEY) or _new_book()
    try:
        apply_order(book, order, dollars)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    book["updated_at"] = datetime.now(timezone.utc).isoformat()
    order["status"] = "confirmed"
    order["actual_dollars"] = round(dollars, 2)
    store.set(BOOK_KEY, book)
    store.set(PENDING_KEY, pending)
    store.set(CACHE_KEY, None)
    log_activity(
        "crypto",
        f"실행 확인 {order['side']} {order['symbol']} "
        f"추천 ${order['dollars']:.0f} → 실제 ${dollars:.0f}",
    )
    # Rebuild the panel against the updated book (keep pending confirmations).
    data = advise_and_apply(force=True)
    return data


def reset_book() -> None:
    store.set(BOOK_KEY, _new_book())
    store.set(PENDING_KEY, [])
    store.set(CACHE_KEY, None)


def import_holdings(
    cash: float, holdings: list[dict], principal: float | None = None,
) -> dict:
    """Rebuild the book from the user's real Robinhood holdings.

    Cost basis inside the book is marked to market at import (so summary P/L
    measures improvement *since import*); the original avg cost is kept per
    position for the truthful total-return display. `principal` is the
    recovery target (original capital); if omitted it is inferred from
    qty × avg_cost + cash.
    """
    valid = {p.split("/")[0]: p for p in CANDIDATES}
    frames = fetch_bars()
    metrics = {s: m for s, m in
               ((sym, _coin_metrics(df)) for sym, df in frames.items()) if m}
    book = {"budget": 0.0, "cash": float(cash), "positions": {},
            "realized_pl": 0.0, "principal": 0.0}
    skipped: list[str] = []
    inferred = float(cash)
    for h in holdings:
        sym = str(h.get("symbol", "")).upper().strip()
        qty = float(h.get("qty") or 0)
        pair = valid.get(sym)
        if not pair or qty <= 0:
            skipped.append(sym or "?")
            continue
        m = metrics.get(pair)
        if m is None:
            skipped.append(sym)
            continue
        price = m["price"]
        avg_cost = float(h["avg_cost"]) if h.get("avg_cost") else None
        book["positions"][pair] = {
            "units": [{"dollars": qty * price, "price": price, "qty": qty}],
            "anchor": price,
            "step": _step_for(m["range30"]),
            "avg_cost": avg_cost,
        }
        inferred += qty * (avg_cost if avg_cost else price)
    book["budget"] = book["cash"] + sum(
        sum(u["dollars"] for u in p["units"]) for p in book["positions"].values()
    )
    book["principal"] = float(principal) if principal and principal > 0 else inferred
    book["updated_at"] = datetime.now(timezone.utc).isoformat()
    store.set(BOOK_KEY, book)
    store.set(PENDING_KEY, [])
    store.set(CACHE_KEY, None)
    log_activity(
        "crypto",
        f"실보유 등록 — {len(book['positions'])}종목 + 현금 ${cash:,.0f}"
        + (f", 제외: {', '.join(skipped)}" if skipped else ""),
    )
    data = advise_and_apply(force=True)
    if data.get("ok") and skipped:
        data["skipped"] = skipped
    return data


def _fmt_px(v: float) -> str:
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 10:
        return f"{v:.2f}"
    if v >= 0.1:
        return f"{v:.3f}"
    return f"{v:.6g}"


def run_scheduled(slot: str) -> bool:
    """Three daily checks (09:00 / 12:00 / 21:00 ET). Telegram on every slot."""
    data = advise_and_apply(force=True)
    if not data.get("ok"):
        log_activity("crypto", f"크립토 어드바이저 실패: {data.get('error')}")
        return False

    s = data["summary"]
    pending_orders = [o for o in data.get("orders", []) if o.get("status") != "confirmed"]
    lines = [
        f"{'🟢 매수' if o['side'] == 'buy' else '🔴 매도'} {o['symbol']} "
        f"${o['dollars']:,.0f} (@${_fmt_px(o['price'])}) — {o['reason']}"
        for o in pending_orders
    ]
    gap = s.get("gap") or 0
    principal = s.get("principal") or s.get("budget") or 0
    status = (
        f"현재 ${s['total']:,.0f} / 원금 ${principal:,.0f} "
        f"(남음 ${gap:,.0f}) · 현금 ${s['cash']:,.0f} · "
        f"시장 {data['market']['label']}"
    )
    labels = {"am": "아침", "noon": "점심", "pm": "저녁"}
    when = labels.get(slot, slot)
    if lines:
        body = (
            f"🪙 크립토 {when} 주문 — 로빈후드에서 실행 후 대시보드에서 확인을 누르세요\n"
            + "\n".join(lines) + "\n" + status
        )
    else:
        body = f"🪙 크립토 {when} 점검 — 주문 없음, 보유 유지\n{status}"

    if not send(body):
        log_activity("crypto", f"크립토 어드바이저({slot}) — 텔레그램 발송 실패")
        return False

    n = len(pending_orders)
    log_activity("crypto", f"크립토 어드바이저({slot}) — 주문 {n}건, {status}")
    return True
