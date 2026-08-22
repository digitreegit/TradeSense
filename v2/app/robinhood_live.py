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


def _mid_from_quote(row: dict) -> float | None:
    """Best available mark from a best_bid_ask result row."""
    raw = row.get("price")
    if raw is not None:
        try:
            px = float(raw)
            if px > 0:
                return px
        except (TypeError, ValueError):
            pass
    bid = row.get("bid_inclusive_of_sell_spread")
    ask = row.get("ask_inclusive_of_buy_spread")
    try:
        if bid is not None and ask is not None:
            b, a = float(bid), float(ask)
            if b > 0 and a > 0:
                return (b + a) / 2.0
        if bid is not None:
            b = float(bid)
            if b > 0:
                return b
        if ask is not None:
            a = float(ask)
            if a > 0:
                return a
    except (TypeError, ValueError):
        pass
    return None


def fetch_robinhood_snapshot() -> dict | None:
    """Account cash + *all* holdings valued at Robinhood live mid prices.

    Advice candidates stay limited to CANDIDATES, but portfolio totals must
    include every crypto holding Robinhood returns — otherwise the dashboard
    understates the app by thousands when the user holds coins outside the list.
    """
    api_key, private_key = get_credentials()
    if not api_key or not private_key:
        return None
    client = RobinhoodCryptoClient(api_key, private_key)
    account = client.get_account()
    # Crypto API exposes buying_power only (no separate cash field).
    cash = float(account.get("buying_power") or 0)
    holdings = client.get_all_holdings()

    qty_by_sym: dict[str, float] = {}
    for row in holdings:
        sym = str(row.get("asset_code") or "").upper().strip()
        qty = float(row.get("total_quantity") or 0)
        if sym and qty > 0:
            qty_by_sym[sym] = qty_by_sym.get(sym, 0.0) + qty

    prices: dict[str, float] = {}
    if qty_by_sym:
        rh_symbols = tuple(f"{sym}-USD" for sym in qty_by_sym)
        try:
            quotes = client.get_best_bid_ask(*rh_symbols)
            for row in quotes.get("results") or []:
                symbol = str(row.get("symbol") or "")
                sym = symbol.replace("-USD", "").upper()
                px = _mid_from_quote(row)
                if px is not None:
                    prices[sym] = px
        except Exception as exc:
            log.warning("robinhood quotes failed: %s", exc)

    positions: list[dict] = []
    unpriced: list[dict] = []
    holdings_value = 0.0
    frames: dict = {}
    try:
        frames = fetch_bars()
    except Exception:
        pass

    for sym, qty in qty_by_sym.items():
        pair = _SYM_TO_PAIR.get(sym)  # None if outside advice universe
        supported = pair is not None
        price = prices.get(sym, 0.0)
        if price <= 0 and pair:
            df = frames.get(pair)
            if df is not None and len(df):
                price = float(df["close"].iloc[-1])
        if price <= 0:
            unpriced.append({"symbol": sym, "qty": qty, "supported": supported})
            # Still list the holding so the UI matches the app; value stays 0.
            positions.append({
                "symbol": sym,
                "pair": pair or f"{sym}/USD",
                "qty": qty,
                "price": 0.0,
                "value": 0.0,
                "supported": supported,
                "priced": False,
            })
            continue
        value = qty * price
        holdings_value += value
        row: dict = {
            "symbol": sym,
            "pair": pair or f"{sym}/USD",
            "qty": qty,
            "price": price,
            "value": round(value, 2),
            "supported": supported,
            "priced": True,
        }
        if pair:
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
    crypto_total = cash + holdings_value
    # Stocks live outside the Crypto API — pulled from book when the user
    # syncs Investing total / stocks value so the hero matches the app.
    book = store.get(BOOK_KEY) or {}
    try:
        stocks_value = max(0.0, float(book.get("stocks_value") or 0))
    except (TypeError, ValueError):
        stocks_value = 0.0
    account_total = crypto_total + stocks_value
    base = crypto_total - day_change
    day_change_pct = (day_change / base) if base > 0 else 0.0

    return {
        "buying_power": round(cash, 2),
        "holdings_value": round(holdings_value, 2),
        "crypto_total": round(crypto_total, 2),
        "stocks_value": round(stocks_value, 2),
        # Hero total matches Robinhood Investing when stocks_value is set.
        "total": round(account_total, 2),
        "day_change": day_change,
        "day_change_pct": day_change_pct,
        "positions": positions,
        "unpriced": unpriced,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def apply_robinhood_live(book: dict, snap: dict) -> None:
    """Sync book qty/cash from Robinhood without clearing orders or avg cost.

    Only advice-universe (CANDIDATES) symbols are written into the book.
    Other holdings still count toward the displayed Robinhood total.
    """
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
        sym = str(row.get("symbol") or "").upper()
        if sym not in _SYM_TO_PAIR:
            continue
        pair = _SYM_TO_PAIR[sym]
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


def book_qty_by_pair(book: dict | None) -> dict[str, float]:
    """Current book quantities keyed by pair (e.g. XRP/USD)."""
    out: dict[str, float] = {}
    for pair, pos in ((book or {}).get("positions") or {}).items():
        qty = sum(float(u.get("qty") or 0) for u in (pos.get("units") or []))
        if qty > 0:
            out[pair] = qty
    return out


def refresh_from_robinhood_live() -> tuple[dict | None, dict[str, float], dict[str, float]]:
    """Pull Robinhood live snapshot into the book.

    Returns (snap, live prices by pair, previous qty by pair before sync).
    """
    if not is_configured():
        return None, {}, {}
    snap = fetch_robinhood_snapshot()
    if not snap:
        return None, {}, {}
    book = store.get(BOOK_KEY) or {}
    prev_qty = book_qty_by_pair(book)
    principal = book.get("principal")
    stocks_value = book.get("stocks_value")
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
    if stocks_value is not None:
        try:
            book["stocks_value"] = max(0.0, float(stocks_value))
        except (TypeError, ValueError):
            pass
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
        and row.get("symbol") in _SYM_TO_PAIR
    }
    return snap, live_prices, prev_qty


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
    summary["crypto_total"] = float(snap.get("crypto_total") or total)
    summary["stocks_value"] = float(snap.get("stocks_value") or 0)
    summary["holdings_value"] = float(snap.get("holdings_value") or 0)
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
    # Surface live-only holdings (e.g. coins outside the advice list) in summary.
    seen = {p["symbol"] for p in positions}
    for live in snap.get("positions") or []:
        if live["symbol"] in seen:
            continue
        positions.append({
            "symbol": live["symbol"],
            "qty": live.get("qty"),
            "price": live.get("price"),
            "value": live.get("value"),
            "invested": 0,
            "pl": live.get("value") or 0,
            "sparkline": live.get("sparkline"),
            "day_change": live.get("day_change"),
            "day_change_pct": live.get("day_change_pct"),
            "supported": live.get("supported", False),
        })
    summary["positions"] = positions
    return summary
