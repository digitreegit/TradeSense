"""Pure decision function shared by the backtester and the live engine.

Given today's feature rows, current positions, and the regime, produce the
orders to execute at the next open. Keeping this pure guarantees that what
was backtested is exactly what trades live.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import config, regime, strategy

MOMENTUM = "momentum"
DIP = "dip"
CRYPTO = "crypto"
DEFENSIVE = "defensive"


@dataclass
class PosMeta:
    """Minimal position view the decision logic needs."""
    symbol: str
    sleeve: str
    held_days: int
    stop_level: float | None


@dataclass
class PendingOrder:
    symbol: str
    sleeve: str
    side: str            # buy | sell
    slot_weight: float = 0.0
    stop_mult: float = 0.0
    reason: str = ""


def decide(
    rows: dict[str, pd.Series],
    positions: dict[str, PosMeta],
    stock_syms: list[str],
    crypto_syms: list[str],
    reg: str,
    week_rollover: bool,
    defensive_syms: list[str] | None = None,
) -> list[PendingOrder]:
    pending: list[PendingOrder] = []
    expo = regime.exposure(reg)

    # 1) exits checked daily: trailing stops and dip-buy exits
    for sym, pos in positions.items():
        row = rows.get(sym)
        if row is None:
            continue
        close = float(row["close"])
        if pos.stop_level is not None and close <= pos.stop_level:
            pending.append(PendingOrder(sym, pos.sleeve, "sell", reason="stop"))
        elif pos.sleeve == DIP and strategy.dip_exit(row, pos.held_days):
            pending.append(PendingOrder(sym, pos.sleeve, "sell", reason="dip-exit"))

    pending_sells = {o.symbol for o in pending if o.side == "sell"}

    # 2) momentum rotation on week boundary (decide Friday, fill Monday)
    if week_rollover:
        stock_rows = {s: rows[s] for s in stock_syms if s in rows}
        targets = strategy.select_momentum(stock_rows)
        for sym, pos in positions.items():
            if pos.sleeve == MOMENTUM and sym not in targets and sym not in pending_sells:
                pending.append(PendingOrder(sym, MOMENTUM, "sell", reason="rotate"))
                pending_sells.add(sym)
        if expo > 0:
            slot = 0.9 / config.MOMENTUM_TOP_N * expo
            for sym in targets:
                if sym not in positions and sym not in pending_sells:
                    pending.append(PendingOrder(
                        sym, MOMENTUM, "buy",
                        slot_weight=slot, stop_mult=config.MOMENTUM_STOP_ATR,
                    ))

    # 3) dip-buy entries daily (skipped in BEAR: no knife catching)
    if reg != regime.BEAR:
        dip_open = sum(1 for p in positions.values() if p.sleeve == DIP)
        budget = config.DIP_MAX_POSITIONS - dip_open
        if budget > 0:
            cands = [
                s for s in stock_syms
                if s in rows and s not in positions and s not in pending_sells
                and strategy.dip_entry(rows[s])
            ]
            cands.sort(key=lambda s: rows[s]["rsi2"])  # most oversold first
            for sym in cands[:budget]:
                pending.append(PendingOrder(
                    sym, DIP, "buy",
                    slot_weight=0.25 * expo, stop_mult=config.DIP_STOP_ATR,
                ))

    # 4) third sleeve: crypto (licensed regions) or defensive macro ETFs (NJ-safe)
    if crypto_syms:
        trend_syms, sleeve, max_w = crypto_syms, CRYPTO, config.CRYPTO_MAX_WEIGHT
    elif defensive_syms:
        trend_syms, sleeve, max_w = defensive_syms, DEFENSIVE, config.DEFENSIVE_MAX_WEIGHT
    else:
        trend_syms, sleeve, max_w = [], "", 0.0

    if trend_syms:
        slot = max_w / max(len(trend_syms), 1)
        for sym in trend_syms:
            row = rows.get(sym)
            if row is None:
                continue
            long_ok = strategy.trend_long(row)
            if long_ok and sym not in positions and sym not in pending_sells:
                pending.append(PendingOrder(
                    sym, sleeve, "buy",
                    slot_weight=slot, stop_mult=config.MOMENTUM_STOP_ATR,
                ))
            elif not long_ok and sym in positions and sym not in pending_sells:
                pending.append(PendingOrder(sym, sleeve, "sell", reason="trend-off"))

    return pending
