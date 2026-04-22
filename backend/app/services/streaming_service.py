"""
Low-latency market data streaming (Alpaca WebSocket).

REST polling tops out around 150–300 ms round-trip from anywhere outside
``us-east``. For a sub-100 ms scalp loop, the bot should *receive* trade /
quote updates via Alpaca's WebSocket and keep them in an in-memory map
the engine reads synchronously.

This module is intentionally small:

- ``LATEST_TRADE[sym]`` → most recent (price, ts)
- ``LATEST_QUOTE[sym]`` → most recent (bid, ask, bid_size, ask_size, ts)
- ``start(...)`` / ``stop()`` lifecycle helpers called from FastAPI lifespan.

``feed`` should be:

- ``"iex"`` on the free Alpaca data plan (default)
- ``"sip"`` on the paid Algo Trader Plus plan — this is a *precondition*
  for proper high-frequency scalping because IEX only sees ~2 % of
  consolidated volume.

Callers should treat the cache as *best-effort*: if the connection
drops, :func:`latest_trade` / :func:`latest_quote` return ``None`` and
callers should fall back to the REST snapshot path.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    symbol: str
    price: float
    size: int
    ts: float  # epoch seconds


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    ts: float


# Module-level caches — tiny, O(1) reads, safe across coroutines.
LATEST_TRADE: Dict[str, Trade] = {}
LATEST_QUOTE: Dict[str, Quote] = {}

_task: Optional[asyncio.Task] = None
_stop_evt: Optional[asyncio.Event] = None
_subscribed: set[str] = set()
_state: Dict[str, object] = {
    "connected": False,
    "last_error": None,
    "feed": None,
    "started_at": None,
}


def latest_trade(symbol: str) -> Optional[Trade]:
    return LATEST_TRADE.get(symbol.upper())


def latest_quote(symbol: str) -> Optional[Quote]:
    return LATEST_QUOTE.get(symbol.upper())


def state() -> Dict[str, object]:
    return {
        **_state,
        "subscribed": sorted(_subscribed),
        "cached_symbols": len(LATEST_TRADE),
    }


async def _run_stream(symbols: Iterable[str], api_key: str, secret: str, feed: str) -> None:
    """Subscribe to Alpaca WebSocket trades + quotes for ``symbols``."""
    try:
        from alpaca.data.live import StockDataStream  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("streaming: alpaca StockDataStream unavailable: %s", exc)
        _state["last_error"] = f"import: {exc}"
        return

    stream = StockDataStream(api_key, secret, feed=feed)

    async def on_trade(trade):
        sym = str(getattr(trade, "symbol", "")).upper()
        if not sym:
            return
        ts_obj = getattr(trade, "timestamp", None)
        ts = ts_obj.timestamp() if ts_obj else time.time()
        LATEST_TRADE[sym] = Trade(
            symbol=sym,
            price=float(getattr(trade, "price", 0.0) or 0.0),
            size=int(getattr(trade, "size", 0) or 0),
            ts=float(ts),
        )

    async def on_quote(q):
        sym = str(getattr(q, "symbol", "")).upper()
        if not sym:
            return
        ts_obj = getattr(q, "timestamp", None)
        ts = ts_obj.timestamp() if ts_obj else time.time()
        LATEST_QUOTE[sym] = Quote(
            symbol=sym,
            bid=float(getattr(q, "bid_price", 0.0) or 0.0),
            ask=float(getattr(q, "ask_price", 0.0) or 0.0),
            bid_size=int(getattr(q, "bid_size", 0) or 0),
            ask_size=int(getattr(q, "ask_size", 0) or 0),
            ts=float(ts),
        )

    syms = sorted({s.upper() for s in symbols if s})
    _subscribed.update(syms)

    try:
        stream.subscribe_trades(on_trade, *syms)
        stream.subscribe_quotes(on_quote, *syms)
    except Exception as exc:  # noqa: BLE001
        logger.warning("streaming: subscribe failed: %s", exc)
        _state["last_error"] = f"subscribe: {exc}"
        return

    logger.info(
        "streaming: subscribed trades+quotes on %d symbols (feed=%s)",
        len(syms), feed,
    )
    _state["connected"] = True
    _state["feed"] = feed
    _state["started_at"] = time.time()
    _state["last_error"] = None

    # alpaca-py ≥ 0.20 exposes _run_forever as the documented async entrypoint.
    try:
        await stream._run_forever()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("streaming: stream crashed: %s", exc)
        _state["last_error"] = f"runtime: {exc}"
    finally:
        _state["connected"] = False
        try:
            await stream.close()
        except Exception:  # noqa: BLE001
            pass


async def _supervisor(symbols: list[str], api_key: str, secret: str, feed: str) -> None:
    """Reconnect with exponential backoff when the socket drops."""
    backoff = 1.0
    while True:
        await _run_stream(symbols, api_key, secret, feed)
        if _stop_evt and _stop_evt.is_set():
            return
        logger.warning("streaming: disconnected, retrying in %.1fs", backoff)
        try:
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            return
        backoff = min(backoff * 2, 30.0)


def start(symbols: Iterable[str], api_key: str, secret: str, feed: Optional[str] = None) -> None:
    """
    Fire-and-forget WebSocket consumer. Safe to call from the FastAPI
    lifespan. If ``feed`` is None, defaults to the ``ALPACA_DATA_FEED`` env
    (``iex`` or ``sip``).
    """
    global _task, _stop_evt
    if _task and not _task.done():
        return
    if not api_key or not secret:
        logger.info("streaming: keys missing — skipping WebSocket start")
        return
    syms = sorted({s.upper() for s in symbols if s})
    if not syms:
        return
    feed = (feed or os.getenv("ALPACA_DATA_FEED", "iex")).lower()
    _stop_evt = asyncio.Event()
    _task = asyncio.create_task(_supervisor(syms, api_key, secret, feed))
    logger.info("streaming: task started (feed=%s, symbols=%d)", feed, len(syms))


# Back-compat alias for callers that may still use the old name.
start_streaming = start


async def stop() -> None:
    global _task
    if _stop_evt:
        _stop_evt.set()
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
    _state["connected"] = False


stop_streaming = stop
