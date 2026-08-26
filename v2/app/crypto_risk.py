"""Persistent, live-quote risk controls for Robinhood crypto positions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

HARD_STOP_PCT = 0.08
TRAILING_STOP_PCT = 0.07
PROFIT_TIERS = (0.10, 0.20, 0.30)
PROFIT_SELL_FRACTION = 0.25
CRASH_30M_PCT = 0.05
DAILY_BUY_HALT_PCT = 0.05
QUOTE_MAX_AGE_SECONDS = 120

FULL_EXIT_KINDS = frozenset({"hard_stop", "trailing_stop", "crash_exit", "exit"})


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def quote_is_fresh(quote_at: str | None, now: datetime | None = None) -> bool:
    when = parse_ts(quote_at)
    if when is None:
        return False
    now = now or datetime.now(timezone.utc)
    age = (now - when).total_seconds()
    return 0 <= age <= QUOTE_MAX_AGE_SECONDS


def fresh_pairs(
    live_prices: dict[str, float],
    *,
    live_quote_fresh: bool = False,
    quote_at_by_pair: dict[str, str] | None = None,
    now: datetime | None = None,
) -> set[str]:
    """Per-symbol freshness. One stale coin must not disable the rest."""
    priced = {pair for pair, px in (live_prices or {}).items() if float(px or 0) > 0}
    if quote_at_by_pair:
        return {
            pair for pair in priced
            if quote_is_fresh((quote_at_by_pair or {}).get(pair), now)
        }
    return priced if live_quote_fresh else set()


def position_qty(pos: dict) -> float:
    return sum(float(unit.get("qty") or 0) for unit in pos.get("units") or [])


def update_tracking(
    book: dict,
    live_prices: dict[str, float],
    *,
    quote_at: str | None = None,
    quote_at_by_pair: dict[str, str] | None = None,
    now: datetime | None = None,
) -> None:
    """Ratchet peaks, retain 30-minute marks, and update the daily buy brake."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=30)
    history = book.setdefault("risk_quotes", {})
    positions = book.get("positions") or {}
    quote_at_by_pair = quote_at_by_pair or {}

    for pair, pos in positions.items():
        price = float(live_prices.get(pair) or 0)
        if price <= 0:
            continue
        ts = quote_at_by_pair.get(pair) or quote_at
        if not quote_is_fresh(ts, now):
            continue
        qty = position_qty(pos)
        pos["peak_price"] = max(float(pos.get("peak_price") or price), price)
        pos.setdefault("initial_risk_qty", qty)
        pos.setdefault("profit_tiers_taken", [])
        pos.setdefault("risk_started_at", now.isoformat())
        rows = history.setdefault(pair, [])
        rows.append({"ts": ts, "price": price})
        history[pair] = [
            row for row in rows
            if (parse_ts(row.get("ts")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
        ][-16:]

    for pair in list(history):
        if pair not in positions:
            del history[pair]

    total = float(book.get("cash") or 0) + sum(
        position_qty(pos) * float(live_prices.get(pair) or pos.get("peak_price") or 0)
        for pair, pos in positions.items()
    )
    day = now.date().isoformat()
    daily = book.get("risk_day") or {}
    if daily.get("date") != day or float(daily.get("start_total") or 0) <= 0:
        daily = {"date": day, "start_total": total}
    start = float(daily.get("start_total") or total)
    daily["current_total"] = total
    daily["change_pct"] = (total / start - 1) if start > 0 else 0.0
    daily["buy_halted"] = daily["change_pct"] <= -DAILY_BUY_HALT_PCT
    book["risk_day"] = daily


def rolling_drop(book: dict, pair: str, price: float) -> float:
    rows = (book.get("risk_quotes") or {}).get(pair) or []
    prior = [float(row.get("price") or 0) for row in rows[:-1]]
    baseline = max(prior) if prior else 0.0
    return price / baseline - 1 if baseline > 0 else 0.0


def evaluate_position(
    pair: str,
    pos: dict,
    price: float,
    *,
    recent_drop: float = 0.0,
) -> dict[str, Any] | None:
    """Return one highest-priority action: hard, trailing, crash, then profit."""
    qty = position_qty(pos)
    if qty <= 0 or price <= 0:
        return None
    value = qty * price
    avg = float(pos.get("avg_cost") or 0)
    peak = max(float(pos.get("peak_price") or price), price)

    if avg > 0 and price <= avg * (1 - HARD_STOP_PCT):
        return {
            "kind": "hard_stop", "dollars": value, "sell_all": True,
            "reason": f"평단 손절 {price / avg - 1:.1%} (기준 -{HARD_STOP_PCT:.0%})",
        }
    if peak > 0 and price <= peak * (1 - TRAILING_STOP_PCT):
        return {
            "kind": "trailing_stop", "dollars": value, "sell_all": True,
            "reason": f"고점 추적 손절 {price / peak - 1:.1%} (기준 -{TRAILING_STOP_PCT:.0%})",
        }
    if recent_drop <= -CRASH_30M_PCT:
        return {
            "kind": "crash_exit", "dollars": value, "sell_all": True,
            "reason": f"30분 급락 {recent_drop:.1%} — 전량 청산",
        }
    if avg > 0:
        gain = price / avg - 1
        taken = {round(float(tier), 4) for tier in pos.get("profit_tiers_taken") or []}
        for tier in PROFIT_TIERS:
            if gain >= tier and round(tier, 4) not in taken:
                initial_qty = float(pos.get("initial_risk_qty") or qty)
                sell_qty = min(qty, initial_qty * PROFIT_SELL_FRACTION)
                return {
                    "kind": "profit_stage",
                    "dollars": sell_qty * price,
                    "sell_all": False,
                    "profit_tier": tier,
                    "reason": f"단계 익절 +{tier:.0%} — 최초 수량 25%",
                }
    return None


def risk_levels(pos: dict) -> dict[str, float | None]:
    avg = float(pos.get("avg_cost") or 0)
    peak = float(pos.get("peak_price") or 0)
    taken = {round(float(tier), 4) for tier in pos.get("profit_tiers_taken") or []}
    next_tier = next((tier for tier in PROFIT_TIERS if round(tier, 4) not in taken), None)
    return {
        "hard_stop": avg * (1 - HARD_STOP_PCT) if avg > 0 else None,
        "trailing_stop": peak * (1 - TRAILING_STOP_PCT) if peak > 0 else None,
        "peak_price": peak or None,
        "next_profit": avg * (1 + next_tier) if avg > 0 and next_tier is not None else None,
    }
