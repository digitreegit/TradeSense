"""
ETF pair mean-reversion signals for **cash (long-only) accounts**.

Classic pairs are long/short two legs; without shorts we only buy the
**relatively cheap** leg when the log spread z-score is extreme, expecting
partial mean reversion vs the peer (XLE vs USO, XLK vs QQQ, etc.).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = ["ETFPairSpec", "DEFAULT_ETF_PAIRS", "pair_long_signal"]


@dataclass(frozen=True)
class ETFPairSpec:
    a: str
    b: str
    label: str
    z_entry: float = 1.35
    lookback: int = 30
    min_aligned: int = 22


DEFAULT_ETF_PAIRS: Tuple[ETFPairSpec, ...] = (
    ETFPairSpec("XLE", "USO", "XLE/USO", z_entry=1.35, lookback=30, min_aligned=22),
    ETFPairSpec("XLK", "QQQ", "XLK/QQQ", z_entry=1.25, lookback=30, min_aligned=22),
)


def _align_closes(bars_a: Sequence[dict], bars_b: Sequence[dict]) -> Tuple[np.ndarray, np.ndarray]:
    by_t = {int(b["time"]): float(b["close"]) for b in bars_a}
    a_list: List[float] = []
    b_list: List[float] = []
    for row in sorted(bars_b, key=lambda x: int(x["time"])):
        t = int(row["time"])
        if t in by_t:
            a_list.append(by_t[t])
            b_list.append(float(row["close"]))
    if len(a_list) < 5:
        return np.array([]), np.array([])
    return np.asarray(a_list, dtype=float), np.asarray(b_list, dtype=float)


def pair_long_signal(
    bars_a: List[dict],
    bars_b: List[dict],
    spec: ETFPairSpec,
) -> Optional[Dict[str, Any]]:
    """
    If log(A) - log(B) z-score (vs prior bars in the lookback) is sufficiently
    negative → **A** is cheap → long **A**; sufficiently positive → long **B**.
    Mean and std use ``spread[:-1]`` so the current point is not in the baseline.
    """
    if not bars_a or not bars_b:
        return None
    ca, cb = _align_closes(bars_a, bars_b)
    if len(ca) < spec.min_aligned or len(cb) < spec.min_aligned:
        return None
    if np.any(ca <= 0) or np.any(cb <= 0):
        return None

    spread = np.log(ca) - np.log(cb)
    tail = spread[-spec.lookback :]
    if len(tail) < spec.min_aligned - 2:
        return None
    past = tail[:-1]
    cur = float(tail[-1])
    mu = float(np.mean(past))
    sd = float(np.std(past))
    if sd < 1e-8:
        return None
    z = (cur - mu) / sd

    last_a = float(ca[-1])
    last_b = float(cb[-1])

    if z <= -spec.z_entry:
        return {
            "target": spec.a,
            "z": z,
            "pair_label": spec.label,
            "price": last_a,
            "spread": cur,
            "mu": mu,
            "sd": sd,
        }
    if z >= spec.z_entry:
        return {
            "target": spec.b,
            "z": z,
            "pair_label": spec.label,
            "price": last_b,
            "spread": cur,
            "mu": mu,
            "sd": sd,
        }
    return None
