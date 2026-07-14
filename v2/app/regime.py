"""Market regime detection from daily SPY bars.

BULL: price above 200SMA and 50SMA rising  -> full risk on
BEAR: price below 200SMA and 50SMA falling -> mostly cash / defensive
CHOP: everything else                      -> reduced size, favor dip-buys
"""
from __future__ import annotations

import pandas as pd

from .config import EXPOSURE_BY_REGIME
from .indicators import sma

BULL = "BULL"
CHOP = "CHOP"
BEAR = "BEAR"


def classify(spy: pd.DataFrame) -> str:
    """Classify regime from a daily-bar DataFrame with a `close` column."""
    close = spy["close"]
    if len(close) < 210:
        return CHOP
    s200 = sma(close, 200)
    s50 = sma(close, 50)
    slope50 = s50.diff(10)
    above = close.iloc[-1] > s200.iloc[-1]
    rising = slope50.iloc[-1] > 0
    if above and rising:
        return BULL
    if not above and not rising:
        return BEAR
    return CHOP


def exposure(regime: str) -> float:
    return EXPOSURE_BY_REGIME.get(regime, EXPOSURE_BY_REGIME[CHOP])
