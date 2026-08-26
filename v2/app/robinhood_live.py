"""Live Robinhood balances and prices for the crypto dashboard."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .crypto_advisor import BOOK_KEY, CANDIDATES, _step_for, fetch_bars, _coin_metrics
from .robinhood_client import RobinhoodCryptoClient
from .robinhood_config import get_credentials, is_configured
from .state import store

log = logging.getLogger(__name__)

_SYM_TO_PAIR = {p.split("/")[0]: p for p in CANDIDATES}
_SNAPSHOT_TTL = timedelta(hours=24)


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
    quote_times: list[datetime] = []
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
                    raw_ts = row.get("timestamp") or row.get("updated_at")
                    try:
                        ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                        quote_times.append(ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))
                    except (TypeError, ValueError):
                        quote_times.append(datetime.now(timezone.utc))
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
        live_quoted = price > 0
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
                "live_quoted": False,
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
            "live_quoted": live_quoted,
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

    book = store.get(BOOK_KEY) or {}
    buying_power = cash
    _, stocks_value, _, stock_rows, source_meta = _cash_and_stocks_from_book(
        book, buying_power, holdings_value,
    )
    # Crypto Trading API only returns holdings + buying_power. Hero total is
    # that live sum — never mix screenshot cash/stocks into it.
    crypto_total = holdings_value + buying_power
    account_total = crypto_total
    base = max(holdings_value, 1e-9)
    day_change_pct = (day_change / base) if base > 0 else 0.0

    return {
        "buying_power": round(buying_power, 2),
        "cash": round(buying_power, 2),
        "cash_label": "Buying power",
        "holdings_value": round(holdings_value, 2),
        "crypto_total": round(crypto_total, 2),
        "stocks_value": round(stocks_value, 2),
        "stock_positions": stock_rows,
        "total": round(account_total, 2),
        "cash_incomplete": False,
        **source_meta,
        "day_change": day_change,
        "day_change_pct": day_change_pct,
        "positions": positions,
        "unpriced": unpriced,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "quote_at": min(quote_times).isoformat() if quote_times else None,
    }


def _stock_last_price(symbol: str) -> float | None:
    try:
        from .alpaca_config import get_credentials
        api_key, secret_key = get_credentials()
        if not api_key or not secret_key:
            return None
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest
        client = StockHistoricalDataClient(api_key, secret_key)
        trade = client.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol))
        row = trade.get(symbol) if isinstance(trade, dict) else None
        if row is None and hasattr(trade, "get"):
            row = trade.get(symbol)
        px = getattr(row, "price", None) if row is not None else None
        return float(px) if px else None
    except Exception as exc:
        log.debug("stock quote %s failed: %s", symbol, exc)
        return None


def _cash_and_stocks_from_book(
    book: dict, buying_power: float, holdings_value: float = 0.0,
) -> tuple[float, float, str, list[dict], dict]:
    """Resolve brokerage Cash + stocks for Investing-matching totals.

    Crypto API only exposes buying_power. Robinhood's Investing total also
    includes cash that is not currently tradeable (unsettled / reserved). When
    we have rh_investing_total from a screenshot, infer the full cash bucket as
    total − live crypto − live stocks.
    """
    stock_positions = book.get("stock_positions") or []
    stock_rows: list[dict] = []
    stocks_value = 0.0
    for raw in stock_positions:
        sym = str(raw.get("symbol") or "").upper().strip()
        try:
            qty = float(raw.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if not sym or qty <= 0:
            continue
        px = raw.get("price")
        try:
            price = float(px) if px not in (None, "") else 0.0
        except (TypeError, ValueError):
            price = 0.0
        # Quantity comes from the screenshot; value should use the latest quote.
        price = _stock_last_price(sym) or price
        value = qty * price if price > 0 else float(raw.get("value") or 0)
        stocks_value += value
        stock_rows.append({
            "symbol": sym, "qty": qty, "price": price, "value": round(value, 2),
        })

    if not stock_rows:
        try:
            legacy_stocks = float(book.get("stocks_value") or 0)
        except (TypeError, ValueError):
            legacy_stocks = 0.0
        if legacy_stocks > 0:
            stocks_value = legacy_stocks

    captured_at = book.get("investing_snapshot_at")
    captured = None
    try:
        captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    snapshot_fresh = bool(
        captured and datetime.now(timezone.utc) - captured <= _SNAPSHOT_TTL
    )
    cash_source = "api_buying_power"
    display_cash = buying_power
    brokerage_cash = book.get("brokerage_cash")
    if brokerage_cash is not None and snapshot_fresh:
        try:
            bc = float(brokerage_cash)
            if bc > buying_power + 0.01:
                display_cash = bc
                cash_source = "screenshot"
        except (TypeError, ValueError):
            pass
    return display_cash, stocks_value, "Cash", stock_rows, {
        "cash_source": cash_source,
        "investing_snapshot_at": captured_at,
        "cash_stale": bool(
            (brokerage_cash is not None or book.get("rh_investing_total") is not None)
            and not snapshot_fresh
        ),
        "stocks_stale": bool((stock_positions or book.get("stocks_value")) and not snapshot_fresh),
        "total_stale": bool(book.get("rh_investing_total") is not None and not snapshot_fresh),
        "total_pinned": False,
        "balance_basis": "live_crypto_api",
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
        live_quoted = bool(row.get("live_quoted"))
        if qty <= 0:
            continue
        seen.add(pair)
        m = metrics.get(pair)
        fallback_px = float(m["price"]) if m else (price or 1.0)
        mark = price if price > 0 else fallback_px
        if pair in book.get("positions", {}):
            pos = book["positions"][pair]
            pos["units"] = [{"dollars": qty * mark, "price": mark, "qty": qty}]
            if live_quoted:
                pos["peak_price"] = max(float(pos.get("peak_price") or mark), mark)
        else:
            book.setdefault("positions", {})[pair] = {
                "units": [{"dollars": qty * mark, "price": mark, "qty": qty}],
                "anchor": mark,
                "step": _step_for(m["range30"]) if m else 0.06,
                "peak_price": mark,
                "initial_risk_qty": qty,
                "profit_tiers_taken": [],
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
    brokerage_cash = book.get("brokerage_cash")
    stock_positions = book.get("stock_positions")
    rh_investing_total = book.get("rh_investing_total")
    investing_snapshot_at = book.get("investing_snapshot_at")
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
    if brokerage_cash is not None:
        try:
            book["brokerage_cash"] = max(0.0, float(brokerage_cash))
        except (TypeError, ValueError):
            pass
    if stock_positions is not None:
        book["stock_positions"] = stock_positions
    if rh_investing_total is not None:
        try:
            book["rh_investing_total"] = float(rh_investing_total)
        except (TypeError, ValueError):
            pass
    if investing_snapshot_at:
        book["investing_snapshot_at"] = investing_snapshot_at
    for pair, pos in book.get("positions", {}).items():
        if avg_by_pair.get(pair):
            pos["avg_cost"] = float(avg_by_pair[pair])
        if anchor_step.get(pair):
            anc, step = anchor_step[pair]
            if anc:
                pos["anchor"] = anc
            if step:
                pos["step"] = step
    live_prices = {
        row["pair"]: float(row["price"])
        for row in (snap.get("positions") or [])
        if row.get("pair") and float(row.get("price") or 0) > 0
        and row.get("symbol") in _SYM_TO_PAIR and row.get("live_quoted")
    }
    if live_prices and snap.get("quote_at"):
        from .crypto_risk import update_tracking
        update_tracking(book, live_prices, quote_at=snap["quote_at"])
    store.set(BOOK_KEY, book)
    return snap, live_prices, prev_qty


def merge_live_into_summary(summary: dict, snap: dict) -> dict:
    """Align displayed totals with Robinhood app balance."""
    if not snap:
        return summary
    by_sym = {p["symbol"]: p for p in snap.get("positions") or []}
    principal = float(summary.get("principal") or summary.get("budget") or 0)
    total = float(snap.get("crypto_total") or snap.get("total") or 0)
    summary = {**summary}
    summary["cash"] = float(snap.get("buying_power") or snap.get("cash") or 0)
    summary["total"] = total
    summary["crypto_total"] = total
    summary["stocks_value"] = float(snap.get("stocks_value") or 0)
    summary["holdings_value"] = float(snap.get("holdings_value") or 0)
    summary["buying_power"] = float(snap.get("buying_power") or 0)
    summary["cash_label"] = snap.get("cash_label") or "Buying power"
    for key in (
        "cash_source", "investing_snapshot_at", "cash_stale", "stocks_stale",
        "total_stale", "total_pinned", "balance_basis",
    ):
        summary[key] = snap.get(key)
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
