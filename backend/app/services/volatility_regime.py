"""
Intraday realized-volatility regime for entry gating.

Uses a liquid market proxy (SPY) so we fetch 1Min/5Min bars once per minute,
not per symbol. Higher short-horizon vol raises the entry score threshold
(selectivity); very quiet periods allow a small relaxation.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

VOL_PROXY = "SPY"
MIN_1M_BARS = 28
MIN_5M_BARS = 16


def _close_to_close_vol_pct(closes: List[float], tail: int = 24) -> Optional[float]:
    if len(closes) < tail + 1:
        return None
    c = np.array(closes[-(tail + 1) :], dtype=float)
    if np.any(c <= 0):
        return None
    r = np.diff(c) / c[:-1] * 100.0
    if len(r) < 8:
        return None
    return float(np.std(r[-tail:]))


def _delta_from_1m(rv: Optional[float]) -> int:
    if rv is None:
        return 0
    if rv < 0.018:
        return -5
    if rv < 0.032:
        return 0
    if rv < 0.055:
        return 7
    if rv < 0.085:
        return 12
    return 18


def _delta_from_5m(rv: Optional[float]) -> int:
    if rv is None:
        return 0
    if rv < 0.048:
        return -3
    if rv < 0.078:
        return 0
    if rv < 0.12:
        return 6
    if rv < 0.18:
        return 10
    return 15


def compute_vol_entry_adjustment(alpaca: Any, now_et: datetime) -> Dict[str, Any]:
    """
    Pull 1Min/5Min proxy bars, compute realized vol of % returns, map to Δthreshold.

    Returns a dict safe to stash in ``regime_data["entry_vol_regime"]``.
    """
    out: Dict[str, Any] = {
        "proxy": VOL_PROXY,
        "rv_1m_pct": None,
        "rv_5m_pct": None,
        "delta_1m": 0,
        "delta_5m": 0,
        "vol_entry_delta": 0,
        "minute_et": now_et.strftime("%Y-%m-%d %H:%M"),
    }

    try:
        bars_1m: List[dict] = alpaca.get_bars(VOL_PROXY, "1Min", max(MIN_1M_BARS, 40))
        bars_5m: List[dict] = alpaca.get_bars(VOL_PROXY, "5Min", max(MIN_5M_BARS, 28))
    except Exception as exc:  # noqa: BLE001
        logger.debug("vol regime: bars fetch failed: %s", exc)
        return out

    c1 = [float(b["close"]) for b in bars_1m] if bars_1m else []
    c5 = [float(b["close"]) for b in bars_5m] if bars_5m else []

    rv1 = _close_to_close_vol_pct(c1, tail=24) if len(c1) >= 10 else None
    rv5 = _close_to_close_vol_pct(c5, tail=12) if len(c5) >= 10 else None

    d1 = _delta_from_1m(rv1)
    d5 = _delta_from_5m(rv5)
    total = d1 + d5
    total = max(-12, min(28, total))

    out.update(
        {
            "rv_1m_pct": round(rv1, 5) if rv1 is not None else None,
            "rv_5m_pct": round(rv5, 5) if rv5 is not None else None,
            "delta_1m": d1,
            "delta_5m": d5,
            "vol_entry_delta": total,
        }
    )
    if rv1 is not None or rv5 is not None:
        logger.debug(
            "vol regime %s: rv1m=%s rv5m=%s Δentry=%+d",
            VOL_PROXY,
            out["rv_1m_pct"],
            out["rv_5m_pct"],
            total,
        )
    return out
