"""Vectorized indicators on pandas Series/DataFrames (daily bars)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100.0).where(avg_loss != 0, 100.0)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range. Expects columns: high, low, close."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def annualized_vol(close: pd.Series, period: int) -> pd.Series:
    return close.pct_change().rolling(period).std() * np.sqrt(252)


def momentum_score(close: pd.Series, lookback: int) -> pd.Series:
    """Risk-adjusted momentum: lookback return divided by annualized vol."""
    ret = close / close.shift(lookback) - 1.0
    vol = annualized_vol(close, lookback)
    return ret / vol.replace(0.0, np.nan)
