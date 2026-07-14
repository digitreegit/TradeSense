"""Signal logic shared by the backtester and the live engine.

Three sleeves:
1. Momentum rotation  — own what is strong (top-N risk-adjusted momentum,
   positive absolute momentum required, wide ATR trailing stop).
2. Dip-buy            — buy short-term panic (RSI(2) < 10) in long-term
   uptrends, sell the bounce.
3. Crypto trend       — long BTC/ETH while above the 50-day EMA with the
   20-day EMA confirming; flat otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import config
from .indicators import atr, ema, momentum_score, rsi, sma


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Precompute all indicator columns for one symbol's daily bars.

    Expects columns: open, high, low, close. Index: DatetimeIndex.
    """
    out = df.copy()
    close = out["close"]
    out["atr"] = atr(out, config.ATR_PERIOD)
    out["mom_score"] = momentum_score(close, config.MOMENTUM_LOOKBACK)
    out["mom_ret"] = close / close.shift(config.MOMENTUM_LOOKBACK) - 1.0
    out["rsi2"] = rsi(close, config.DIP_RSI_PERIOD)
    out["sma200"] = sma(close, 200)
    out["ema_fast"] = ema(close, config.CRYPTO_FAST_EMA)
    out["ema_slow"] = ema(close, config.CRYPTO_SLOW_EMA)
    return out


def select_momentum(rows: dict[str, pd.Series], top_n: int | None = None) -> list[str]:
    """Pick top-N symbols by risk-adjusted momentum, requiring positive
    absolute momentum (dual momentum: a slot with nothing strong stays cash).

    `rows` maps symbol -> feature row as of the decision date.
    """
    top_n = top_n or config.MOMENTUM_TOP_N
    candidates = []
    for sym, row in rows.items():
        score = row.get("mom_score")
        ret = row.get("mom_ret")
        if score is None or pd.isna(score) or pd.isna(ret):
            continue
        if ret <= 0:
            continue
        candidates.append((sym, float(score)))
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in candidates[:top_n]]


def dip_entry(row: pd.Series) -> bool:
    """Short-term panic in a long-term uptrend."""
    if pd.isna(row.get("sma200")) or pd.isna(row.get("rsi2")):
        return False
    return bool(row["close"] > row["sma200"] and row["rsi2"] < config.DIP_RSI_ENTRY)


def dip_exit(row: pd.Series, held_days: int) -> bool:
    if held_days >= config.DIP_MAX_HOLD_DAYS:
        return True
    r = row.get("rsi2")
    return bool(not pd.isna(r) and r > config.DIP_RSI_EXIT)


def crypto_long(row: pd.Series) -> bool:
    if pd.isna(row.get("ema_slow")):
        return False
    return bool(row["close"] > row["ema_slow"] and row["ema_fast"] > row["ema_slow"])


@dataclass
class TrailingStop:
    """ATR trailing stop that only ratchets up."""

    level: float

    @classmethod
    def initial(cls, close: float, atr_value: float, mult: float) -> "TrailingStop":
        return cls(level=close - mult * atr_value)

    def update(self, close: float, atr_value: float, mult: float) -> float:
        self.level = max(self.level, close - mult * atr_value)
        return self.level

    def hit(self, close: float) -> bool:
        return close <= self.level
