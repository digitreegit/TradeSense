"""Replay the v4 grid (app/grid.py, the exact live code path) on cached daily bars.

Conservative fill model: at most one action per symbol per day. A sell fills
at `sell_at` if the day's high reaches it, otherwise a buy fills at `buy_at`
if the low reaches it. The live loop runs every 15 minutes and can harvest
more than one rung on a volatile day, so these numbers understate live.

Usage:
  python scripts/grid_replay.py                       # both venues, default steps
  python scripts/grid_replay.py --venue crypto --start 2024-09-01 --steps 3,5,8
  python scripts/grid_replay.py --venue stocks --cash 500
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import grid  # noqa: E402

CACHE_DIRS = (ROOT / "data" / "cache_grid", ROOT / "data" / "cache", ROOT / "data" / "cache" / "crypto")
COST = {"stocks": 0.0005, "crypto": 0.005}  # per side, marketable-limit slippage + spread

VENUES = {
    "crypto": [s.replace("/USD", "-USD") for s in grid.CRYPTO_UNIVERSE],
    "stocks": list(grid.STOCK_UNIVERSE),
}


def load(sym: str) -> pd.DataFrame:
    for d in CACHE_DIRS:
        p = d / f"{sym}.csv"
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.columns = [c.lower() for c in df.columns]
            return df.dropna(subset=["close", "high", "low"])
    raise FileNotFoundError(f"no cached bars for {sym} (looked in {[str(d) for d in CACHE_DIRS]})")


def replay(frames: dict[str, pd.DataFrame], *, step: float, cash: float, cost: float) -> tuple[pd.Series, int]:
    """Run one ladder per symbol from a shared cash pool; return equity curve + trades."""
    idx = sorted(set.intersection(*[set(df.index) for df in frames.values()]))
    unit = grid.unit_size(cash, len(frames))
    ladders = {s: grid.new_ladder(s, "sim", unit) for s in frames}
    trades = 0
    eq = []
    for ts in idx:
        # Sells first so freed cash can fund the day's buys (same as the engine).
        for phase in ("sell", "buy"):
            for sym, ladder in ladders.items():
                row = frames[sym].loc[ts]
                hi, lo, close = float(row["high"]), float(row["low"]), float(row["close"])
                if not ladder["seeded"]:
                    if phase != "buy":
                        continue
                    a = grid.decide(ladder, close, step, cash)
                    if a:
                        px = close * (1 + cost)
                        grid.apply_fill(ladder, side="buy", qty=a["dollars"] / px, price=px,
                                        dollars=a["dollars"], n_units=a["n_units"])
                        cash -= a["dollars"]
                        trades += 1
                    continue
                lv = grid.levels(ladder, step)
                if phase == "sell" and lv["sell_at"] and hi >= lv["sell_at"]:
                    a = grid.decide(ladder, lv["sell_at"], step, cash)
                    if a and a["side"] == "sell":
                        px = lv["sell_at"] * (1 - cost)
                        grid.apply_fill(ladder, side="sell", qty=a["qty"], price=px, dollars=a["qty"] * px)
                        cash += a["qty"] * px
                        trades += 1
                elif phase == "buy" and lv["buy_at"] and lo <= lv["buy_at"]:
                    a = grid.decide(ladder, lv["buy_at"], step, cash)
                    if a and a["side"] == "buy":
                        px = lv["buy_at"] * (1 + cost)
                        grid.apply_fill(ladder, side="buy", qty=a["dollars"] / px, price=px, dollars=a["dollars"])
                        cash -= a["dollars"]
                        trades += 1
        for sym, ladder in ladders.items():
            grid.observe(ladder, float(frames[sym].loc[ts]["close"]))
        value = cash + sum(grid.held_qty(l) * float(frames[s].loc[ts]["close"]) for s, l in ladders.items())
        eq.append((ts, value))
    return pd.Series(dict(eq)).sort_index(), trades


def metrics(eq: pd.Series) -> dict:
    rets = eq.pct_change().dropna()
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    dd = (eq / eq.cummax() - 1).min()
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0.0
    monthly = eq.resample("ME").last().pct_change().dropna()
    return {"total": eq.iloc[-1] / eq.iloc[0] - 1, "cagr": cagr, "maxdd": dd, "sharpe": sharpe,
            "pos_months": (monthly > 0).mean() if len(monthly) else float("nan")}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--venue", choices=["crypto", "stocks", "both"], default="both")
    p.add_argument("--start", default="2024-06-01")
    p.add_argument("--steps", default="3,5,8,10", help="percent steps, comma separated")
    p.add_argument("--cash", type=float, default=None, help="starting cash (default 8000 crypto / 500 stocks)")
    p.add_argument("--anchor", choices=["follow", "classic"],
                   default="follow" if grid.FOLLOW_HIGH else "classic",
                   help="flat re-entry reference: follow the high, or wait at the last sale (RuleFive)")
    args = p.parse_args()
    grid.FOLLOW_HIGH = args.anchor == "follow"
    steps = [float(s) / 100 for s in args.steps.split(",")]
    venues = ["crypto", "stocks"] if args.venue == "both" else [args.venue]

    for venue in venues:
        syms = VENUES[venue]
        cash = args.cash or (8000.0 if venue == "crypto" else 500.0)
        frames = {}
        for s in syms:
            try:
                frames[s] = load(s).loc[args.start:]
            except FileNotFoundError as exc:
                print(f"  skip {s}: {exc}")
        if not frames:
            continue
        bh = np.mean([df["close"].iloc[-1] / df["close"].iloc[0] - 1 for df in frames.values()])
        print(f"\n== {venue}: {', '.join(frames)}  from {args.start}  cash ${cash:,.0f}  "
              f"cost {COST[venue]:.2%}/side")
        print(f"   equal-weight buy&hold: {bh:+.1%}")
        hdr = f"   {'step':>5} | {'total':>8} {'CAGR':>7} {'maxDD':>7} {'sharpe':>6} {'+months':>7} {'trades':>6} {'unit':>8}"
        print(hdr)
        print("   " + "-" * (len(hdr) - 3))
        for step in steps:
            eq, tr = replay(frames, step=step, cash=cash, cost=COST[venue])
            m = metrics(eq)
            unit = grid.unit_size(cash, len(frames))
            print(f"   {step:>5.0%} | {m['total']:>+8.1%} {m['cagr']:>+7.1%} {m['maxdd']:>7.1%} "
                  f"{m['sharpe']:>6.2f} {m['pos_months']:>7.0%} {tr:>6} ${unit:>7.2f}")


if __name__ == "__main__":
    main()
