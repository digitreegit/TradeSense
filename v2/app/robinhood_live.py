"""Live Robinhood balances and prices for the crypto dashboard."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .crypto_advisor import BOOK_KEY, CANDIDATES, _step_for, fetch_bars, _coin_metrics
from .robinhood_client import RobinhoodCryptoClient
from .robinhood_config import get_credentials, is_configured
from .state import store

log = logging.getLogger(__name__)

_SYM_TO_PAIR = {p.split("/")[0]: p for p in CANDIDATES}


def fetch_robinhood_snapshot() -> dict | None:
    """Account cash + holdings valued at Robinhood live mid prices."""
    api_key, private_key = get_credentials()
    if not api_key or not private_key:
        return None
    client = RobinhoodCryptoClient(api_key, private_key)
    account = client.get_account()
    cash = float(account.get("buying_power") or 0)
    holdings = client.get_all_holdings()

    qty_by_sym: dict[str, float] = {}
    for row in holdings:
        sym = str(row.get("asset_code") or "").upper().strip()
        qty = float(row.get("total_quantity") or 0)
        if sym and qty > 0:
            qty_by_sym[sym] = qty

    prices: dict[str, float] = {}
    if qty_by_sym:
        rh_symbols = tuple(f"{sym}-USD" for sym in qty_by_sym if sym in _SYM_TO_PAIR)
        if rh_symbols:
            try:
                quotes = client.get_best_bid_ask(*rh_symbols)
                for row in quotes.get("results") or []:
                    symbol = str(row.get("symbol") or "")
                    sym = symbol.replace("-USD", "").upper()
                    px = row.get("price")
                    if px is None and row.get("bid_inclusive_of_sell_spread") is not None:
                        px = row.get("bid_inclusive_of_sell_spread")
                    if px is not None:
                        prices[sym] = float(px)
            except Exception as exc:
                log.warning("robinhood quotes failed: %s", exc)

    positions: list[dict] = []
    holdings_value = 0.0
    frames: dict = {}
    try:
        frames = fetch_bars()
    except Exception:
        pass

    for sym, qty in qty_by_sym.items():
        if sym not in _SYM_TO_PAIR:
            continue
        pair = _SYM_TO_PAIR[sym]
        price = prices.get(sym, 0.0)
        if price <= 0:
            df = frames.get(pair)
            if df is not None and len(df):
                price = float(df["close"].iloc[-1])
        value = qty * price if price > 0 else 0.0
        holdings_value += value
        row: dict = {
            "symbol": sym,
            "pair": pair,
            "qty": qty,
            "price": price,
            "value": round(value, 2),
        }
        df = frames.get(pair)
        if df is not None and len(df) >= 2:
            closes = [float(c) for c in df["close"].tail(20).tolist()]
            row["sparkline"] = closes
            prev = float(df["close"].iloc[-2])
            if price > 0 and prev > 0:
                row["day_change"] = round((price - prev) * qty, 2)
                row["day_change_pct"] = price / prev - 1
        positions.append(row)

    positions.sort(key=lambda p: p.get("value") or 0, reverse=True)
    day_change = round(sum(float(p.get("day_change") or 0) for p in positions), 2)
    total = cash + holdings_value
    base = total - day_change
    day_change_pct = (day_change / base) if base > 0 else 0.0

    return {
        "buying_power": round(cash, 2),
        "holdings_value": round(holdings_value, 2),
        "total": round(cash + holdings_value, 2),
        "day_change": day_change,
        "day_change_pct": day_change_pct,
        "positions": positions,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def apply_robinhood_live(book: dict, snap: dict) -> None:
    """Sync book qty/cash from Robinhood without clearing orders or avg cost."""
    book["cash"] = float(snap.get("buying_power") or 0)
    seen: set[str] = set()
    metrics: dict = {}
    try:
        frames = fetch_bars()
        metrics = {
            s: m for s, m in
            ((sym, _coin_metrics(df)) for sym, df in frames.items()) if m
        }
    except Exception:
        pass

    for row in snap.get("positions") or []:
        pair = row.get("pair") or _SYM_TO_PAIR.get(row["symbol"])
        if not pair:
            continue
        qty = float(row["qty"] or 0)
        price = float(row.get("price") or 0)
        if qty <= 0:
            continue
        seen.add(pair)
        m = metrics.get(pair)
        fallback_px = float(m["price"]) if m else (price or 1.0)
        mark = price if price > 0 else fallback_px
        if pair in book.get("positions", {}):
            pos = book["positions"][pair]
            pos["units"] = [{"dollars": qty * mark, "price": mark, "qty": qty}]
        else:
            book.setdefault("positions", {})[pair] = {
                "units": [{"dollars": qty * mark, "price": mark, "qty": qty}],
                "anchor": mark,
                "step": _step_for(m["range30"]) if m else 0.06,
            }

    for pair in list(book.get("positions", {})):
        if pair not in seen:
            del book["positions"][pair]

    book["updated_at"] = snap.get("updated_at") or datetime.now(timezone.utc).isoformat()


def refresh_from_robinhood_live() -> tuple[dict | None, dict[str, float]]:
    """Pull Robinhood live snapshot into the book. Returns (snap, live prices by pair)."""
    if not is_configured():
        return None, {}
    snap = fetch_robinhood_snapshot()
    if not snap:
        return None, {}
    book = store.get(BOOK_KEY) or {}
    principal = book.get("principal")
    avg_by_pair = {
        pair: pos.get("avg_cost")
        for pair, pos in (book.get("positions") or {}).items()
        if pos.get("avg_cost")
    }
    anchor_step = {
        pair: (pos.get("anchor"), pos.get("step"))
        for pair, pos in (book.get("positions") or {}).items()
    }
    apply_robinhood_live(book, snap)
    if principal and float(principal) > 0:
        book["principal"] = float(principal)
    for pair, pos in book.get("positions", {}).items():
        if avg_by_pair.get(pair):
            pos["avg_cost"] = float(avg_by_pair[pair])
        if anchor_step.get(pair):
            anc, step = anchor_step[pair]
            if anc:
                pos["anchor"] = anc
            if step:
                pos["step"] = step
    store.set(BOOK_KEY, book)
    live_prices = {
        row["pair"]: float(row["price"])
        for row in (snap.get("positions") or [])
        if row.get("pair") and float(row.get("price") or 0) > 0
    }
    return snap, live_prices


def merge_live_into_summary(summary: dict, snap: dict) -> dict:
    """Align displayed totals with Robinhood app balance."""
    if not snap:
        return summary
    by_sym = {p["symbol"]: p for p in snap.get("positions") or []}
    principal = float(summary.get("principal") or summary.get("budget") or 0)
    total = float(snap.get("total") or 0)
    summary = {**summary}
    summary["cash"] = float(snap.get("buying_power") or 0)
    summary["total"] = total
    if principal > 0:
        summary["gap"] = max(0.0, principal - total)
        summary["recovered_pct"] = total / principal
    positions = []
    for row in summary.get("positions") or []:
        live = by_sym.get(row["symbol"])
        if not live:
            positions.append(row)
            continue
        invested = float(row.get("invested") or 0)
        value = float(live.get("value") or 0)
        price = float(live.get("price") or 0)
        qty = float(live.get("qty") or 0)
        avg_cost = row.get("avg_cost")
        positions.append({
            **row,
            "price": price,
            "value": value,
            "qty": qty,
            "pl": value - invested,
            "total_return": (price / avg_cost - 1) if avg_cost else row.get("total_return"),
            "sparkline": live.get("sparkline"),
            "day_change": live.get("day_change"),
            "day_change_pct": live.get("day_change_pct"),
        })
    summary["positions"] = positions
    return summary
