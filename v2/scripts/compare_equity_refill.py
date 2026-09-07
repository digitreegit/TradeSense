"""Offline $500 comparison of weekly-only entries versus daily vacant slots.

Cached adjusted prices, fixed current universe (survivorship bias), 5 bps
per-side baseline cost. No broker or live account access.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config, backtest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--starts', nargs='+', default=['2018-01-01', '2022-01-01', '2024-01-01', '2026-01-01'])
    parser.add_argument('--cost-bps', type=float, default=5)
    args = parser.parse_args()
    if args.cost_bps < 0:
        parser.error('cost must be nonnegative')
    cache = config.DATA_DIR / 'cache'
    stocks = {sym: pd.read_csv(cache / f'{sym}.csv', index_col=0, parse_dates=True)
              for sym in config.EQUITY_UNIVERSE if (cache / f'{sym}.csv').exists()}
    missing = set(config.EQUITY_UNIVERSE) - set(stocks)
    if missing:
        raise RuntimeError(f'Missing cached data: {sorted(missing)}')
    backtest.EQUITY_SLIP = args.cost_bps / 10000
    for start in args.starts:
        for refill in (False, True):
            config.MOMENTUM_REFILL_ENABLED = refill
            result = backtest.Backtester(stocks, {}, 500,
                momentum_syms=config.MOMENTUM_UNIVERSE,
                defensive_syms=config.DEFENSIVE_UNIVERSE).run(start)
            curve = result.equity_curve
            if curve.empty:
                raise RuntimeError(f'No cached observations for {start}')
            spy = stocks['SPY']['close'].reindex(curve.index)
            benchmark = 500 * (1 - backtest.EQUITY_SLIP) * spy.iloc[-1] / spy.iloc[0] * (1 - backtest.EQUITY_SLIP)
            print(json.dumps({'refill': refill, 'cost_bps': args.cost_bps,
                              'spy_final': round(benchmark, 2), **result.metrics}), flush=True)


if __name__ == '__main__':
    main()
