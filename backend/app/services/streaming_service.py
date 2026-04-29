"""
Low-latency market data streaming (Alpaca WebSocket).

REST polling tops out around 150–300 ms round-trip from anywhere outside
``us-east``. For a sub-100 ms scalp loop, the bot should *receive* trade /
quote updates via Alpaca's WebSocket and keep them in an in-memory map
the engine reads synchronously.

This module is intentionally small:

- ``LATEST_TRADE[sym]`` → most recent (price, ts)
- ``LATEST_QUOTE[sym]`` → most recent (bid, ask, bid_size, ask_size, ts)
- ``MINUTE_BARS[sym]`` → deque of recent **1-minute** OHLCV bars from
  ``subscribe_bars`` (Alpaca streams minute bars only).  Callers that need
  ``5Min`` bars aggregate these in memory; see :func:`intraday_bars_from_buffer`.
- ``start(...)`` / ``stop()`` lifecycle helpers called from FastAPI lifespan.

``feed`` should be:

- ``"iex"`` on the free Alpaca data plan (default)
- ``"sip"`` on the paid Algo Trader Plus plan — this is a *precondition*
  for proper high-frequency scalping because IEX only sees ~2 % of
  consolidated volume.

Callers should treat the cache as *best-effort*: if the connection
drops, :func:`latest_trade` / :func:`latest_quote` return ``None`` and
callers should fall back to the REST snapshot path.  Minute bars use the
same rule: :func:`intraday_bars_from_buffer` returns ``None`` until the
buffer is warm, then :class:`AlpacaService` falls back to REST history.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

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
# Completed 1-minute bars from WebSocket (newest at the right).
MINUTE_BARS: Dict[str, deque] = {}
BAR_BUFFER_MAX: int = max(60, int(os.getenv("STREAMING_BAR_BUFFER", "360")))

_task: Optional[asyncio.Task] = None
_stop_evt: Optional[asyncio.Event] = None
_subscribed: set[str] = set()
_state: Dict[str, object] = {
    "connected": False,
    "last_error": None,
    "feed": None,
    "started_at": None,
    "minute_bars_channel": None,  # True / False once subscribe_bars attempted
}


def latest_trade(symbol: str) -> Optional[Trade]:
    return LATEST_TRADE.get(symbol.upper())


def latest_quote(symbol: str) -> Optional[Quote]:
    return LATEST_QUOTE.get(symbol.upper())


def _bar_buffer_quick_stats() -> Dict[str, Any]:
    """Cheap stats for /health (no per-symbol aggregation)."""
    depths = [len(MINUTE_BARS[s]) for s in _subscribed if s in MINUTE_BARS]
    if not depths:
        return {
            "symbols_with_1m": 0,
            "max_1m_depth": 0,
            "likely_warm_5m": 0,
        }
    return {
        "symbols_with_1m": len(depths),
        "max_1m_depth": max(depths),
        # Heuristic: ~20 full 5m bars need ~100 consecutive 1m bars
        "likely_warm_5m": sum(1 for d in depths if d >= 100),
    }


def state() -> Dict[str, object]:
    out: Dict[str, Any] = {
        **_state,
        "subscribed": sorted(_subscribed),
        "cached_symbols": len(LATEST_TRADE),
        "minute_bar_symbols": len(MINUTE_BARS),
        "bar_buffer_max": BAR_BUFFER_MAX,
        "bars": _bar_buffer_quick_stats(),
    }
    started = _state.get("started_at")
    if isinstance(started, (int, float)) and _state.get("connected"):
        out["connected_seconds"] = round(time.time() - float(started), 1)
    return out


def _aggregate_minutes_to_period(minutes: List[Dict[str, Any]], period_minutes: int) -> List[Dict[str, Any]]:
    """Roll 1-minute bars into *period_minutes* OHLCV (bucket start timestamps)."""
    if not minutes or period_minutes < 1:
        return []
    period_sec = period_minutes * 60
    out: List[Dict[str, Any]] = []
    cur_bucket: Optional[int] = None
    cur: Optional[Dict[str, Any]] = None
    for b in minutes:
        ts = int(b["time"])
        bs = ts - (ts % period_sec)
        if cur_bucket != bs:
            if cur is not None:
                out.append(cur)
            cur_bucket = bs
            cur = {
                "time": bs,
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": int(b["volume"]),
            }
        else:
            if cur is None:
                cur_bucket = bs
                cur = {
                    "time": bs,
                    "open": float(b["open"]),
                    "high": float(b["high"]),
                    "low": float(b["low"]),
                    "close": float(b["close"]),
                    "volume": int(b["volume"]),
                }
                continue
            cur["high"] = max(cur["high"], float(b["high"]))
            cur["low"] = min(cur["low"], float(b["low"]))
            cur["close"] = float(b["close"])
            cur["volume"] = int(cur["volume"]) + int(b["volume"])
    if cur is not None:
        out.append(cur)
    return out


def intraday_bars_from_buffer(
    symbol: str,
    timeframe: str,
    limit: int,
    *,
    min_rows: int = 20,
) -> Optional[List[Dict[str, Any]]]:
    """
    Build ``1Min`` / ``5Min`` bar lists from the WebSocket minute buffer.

    Returns ``None`` if the buffer is too thin so callers can REST backfill.
    """
    sym = symbol.upper()
    buf = MINUTE_BARS.get(sym)
    if not buf or len(buf) < 1:
        return None
    minutes = list(buf)
    tf = (timeframe or "").strip()
    required = min(limit, min_rows) if limit < min_rows else min_rows
    if tf == "1Min":
        if len(minutes) < required:
            return None
        return minutes[-limit:] if limit > 0 else minutes
    if tf == "5Min":
        agg = _aggregate_minutes_to_period(minutes, 5)
        if len(agg) < required:
            return None
        return agg[-limit:] if limit > 0 else agg
    return None


async def _run_stream(symbols: Iterable[str], api_key: str, secret: str, feed: str) -> None:
    """Subscribe to Alpaca WebSocket trades, quotes, and minute bars for ``symbols``."""
    try:
        from alpaca.data.live import StockDataStream  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logger.warning("streaming: alpaca StockDataStream unavailable: %s", exc)
        _state["last_error"] = f"import: {exc}"
        return

    stream = StockDataStream(api_key, secret, feed=feed)
    _state["minute_bars_channel"] = None

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

    async def on_bar(bar):
        sym = str(getattr(bar, "symbol", "")).upper()
        if not sym:
            return
        ts_obj = getattr(bar, "timestamp", None)
        if ts_obj:
            ts = int(ts_obj.timestamp())
        else:
            ts = int(time.time())
        ts = ts - (ts % 60)
        row = {
            "time": ts,
            "open": float(getattr(bar, "open", 0.0) or 0.0),
            "high": float(getattr(bar, "high", 0.0) or 0.0),
            "low": float(getattr(bar, "low", 0.0) or 0.0),
            "close": float(getattr(bar, "close", 0.0) or 0.0),
            "volume": int(getattr(bar, "volume", 0) or 0),
        }
        dq = MINUTE_BARS.setdefault(sym, deque(maxlen=BAR_BUFFER_MAX))
        if dq and dq[-1]["time"] == ts:
            dq[-1] = row
        else:
            dq.append(row)

    syms = sorted({s.upper() for s in symbols if s})
    _subscribed.update(syms)

    try:
        stream.subscribe_trades(on_trade, *syms)
        stream.subscribe_quotes(on_quote, *syms)
    except Exception as exc:  # noqa: BLE001
        logger.warning("streaming: subscribe failed: %s", exc)
        _state["last_error"] = f"subscribe: {exc}"
        return

    try:
        stream.subscribe_bars(on_bar, *syms)
        _state["minute_bars_channel"] = True
    except Exception as exc:  # noqa: BLE001
        _state["minute_bars_channel"] = False
        logger.warning("streaming: subscribe_bars failed (minute bars via REST only): %s", exc)

    ch = _state.get("minute_bars_channel")
    logger.info(
        "streaming: subscribed trades+quotes%s on %d symbols (feed=%s)",
        "+bars" if ch else " (no bar channel)",
        len(syms),
        feed,
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
    global BAR_BUFFER_MAX
    try:
        from app.core.config import settings as _settings

        BAR_BUFFER_MAX = max(60, int(getattr(_settings, "streaming_bar_buffer_max", 360)))
    except Exception:
        BAR_BUFFER_MAX = max(60, int(os.getenv("STREAMING_BAR_BUFFER", "360")))
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
    _state["minute_bars_channel"] = None
    _state["started_at"] = None
    MINUTE_BARS.clear()


stop_streaming = stop
