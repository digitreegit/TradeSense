"""Persistent, live-quote risk controls for Robinhood crypto positions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Stop widths scale with each coin's own 30-day daily range (range30 =
# mean((high-low)/close)). A fixed 7% trail on a coin that moves 6% a day is
# a coin flip, so *_PCT is the floor and *_RANGE_MULT stretches it. Set the
# mult to 0 for the legacy fixed-width behaviour (scripts/replay_crypto_live.py
# compares both).
HARD_STOP_PCT = 0.08            # floor
HARD_STOP_RANGE_MULT = 3.0      # BTC (range ~3%) -> ~10%, SOL/alts -> 15% cap
HARD_STOP_MAX = 0.15
TRAILING_STOP_PCT = 0.07        # floor
TRAILING_RANGE_MULT = 4.0       # BTC -> ~13%, SOL/alts -> 20% cap
TRAILING_STOP_MAX = 0.20
# "close": trail from the highest *completed daily close* since entry, so an
# intraday spike does not ratchet the stop up under the price.
# "tick": legacy — trail from the highest live quote seen.
TRAILING_BASE = "close"
# Staged partial profit-taking. Empty = let winners run to the trend exit;
# the replay showed +10/20/30% trims capped the winners that paid for the
# -8% full-size stop-outs.
PROFIT_TIERS: tuple[float, ...] = ()
PROFIT_SELL_FRACTION = 0.25
CRASH_30M_PCT = 0.05
DAILY_BUY_HALT_PCT = 0.05
QUOTE_MAX_AGE_SECONDS = 120

FULL_EXIT_KINDS = frozenset({"hard_stop", "trailing_stop", "crash_exit", "exit"})


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def stop_widths(range30: float | None) -> dict[str, float]:
    """Per-coin hard/trailing stop widths from its 30-day daily range."""
    r = float(range30 or 0)
    hard = HARD_STOP_PCT if HARD_STOP_RANGE_MULT <= 0 or r <= 0 else _clamp(
        HARD_STOP_RANGE_MULT * r, HARD_STOP_PCT, HARD_STOP_MAX)
    trail = TRAILING_STOP_PCT if TRAILING_RANGE_MULT <= 0 or r <= 0 else _clamp(
        TRAILING_RANGE_MULT * r, TRAILING_STOP_PCT, TRAILING_STOP_MAX)
    return {"hard_pct": round(hard, 4), "trail_pct": round(trail, 4)}


def hard_pct_for(pos: dict) -> float:
    try:
        v = float(pos.get("hard_pct") or 0)
    except (TypeError, ValueError):
        v = 0.0
    return v if v > 0 else HARD_STOP_PCT


def trail_pct_for(pos: dict) -> float:
    try:
        v = float(pos.get("trail_pct") or 0)
    except (TypeError, ValueError):
        v = 0.0
    return v if v > 0 else TRAILING_STOP_PCT


def trailing_peak(pos: dict, price: float) -> float:
    """Reference high for the trailing stop under the configured base."""
    if TRAILING_BASE == "close":
        base = float(pos.get("peak_close") or 0)
        if base > 0:
            return base
    return max(float(pos.get("peak_price") or price), price)


def sync_daily_risk(pos: dict, *, range30: float | None, last_close: float | None) -> None:
    """Refresh per-position daily fields from completed bars.

    Called on every advisor run with the newest *completed* daily bar, so
    `peak_close` ratchets once per day and stop widths follow the coin's
    current volatility. Safe on legacy positions that lack the fields.
    """
    widths = stop_widths(range30)
    pos["hard_pct"] = widths["hard_pct"]
    pos["trail_pct"] = widths["trail_pct"]
    close = float(last_close or 0)
    prev = float(pos.get("peak_close") or 0)
    if prev <= 0:
        # Seed from cost so a position bought above today's close is not
        # instantly "under" a trail measured from a lower close.
        avg = float(pos.get("avg_cost") or 0)
        units = pos.get("units") or []
        entry = avg if avg > 0 else max(
            (float(u.get("price") or 0) for u in units), default=0.0)
        prev = entry
    if close > 0:
        prev = max(prev, close)
    if prev > 0:
        pos["peak_close"] = prev


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
    hard = hard_pct_for(pos)
    trail = trail_pct_for(pos)
    peak = trailing_peak(pos, price)

    if avg > 0 and price <= avg * (1 - hard):
        return {
            "kind": "hard_stop", "dollars": value, "sell_all": True,
            "reason": f"평단 손절 {price / avg - 1:.1%} (기준 -{hard:.0%})",
        }
    if peak > 0 and price <= peak * (1 - trail):
        base = "종가 고점" if TRAILING_BASE == "close" else "고점"
        return {
            "kind": "trailing_stop", "dollars": value, "sell_all": True,
            "reason": f"{base} 추적 손절 {price / peak - 1:.1%} (기준 -{trail:.0%})",
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
    peak = trailing_peak(pos, 0.0) if pos.get("peak_price") or pos.get("peak_close") else 0.0
    taken = {round(float(tier), 4) for tier in pos.get("profit_tiers_taken") or []}
    next_tier = next((tier for tier in PROFIT_TIERS if round(tier, 4) not in taken), None)
    return {
        "hard_stop": avg * (1 - hard_pct_for(pos)) if avg > 0 else None,
        "trailing_stop": peak * (1 - trail_pct_for(pos)) if peak > 0 else None,
        "hard_pct": hard_pct_for(pos),
        "trail_pct": trail_pct_for(pos),
        "peak_price": peak or None,
        "next_profit": avg * (1 + next_tier) if avg > 0 and next_tier is not None else None,
    }
