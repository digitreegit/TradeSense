"""v5 crypto rule — pure logic, no broker calls.

Watch every coin Robinhood lets the API buy. When a coin trades `dip`
below its rolling 24-hour high, buy a fixed dollar amount; park a GTC sell
`dip` above the fill; when that fills, the coin is free to trigger again.
One open lot per coin keeps a long slide from soaking up all the cash.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

DEFAULT_DIP = 0.05
MIN_DIP = 0.01
MAX_DIP = 0.30
DEFAULT_ORDER_DOLLARS = 1000.0
MIN_ORDER_DOLLARS = 5.0
LOOKBACK_HOURS = 24
# Leftover fractions from old ladders (a few cents) can't be sold via the
# API (Robinhood: qty >= 0.000001, ~$1 notional). Ignore them.
DUST_DOLLARS = 1.0
MIN_QTY = 0.000001
# Keep a little more than the lookback so the window is always full.
MAX_SAMPLE_AGE_HOURS = 26

# Pegged assets never move 5%; a 5% "dip" there is a broken peg, not a buy.
STABLECOINS = frozenset({
    "USDC", "USDT", "DAI", "PYUSD", "USDP", "TUSD", "BUSD", "FDUSD",
    "RLUSD", "USD1", "GUSD", "EURC", "USDS", "USDE",
})


def clamp_dip(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return DEFAULT_DIP
    return max(MIN_DIP, min(MAX_DIP, v))


def clamp_order(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return DEFAULT_ORDER_DOLLARS
    return max(MIN_ORDER_DOLLARS, round(v, 2))


def is_dust(qty: float, price: float | None) -> bool:
    q = float(qty or 0)
    if q <= 0 or q < MIN_QTY:
        return True
    return bool(price) and q * float(price) < DUST_DOLLARS


def is_stable(pair: str) -> bool:
    return str(pair).split("/")[0].upper() in STABLECOINS


def _ts(iso: str) -> datetime:
    d = datetime.fromisoformat(iso)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def append_samples(history: dict, prices: dict[str, float],
                   now: datetime | None = None) -> dict:
    """history: {pair: [[iso, price], ...]} oldest→newest, trimmed to the window."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MAX_SAMPLE_AGE_HOURS)
    out: dict[str, list] = {}
    for sym in set(history) | set(prices):
        rows = [r for r in (history.get(sym) or []) if _ts(r[0]) >= cutoff]
        px = prices.get(sym)
        if px and px > 0:
            rows.append([now.isoformat(), float(px)])
        if rows:
            out[sym] = rows
    return out


def high_24h(samples: list, now: datetime | None = None) -> float | None:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    vals = [float(r[1]) for r in (samples or []) if _ts(r[0]) >= cutoff and float(r[1]) > 0]
    return max(vals) if vals else None


def window_hours(samples: list, now: datetime | None = None) -> float:
    """How much of the 24h window is actually covered by samples."""
    if not samples:
        return 0.0
    now = now or datetime.now(timezone.utc)
    oldest = min(_ts(r[0]) for r in samples)
    return min(float(LOOKBACK_HOURS), (now - oldest).total_seconds() / 3600.0)


def change_from_high(price: float, high: float | None) -> float | None:
    if not high or high <= 0 or not price or price <= 0:
        return None
    return price / high - 1.0


def trigger_price(high: float | None, dip: float) -> float | None:
    return high * (1.0 - dip) if high else None


def should_buy(price: float, high: float | None, dip: float) -> bool:
    t = trigger_price(high, dip)
    return bool(t) and price > 0 and price <= t


def sell_target(buy_price: float, dip: float) -> float:
    return float(buy_price) * (1.0 + dip)


def new_lot(symbol: str, *, qty: float, price: float, dollars: float,
            at: datetime | None = None, source: str = "dip") -> dict:
    at = at or datetime.now(timezone.utc)
    return {
        "symbol": symbol,
        "qty": float(qty),
        "price": float(price),
        "dollars": round(float(dollars), 2),
        "at": at.isoformat(),
        "source": source,       # dip | adopted
        "sell_order": None,     # {id, api_version, limit_price, qty}
        "last_error": None,
    }


def lot_pl(lot: dict, sell_price: float, sell_qty: float | None = None) -> float:
    qty = float(sell_qty if sell_qty is not None else lot["qty"])
    frac = qty / float(lot["qty"]) if float(lot["qty"]) > 0 else 1.0
    return round(qty * float(sell_price) - float(lot["dollars"]) * frac, 4)


def watch_rows(history: dict, prices: dict[str, float], lots: dict,
               dip: float, now: datetime | None = None) -> list[dict]:
    """Dashboard rows for every watched coin, most-fallen first."""
    now = now or datetime.now(timezone.utc)
    rows = []
    for sym, px in prices.items():
        samples = history.get(sym) or []
        hi = high_24h(samples, now)
        chg = change_from_high(px, hi)
        lot = lots.get(sym)
        rows.append({
            "symbol": sym,
            "price": float(px),
            "high_24h": hi,
            "change": chg,
            "trigger_at": trigger_price(hi, dip),
            "hours": round(window_hours(samples, now), 1),
            "held": bool(lot),
            "armed": (not lot) and should_buy(px, hi, dip),
        })
    rows.sort(key=lambda r: (r["change"] if r["change"] is not None else 1.0))
    return rows


def lot_rows(lots: dict, prices: dict[str, float], dip: float) -> list[dict]:
    out = []
    for sym, lot in lots.items():
        px = prices.get(sym) or lot.get("last_price")
        qty = float(lot["qty"])
        value = qty * px if px else None
        so = lot.get("sell_order") or {}
        out.append({
            "symbol": sym,
            "qty": qty,
            "price": float(lot["price"]),
            "dollars": float(lot["dollars"]),
            "current": px,
            "target": sell_target(lot["price"], dip),
            "value": round(value, 2) if value is not None else None,
            "unrealized_pl": round(value - float(lot["dollars"]), 2) if value is not None else None,
            "at": lot.get("at"),
            "source": lot.get("source"),
            "resting": bool(so.get("id")),
            "resting_at": so.get("limit_price"),
            "last_error": lot.get("last_error"),
        })
    out.sort(key=lambda r: r["at"] or "", reverse=True)
    return out
