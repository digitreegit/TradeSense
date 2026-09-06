"""Offline daily execution smoke backtest. Never connects to a broker.

Uses cached BTC/ETH data and yesterday's completed signal with next-open
fills. This is NOT a replay of 15-minute live risk checks or actual account
performance. Reports realized SELL-fill win rate, including partial sells.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.crypto_advisor import apply_order, generate_orders, _new_book


def run(frames, start, capital, cost_bps):
    calendar = frames['BTC/USD'].index.intersection(frames['ETH/USD'].index)
    book = _new_book()
    book.update(cash=capital, budget=capital)
    pending = []
    curve, outcomes = [], []
    cost = cost_bps / 10000
    for day in calendar:
        if day < pd.Timestamp(start):
            continue
        for order in sorted(pending, key=lambda x: x['side'] == 'buy'):
            pair = order['pair']
            price = float(frames[pair].loc[day, 'open'])
            order = {**order, 'price': price}
            if order['side'] == 'buy':
                amount = min(order['dollars'], book['cash'] / (1 + cost))
                if amount < 25:
                    continue
            else:
                pos = book['positions'].get(pair)
                if not pos:
                    continue
                qty = sum(u['qty'] for u in pos['units'])
                if order['kind'] == 'take_profit':
                    sell_qty = pos['units'][-1]['qty']
                elif order['kind'] in ('trim', 'profit_stage'):
                    sell_qty = min(qty, order['signal_qty'])
                else:
                    sell_qty = qty
                amount = sell_qty * price
            realized = book['realized_pl']
            apply_order(book, order, amount)
            book['cash'] -= amount * cost
            if order['side'] == 'sell':
                # Includes estimated entry cost as well as exit cost.
                gross_pnl = book['realized_pl'] - realized
                outcomes.append(gross_pnl - (2 * amount - gross_pnl) * cost)
        prices = {s: float(df.loc[day, 'close']) for s, df in frames.items()}
        curve.append(book['cash'] + sum(sum(u['qty'] for u in p['units']) * prices[s]
                                       for s, p in book['positions'].items()))
        history = {s: df.loc[:day] for s, df in frames.items()}
        pending, _, _ = generate_orders(history, book)
        for order in pending:
            order['signal_qty'] = order['dollars'] / order['price']
    if not curve:
        raise ValueError('No cached observations on or after start date')
    values = pd.Series(curve, dtype=float)
    return dict(start=start, end=str(calendar[-1].date()), capital=capital,
                cost_bps_per_side=cost_bps, final=round(values.iloc[-1], 2),
                max_drawdown=round(float((values / values.cummax() - 1).min()), 4),
                sell_fills=len(outcomes),
                sell_fill_win_rate=round(sum(x > 0 for x in outcomes) / len(outcomes), 4) if outcomes else None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2024-01-01')
    parser.add_argument('--capital', type=float, default=1000)
    parser.add_argument('--cost-bps', type=float, default=50)
    parser.add_argument('--hold-trend', action='store_true', help='research: disable unit grid profit-taking')
    args = parser.parse_args()
    if args.hold_trend:
        from app import crypto_advisor
        crypto_advisor.GRID_TAKE_PROFIT_ENABLED = False
    if args.capital <= 0 or args.cost_bps < 0:
        parser.error('capital must be positive and costs nonnegative')
    cache = Path(__file__).resolve().parents[1] / 'data' / 'cache'
    frames = {s + '/USD': pd.read_csv(cache / (s + '-USD.csv'), index_col=0, parse_dates=True)
              for s in ('BTC', 'ETH')}
    result = run(frames, args.start, args.capital, args.cost_bps)
    result['policy'] = 'hold_trend_research' if args.hold_trend else 'grid_profit'
    print(json.dumps(result, indent=2))
