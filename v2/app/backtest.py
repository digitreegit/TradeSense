"""Daily-bar backtester running the exact decision logic used live
(see decisions.decide).

Execution model: signals are computed on day t's close and executed at day
t+1's open (same as the live engine). Slippage: 5 bps per side on equities,
25 bps per side on crypto (Alpaca taker fee tier).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config, regime, strategy
from .decisions import PendingOrder, PosMeta, decide
from .risk import DrawdownBrake, position_dollars

EQUITY_SLIP = 0.0005
CRYPTO_SLIP = 0.0025


@dataclass
class Position:
    symbol: str
    sleeve: str
    qty: float
    entry_price: float
    entry_date: pd.Timestamp
    stop: strategy.TrailingStop | None = None
    stop_mult: float = 0.0
    held_days: int = 0


@dataclass
class Trade:
    symbol: str
    sleeve: str
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    reason: str


@dataclass
class Result:
    equity_curve: pd.Series
    trades: list[Trade]
    metrics: dict = field(default_factory=dict)


def _slip(symbol: str) -> float:
    return CRYPTO_SLIP if "/" in symbol or symbol.endswith("-USD") else EQUITY_SLIP


class Backtester:
    def __init__(
        self,
        stock_data: dict[str, pd.DataFrame],
        crypto_data: dict[str, pd.DataFrame],
        initial_capital: float = 3000.0,
    ):
        self.features: dict[str, pd.DataFrame] = {
            s: strategy.compute_features(df) for s, df in {**stock_data, **crypto_data}.items()
        }
        self.stock_syms = list(stock_data)
        self.crypto_syms = list(crypto_data)
        self.initial_capital = initial_capital
        # trade on the equity calendar (SPY); crypto rows are aligned forward
        self.calendar = self.features[config.REGIME_SYMBOL].index

    # -- helpers ------------------------------------------------------------
    def _row(self, symbol: str, ts: pd.Timestamp) -> pd.Series | None:
        df = self.features[symbol]
        idx = df.index.searchsorted(ts, side="right") - 1
        if idx < 0:
            return None
        row = df.iloc[idx]
        # stale guard: don't act on data more than 5 days old
        if (ts - df.index[idx]).days > 5:
            return None
        return row

    def _open_price(self, symbol: str, ts: pd.Timestamp) -> float | None:
        df = self.features[symbol]
        if ts in df.index:
            return float(df.loc[ts, "open"])
        row = self._row(symbol, ts)
        return float(row["close"]) if row is not None else None

    # -- main loop ----------------------------------------------------------
    def run(self, start: str | None = None) -> Result:
        cash = self.initial_capital
        positions: dict[str, Position] = {}
        pending: list[PendingOrder] = []
        trades: list[Trade] = []
        brake = DrawdownBrake(peak_equity=self.initial_capital)
        equity_hist: dict[pd.Timestamp, float] = {}

        cal = self.calendar
        warmup = 210
        start_ts = pd.Timestamp(start) if start else None

        for i in range(warmup, len(cal) - 1):
            today = cal[i]
            if start_ts is not None and today < start_ts:
                continue

            # 1) execute yesterday's decisions at today's open ---------------
            equity_now = equity_hist.get(cal[i - 1], self.initial_capital)
            for order in pending:
                px = self._open_price(order.symbol, today)
                if px is None:
                    continue
                if order.side == "sell" and order.symbol in positions:
                    pos = positions.pop(order.symbol)
                    fill = px * (1 - _slip(order.symbol))
                    cash += pos.qty * fill
                    trades.append(Trade(
                        symbol=pos.symbol, sleeve=pos.sleeve,
                        entry_date=pos.entry_date, exit_date=today,
                        entry_price=pos.entry_price, exit_price=fill,
                        qty=pos.qty, pnl=(fill - pos.entry_price) * pos.qty,
                        reason=order.reason,
                    ))
                elif order.side == "buy" and order.symbol not in positions:
                    row = self._row(order.symbol, today)
                    if row is None or pd.isna(row["atr"]):
                        continue
                    dollars = position_dollars(
                        equity=equity_now,
                        slot_weight=order.slot_weight,
                        price=px,
                        atr_value=float(row["atr"]),
                        stop_mult=order.stop_mult,
                        exposure=1.0,  # exposure baked into slot_weight at decision time
                        dd_scale=brake.scale(equity_now),
                    )
                    dollars = min(dollars, cash)
                    if dollars < config.MIN_ORDER_NOTIONAL:
                        continue
                    fill = px * (1 + _slip(order.symbol))
                    qty = dollars / fill
                    cash -= dollars
                    stop = strategy.TrailingStop.initial(fill, float(row["atr"]), order.stop_mult)
                    positions[order.symbol] = Position(
                        symbol=order.symbol, sleeve=order.sleeve, qty=qty,
                        entry_price=fill, entry_date=today,
                        stop=stop, stop_mult=order.stop_mult,
                    )
            pending = []

            # 2) mark to market at close, update stops / brake ---------------
            equity = cash
            for pos in positions.values():
                row = self._row(pos.symbol, today)
                if row is None:
                    equity += pos.qty * pos.entry_price
                    continue
                close = float(row["close"])
                equity += pos.qty * close
                pos.held_days += 1
                if pos.stop is not None and not pd.isna(row["atr"]):
                    pos.stop.update(close, float(row["atr"]), pos.stop_mult)
            equity_hist[today] = equity
            brake.update(equity)

            # 3) decide at close -> pending orders for tomorrow's open -------
            if brake.halted:
                for sym in positions:
                    pending.append(PendingOrder(sym, positions[sym].sleeve, "sell", reason="dd-halt"))
                continue

            spy_hist = self.features[config.REGIME_SYMBOL].iloc[: i + 1]
            reg = regime.classify(spy_hist)

            rows: dict[str, pd.Series] = {}
            for sym in self.stock_syms + self.crypto_syms:
                row = self._row(sym, today)
                if row is not None:
                    rows[sym] = row

            metas = {
                sym: PosMeta(
                    symbol=sym, sleeve=pos.sleeve, held_days=pos.held_days,
                    stop_level=pos.stop.level if pos.stop else None,
                )
                for sym, pos in positions.items()
            }
            week_rollover = cal[i + 1].weekday() < today.weekday()
            pending = decide(
                rows=rows, positions=metas,
                stock_syms=self.stock_syms, crypto_syms=self.crypto_syms,
                reg=reg, week_rollover=week_rollover,
            )

        curve = pd.Series(equity_hist).sort_index()
        return Result(equity_curve=curve, trades=trades, metrics=compute_metrics(curve, trades))


def compute_metrics(curve: pd.Series, trades: list[Trade]) -> dict:
    if curve.empty:
        return {}
    rets = curve.pct_change().dropna()
    years = max((curve.index[-1] - curve.index[0]).days / 365.25, 1e-9)
    cagr = (curve.iloc[-1] / curve.iloc[0]) ** (1 / years) - 1
    dd = (curve / curve.cummax() - 1).min()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0
    wins = [t for t in trades if t.pnl > 0]
    return {
        "start": str(curve.index[0].date()),
        "end": str(curve.index[-1].date()),
        "initial": round(float(curve.iloc[0]), 2),
        "final": round(float(curve.iloc[-1]), 2),
        "cagr": round(float(cagr), 4),
        "max_drawdown": round(float(dd), 4),
        "sharpe": round(sharpe, 2),
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3) if trades else 0.0,
        "avg_pnl": round(float(np.mean([t.pnl for t in trades])), 2) if trades else 0.0,
    }
