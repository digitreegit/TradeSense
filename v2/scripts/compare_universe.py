"""Compare the live strategy with a momentum universe expanded by the
high-volatility names surfaced by the 2026-08 research (see grid_sim.py).

Variants share the same engine/decision code; only the universe (and the
single-name scaling list) changes.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config
from app.backtest import Backtester
from app.data import load_universe

VOL_NAMES = ["AMD", "PLTR", "COIN", "MSTR", "SMCI"]
LEV_ETFS = ["TQQQ", "SOXL"]

VARIANTS = {
    "base (현행)": ([], []),
    "+vol5": (VOL_NAMES, VOL_NAMES),
    "+vol5+lev": (VOL_NAMES + LEV_ETFS, VOL_NAMES + LEV_ETFS),
}

STARTS = ["2024-06-01", "2022-01-03", "2020-01-02", "2018-01-02"]


def main() -> None:
    capital = float(sys.argv[1]) if len(sys.argv) > 1 else 500.0
    all_syms = sorted(set(config.EQUITY_UNIVERSE + VOL_NAMES + LEV_ETFS))
    print(f"loading {len(all_syms)} symbols (capital ${capital:.0f}) ...")
    stocks = load_universe(all_syms, start="2016-01-01")

    # "base" is the pre-2026-08 universe (megacaps only), regardless of what
    # config currently ships, so this comparison stays reproducible.
    base_singles = list(config.MEGACAPS)
    base_momentum = [
        s for s in config.MOMENTUM_UNIVERSE if s not in VOL_NAMES + LEV_ETFS
    ]
    hdr = f"{'variant':<12} {'start':<11} {'CAGR':>8} {'maxDD':>8} {'sharpe':>7} {'trades':>7} {'win':>6} {'final':>9}"
    print(hdr); print("-" * len(hdr))
    for name, (extra_univ, extra_scaled) in VARIANTS.items():
        config.SINGLE_STOCKS = base_singles + extra_scaled
        momentum = base_momentum + extra_univ
        for start in STARTS:
            bt = Backtester(
                stocks, {}, initial_capital=capital,
                momentum_syms=momentum,
                defensive_syms=config.DEFENSIVE_UNIVERSE,
            )
            r = bt.run(start=start)
            m = r.metrics
            print(f"{name:<12} {start:<11} {m['cagr']:>8.1%} {m['max_drawdown']:>8.1%} "
                  f"{m['sharpe']:>7.2f} {m['trades']:>7} {m['win_rate']:>6.0%} {m['final']:>9.2f}")
        print()
    config.SINGLE_STOCKS = base_singles


if __name__ == "__main__":
    main()
