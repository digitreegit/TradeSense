"""Crypto advisor — the bot "trades" a virtual $1,000 book and tells the user
exactly what to buy or sell; the user only executes the orders on Robinhood.

Alpaca cannot trade crypto in this account's state, so no real orders are
ever placed here. The book (positions, cash, anchors) lives in the store and
is checked three times a day (09:00 / 12:00 / 21:00 ET) by the cron scheduler; each order
is assumed executed at the quoted price.

Signal design (lesson from scripts/grid_sim.py on stocks): a naked grid
bleeds in downtrends, so entries require an uptrend (price > 50EMA and
20EMA >= 50EMA), a trend break liquidates, and the RuleFive step is sized by
each coin's own realized daily range instead of a fixed 5%.
"""
from __future__ import annotations

import logging
import time
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
CACHE_KEY = "crypto_advice"
CACHE_TTL = 900.0      # panel refresh window; scheduled runs bypass it

MIN_STEP = 0.04        # never advise a step tighter than 4%
MAX_STEP = 0.12
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
    return {"budget": BUDGET, "cash": BUDGET, "positions": {}, "realized_pl": 0.0}


def _market_state(metrics: dict[str, dict]) -> tuple[str, str]:
    btc = metrics.get("BTC/USD")
    ups = sum(1 for m in metrics.values() if m["trend"] == "up")
    breadth = ups / len(metrics) if metrics else 0.0
    if btc and btc["trend"] == "up" and breadth >= 0.5:
        return "BULL", "강세 — BTC 상승 추세, 시장 폭 양호"
    if (btc and btc["trend"] == "down") or breadth < 0.25:
        return "BEAR", "약세 — BTC 하락 추세. 신규 진입 절반 크기, 이탈 시 즉시 정리"
    return "CHOP", "혼조 — 상승 추세 코인만 제한적으로"


def generate_orders(
    frames: dict[str, pd.DataFrame], book: dict
) -> tuple[list[dict], dict, dict]:
    """Pure decision step: (orders, updated book, market info).

    Orders are applied to the book at the quoted price — the user's manual
    execution is assumed to follow.
    """
    metrics = {}
    for sym, df in frames.items():
        m = _coin_metrics(df)
        if m is not None:
            metrics[sym] = m

    label, comment = _market_state(metrics)
    bear = label == "BEAR"
    unit = round(BUDGET / MAX_POSITIONS / MAX_UNITS, 0)   # $125
    if bear:
        unit = round(unit / 2, 0)
    orders: list[dict] = []

    def _order(side: str, sym: str, dollars: float, price: float, reason: str):
        orders.append({
            "side": side, "symbol": sym.split("/")[0], "pair": sym,
            "dollars": round(dollars, 0), "price": price, "reason": reason,
        })

    # 1) manage held positions: trend-break exit, take profit, add on dip
    sold_this_run: set[str] = set()
    for sym in list(book["positions"]):
        m = metrics.get(sym)
        pos = book["positions"][sym]
        if m is None:
            continue
        price, step = m["price"], pos["step"]
        invested = sum(u["dollars"] for u in pos["units"])
        value = sum(u["qty"] for u in pos["units"]) * price

        if m["trend"] == "down" or price < m["ema50"]:
            _order("sell", sym, value, price, "추세 이탈 — 전량 매도")
            book["cash"] += value
            book["realized_pl"] += value - invested
            del book["positions"][sym]
            sold_this_run.add(sym)
        elif price >= pos["anchor"] * (1 + step):
            u = pos["units"].pop()                        # LIFO: last buy first
            got = u["qty"] * price
            _order("sell", sym, got, price, f"익절 +{step:.0%}")
            book["cash"] += got
            book["realized_pl"] += got - u["dollars"]
            pos["anchor"] = pos["anchor"] * (1 + step)
            sold_this_run.add(sym)
            if not pos["units"]:
                del book["positions"][sym]
        elif (
            price <= pos["anchor"] * (1 - step)
            and len(pos["units"]) < MAX_UNITS
            and book["cash"] >= unit
        ):
            _order("buy", sym, unit, price, f"−{step:.0%} 추가 매수")
            pos["units"].append({"dollars": unit, "price": price, "qty": unit / price})
            book["cash"] -= unit
            pos["anchor"] = pos["anchor"] * (1 - step)

    # 2) new entries: highest-range uptrending coins, not overheated. A coin
    # sold this run must not be rebought in the same breath.
    candidates = sorted(
        (
            (sym, m) for sym, m in metrics.items()
            if sym not in book["positions"] and sym not in sold_this_run
            and m["trend"] == "up" and m["rsi14"] < 70
        ),
        key=lambda x: x[1]["range30"], reverse=True,
    )
    for sym, m in candidates:
        if len(book["positions"]) >= MAX_POSITIONS or book["cash"] < unit:
            break
        step = _step_for(m["range30"])
        _order("buy", sym, unit, m["price"],
               ("약세장 절반 크기 · " if bear else "") + "신규 진입 — 상승 추세")
        book["positions"][sym] = {
            "units": [{"dollars": unit, "price": m["price"], "qty": unit / m["price"]}],
            "anchor": m["price"],
            "step": step,
        }
        book["cash"] -= unit

    book["updated_at"] = datetime.now(timezone.utc).isoformat()

    # valuation snapshot for the panel / notification
    positions_view = []
    total = book["cash"]
    for sym, pos in book["positions"].items():
        m = metrics.get(sym)
        price = m["price"] if m else pos["units"][-1]["price"]
        qty = sum(u["qty"] for u in pos["units"])
        invested = sum(u["dollars"] for u in pos["units"])
        value = qty * price
        total += value
        positions_view.append({
            "symbol": sym.split("/")[0],
            "price": price,
            "invested": invested,
            "value": value,
            "pl": value - invested,
            "units": len(pos["units"]),
            "sell_at": pos["anchor"] * (1 + pos["step"]),
            "add_at": pos["anchor"] * (1 - pos["step"]) if len(pos["units"]) < MAX_UNITS else None,
            "exit_at": m["ema50"] if m else None,
        })

    market = {
        "label": label, "comment": comment,
        "btc_price": metrics.get("BTC/USD", {}).get("price"),
        "btc_ret30": metrics.get("BTC/USD", {}).get("ret30"),
    }
    summary = {
        "cash": book["cash"],
        "total": total,
        "pl": total - book["budget"] ,
        "realized_pl": book["realized_pl"],
        "budget": book["budget"],
        "positions": positions_view,
    }
    return orders, book, {"market": market, "summary": summary}


def advise_and_apply(force: bool = False) -> dict:
    """Compute today's orders and roll them into the virtual book (cached)."""
    if not force:
        cached = store.get(CACHE_KEY)
        if cached and time.time() - cached.get("cached_at", 0) < CACHE_TTL:
            return cached["data"]
    try:
        frames = fetch_bars()
        if not frames:
            raise RuntimeError("no crypto bars returned")
        book = store.get(BOOK_KEY) or _new_book()
        orders, book, view = generate_orders(frames, book)
        store.set(BOOK_KEY, book)
    except Exception as exc:
        log.exception("crypto advice failed")
        return {"ok": False, "error": f"크립토 분석 실패: {exc}"}
    data = {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schedule": SCHEDULE,
        "orders": orders,
        **view,
    }
    store.set(CACHE_KEY, {"cached_at": time.time(), "data": data})
    return data


def reset_book() -> None:
    store.set(BOOK_KEY, _new_book())
    store.set(CACHE_KEY, None)  # invalidate the panel cache


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
    lines = [
        f"{'🟢 매수' if o['side'] == 'buy' else '🔴 매도'} {o['symbol']} "
        f"${o['dollars']:,.0f} (@${_fmt_px(o['price'])}) — {o['reason']}"
        for o in data["orders"]
    ]
    status = (
        f"평가 ${s['total']:,.0f} ({s['pl']:+,.0f}) · 현금 ${s['cash']:,.0f} · "
        f"시장 {data['market']['label']}"
    )
    labels = {"am": "아침", "noon": "점심", "pm": "저녁"}
    when = labels.get(slot, slot)
    if lines:
        send(f"🪙 크립토 {when} 주문 — 로빈후드에서 실행하세요\n"
             + "\n".join(lines) + "\n" + status)
    else:
        send(f"🪙 크립토 {when} 점검 — 주문 없음, 보유 유지\n{status}")

    n = len(data["orders"])
    log_activity("crypto", f"크립토 어드바이저({slot}) — 주문 {n}건, {status}")
    return True
