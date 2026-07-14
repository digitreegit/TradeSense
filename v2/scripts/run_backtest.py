"""Run the TradeSense v2 backtest over ~10 years of daily data.

Usage:
    python scripts/run_backtest.py [--start 2016-01-01] [--capital 3000]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.backtest import Backtester, compute_metrics  # noqa: E402
from app.data import load_universe  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2016-01-01")
    p.add_argument("--trade-start", default=None, help="first trade date (after warmup)")
    p.add_argument("--capital", type=float, default=3000.0)
    args = p.parse_args()

    print(f"loading data from {args.start} ...")
    stocks = load_universe(config.EQUITY_UNIVERSE, start=args.start)
    crypto = load_universe(config.CRYPTO_UNIVERSE, start=args.start)
    print(f"loaded {len(stocks)} stock symbols, {len(crypto)} crypto symbols")

    bt = Backtester(stocks, crypto, initial_capital=args.capital)
    result = bt.run(start=args.trade_start)

    print("\n=== TradeSense v2 backtest ===")
    for k, v in result.metrics.items():
        print(f"  {k:>14}: {v}")

    # benchmark: SPY buy & hold over the same window
    spy = stocks["SPY"]["close"]
    spy = spy.loc[result.equity_curve.index[0]: result.equity_curve.index[-1]]
    bench = spy / spy.iloc[0] * result.equity_curve.iloc[0]
    bm = compute_metrics(bench, [])
    print("\n=== SPY buy & hold (benchmark) ===")
    for k in ("cagr", "max_drawdown", "sharpe", "final"):
        print(f"  {k:>14}: {bm[k]}")

    # sleeve breakdown
    from collections import defaultdict
    pnl_by, cnt_by = defaultdict(float), defaultdict(int)
    for t in result.trades:
        pnl_by[t.sleeve] += t.pnl
        cnt_by[t.sleeve] += 1
    print("\n=== per-sleeve ===")
    for sleeve in sorted(pnl_by):
        print(f"  {sleeve:>10}: trades={cnt_by[sleeve]:>4}  pnl=${pnl_by[sleeve]:,.0f}")

    out = config.DATA_DIR / "backtest_equity.csv"
    result.equity_curve.rename("equity").to_csv(out)
    print(f"\nequity curve -> {out}")


if __name__ == "__main__":
    main()
