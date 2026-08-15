"""RuleFive-style grid simulator: buy a unit when price falls `step` from the
last fill, sell a unit when it rises `step`. Long-only, per-symbol slots.

Fill model on daily bars (conservative):
- Triggers use the day's high/low; fills at the trigger price +/- slippage.
- Multiple buys (down to the low) or multiple sells (up to the high) may fill
  in one day, but never a buy-then-sell zigzag inside one bar, since the
  intraday path is unknowable. This *understates* what a 15-min live loop
  would harvest, which is the safe direction for a go/no-go decision.
- Optional 200SMA trend filter: below the SMA the grid liquidates and pauses.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache_grid"
SLIP = 0.0005  # 5 bps per side


def load(sym: str) -> pd.DataFrame:
    df = pd.read_csv(CACHE / f"{sym}.csv", index_col=0, parse_dates=True)
    df.columns = [c.lower() for c in df.columns]
    df["sma200"] = df["close"].rolling(200).mean()
    return df.dropna(subset=["close"])


@dataclass
class SymResult:
    equity: pd.Series
    trades: int


def run_symbol(df: pd.DataFrame, start: str, *, step: float, max_units: int,
               start_units: int, trend_filter: bool) -> SymResult:
    df = df.loc[df.index >= start]
    capital = 1.0                      # normalized slot
    unit_cash = capital / max_units
    cash = capital
    units: list[float] = []            # share counts per unit
    anchor = float(df["close"].iloc[0])
    trades = 0
    paused = False
    eq = []

    first = True
    for ts, row in df.iterrows():
        lo, hi, close = float(row["low"]), float(row["high"]), float(row["close"])
        below_trend = trend_filter and not np.isnan(row["sma200"]) and close < row["sma200"]

        if first:
            for _ in range(start_units):
                px = close * (1 + SLIP)
                qty = unit_cash / px
                units.append(qty); cash -= unit_cash
            anchor = close
            first = False
            eq.append((ts, cash + sum(units) * close))
            continue

        if below_trend:
            if units:                  # liquidate, pause the grid
                px = close * (1 - SLIP)
                cash += sum(units) * px
                trades += len(units)
                units = []
            anchor = close             # re-anchor while paused
            paused = True
            eq.append((ts, cash))
            continue
        if trend_filter and paused:    # trend regained: rebuild the base inventory
            for _ in range(start_units):
                if cash < unit_cash * 0.999:
                    break
                px = close * (1 + SLIP)
                units.append(unit_cash / px); cash -= unit_cash
                trades += 1
            anchor = close
            paused = False

        # sells first: rising day harvests from the existing inventory
        while units and hi >= anchor * (1 + step):
            px = anchor * (1 + step) * (1 - SLIP)
            cash += units.pop() * px
            anchor = anchor * (1 + step)
            trades += 1
        while len(units) < max_units and cash >= unit_cash * 0.999 and lo <= anchor * (1 - step):
            px = anchor * (1 - step) * (1 + SLIP)
            qty = unit_cash / px
            units.append(qty); cash -= unit_cash
            anchor = anchor * (1 - step)
            trades += 1

        eq.append((ts, cash + sum(units) * close))

    s = pd.Series(dict(eq)).sort_index()
    return SymResult(s, trades)


def metrics(eq: pd.Series) -> dict:
    rets = eq.pct_change().dropna()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0
    dd = (eq / eq.cummax() - 1).min()
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0.0
    return {"cagr": cagr, "maxdd": dd, "sharpe": sharpe, "final": eq.iloc[-1]}


def run_portfolio(syms: list[str], start: str, **kw) -> tuple[dict, int]:
    curves, trades = [], 0
    for s in syms:
        r = run_symbol(load(s), start, **kw)
        curves.append(r.equity); trades += r.trades
    eq = pd.concat(curves, axis=1).ffill().dropna().mean(axis=1)
    return metrics(eq), trades


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--syms", default="SOXL,SMCI,MSTR,AMD,COIN,TQQQ")
    p.add_argument("--start", default="2024-06-01")
    args = p.parse_args()
    syms = args.syms.split(",")

    print(f"universe: {syms}  start: {args.start}\n")
    hdr = f"{'step':>5} {'units':>5} {'trend':>6} | {'CAGR':>8} {'maxDD':>8} {'sharpe':>7} {'trades':>7}"
    print(hdr); print("-" * len(hdr))
    for step in (0.01, 0.02, 0.03, 0.05, 0.08):
        for max_units in (3, 5):
            for tf in (False, True):
                m, tr = run_portfolio(
                    syms, args.start, step=step, max_units=max_units,
                    start_units=max_units // 2 + 1, trend_filter=tf,
                )
                print(f"{step:>5.0%} {max_units:>5} {str(tf):>6} | "
                      f"{m['cagr']:>8.1%} {m['maxdd']:>8.1%} {m['sharpe']:>7.2f} {tr:>7}")

    # benchmarks
    for b in ("SPY", "QQQ"):
        df = load(b); df = df.loc[df.index >= args.start]
        eq = df["close"] / df["close"].iloc[0]
        m = metrics(eq)
        print(f"\n{b} buy&hold: CAGR {m['cagr']:.1%}  maxDD {m['maxdd']:.1%}  sharpe {m['sharpe']:.2f}")


if __name__ == "__main__":
    main()
