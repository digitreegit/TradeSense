"""Historical daily bars for backtesting (yfinance, cached locally).

Live trading pulls bars from Alpaca (see broker.py); backtests use Yahoo
because it offers 10+ years of adjusted daily history for free.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import DATA_DIR

CACHE_DIR = DATA_DIR / "cache"

COLUMN_MAP = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


def _yf_symbol(symbol: str) -> str:
    # Alpaca crypto "BTC/USD" -> Yahoo "BTC-USD"
    return symbol.replace("/", "-")


def _cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"{_yf_symbol(symbol)}.csv"


def _cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return mtime.date() == date.today()


def load_daily(symbol: str, start: str, end: str | None = None) -> pd.DataFrame:
    """Load adjusted daily OHLCV for one symbol, caching to CSV."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(symbol)
    if _cache_fresh(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        import yfinance as yf

        raw = yf.download(
            _yf_symbol(symbol), start=start, end=end,
            auto_adjust=True, progress=False, multi_level_index=False,
        )
        if raw is None or raw.empty:
            raise RuntimeError(f"no data for {symbol}")
        df = raw.rename(columns=COLUMN_MAP)[list(COLUMN_MAP.values())]
        df.index.name = "date"
        df.to_csv(path)
        time.sleep(0.3)  # be polite to Yahoo
    df = df.loc[df.index >= pd.Timestamp(start)]
    if end:
        df = df.loc[df.index <= pd.Timestamp(end)]
    return df.dropna()


def load_universe(symbols: list[str], start: str, end: str | None = None) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            out[sym] = load_daily(sym, start, end)
        except Exception as exc:  # a single bad ticker should not kill the run
            print(f"[data] skipping {sym}: {exc}")
    return out
