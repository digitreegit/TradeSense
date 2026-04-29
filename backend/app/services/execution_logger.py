"""
Execution-quality JSONL logger.

For each outgoing order the engine emits:

- ``event="signal"``   → what the strategy wanted to do (reference price,
  reasoning, bid/ask at signal time)
- ``event="order"``    → the order that was actually submitted (type, TIF,
  limit price, submitted_at, broker order id)
- ``event="fill"``     → reconciled with broker after fill (filled_avg_price,
  qty, timestamp, latency)
- ``event="slippage"`` → computed slippage_bps vs signal price

One line per event. Files rotate by ET trading date.

The engine calls these helpers synchronously; writes are buffered by the
OS and tiny (a few hundred bytes), so even at 500 events/day the cost is
negligible. Callers should not raise on logger failures — that's why we
wrap every call in try/except.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz

from app.core.config import settings

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")


def _today_iso() -> str:
    return datetime.now(ET).date().isoformat()


class ExecutionLogger:
    """Per-engine JSONL execution-quality log writer."""

    def __init__(self, log_dir: Optional[Path] = None, owner_tag: str = "default"):
        base = log_dir or Path(os.getenv("TRADESENSE_LOG_DIR", "./trade_logs"))
        base.mkdir(parents=True, exist_ok=True)
        self._dir = base
        self._owner = owner_tag
        # In-memory pending map: client_order_id → signal context (for fill reconciliation)
        self._pending: Dict[str, Dict[str, Any]] = {}

    @property
    def enabled(self) -> bool:
        return bool(getattr(settings, "execution_log_enabled", True))

    def _path(self) -> Path:
        return self._dir / f"execution-{_today_iso()}.jsonl"

    def _write(self, record: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            record.setdefault("ts", time.time())
            record.setdefault("iso", datetime.now(ET).isoformat())
            record.setdefault("owner", self._owner)
            with self._path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("execution logger write failed: %s", exc)

    # ─── Signal / order / fill hooks ────────────────────────────
    def new_client_id(self) -> str:
        return uuid.uuid4().hex[:16]

    def log_signal(
        self,
        *,
        symbol: str,
        side: str,
        qty: int,
        ref_price: float,
        bid: float,
        ask: float,
        score: Optional[float] = None,
        reasons: Optional[list] = None,
        playbook: Optional[str] = None,
    ) -> str:
        cid = self.new_client_id()
        self._pending[cid] = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "ref_price": float(ref_price or 0.0),
            "bid": float(bid or 0.0),
            "ask": float(ask or 0.0),
            "signal_ts": time.time(),
        }
        self._write({
            "event": "signal",
            "client_id": cid,
            "symbol": symbol,
            "side": side,
            "qty": int(qty),
            "ref_price": float(ref_price or 0.0),
            "bid": float(bid or 0.0),
            "ask": float(ask or 0.0),
            "score": score,
            "reasons": reasons or [],
            "playbook": playbook,
        })
        return cid

    def log_order(self, client_id: str, order: Dict[str, Any]) -> None:
        ctx = self._pending.get(client_id, {})
        submit_ts = time.time()
        ctx["submit_ts"] = submit_ts
        ctx["broker_id"] = order.get("id")
        ctx["limit_price"] = order.get("limit_price")
        ctx["tif"] = order.get("tif") or order.get("time_in_force")
        ctx["order_type"] = order.get("type") or ("market" if order.get("type") is None else order.get("type"))
        self._pending[client_id] = ctx
        self._write({
            "event": "order",
            "client_id": client_id,
            "broker_id": ctx.get("broker_id"),
            "symbol": order.get("symbol") or ctx.get("symbol"),
            "side": order.get("side") or ctx.get("side"),
            "qty": order.get("qty") or ctx.get("qty"),
            "type": ctx.get("order_type"),
            "tif": ctx.get("tif"),
            "limit_price": ctx.get("limit_price"),
            "signal_to_submit_ms": round((submit_ts - ctx.get("signal_ts", submit_ts)) * 1000, 2),
            "status": order.get("status"),
        })

    def log_reject(self, client_id: str, reason: str) -> None:
        ctx = self._pending.pop(client_id, {})
        self._write({
            "event": "reject",
            "client_id": client_id,
            "symbol": ctx.get("symbol"),
            "side": ctx.get("side"),
            "qty": ctx.get("qty"),
            "reason": reason,
        })

    def log_fill(
        self,
        client_id: str,
        *,
        filled_avg_price: float,
        filled_qty: float,
        status: str,
        filled_at: Optional[str] = None,
    ) -> Optional[float]:
        """Reconcile a fill with the original signal. Returns slippage_bps."""
        ctx = self._pending.pop(client_id, None)
        if ctx is None:
            return None

        ref = float(ctx.get("ref_price") or 0.0)
        side = ctx.get("side")
        slip_bps: Optional[float] = None
        if ref > 0 and filled_avg_price and filled_avg_price > 0:
            # BUY slippage positive if we paid above ref; SELL positive if we
            # sold below ref. Sign-invariant "cost of execution" = how much
            # worse we did vs the signal price.
            if side == "buy":
                slip_bps = (filled_avg_price - ref) / ref * 1e4
            else:
                slip_bps = (ref - filled_avg_price) / ref * 1e4

        now_ts = time.time()
        submit_to_fill_ms = None
        if ctx.get("submit_ts"):
            submit_to_fill_ms = round((now_ts - ctx["submit_ts"]) * 1000, 2)

        self._write({
            "event": "fill",
            "client_id": client_id,
            "broker_id": ctx.get("broker_id"),
            "symbol": ctx.get("symbol"),
            "side": side,
            "qty_sent": ctx.get("qty"),
            "qty_filled": float(filled_qty or 0.0),
            "ref_price": ref,
            "filled_avg_price": float(filled_avg_price or 0.0),
            "slippage_bps": round(slip_bps, 2) if slip_bps is not None else None,
            "status": status,
            "filled_at": filled_at,
            "submit_to_fill_ms": submit_to_fill_ms,
        })
        return slip_bps

    def has_pending(self, client_id: str) -> bool:
        return client_id in self._pending

    def pending_ids(self) -> list:
        return list(self._pending.keys())
