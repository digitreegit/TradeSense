"""Crypto advisor — the bot tells the user exactly what to buy or sell
on Robinhood. Primary objective: recover original principal.

Alpaca cannot trade crypto in this account's state, so no real orders are
ever placed here. Proposed orders stay pending until the user confirms
(optionally with the actual Robinhood fill size). The book is updated only
on confirm. Checks run every ~15 min while awake (06:00–23:59 ET);
Telegram only when a tip needs approval (quiet 00:00–05:59 ET).

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
from zoneinfo import ZoneInfo

import pandas as pd

from .briefing import log_activity
from .config import settings
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
NOTIFY_FP_KEY = "crypto_notify_fp"
CACHE_KEY = "crypto_advice"
QTY_SEEN_KEY = "crypto_rh_qty_seen"  # last RH qty used for fill detection
CACHE_TTL = 900.0      # panel refresh window; scheduled runs bypass it
LIVE_CACHE_TTL = 45.0  # when Robinhood API is linked, refresh more often
CONFIRM_COOLDOWN_HOURS = 24.0  # don't re-queue same side+symbol after confirm

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
SCHEDULE = "수시 점검 (06:00–24:00 ET) · 거래 필요할 때만 텔레그램 · 00–06시 조용"
QUIET_START_HOUR = 0   # inclusive ET
QUIET_END_HOUR = 6     # exclusive — no Telegram midnight–6 AM ET


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
        "realized_pl": 0.0, "principal": BUDGET, "stocks_value": 0.0,
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
    deployable = max(0.0, sim["cash"] - floor)
    if deployable >= MIN_UNIT:
        unit = min(unit, deployable)
    else:
        unit = 0.0

    def _order(side: str, sym: str, dollars: float, price: float,
               reason: str, kind: str, step: float):
        pos = sim["positions"].get(sym)
        baseline = sum(float(u.get("qty") or 0) for u in (pos or {}).get("units") or [])
        orders.append({
            "id": uuid.uuid4().hex[:12],
            "side": side, "symbol": sym.split("/")[0], "pair": sym,
            "dollars": round(dollars, 0), "price": price, "reason": reason,
            "kind": kind, "step": step,
            "status": "pending", "actual_dollars": None,
            "baseline_qty": baseline,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    sold_this_run: set[str] = set()
    bought_this_run: set[str] = set()
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
            bought_this_run.add(sym)

    def _can_deploy(new_slot: bool) -> bool:
        if unit < MIN_UNIT:
            return False
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
            and sym not in bought_this_run
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


def _action_key(o: dict) -> tuple:
    return (o["side"], o["symbol"])


_SELL_KIND_PRIORITY = {"exit": 0, "trim": 1, "take_profit": 2}
_BUY_KIND_PRIORITY = {"rotate": 0, "add": 1, "entry": 2}


def _action_priority(o: dict) -> tuple:
    """Lower tuple wins. Tie-break: higher dollars wins."""
    side = o["side"]
    kind = o.get("kind") or ""
    pri = (_SELL_KIND_PRIORITY if side == "sell" else _BUY_KIND_PRIORITY).get(kind, 99)
    return (pri, -float(o.get("dollars") or 0))


_TERMINAL = frozenset({"confirmed", "denied"})


def _collapse_actionable(orders: list[dict]) -> list[dict]:
    """Keep at most one pending order per (side, symbol). Terminal orders untouched."""
    terminal = [o for o in orders if o.get("status") in _TERMINAL]
    pending = [o for o in orders if o.get("status") not in _TERMINAL]
    best: dict[tuple, dict] = {}
    for o in pending:
        key = _action_key(o)
        if key not in best or _action_priority(o) < _action_priority(best[key]):
            best[key] = o
    return terminal + list(best.values())


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_recent(ts: str | None, hours: float = CONFIRM_COOLDOWN_HOURS) -> bool:
    when = _parse_ts(ts)
    if when is None:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when >= datetime.now(timezone.utc) - timedelta(hours=hours)


def _recently_confirmed_actions(orders: list[dict]) -> set[tuple]:
    """(side, symbol) pairs confirmed recently — suppress re-queue."""
    out: set[tuple] = set()
    for o in orders:
        if o.get("status") != "confirmed":
            continue
        if _is_recent(o.get("confirmed_at")):
            out.add(_action_key(o))
    return out


def _merge_pending(old: list[dict], fresh: list[dict]) -> list[dict]:
    """Keep confirmation/denial state when the same action is re-proposed."""
    by_fp = {_fp(o): o for o in old}
    by_action: dict[tuple, dict] = {}
    for o in old:
        if o.get("status") not in _TERMINAL:
            by_action[_action_key(o)] = o
    recent_confirmed = _recently_confirmed_actions(old)
    out: list[dict] = []
    seen_fp: set[tuple] = set()
    for o in fresh:
        fp = _fp(o)
        action = _action_key(o)
        # Don't put a just-filled recommendation back on the main list.
        if action in recent_confirmed:
            continue
        prev_fp = by_fp.get(fp)
        if prev_fp and prev_fp.get("status") == "denied":
            seen_fp.add(fp)
            if not any(x.get("id") == prev_fp.get("id") for x in out):
                out.append(prev_fp)
            continue
        if prev_fp and prev_fp.get("status") == "confirmed":
            if _is_recent(prev_fp.get("confirmed_at")):
                # Same tip already executed recently — keep history only.
                seen_fp.add(fp)
                if not any(x.get("id") == prev_fp.get("id") for x in out):
                    out.append(prev_fp)
                continue
            # Cooldown expired — allow a fresh recommendation with a new id.
            o = {**o, "id": str(uuid.uuid4())}
        else:
            prev_action = by_action.get(action)
            if prev_action:
                o = {**o, "id": prev_action["id"]}
                if prev_action.get("baseline_qty") is not None:
                    o["baseline_qty"] = prev_action["baseline_qty"]
        seen_fp.add(fp)
        out.append(o)
    for o in old:
        if o.get("status") in _TERMINAL and _fp(o) not in seen_fp:
            out.append(o)
    return out


def _history_ts(o: dict) -> str:
    return o.get("confirmed_at") or o.get("denied_at") or ""


def _panel(orders: list[dict], view: dict) -> dict:
    from .robinhood_config import get_execution_mode, is_configured

    active = [o for o in orders if o.get("status") not in _TERMINAL]
    history = [o for o in orders if o.get("status") in _TERMINAL]
    history.sort(key=_history_ts, reverse=True)
    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schedule": SCHEDULE,
        "orders": active,
        "order_history": history,
        "execution_mode": get_execution_mode(),
        "robinhood_configured": is_configured(),
        **view,
    }


def _ensure_order_split(data: dict) -> dict:
    """Guarantee terminal orders live in order_history, not the active todo list."""
    if not data.get("ok"):
        return data
    combined: dict[str, dict] = {}
    for o in (data.get("orders") or []) + (data.get("order_history") or []):
        oid = o.get("id") or str(uuid.uuid4())
        combined[oid] = o
    orders = list(combined.values())
    active = [o for o in orders if o.get("status") not in _TERMINAL]
    history = [o for o in orders if o.get("status") in _TERMINAL]
    history.sort(key=_history_ts, reverse=True)
    return {**data, "orders": active, "order_history": history}


def _order_fingerprint(orders: list[dict]) -> tuple:
    return tuple(sorted(
        (o.get("id"), o["side"], o["symbol"], round(float(o["dollars"]), 2))
        for o in orders
    ))


def _format_crypto_telegram(data: dict, source: str) -> str:
    from .robinhood_config import get_execution_mode

    s = data.get("summary") or {}
    pending = data.get("orders") or []
    mode = get_execution_mode()
    lines = [
        f"{'🟢 매수' if o['side'] == 'buy' else '🔴 매도'} {o['symbol']} "
        f"${o['dollars']:,.0f} (@${_fmt_px(o['price'])}) — {o['reason']}"
        for o in pending
    ]
    gap = s.get("gap") or 0
    principal = s.get("principal") or s.get("budget") or 0
    status = (
        f"현재 ${s.get('total', 0):,.0f} / 원금 ${principal:,.0f} "
        f"(남음 ${gap:,.0f}) · 현금 ${s.get('cash', 0):,.0f} · "
        f"시장 {(data.get('market') or {}).get('label', '?')}"
    )
    if not lines:
        return f"🪙 크립토 {source} — 주문 없음, 보유 유지\n{status}"

    if mode == "semi":
        header = (
            f"⚠️ 거래 승인 필요 ({source})\n"
            f"앱 열고 → 크립토 탭 → [API 주문] 눌러 주세요\n"
            f"https://tradesense.skyface.com"
        )
    elif mode == "auto":
        header = f"🤖 크립토 자동실행 대기/진행 ({source})"
    else:
        header = (
            f"🪙 크립토 {source} — 로빈후드 앱에서 실행 후 대시보드에서 확인\n"
            f"https://tradesense.skyface.com"
        )
    return header + "\n" + "\n".join(lines) + "\n" + status


def _in_quiet_hours(now: datetime | None = None) -> bool:
    """True during ET quiet window (default midnight–06:00)."""
    tz = ZoneInfo(settings.timezone)
    local = (now or datetime.now(tz)).astimezone(tz)
    return QUIET_START_HOUR <= local.hour < QUIET_END_HOUR


def notify_crypto_orders(data: dict, source: str, *, force: bool = False) -> bool:
    """Telegram when crypto tips need attention.

    - Sends only when there are actionable pending tips (unless force=True).
    - Dedupes identical tip sets via fingerprint.
    - Quiet hours (00:00–05:59 ET): never send, even with force.
    """
    if not data.get("ok"):
        return False
    if _in_quiet_hours():
        log.info("crypto telegram skipped — quiet hours (%s)", source)
        return True
    pending = data.get("orders") or []
    if not pending and not force:
        return True
    # Prefer not to spam empty "할 일 없음" — force empty is reserved for rare ops.
    if not pending and force:
        # Still allow empty pings only outside quiet hours when explicitly forced
        # for diagnostics; scheduled checks no longer force empty.
        pass
    fp = _order_fingerprint(pending) if pending else ("empty",)
    if not force and store.get(NOTIFY_FP_KEY) == fp:
        return True
    body = _format_crypto_telegram(data, source)
    if not send(body):
        log.warning("crypto telegram notify failed (%s)", source)
        return False
    store.set(NOTIFY_FP_KEY, fp)
    return True


# Auto-confirm when RH holdings / fills moved at least this fraction of recommended $
_AUTO_FILL_MIN_FRAC = 0.35
_AUTO_FILL_MIN_DOLLARS = 25.0


def _snap_qty_by_pair(snap: dict | None) -> dict[str, float]:
    if not snap:
        return {}
    return {
        row["pair"]: float(row.get("qty") or 0)
        for row in (snap.get("positions") or [])
        if row.get("pair")
    }


def _filled_order_notional(row: dict) -> float:
    qty = float(row.get("filled_asset_quantity") or 0)
    avg = float(row.get("average_price") or 0)
    if qty > 0 and avg > 0:
        return qty * avg
    for key in ("market_order_config", "limit_order_config",
                "stop_loss_order_config", "stop_limit_order_config"):
        cfg = row.get(key) or {}
        qa = cfg.get("quote_amount")
        if qa is not None:
            try:
                return float(qa)
            except (TypeError, ValueError):
                pass
        aq = cfg.get("asset_quantity")
        if aq is not None and avg > 0:
            try:
                return float(aq) * avg
            except (TypeError, ValueError):
                pass
    return 0.0


def _rh_symbol_to_pair(symbol: str) -> str | None:
    sym = str(symbol or "").upper().replace("-USD", "").replace("/USD", "").strip()
    if not sym:
        return None
    for pair in CANDIDATES:
        if pair.split("/")[0] == sym:
            return pair
    return None


def _qty_delta_dollars(
    baseline_qty: float,
    snap: dict,
    order: dict,
) -> float | None:
    """Estimate fill notional from RH qty change vs baseline. Positive or None."""
    pair = order.get("pair") or ""
    side = order.get("side")
    by_pair = {
        (row.get("pair") or ""): row
        for row in (snap.get("positions") or [])
    }
    row = by_pair.get(pair)
    new_qty = float(row["qty"]) if row else 0.0
    old_qty = float(baseline_qty)
    price = float(row["price"]) if row and float(row.get("price") or 0) > 0 else 0.0
    if price <= 0 and side == "sell" and old_qty > new_qty:
        price = float(order.get("price") or 0)
    if price <= 0:
        return None
    if side == "buy":
        delta = new_qty - old_qty
    else:
        delta = old_qty - new_qty
    if delta <= 1e-12:
        return None
    return round(delta * price, 2)


def _mark_confirmed(order: dict, dollars: float, *, source: str) -> None:
    recommended = float(order.get("dollars") or 0)
    order["status"] = "confirmed"
    order["actual_dollars"] = round(float(dollars), 2)
    order["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    order["auto_confirmed"] = True
    order["auto_confirm_source"] = source
    log_activity(
        "crypto",
        f"자동 확인 {order.get('side')} {order.get('symbol')} "
        f"추천 ${recommended:.0f} → RH 반영 ${float(dollars):.0f}"
        + (f" ({source})" if source else ""),
    )


def _save_pending_after_confirm(pending: list[dict], confirmed: list[dict]) -> None:
    confirmed_actions = {_action_key(o) for o in confirmed}
    keep = [
        o for o in pending
        if o.get("status") in _TERMINAL or _action_key(o) not in confirmed_actions
    ]
    by_id = {o.get("id"): o for o in keep}
    for o in confirmed:
        by_id[o.get("id")] = o
    store.set(PENDING_KEY, list(by_id.values()))
    store.set(CACHE_KEY, None)


def auto_confirm_from_robinhood(
    prev_qty: dict[str, float],
    snap: dict | None,
    pending: list[dict],
    filled_orders: list[dict] | None = None,
) -> list[dict]:
    """Mark pending recs confirmed when Robinhood shows a matching fill.

    Prefers RH filled-order history; falls back to holdings qty delta vs a
    stable baseline (order.baseline_qty or last seen qty). Does not mutate the
    book — live sync already applied holdings.
    """
    if not snap or not pending:
        return []
    confirmed: list[dict] = []
    used_pairs: set[str] = set()
    used_fill_ids: set[str] = set()
    pending_changed = False

    # 1) Match Robinhood filled orders (most reliable).
    for fill in filled_orders or []:
        state = str(fill.get("state") or "").lower()
        if state not in ("filled", "partially_filled"):
            continue
        fill_id = str(fill.get("id") or "")
        if fill_id and fill_id in used_fill_ids:
            continue
        pair = _rh_symbol_to_pair(str(fill.get("symbol") or ""))
        if not pair or pair in used_pairs:
            continue
        side = str(fill.get("side") or "").lower()
        if side not in ("buy", "sell"):
            continue
        dollars = _filled_order_notional(fill)
        if dollars < _AUTO_FILL_MIN_DOLLARS:
            continue
        fill_ts = _parse_ts(fill.get("updated_at") or fill.get("created_at"))
        for order in pending:
            if order.get("status") in _TERMINAL:
                continue
            if order.get("pair") != pair or order.get("side") != side:
                continue
            recommended = float(order.get("dollars") or 0)
            need = max(_AUTO_FILL_MIN_DOLLARS, recommended * _AUTO_FILL_MIN_FRAC)
            if dollars < need:
                continue
            rec_ts = _parse_ts(order.get("created_at"))
            # Ignore fills that clearly happened before this tip was created.
            if fill_ts and rec_ts and fill_ts < rec_ts - timedelta(minutes=5):
                continue
            _mark_confirmed(order, dollars, source="order")
            if fill_id:
                order["rh_order_id"] = fill_id
                used_fill_ids.add(fill_id)
            used_pairs.add(pair)
            confirmed.append(order)
            break

    # 2) Qty delta vs baseline (works when orders API is empty / delayed).
    for order in pending:
        if order.get("status") in _TERMINAL:
            continue
        pair = order.get("pair") or ""
        if not pair or pair in used_pairs:
            continue
        side = order.get("side")
        if side not in ("buy", "sell"):
            continue
        if order.get("baseline_qty") is None:
            # Seed once from last-seen qty so the *next* real fill can be detected.
            order["baseline_qty"] = float(prev_qty.get(pair) or 0.0)
            pending_changed = True
        dollars = _qty_delta_dollars(float(order["baseline_qty"]), snap, order)
        if dollars is None:
            continue
        recommended = float(order.get("dollars") or 0)
        need = max(_AUTO_FILL_MIN_DOLLARS, recommended * _AUTO_FILL_MIN_FRAC)
        if dollars < need:
            continue
        _mark_confirmed(order, dollars, source="qty")
        used_pairs.add(pair)
        confirmed.append(order)

    if confirmed:
        _save_pending_after_confirm(pending, confirmed)
    elif pending_changed:
        store.set(PENDING_KEY, pending)

    # Advance the durable qty watermark after we've had a chance to match fills.
    store.set(QTY_SEEN_KEY, _snap_qty_by_pair(snap))
    return confirmed


def holdings_qty_changed(prev_qty: dict[str, float], snap: dict | None) -> bool:
    if not snap:
        return False
    new_qty = _snap_qty_by_pair(snap)
    keys = set(prev_qty) | set(new_qty)
    for k in keys:
        if abs(float(prev_qty.get(k) or 0) - float(new_qty.get(k) or 0)) > 1e-9:
            return True
    return False


def advise_and_apply(force: bool = False) -> dict:
    """Propose orders. Confirmed book is not touched until confirm_order()."""
    rh_live = None
    prev_qty: dict[str, float] = {}
    auto_confirmed: list[dict] = []
    try:
        from .robinhood_config import is_configured, get_credentials
        from .robinhood_client import RobinhoodCryptoClient
        from .robinhood_live import merge_live_into_summary, refresh_from_robinhood_live

        if is_configured():
            # Prefer durable last-seen qty over book (book may already include the fill).
            seen = store.get(QTY_SEEN_KEY)
            rh_live, _live_prices, book_prev = refresh_from_robinhood_live()
            prev_qty = seen if isinstance(seen, dict) else book_prev
            if rh_live:
                filled: list[dict] = []
                try:
                    api_key, private_key = get_credentials()
                    if api_key and private_key:
                        filled = RobinhoodCryptoClient(api_key, private_key).get_recent_filled_orders()
                except Exception:
                    log.exception("robinhood filled orders fetch failed")
                auto_confirmed = auto_confirm_from_robinhood(
                    prev_qty, rh_live, store.get(PENDING_KEY) or [], filled,
                )
                if auto_confirmed or holdings_qty_changed(prev_qty, rh_live):
                    force = True
                    store.set(CACHE_KEY, None)
    except Exception:
        log.exception("robinhood live refresh failed")

    cache_ttl = LIVE_CACHE_TTL if rh_live else CACHE_TTL
    if not force:
        cached = store.get(CACHE_KEY)
        if cached and time.time() - cached.get("cached_at", 0) < cache_ttl:
            data = _ensure_order_split(cached["data"])
            if rh_live:
                data["robinhood_live"] = rh_live
                if data.get("summary"):
                    data["summary"] = merge_live_into_summary(data["summary"], rh_live)
            from .robinhood_config import get_execution_mode, is_configured
            data["execution_mode"] = get_execution_mode()
            data["robinhood_configured"] = is_configured()
            return data
    try:
        frames = fetch_bars()
        if not frames:
            raise RuntimeError("no crypto bars returned")
        book = store.get(BOOK_KEY) or _new_book()
        orders, _, view = generate_orders(frames, book)
        # Drop tips that were just (auto)confirmed so they can't bounce back.
        recent = _recently_confirmed_actions(store.get(PENDING_KEY) or [])
        if recent:
            orders = [o for o in orders if _action_key(o) not in recent]
        orders = _merge_pending(store.get(PENDING_KEY) or [], orders)
        orders = _collapse_actionable(orders)
        if rh_live:
            bp = float(rh_live.get("buying_power") or 0)
            max_buy = max(0.0, round(bp * 0.98, 0))
            for o in orders:
                if o.get("side") != "buy" or o.get("status") in _TERMINAL:
                    continue
                if max_buy < MIN_UNIT:
                    continue
                o["dollars"] = min(float(o.get("dollars") or 0), max_buy)
        store.set(PENDING_KEY, orders)
    except Exception as exc:
        log.exception("crypto advice failed")
        return {"ok": False, "error": f"크립토 분석 실패: {exc}"}
    if rh_live and view.get("summary"):
        view["summary"] = merge_live_into_summary(view["summary"], rh_live)
    data = _panel(orders, view)
    data = _ensure_order_split(data)
    if rh_live:
        data["robinhood_live"] = rh_live
    if auto_confirmed:
        data["auto_confirmed"] = [
            {"id": o.get("id"), "side": o.get("side"), "symbol": o.get("symbol"),
             "actual_dollars": o.get("actual_dollars")}
            for o in auto_confirmed
        ]
    store.set(CACHE_KEY, {"cached_at": time.time(), "data": data})
    # Semi-auto: ping Telegram whenever actionable tips appear (deduped).
    from .robinhood_config import get_execution_mode
    if get_execution_mode() == "semi" and (data.get("orders") or []):
        notify_crypto_orders(data, "승인 요청", force=False)
    return data


def _execute_on_robinhood(order: dict, dollars: float) -> dict:
    """Place market order via Crypto API. Mutates order with fill metadata."""
    from .robinhood_orders import place_market_dollars

    cid = order.get("rh_client_order_id")
    sell_all = order.get("kind") in ("exit",) and order.get("side") == "sell"
    result = place_market_dollars(
        side=order["side"],
        pair=order.get("pair") or f"{order['symbol']}/USD",
        dollars=dollars,
        client_order_id=cid,
        fallback_price=float(order.get("price") or 0) or None,
        sell_all=sell_all,
    )
    if result.get("client_order_id"):
        order["rh_client_order_id"] = result["client_order_id"]
    if not result.get("ok"):
        return result
    order["rh_order_id"] = result.get("rh_order_id")
    order["rh_state"] = result.get("state")
    order["api_executed"] = True
    if result.get("price"):
        order["price"] = float(result["price"])
    return result


def confirm_order(order_id: str, actual_dollars: float | None = None) -> dict:
    """Confirm a tip. In semi/auto mode, places the order on Robinhood first."""
    from .robinhood_config import get_execution_mode, is_configured

    pending = store.get(PENDING_KEY) or []
    order = next((o for o in pending if o.get("id") == order_id), None)
    if order is None:
        return {"ok": False, "error": "해당 주문을 찾을 수 없습니다. 패널을 새로고침하세요."}
    if order.get("status") == "confirmed":
        cached = store.get(CACHE_KEY)
        raw = (cached or {}).get("data") or _panel(pending, {})
        return _ensure_order_split(raw)

    dollars = float(actual_dollars) if actual_dollars is not None else float(order["dollars"])
    mode = get_execution_mode()
    if mode in ("semi", "auto"):
        if not is_configured():
            return {"ok": False, "error": "API 실행 모드인데 Robinhood 키가 없습니다."}
        placed = _execute_on_robinhood(order, dollars)
        # Persist client_order_id even on failure so retries stay idempotent.
        store.set(PENDING_KEY, pending)
        if not placed.get("ok"):
            return {
                "ok": False,
                "error": placed.get("error") or "Robinhood 주문 실패",
                "execution_mode": mode,
            }
        dollars = float(placed.get("dollars") or dollars)

    book = store.get(BOOK_KEY) or _new_book()
    try:
        apply_order(book, order, dollars)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    book["updated_at"] = datetime.now(timezone.utc).isoformat()
    order["status"] = "confirmed"
    order["actual_dollars"] = round(dollars, 2)
    order["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    action = _action_key(order)
    pending = [
        o for o in pending
        if o.get("status") in _TERMINAL or _action_key(o) != action
    ]
    store.set(BOOK_KEY, book)
    store.set(PENDING_KEY, pending)
    store.set(CACHE_KEY, None)
    via = "API" if order.get("api_executed") else "수동"
    log_activity(
        "crypto",
        f"실행 확인({via}) {order['side']} {order['symbol']} "
        f"추천 ${order['dollars']:.0f} → 실제 ${dollars:.0f}",
    )
    data = advise_and_apply(force=True)
    return _ensure_order_split(data)


def execute_pending_auto(*, limit: int = 4) -> list[dict]:
    """Place up to `limit` pending tips when execution_mode == auto."""
    from .robinhood_config import get_execution_mode

    if get_execution_mode() != "auto":
        return []
    pending = [
        o for o in (store.get(PENDING_KEY) or [])
        if o.get("status") not in _TERMINAL
    ]
    done: list[dict] = []
    for order in pending[:limit]:
        result = confirm_order(order["id"], float(order.get("dollars") or 0))
        done.append({
            "id": order.get("id"),
            "symbol": order.get("symbol"),
            "side": order.get("side"),
            "ok": bool(result.get("ok")),
            "error": result.get("error"),
            "dollars": result.get("summary") and None,
        })
        if result.get("ok"):
            # Pull filled dollars from history tip if present
            hist = (result.get("order_history") or []) + (result.get("orders") or [])
            match = next((h for h in hist if h.get("id") == order["id"]), None)
            if match and match.get("actual_dollars") is not None:
                done[-1]["dollars"] = match["actual_dollars"]
            else:
                done[-1]["dollars"] = float(order.get("dollars") or 0)
        else:
            break  # stop on first failure so we don't cascade
    return done


def deny_order(order_id: str) -> dict:
    """Dismiss a pending recommendation without updating the book."""
    pending = store.get(PENDING_KEY) or []
    order = next((o for o in pending if o.get("id") == order_id), None)
    if order is None:
        return {"ok": False, "error": "해당 주문을 찾을 수 없습니다. 패널을 새로고침하세요."}
    if order.get("status") in _TERMINAL:
        cached = store.get(CACHE_KEY)
        raw = (cached or {}).get("data") or _panel(pending, {})
        return _ensure_order_split(raw)
    order["status"] = "denied"
    order["denied_at"] = datetime.now(timezone.utc).isoformat()
    action = _action_key(order)
    pending = [
        o for o in pending
        if o.get("status") in _TERMINAL or _action_key(o) != action
    ]
    store.set(PENDING_KEY, pending)
    store.set(CACHE_KEY, None)
    log_activity(
        "crypto",
        f"추천 거부 {order['side']} {order['symbol']} "
        f"${order['dollars']:.0f} — {order.get('reason', '')}",
    )
    data = advise_and_apply(force=True)
    return _ensure_order_split(data)


def reset_book() -> None:
    store.set(BOOK_KEY, _new_book())
    store.set(PENDING_KEY, [])
    store.set(CACHE_KEY, None)
    store.set(NOTIFY_FP_KEY, None)


def set_principal(principal: float) -> dict:
    """Update the recovery target without touching positions or orders."""
    if principal <= 0:
        return {"ok": False, "error": "원금은 0보다 커야 합니다."}
    book = store.get(BOOK_KEY) or _new_book()
    book["principal"] = round(float(principal), 2)
    book["updated_at"] = datetime.now(timezone.utc).isoformat()
    store.set(BOOK_KEY, book)
    store.set(CACHE_KEY, None)
    log_activity("crypto", f"원금 목표 ${principal:,.0f}로 설정")
    return _ensure_order_split(advise_and_apply(force=True))


def set_stocks_value(stocks_value: float) -> dict:
    """Persist Robinhood equity (stocks/ETF) value so Investing totals match.

    Crypto API has no equities endpoint — this bridges the gap so
    crypto + stocks + buying power equals the Robinhood Investing total.
    """
    if stocks_value < 0:
        return {"ok": False, "error": "주식 평가액은 0 이상이어야 합니다."}
    book = store.get(BOOK_KEY) or _new_book()
    book["stocks_value"] = round(float(stocks_value), 2)
    book["updated_at"] = datetime.now(timezone.utc).isoformat()
    store.set(BOOK_KEY, book)
    store.set(CACHE_KEY, None)
    log_activity("crypto", f"주식·ETF 평가액 ${stocks_value:,.2f}로 설정")
    return _ensure_order_split(advise_and_apply(force=True))


def set_investing_total(investing_total: float) -> dict:
    """Infer stocks value from the Robinhood Investing account total.

    stocks = investing_total − crypto_holdings − buying_power
    """
    if investing_total <= 0:
        return {"ok": False, "error": "앱 총액은 0보다 커야 합니다."}
    from .robinhood_live import fetch_robinhood_snapshot

    snap = None
    try:
        snap = fetch_robinhood_snapshot()
    except Exception:
        log.exception("investing total: live snapshot failed")
    book = store.get(BOOK_KEY) or _new_book()
    if snap:
        crypto_holdings = float(snap.get("holdings_value") or 0)
        cash = float(snap.get("buying_power") or 0)
    else:
        cash = float(book.get("cash") or 0)
        crypto_holdings = sum(
            sum(float(u.get("dollars") or 0) for u in (pos.get("units") or []))
            for pos in (book.get("positions") or {}).values()
        )
    stocks = round(max(0.0, float(investing_total) - crypto_holdings - cash), 2)
    book["stocks_value"] = stocks
    book["updated_at"] = datetime.now(timezone.utc).isoformat()
    store.set(BOOK_KEY, book)
    store.set(CACHE_KEY, None)
    log_activity(
        "crypto",
        f"Investing 총액 ${investing_total:,.2f} 동기화 → 주식 ${stocks:,.2f}",
    )
    return _ensure_order_split(advise_and_apply(force=True))


def import_holdings(
    cash: float, holdings: list[dict], principal: float | None = None,
    *, notify_as: str | None = "스크린샷 분석",
    brokerage_cash: float | None = None,
    stock_positions: list[dict] | None = None,
    rh_investing_total: float | None = None,
) -> dict:
    """Rebuild the book from the user's real Robinhood holdings.

    Cost basis inside the book is marked to market at import (so summary P/L
    measures improvement *since import*); the original avg cost is kept per
    position for the truthful total-return display. `principal` is the
    recovery target (original capital); if omitted it is inferred from
    qty × avg_cost + cash.

    `brokerage_cash` is Investing Cash (may exceed crypto buying_power).
    `stock_positions` are equities shown on the Investing screen.
    """
    prev = store.get(BOOK_KEY) or {}
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
    if brokerage_cash is not None and float(brokerage_cash) >= 0:
        book["brokerage_cash"] = round(float(brokerage_cash), 2)
        book["stocks_value"] = 0.0  # clear legacy lump
    elif prev.get("brokerage_cash") is not None:
        book["brokerage_cash"] = prev["brokerage_cash"]
    if stock_positions is not None:
        cleaned = []
        for s in stock_positions:
            sym = str(s.get("symbol") or "").upper().strip()
            qty = float(s.get("qty") or 0)
            if sym and qty > 0:
                row = {"symbol": sym, "qty": qty}
                if s.get("price") not in (None, ""):
                    try:
                        row["price"] = float(s["price"])
                    except (TypeError, ValueError):
                        pass
                cleaned.append(row)
        book["stock_positions"] = cleaned
        book["stocks_value"] = 0.0
    elif prev.get("stock_positions"):
        book["stock_positions"] = prev["stock_positions"]
    if rh_investing_total is not None and rh_investing_total > 0:
        book["rh_investing_total"] = round(float(rh_investing_total), 2)
    elif prev.get("rh_investing_total"):
        book["rh_investing_total"] = prev["rh_investing_total"]
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
    if data.get("ok") and notify_as:
        notify_crypto_orders(data, notify_as, force=True)
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


def run_scheduled(slot: str = "check") -> bool:
    """Frequent awake-hours check. Telegram only when tips need approval."""
    data = advise_and_apply(force=True)
    if not data.get("ok"):
        log_activity("crypto", f"크립토 어드바이저 실패: {data.get('error')}")
        return False

    auto_results = execute_pending_auto()
    if auto_results:
        ok_n = sum(1 for r in auto_results if r.get("ok"))
        log_activity("crypto", f"자동 실행 — 성공 {ok_n}/{len(auto_results)}")
        data = advise_and_apply(force=True)

    n = len(data.get("orders") or [])
    # Only notify when there is something to approve/execute (deduped).
    if n:
        if not notify_crypto_orders(data, "승인 요청", force=False):
            log_activity("crypto", f"크립토 어드바이저({slot}) — 텔레그램 발송 실패")
            return False

    s = data.get("summary") or {}
    gap = s.get("gap") or 0
    principal = s.get("principal") or s.get("budget") or 0
    status = (
        f"현재 ${s.get('total', 0):,.0f} / 원금 ${principal:,.0f} "
        f"(남음 ${gap:,.0f})"
    )
    log_activity("crypto", f"크립토 어드바이저({slot}) — 주문 {n}건, {status}")
    return True
