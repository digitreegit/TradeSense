"""
Quantitative market-regime scoring.

Pulls a handful of liquid ETFs/proxies from Alpaca instead of relying on
AI hallucinations for macro context. All scores are 0..100 with *higher =
better for bullish risk-on equity scalping*.

Proxies (all standard US-listed ETFs, available via Alpaca):

- VIXY : short-vol ETF (up ⇒ vol rising ⇒ risk-off)
- TLT  : 20y+ treasuries (up ⇒ flight to safety ⇒ risk-off)
- UUP  : USD index ETF (up ⇒ tight USD ⇒ risk-off for equities)
- GLD  : gold (up ⇒ risk-off)
- XLE  : energy sector (used for sector rotation cue)
- BITO : Bitcoin futures ETF (up ⇒ risk-on sentiment)
- SPY  : S&P 500 (own trend / breadth proxy)

The composite is a deliberately simple weighted average so the UI can
explain it in one sentence. Replace individual scorers without touching
callers.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# --- per-proxy weights ------------------------------------------------
WEIGHTS = {
    "vix":    0.22,  # volatility
    "bonds":  0.14,  # TLT
    "dxy":    0.12,  # UUP
    "gold":   0.10,  # GLD
    "energy": 0.08,  # XLE — sector rotation hint only, small weight
    "crypto": 0.08,  # BITO — risk-appetite
    "spy":    0.26,  # own trend
}


def _pct_change(bars: list, window: int) -> Optional[float]:
    if not bars or len(bars) < window + 1:
        return None
    old = bars[-window - 1].get("close")
    new = bars[-1].get("close")
    if not old:
        return None
    return (new - old) / old * 100.0


def _clip(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


class RegimeService:
    """Computes a macro 'Market Status' score using Alpaca bar data."""

    PROXIES = ["VIXY", "TLT", "UUP", "GLD", "XLE", "BITO", "SPY"]

    def __init__(self, alpaca_service):
        self._alpaca = alpaca_service
        self._cache: Dict[str, dict] = {}
        self._cache_ts: float = 0.0

    # ─── Fetch helpers ───────────────────────────────────────────
    def _bars(self, symbol: str, limit: int = 30) -> list:
        try:
            return self._alpaca.get_bars(symbol, "1Day", limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("regime bar fetch failed for %s: %s", symbol, exc)
            return []

    # ─── Per-proxy scorers (higher = better for risk-on) ─────────
    @staticmethod
    def _score_vix(change_5d: Optional[float]) -> float:
        # VIXY up 10% ⇒ very bad; VIXY down 10% ⇒ very good
        if change_5d is None:
            return 50.0
        return _clip(50.0 - change_5d * 4.0)

    @staticmethod
    def _score_inverse(change_5d: Optional[float]) -> float:
        if change_5d is None:
            return 50.0
        return _clip(50.0 - change_5d * 6.0)

    @staticmethod
    def _score_trend(change_5d: Optional[float]) -> float:
        if change_5d is None:
            return 50.0
        return _clip(50.0 + change_5d * 8.0)

    # ─── Composite ───────────────────────────────────────────────
    def compute_scores(self) -> dict:
        """Compute per-proxy scores + composite and return a UI-ready dict."""
        bars = {sym: self._bars(sym, 30) for sym in self.PROXIES}
        chg = {sym: _pct_change(bars[sym], 5) for sym in self.PROXIES}

        scores = {
            "vix":    self._score_vix(chg["VIXY"]),
            "bonds":  self._score_inverse(chg["TLT"]),
            "dxy":    self._score_inverse(chg["UUP"]),
            "gold":   self._score_inverse(chg["GLD"]),
            "energy": self._score_trend(chg["XLE"]),
            "crypto": self._score_trend(chg["BITO"]),
            "spy":    self._score_trend(chg["SPY"]),
        }

        composite = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)

        # Crude VIX level estimate from VIXY 5d return + a 16 baseline.
        vix_level = 16.0 * (1.0 + (chg.get("VIXY") or 0.0) / 100.0)

        # Sector tilt hint — "focus energy if XLE > SPY by >1% over 5d"
        tilt = None
        if chg.get("XLE") is not None and chg.get("SPY") is not None:
            if chg["XLE"] - chg["SPY"] > 1.0:
                tilt = "energy"
            elif chg["SPY"] - chg["XLE"] > 2.0:
                tilt = "tech"

        return {
            "composite": round(composite, 1),
            "scores": {k: round(v, 1) for k, v in scores.items()},
            "changes_5d_pct": {k: round(v, 2) if v is not None else None for k, v in chg.items()},
            "vix_proxy_level": round(vix_level, 2),
            "sector_tilt": tilt,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }

    # ─── Focus universe suggestion ───────────────────────────────
    @staticmethod
    def suggested_universe(tilt: Optional[str]) -> list:
        """Blend tech core with sector tilt so we're not stuck in tech only."""
        core_tech = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AMD", "TSLA"]
        liquid_etfs = ["SPY", "QQQ"]
        energy = ["XLE", "XOM", "CVX", "OXY", "SLB"]
        defensives = ["XLP", "XLU", "KO", "PG"]

        if tilt == "energy":
            return energy + core_tech[:5] + liquid_etfs
        if tilt == "tech":
            return core_tech + liquid_etfs
        return core_tech[:6] + liquid_etfs + defensives[:2]
