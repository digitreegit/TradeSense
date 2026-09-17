"""TradeSense v4 — one-rule grid.

Buy one unit every time price falls `step` below the last fill, sell one
unit every time it rises `step` above the last fill. Repeat forever. The
only user setting is `step`.

A *ladder* is the per-symbol state. It is a plain dict so it can be stored
as JSON and replayed in the offline simulator with the exact same code path
that the live engine uses (see scripts/grid_replay.py).

Ladder rules
- Capital per symbol is split into MAX_UNITS equal dollar units, sized once
  when the grid starts (`unit_dollars`).
- Seeding: a fresh ladder buys START_UNITS at market so it has inventory to
  sell into the first up-move.
- Holding units: anchor = last fill price. Sell the most recent unit when
  price >= anchor * (1 + step); buy one more (up to MAX_UNITS) when
  price <= anchor * (1 - step). Each fill re-anchors.
- Flat (all units sold): the reference is the last sale price (`hwm`); the
  first `step` drop below it buys one unit again. See FOLLOW_HIGH.
"""
from __future__ import annotations

from datetime import datetime, timezone

MAX_UNITS = 5
START_UNITS = 3
DEFAULT_STEP = 0.08  # replay: 8-10% beat 3-5% on both venues after costs
MIN_STEP = 0.01
MAX_STEP = 0.25
# Alpaca fractional orders need >= $1; Robinhood crypto also has a small
# minimum. Anything under this is rounding noise, not a rung.
MIN_ORDER_DOLLARS = 5.0
# Share of venue cash the grid may allocate at start; the rest absorbs fees
# and marketable-limit slippage so the last rung never fails on cash.
CASH_USE = 0.95

# While flat, the re-entry reference either follows the running high (True)
# or stays at the last sale price until the market comes back to it (False,
# the RuleFive original). Replays 2023-01 / 2024-09 / 2025-09 on both
# universes (scripts/grid_replay.py) favour the original: following the high
# re-enters near every top and rides the next leg down with a full ladder
# (crypto 5%: -10% vs +17%, maxDD -39% vs -14% from 2024-09).
FOLLOW_HIGH = False

CRYPTO_UNIVERSE: tuple[str, ...] = ("BTC/USD", "ETH/USD", "SOL/USD")
STOCK_UNIVERSE: tuple[str, ...] = ("AMD", "COIN", "MSTR", "SMCI", "PLTR", "TSLA")


def clamp_step(step: float) -> float:
    try:
        s = float(step)
    except (TypeError, ValueError):
        return DEFAULT_STEP
    if s != s:  # NaN
        return DEFAULT_STEP
    return max(MIN_STEP, min(MAX_STEP, s))


def unit_size(cash: float, n_symbols: int, *, max_units: int = MAX_UNITS) -> float:
    """Dollar size of one rung when `cash` is spread over `n_symbols`."""
    if n_symbols <= 0 or cash <= 0:
        return 0.0
    return round(cash * CASH_USE / n_symbols / max_units, 2)


def new_ladder(symbol: str, venue: str, unit_dollars: float, *,
               max_units: int = MAX_UNITS, start_units: int = START_UNITS) -> dict:
    return {
        "symbol": symbol,
        "venue": venue,
        "unit_dollars": round(float(unit_dollars), 2),
        "max_units": int(max_units),
        "start_units": int(min(start_units, max_units)),
        "units": [],          # stack of {"qty", "price", "dollars"}; last = newest
        "anchor": None,       # last fill price while holding
        "hwm": None,          # running high while flat
        "seeded": False,
        "realized_pl": 0.0,
        "fees_est": 0.0,
        "trades": 0,
        "last_fill_at": None,
        "last_error": None,
        "last_price": None,
    }


def held_qty(ladder: dict) -> float:
    return float(sum(float(u.get("qty") or 0) for u in ladder.get("units") or []))


def cost_basis(ladder: dict) -> float:
    return float(sum(float(u.get("dollars") or 0) for u in ladder.get("units") or []))


def levels(ladder: dict, step: float) -> dict:
    """Next trigger prices for the UI and the decision function."""
    step = clamp_step(step)
    units = ladder.get("units") or []
    anchor = ladder.get("anchor")
    hwm = ladder.get("hwm")
    if units and anchor:
        ref = float(anchor)
        sell_at = ref * (1 + step)
    else:
        ref = float(hwm) if hwm else None
        sell_at = None
    buy_at = ref * (1 - step) if ref and len(units) < int(ladder.get("max_units") or MAX_UNITS) else None
    return {"buy_at": buy_at, "sell_at": sell_at, "reference": ref}


def observe(ladder: dict, price: float) -> None:
    """Record a price tick. While flat, the reference follows the high."""
    if price is None or price <= 0:
        return
    ladder["last_price"] = float(price)
    if not ladder.get("units"):
        hwm = ladder.get("hwm")
        if not hwm:
            ladder["hwm"] = float(price)
        elif FOLLOW_HIGH:
            ladder["hwm"] = max(float(hwm), float(price))


def decide(ladder: dict, price: float, step: float, cash: float) -> dict | None:
    """Return the single action for this tick, or None.

    One action per symbol per tick keeps every fill observable before the
    next decision; with a 15-minute loop that is plenty for any `step`.
    """
    if price is None or price <= 0:
        return None
    step = clamp_step(step)
    unit = float(ladder.get("unit_dollars") or 0)
    if unit < MIN_ORDER_DOLLARS:
        return None
    units = ladder.get("units") or []
    max_units = int(ladder.get("max_units") or MAX_UNITS)

    if not ladder.get("seeded"):
        want = int(ladder.get("start_units") or START_UNITS)
        affordable = int(cash // unit) if unit > 0 else 0
        n = max(0, min(want, affordable, max_units))
        if n <= 0:
            return None
        return {"side": "buy", "dollars": round(unit * n, 2), "n_units": n,
                "reason": f"초기 {n}칸 매수"}

    lv = levels(ladder, step)
    if units and lv["sell_at"] is not None and price >= lv["sell_at"]:
        top = units[-1]
        return {
            "side": "sell", "qty": float(top["qty"]), "n_units": 1,
            "dollars": round(float(top["qty"]) * price, 2),
            "reason": f"+{step:.1%} 위 (기준 {lv['reference']:.6g})",
        }
    if len(units) < max_units and lv["buy_at"] is not None and price <= lv["buy_at"]:
        if cash < unit * 0.999:
            return None
        return {
            "side": "buy", "dollars": round(unit, 2), "n_units": 1,
            "reason": f"-{step:.1%} 아래 (기준 {lv['reference']:.6g})",
        }
    return None


def apply_fill(ladder: dict, *, side: str, qty: float, price: float, dollars: float,
               n_units: int = 1, at: datetime | None = None, fee: float = 0.0) -> dict:
    """Mutate the ladder for a confirmed fill and return the trade record."""
    at = at or datetime.now(timezone.utc)
    qty = float(qty)
    price = float(price)
    dollars = float(dollars) if dollars else qty * price
    units: list[dict] = ladder.setdefault("units", [])
    pl = 0.0
    if side == "buy":
        n = max(1, int(n_units))
        for _ in range(n):
            units.append({"qty": qty / n, "price": price, "dollars": dollars / n,
                          "at": at.isoformat()})
        ladder["anchor"] = price
        ladder["hwm"] = None
        ladder["seeded"] = True
    elif side == "sell":
        remaining = qty
        # Pop newest units first; a partial fill leaves a smaller top unit.
        while remaining > 1e-12 and units:
            top = units[-1]
            top_qty = float(top["qty"])
            if remaining >= top_qty * 0.999:
                units.pop()
                pl += top_qty * price - float(top["dollars"])
                remaining -= top_qty
            else:
                frac = remaining / top_qty
                pl += remaining * price - float(top["dollars"]) * frac
                top["qty"] = top_qty - remaining
                top["dollars"] = float(top["dollars"]) * (1 - frac)
                remaining = 0.0
        ladder["anchor"] = price
        if not units:
            ladder["hwm"] = price
        ladder["realized_pl"] = round(float(ladder.get("realized_pl") or 0) + pl - fee, 4)
    else:
        raise ValueError(f"unknown side {side!r}")
    ladder["fees_est"] = round(float(ladder.get("fees_est") or 0) + fee, 4)
    ladder["trades"] = int(ladder.get("trades") or 0) + 1
    ladder["last_fill_at"] = at.isoformat()
    ladder["last_error"] = None
    ladder["last_price"] = price
    return {
        "at": at.isoformat(),
        "venue": ladder.get("venue"),
        "symbol": ladder.get("symbol"),
        "side": side,
        "qty": qty,
        "price": price,
        "dollars": round(dollars, 2),
        "pl": round(pl, 4) if side == "sell" else None,
        "units_after": len(units),
    }


def top_up_deficit(ladder: dict) -> float:
    """Dollars needed to bring every held unit up to the current unit size.
    Used after the ladder is resized upward (new cash arrived)."""
    units = ladder.get("units") or []
    if not units:
        return 0.0
    target = len(units) * float(ladder.get("unit_dollars") or 0)
    return max(0.0, round(target - cost_basis(ladder), 2))


def apply_top_up(ladder: dict, *, qty: float, price: float, dollars: float,
                 at: datetime | None = None) -> dict:
    """Spread a top-up buy across the held units so the rung count stays the
    same and each rung ends up ~unit-sized. Re-anchors at the fill price."""
    at = at or datetime.now(timezone.utc)
    units: list[dict] = ladder.get("units") or []
    if not units:
        return apply_fill(ladder, side="buy", qty=qty, price=price, dollars=dollars, at=at)
    n = len(units)
    for u in units:
        u["qty"] = float(u["qty"]) + float(qty) / n
        u["dollars"] = float(u["dollars"]) + float(dollars) / n
        u["price"] = u["dollars"] / u["qty"] if u["qty"] > 0 else float(price)
    ladder["anchor"] = float(price)
    ladder["hwm"] = None
    ladder["trades"] = int(ladder.get("trades") or 0) + 1
    ladder["last_fill_at"] = at.isoformat()
    ladder["last_error"] = None
    ladder["last_price"] = float(price)
    ladder.pop("top_up", None)
    return {
        "at": at.isoformat(), "venue": ladder.get("venue"), "symbol": ladder.get("symbol"),
        "side": "buy", "qty": float(qty), "price": float(price), "dollars": round(float(dollars), 2),
        "pl": None, "units_after": n,
    }


def top_unit_bought_on(ladder: dict, day, tz) -> bool:
    """True when the unit a sell would pop was bought on calendar day `day`
    in timezone `tz`. Used to avoid same-day round trips (PDT) on stocks."""
    units = ladder.get("units") or []
    if not units:
        return False
    raw = units[-1].get("at")
    if not raw:
        return False
    try:
        bought = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if bought.tzinfo is None:
        bought = bought.replace(tzinfo=timezone.utc)
    return bought.astimezone(tz).date() == day


def reconcile(ladder: dict, broker_qty: float, price: float) -> str | None:
    """Align the ladder with what the broker actually holds.

    Manual sells in the app shrink the ladder from the top; manual buys (or a
    fill the engine could not record) are adopted as one extra unit at the
    current price so the grid keeps selling into strength. Returns a note
    for the activity log, or None when nothing changed.
    """
    broker_qty = float(broker_qty or 0)
    mine = held_qty(ladder)
    if mine <= 0 and broker_qty <= 0:
        return None
    unit_qty_ref = None
    units = ladder.get("units") or []
    if units:
        unit_qty_ref = float(units[-1]["qty"])
    elif price and ladder.get("unit_dollars"):
        unit_qty_ref = float(ladder["unit_dollars"]) / float(price)
    tol = max((unit_qty_ref or 0) * 0.05, 1e-9)
    diff = broker_qty - mine
    if abs(diff) <= tol:
        return None
    if diff < 0:
        # Fewer shares than we think: trim newest units until it matches.
        shortfall = -diff
        while shortfall > tol and units:
            top = units[-1]
            top_qty = float(top["qty"])
            if shortfall >= top_qty * 0.999:
                units.pop()
                shortfall -= top_qty
            else:
                frac = shortfall / top_qty
                top["qty"] = top_qty - shortfall
                top["dollars"] = float(top["dollars"]) * (1 - frac)
                shortfall = 0.0
        if not units:
            ladder["hwm"] = float(price) if price else ladder.get("anchor")
        return f"{ladder.get('symbol')} 보유 수량이 장부보다 적어 사다리를 {len(units)}칸으로 맞췄습니다."
    if price and price > 0 and len(units) < int(ladder.get("max_units") or MAX_UNITS):
        units.append({"qty": diff, "price": float(price), "dollars": diff * float(price)})
        ladder["anchor"] = float(price)
        ladder["hwm"] = None
        ladder["seeded"] = True
        return f"{ladder.get('symbol')} 장부에 없는 {diff:.6g} 수량을 현재가 기준 1칸으로 편입했습니다."
    return None


def summary(ladder: dict, step: float, price: float | None = None) -> dict:
    """Read-only view for the dashboard."""
    px = float(price) if price else (float(ladder["last_price"]) if ladder.get("last_price") else None)
    qty = held_qty(ladder)
    basis = cost_basis(ladder)
    value = qty * px if px else None
    lv = levels(ladder, step)
    return {
        "symbol": ladder.get("symbol"),
        "venue": ladder.get("venue"),
        "price": px,
        "units": len(ladder.get("units") or []),
        "max_units": int(ladder.get("max_units") or MAX_UNITS),
        "unit_dollars": ladder.get("unit_dollars"),
        "qty": qty,
        "cost_basis": round(basis, 2),
        "value": round(value, 2) if value is not None else None,
        "unrealized_pl": round(value - basis, 2) if value is not None else None,
        "realized_pl": round(float(ladder.get("realized_pl") or 0), 2),
        "trades": int(ladder.get("trades") or 0),
        "anchor": ladder.get("anchor"),
        "buy_at": lv["buy_at"],
        "sell_at": lv["sell_at"],
        "seeded": bool(ladder.get("seeded")),
        "last_fill_at": ladder.get("last_fill_at"),
        "last_error": ladder.get("last_error"),
    }
