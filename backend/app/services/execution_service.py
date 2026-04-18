"""
Execution helpers: spread filter + marketable-limit order wrapper.

Keeps the trading engine focused on *what* to trade; this module owns
*how* the order actually hits the exchange. Reduces slippage vs naive
market orders and blocks symbols with dangerously wide spreads.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def spread_info(snapshot: dict) -> Tuple[float, float, float]:
    """Return (bid, ask, spread_pct). Returns (0, 0, 0) if data missing."""
    try:
        q = snapshot.get("latest_quote") if snapshot else None
        if not q:
            return 0.0, 0.0, 0.0
        bid = float(q.get("bid") or 0.0)
        ask = float(q.get("ask") or 0.0)
        if bid <= 0 or ask <= 0 or ask < bid:
            return bid, ask, 0.0
        mid = (bid + ask) / 2.0
        spread_pct = (ask - bid) / mid * 100.0
        return bid, ask, spread_pct
    except Exception:  # noqa: BLE001
        return 0.0, 0.0, 0.0


def marketable_limit_price(
    side: str,
    bid: float,
    ask: float,
    slippage_bps: float = 5.0,
) -> Optional[float]:
    """
    Build a *marketable* limit price:

    - BUY  → ask × (1 + slippage_bps/1e4), rounded to 2 decimals
    - SELL → bid × (1 − slippage_bps/1e4)

    Returns None if quotes are invalid.
    """
    if bid <= 0 or ask <= 0:
        return None
    slip = slippage_bps / 1e4
    px = ask * (1.0 + slip) if side == "buy" else bid * (1.0 - slip)
    # Equities trade in cents above $1.
    return round(max(px, 0.01), 2)


def should_skip_spread(spread_pct: float, limit_pct: float) -> bool:
    """True if spread is too wide vs allowed limit (both in percent)."""
    if spread_pct <= 0 or limit_pct <= 0:
        return False
    return spread_pct > limit_pct


class Executor:
    """Thin wrapper that standardizes every outgoing order."""

    def __init__(self, alpaca_service):
        self._alpaca = alpaca_service

    def buy(self, symbol: str, qty: int, snapshot: dict, spread_limit_pct: float) -> dict:
        bid, ask, spread = spread_info(snapshot)
        if should_skip_spread(spread, spread_limit_pct):
            return {"error": f"spread {spread:.3f}% > limit {spread_limit_pct:.3f}%"}
        px = marketable_limit_price("buy", bid, ask)
        if px is None:
            # fall back to market if we literally have no quote
            logger.info("executor: no quote for %s, using market order", symbol)
            return self._alpaca.submit_market_order(symbol, qty, "buy")
        return self._alpaca.submit_limit_order(symbol, qty, "buy", px)

    def sell(self, symbol: str, qty: int, snapshot: dict, spread_limit_pct: float) -> dict:
        bid, ask, spread = spread_info(snapshot)
        if should_skip_spread(spread, spread_limit_pct):
            # selling through a wide spread is usually worth it for stop-loss;
            # only block when truly insane (>5× limit).
            if spread > spread_limit_pct * 5:
                return {"error": f"spread too wide to exit safely ({spread:.3f}%)"}
        px = marketable_limit_price("sell", bid, ask)
        if px is None:
            return self._alpaca.submit_market_order(symbol, qty, "sell")
        return self._alpaca.submit_limit_order(symbol, qty, "sell", px)
