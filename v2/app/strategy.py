"""Signal logic shared by the backtester and the live engine.

Three sleeves:
1. Momentum rotation  — own what is strong (top-N risk-adjusted momentum,
   positive absolute momentum required, wide ATR trailing stop).
2. Dip-buy            — buy short-term panic (RSI(2) < 10) in long-term
   uptrends, sell the bounce.
3. Macro trend        — long BTC/ETH (where licensed) OR GLD/TLT/IEF when
   crypto is disabled (e.g. NJ). Above 50-day EMA with 20-day confirming.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import config
from .indicators import annualized_vol, atr, ema, momentum_score, rsi, sma


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Precompute all indicator columns for one symbol's daily bars.

    Expects columns: open, high, low, close. Index: DatetimeIndex.
    """
    out = df.copy()
    close = out["close"]
    out["atr"] = atr(out, config.ATR_PERIOD)
    out["mom_score"] = momentum_score(close, config.MOMENTUM_LOOKBACK)
    out["mom_ret"] = close / close.shift(config.MOMENTUM_LOOKBACK) - 1.0
    out["mom_vol"] = annualized_vol(close, config.MOMENTUM_LOOKBACK)
    out["rsi2"] = rsi(close, config.DIP_RSI_PERIOD)
    out["volume_ratio"] = out["volume"] / out["volume"].rolling(20).mean()
    candle_range = (out["high"] - out["low"]).replace(0.0, float("nan"))
    out["upper_wick"] = (
        out["high"] - out[["open", "close"]].max(axis=1)
    ) / candle_range
    out["sma200"] = sma(close, 200)
    out["ema_fast"] = ema(close, config.CRYPTO_FAST_EMA)
    out["ema_slow"] = ema(close, config.CRYPTO_SLOW_EMA)
    return out


def select_momentum(rows: dict[str, pd.Series], top_n: int | None = None) -> list[str]:
    """Pick top-N symbols by configurable momentum rank, requiring positive
    absolute momentum (dual momentum: a slot with nothing strong stays cash).

    `rows` maps symbol -> feature row as of the decision date.
    """
    top_n = top_n or config.MOMENTUM_TOP_N
    candidates = []
    for sym, row in rows.items():
        ret = row.get("mom_ret")
        vol = row.get("mom_vol")
        if ret is None or vol is None or pd.isna(ret) or pd.isna(vol) or vol <= 0:
            continue
        if ret <= 0:
            continue
        penalty = config.MOMENTUM_VOL_PENALTY
        score = float(ret) / float(vol) ** penalty
        candidates.append((sym, score))
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in candidates[:top_n]]


def dip_entry(row: pd.Series) -> bool:
    """Short-term panic in a long-term uptrend."""
    if (
        pd.isna(row.get("sma200"))
        or pd.isna(row.get("rsi2"))
        or pd.isna(row.get("volume_ratio"))
    ):
        return False
    return bool(
        row["close"] > row["sma200"]
        and row["rsi2"] < config.DIP_RSI_ENTRY
        and row["volume_ratio"] >= config.DIP_ENTRY_MIN_VOLUME_RATIO
    )


def dip_exit(
    row: pd.Series, held_days: int, entry_price: float | None = None
) -> bool:
    if (
        config.DIP_PROFIT_TARGET > 0
        and entry_price is not None
        and float(row["close"]) >= entry_price * (1 + config.DIP_PROFIT_TARGET)
    ):
        return True
    if held_days >= config.DIP_MAX_HOLD_DAYS:
        return True
    r = row.get("rsi2")
    return bool(not pd.isna(r) and r > config.DIP_RSI_EXIT)


def distribution_exit(row: pd.Series) -> bool:
    """High-volume failed rally / upper-wick exit."""
    if not config.DISTRIBUTION_EXIT_ENABLED:
        return False
    volume_ratio = row.get("volume_ratio")
    upper_wick = row.get("upper_wick")
    return bool(
        not pd.isna(volume_ratio)
        and not pd.isna(upper_wick)
        and volume_ratio >= config.DISTRIBUTION_MIN_VOLUME_RATIO
        and upper_wick >= config.DISTRIBUTION_MIN_UPPER_WICK
    )


def trend_long(row: pd.Series) -> bool:
    """EMA trend filter shared by crypto and defensive macro sleeves."""
    if pd.isna(row.get("ema_slow")):
        return False
    return bool(row["close"] > row["ema_slow"] and row["ema_fast"] > row["ema_slow"])


def crypto_long(row: pd.Series) -> bool:
    return trend_long(row)


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
