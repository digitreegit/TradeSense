"""
Execution helpers: spread filter + marketable-limit order wrapper.

Keeps the trading engine focused on *what* to trade; this module owns
*how* the order actually hits the exchange. Avoids **market orders** so
fills are capped by an explicit limit price (slippage budget in bps).

Features:
- Marketable-limit from NBBO; falls back to ``ref_price`` ± bps when quote
  legs are missing (still a limit, never a market)
- Spread filter (% of mid) with a looser bound for urgent exits
- IOC / FOK / DAY via Alpaca ``submit_limit_order`` (entries default IOC)
- Optional execution-quality logging hooks (signal / order / reject)
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _slippage_bps() -> float:
    try:
        from app.core.config import settings

        return float(getattr(settings, "execution_slippage_bps", 8.0))
    except Exception:
        return 8.0


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
    except Exception:
        return 0.0, 0.0, 0.0


def marketable_limit_price(
    side: str,
    bid: float,
    ask: float,
    slippage_bps: Optional[float] = None,
) -> Optional[float]:
    """Build a *marketable* limit price from NBBO.

    - BUY  → ask × (1 + bps)
    - SELL → bid × (1 − bps)

    Returns ``None`` if quotes are invalid.
    """
    if bid <= 0 or ask <= 0:
        return None
    bps = float(slippage_bps if slippage_bps is not None else _slippage_bps())
    slip = bps / 1e4
    px = ask * (1.0 + slip) if side == "buy" else bid * (1.0 - slip)
    return round(max(px, 0.01), 2)


def marketable_limit_from_reference(
    side: str,
    ref_price: float,
    slippage_bps: Optional[float] = None,
) -> Optional[float]:
    """When bid/ask are missing, anchor the limit to ``ref_price`` (last/trade/mid)."""
    ref = float(ref_price or 0.0)
    if ref <= 0:
        return None
    bps = float(slippage_bps if slippage_bps is not None else _slippage_bps())
    slip = bps / 1e4
    px = ref * (1.0 + slip) if side == "buy" else ref * (1.0 - slip)
    return round(max(px, 0.01), 2)


def resolve_marketable_limit(
    side: str,
    bid: float,
    ask: float,
    ref_price: Optional[float],
    slippage_bps: Optional[float] = None,
) -> Optional[float]:
    """NBBO first; else ``ref_price`` cushion. Never returns without a numeric cap."""
    px = marketable_limit_price(side, bid, ask, slippage_bps)
    if px is not None:
        return px
    return marketable_limit_from_reference(side, float(ref_price or 0.0), slippage_bps)


def should_skip_spread(spread_pct: float, limit_pct: float) -> bool:
    """True if spread is too wide vs allowed limit (both in percent)."""
    if spread_pct <= 0 or limit_pct <= 0:
        return False
    return spread_pct > limit_pct


class Executor:
    """Thin wrapper that standardizes every outgoing order.

    ``exec_logger`` is an optional ``ExecutionLogger``; when set, every
    buy/sell is instrumented for slippage analysis later.
    """

    def __init__(self, alpaca_service, exec_logger=None):
        self._alpaca = alpaca_service
        self._log = exec_logger

    # ── internal helpers ────────────────────────────────────────
    def _log_signal(self, symbol, side, qty, ref_price, bid, ask, **extra) -> Optional[str]:
        if not self._log:
            return None
        try:
            return self._log.log_signal(
                symbol=symbol,
                side=side,
                qty=qty,
                ref_price=ref_price,
                bid=bid,
                ask=ask,
                **extra,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("executor: signal log failed: %s", exc)
            return None

    def _log_order(self, cid, order):
        if self._log and cid:
            try:
                self._log.log_order(cid, order)
            except Exception as exc:  # noqa: BLE001
                logger.warning("executor: order log failed: %s", exc)

    def _log_reject(self, cid, reason):
        if self._log and cid:
            try:
                self._log.log_reject(cid, reason)
            except Exception:
                pass

    # ── public API ─────────────────────────────────────────────
    def buy(
        self,
        symbol: str,
        qty: int,
        snapshot: dict,
        spread_limit_pct: float,
        *,
        tif: str = "ioc",
        extended_hours: bool = False,
        score: Optional[float] = None,
        reasons: Optional[list] = None,
        playbook: Optional[str] = None,
        ref_price: Optional[float] = None,
    ) -> dict:
        bid, ask, spread = spread_info(snapshot)
        ref = float(ref_price if ref_price is not None else (ask or bid or 0.0))
        cid = self._log_signal(
            symbol, "buy", qty, ref, bid, ask,
            score=score, reasons=reasons, playbook=playbook,
        )

        if should_skip_spread(spread, spread_limit_pct):
            reason = f"spread {spread:.3f}% > limit {spread_limit_pct:.3f}%"
            self._log_reject(cid, reason)
            return {"error": reason, "client_id": cid}

        px = resolve_marketable_limit("buy", bid, ask, ref_price=ref)
        if px is None:
            reason = "no quote or reference price for marketable buy limit"
            self._log_reject(cid, reason)
            return {"error": reason, "client_id": cid}

        tif_eff = "day" if extended_hours else tif
        order = self._alpaca.submit_limit_order(
            symbol, qty, "buy", px, tif=tif_eff, extended_hours=extended_hours
        )

        if "error" in order:
            self._log_reject(cid, order.get("error"))
            order["client_id"] = cid
            return order

        order["client_id"] = cid
        self._log_order(cid, order)
        return order

    def sell(
        self,
        symbol: str,
        qty: int,
        snapshot: dict,
        spread_limit_pct: float,
        *,
        tif: str = "day",
        extended_hours: bool = False,
        score: Optional[float] = None,
        reasons: Optional[list] = None,
        playbook: Optional[str] = None,
        ref_price: Optional[float] = None,
    ) -> dict:
        bid, ask, spread = spread_info(snapshot)
        ref = float(ref_price if ref_price is not None else (bid or ask or 0.0))
        cid = self._log_signal(
            symbol, "sell", qty, ref, bid, ask,
            score=score, reasons=reasons, playbook=playbook,
        )

        if should_skip_spread(spread, spread_limit_pct):
            # Exits are more urgent than entries — only block truly insane spreads.
            if spread > spread_limit_pct * 5:
                reason = f"spread too wide to exit safely ({spread:.3f}%)"
                self._log_reject(cid, reason)
                return {"error": reason, "client_id": cid}

        px = resolve_marketable_limit("sell", bid, ask, ref_price=ref)
        if px is None:
            reason = "no quote or reference price for marketable sell limit"
            self._log_reject(cid, reason)
            return {"error": reason, "client_id": cid}

        tif_eff = "day" if extended_hours else tif
        order = self._alpaca.submit_limit_order(
            symbol, qty, "sell", px, tif=tif_eff, extended_hours=extended_hours
        )

        if "error" in order:
            self._log_reject(cid, order.get("error"))
            order["client_id"] = cid
            return order

        order["client_id"] = cid
        self._log_order(cid, order)
        return order
