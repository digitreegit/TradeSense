"""
Low-latency market data streaming (Alpaca WebSocket).

REST polling tops out around 150–300 ms round-trip from anywhere outside
us-east. For a 100 ms-target cash-scalp, the bot should *receive* bar /
trade updates via Alpaca's WebSocket and keep them in an in-memory map
the engine reads synchronously. This module is the glue; flip it on by
calling :func:`start_streaming` from the FastAPI lifespan when running
against the live market.

The stream runs in a background task and updates ``LATEST`` so that
``latest_trade(symbol)`` is O(1) for the engine. Keep the public surface
small so a later migration (e.g. Polygon WebSocket, or broker-hosted)
doesn't require touching callers.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass
class Tick:
    symbol: str
    price: float
    ts: float


LATEST: Dict[str, Tick] = {}
_task: Optional[asyncio.Task] = None
_stop_evt: Optional[asyncio.Event] = None


def latest_trade(symbol: str) -> Optional[Tick]:
    return LATEST.get(symbol.upper())


async def _run_stream(symbols: Iterable[str], api_key: str, secret: str, feed: str = "iex"):
    """
    Subscribe to Alpaca WebSocket trades for the given symbols.

    Uses the official ``alpaca-py`` ``StockDataStream``. ``feed`` is
    ``"iex"`` for free paper accounts and ``"sip"`` for the paid real-time
    consolidated feed (required for a real 100 ms target).
    """
    try:
        from alpaca.data.live import StockDataStream  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("streaming: alpaca StockDataStream unavailable: %s", exc)
        return

    stream = StockDataStream(api_key, secret, feed=feed)

    async def on_trade(trade):
        sym = str(getattr(trade, "symbol", "")).upper()
        if not sym:
            return
        LATEST[sym] = Tick(
            symbol=sym,
            price=float(getattr(trade, "price", 0.0) or 0.0),
            ts=float(getattr(trade, "timestamp", 0).timestamp()) if getattr(trade, "timestamp", None) else 0.0,
        )

    syms = [s.upper() for s in symbols]
    stream.subscribe_trades(on_trade, *syms)
    logger.info("streaming: subscribed to %d symbols (feed=%s)", len(syms), feed)

    try:
        await stream._run_forever()  # alpaca-py internal; wraps aiohttp loop
    except Exception as exc:  # noqa: BLE001
        logger.warning("streaming: stream crashed: %s", exc)


def start_streaming(symbols: Iterable[str], api_key: str, secret: str, feed: str = "iex") -> None:
    """
    Fire-and-forget WebSocket consumer. Safe to call from the FastAPI
    lifespan; callers can ignore return value.
    """
    global _task, _stop_evt
    if _task and not _task.done():
        return
    _stop_evt = asyncio.Event()
    _task = asyncio.create_task(_run_stream(symbols, api_key, secret, feed))


async def stop_streaming() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
