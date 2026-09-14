"""Replay the live Robinhood crypto advisor *including* the 15-minute risk
rules on daily bars for every coin in the advice universe. Never connects to
a broker.

The intraday risk loop is approximated with each day's bar:
  - hard / trailing stops are checked against the day's LOW (after the peak
    has ratcheted to the OPEN) and fill at the stop level;
  - staged profit tiers are checked against the day's HIGH;
  - the daily strategy then runs on completed bars with the CLOSE as the
    live quote, exactly like advise_and_apply(), and its orders fill at the
    next OPEN.
The 30-minute crash exit and the daily buy halt need real ticks and are not
modelled. Costs are charged per side (Robinhood spread ~0.5%).

    python scripts/replay_crypto_live.py --start 2024-03-01 --capital 8000
    python scripts/replay_crypto_live.py --variant legacy      # rules before 2026-09
    python scripts/replay_crypto_live.py --variant proposed    # current module defaults
    python scripts/replay_crypto_live.py --variant all         # side by side
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import crypto_advisor as adv  # noqa: E402
from app import crypto_risk as risk  # noqa: E402
from app.crypto_advisor import (  # noqa: E402
    _new_book, apply_order, generate_orders, sync_book_daily_risk,
)

CACHE = ROOT / "data" / "cache" / "crypto"

# Rule sets. "legacy" is what ran live until 2026-09; "proposed" is whatever
# the modules currently default to, so this script keeps measuring the code
# that will actually run.
VARIANTS: dict[str, dict] = {
    "legacy": {
        "risk": {
            "HARD_STOP_RANGE_MULT": 0.0, "TRAILING_RANGE_MULT": 0.0,
            "TRAILING_BASE": "tick", "PROFIT_TIERS": (0.10, 0.20, 0.30),
        },
        "adv": {"GRID_TAKE_PROFIT_ENABLED": True, "STOP_COOLDOWN_HOURS": 24.0,
                "BEAR_ALLOW_BUYS": True, "ENTRY_UNIVERSE": list(adv.CANDIDATES)},
    },
    "proposed": {"risk": {}, "adv": {}},
    "proposed_all12": {"risk": {}, "adv": {"ENTRY_UNIVERSE": list(adv.CANDIDATES)}},
    "no_live_risk": {  # daily trend logic only — what check_crypto_strategy measured
        "risk": {"HARD_STOP_PCT": 1.0, "TRAILING_STOP_PCT": 1.0,
                 "HARD_STOP_RANGE_MULT": 0.0, "TRAILING_RANGE_MULT": 0.0,
                 "PROFIT_TIERS": ()},
        "adv": {"GRID_TAKE_PROFIT_ENABLED": False, "BEAR_ALLOW_BUYS": True},
    },
}


@contextlib.contextmanager
def overrides(spec: dict):
    saved = []
    for mod, values in ((risk, spec.get("risk", {})), (adv, spec.get("adv", {}))):
        for key, value in values.items():
            saved.append((mod, key, getattr(mod, key)))
            setattr(mod, key, value)
    try:
        yield
    finally:
        for mod, key, value in reversed(saved):
            setattr(mod, key, value)


def load_frames(pairs: list[str], refresh: bool = False) -> dict[str, pd.DataFrame]:
    CACHE.mkdir(parents=True, exist_ok=True)
    out: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for pair in pairs:
        path = CACHE / (pair.replace("/", "-") + ".csv")
        if path.exists() and not refresh:
            out[pair] = pd.read_csv(path, index_col=0, parse_dates=True)
        else:
            missing.append(pair)
    if missing:
        with overrides({"adv": {"CANDIDATES": missing}}):
            fetched = adv.fetch_bars(days=1000)
        for pair, df in fetched.items():
            df.to_csv(CACHE / (pair.replace("/", "-") + ".csv"))
            out[pair] = df
    return out


def _qty(pos: dict) -> float:
    return sum(float(u.get("qty") or 0) for u in pos.get("units") or [])


def _sell_qty(order: dict, pos: dict) -> float:
    qty = _qty(pos)
    kind = order.get("kind")
    if order.get("sell_all") or kind in risk.FULL_EXIT_KINDS:
        return qty
    if kind == "take_profit":
        return float(pos["units"][-1]["qty"])
    signal_qty = float(order.get("dollars") or 0) / float(order.get("signal_price") or order["price"])
    return min(qty, signal_qty)


def run(frames: dict[str, pd.DataFrame], *, start: str, capital: float,
        cost_bps: float, stop_cooldown_days: int | None = None) -> dict:
    cost = cost_bps / 10000.0
    cooldown_days = (
        stop_cooldown_days if stop_cooldown_days is not None
        else max(1, int(round(adv.STOP_COOLDOWN_HOURS / 24)))
    )
    calendar = sorted(set().union(*(df.index for df in frames.values())))
    book = _new_book()
    book.update(cash=capital, budget=capital, principal=capital)
    pending: list[dict] = []
    trades: list[dict] = []
    curve: list[tuple[pd.Timestamp, float]] = []
    last_buy: dict[str, pd.Timestamp] = {}
    stopped: dict[str, pd.Timestamp] = {}
    open_lots: dict[str, float] = {}  # pair -> cost basis of open position (for trade P/L)
    exit_kinds: dict[str, int] = {}

    def record_sell(pair: str, amount: float, kind: str, day: pd.Timestamp, qty_sold: float, qty_before: float) -> None:
        basis = open_lots.get(pair, 0.0) * (qty_sold / qty_before if qty_before > 0 else 1.0)
        pnl = amount * (1 - cost) - basis
        trades.append({"day": str(day.date()), "pair": pair, "kind": kind,
                       "amount": round(amount, 2), "pnl": round(pnl, 2)})
        open_lots[pair] = max(0.0, open_lots.get(pair, 0.0) - basis)
        exit_kinds[kind] = exit_kinds.get(kind, 0) + 1

    start_ts = pd.Timestamp(start)
    for day in calendar:
        if day < start_ts:
            continue
        bars = {p: df.loc[day] for p, df in frames.items() if day in df.index}

        # 1) yesterday's signals fill at today's open (sells first)
        for order in sorted(pending, key=lambda o: o["side"] == "buy"):
            pair = order["pair"]
            if pair not in bars:
                continue
            px = float(bars[pair]["open"])
            filled = {**order, "signal_price": order["price"], "price": px}
            if order["side"] == "buy":
                amount = min(float(order["dollars"]), book["cash"] / (1 + cost))
                if amount < adv.MIN_UNIT:
                    continue
                apply_order(book, filled, amount)
                book["cash"] -= amount * cost
                open_lots[pair] = open_lots.get(pair, 0.0) + amount * (1 + cost)
                last_buy[pair] = day
                continue
            pos = book["positions"].get(pair)
            if not pos:
                continue
            qty_before = _qty(pos)
            sell_qty = _sell_qty(filled, pos)
            amount = sell_qty * px
            if amount <= 0:
                continue
            apply_order(book, filled, amount)
            book["cash"] -= amount * cost
            record_sell(pair, amount, order.get("kind") or "exit", day, sell_qty, qty_before)
            if order.get("kind") in risk.FULL_EXIT_KINDS:
                stopped[pair] = day

        # 2) intraday risk approximation on today's bar
        for pair in list(book["positions"]):
            pos = book["positions"][pair]
            bar = bars.get(pair)
            if bar is None:
                continue
            o, h, lo = float(bar["open"]), float(bar["high"]), float(bar["low"])
            pos["peak_price"] = max(float(pos.get("peak_price") or o), o)
            hit = risk.evaluate_position(pair, pos, lo)
            if hit and hit["kind"] in ("hard_stop", "trailing_stop"):
                levels = risk.risk_levels(pos)
                level = levels["hard_stop"] if hit["kind"] == "hard_stop" else levels["trailing_stop"]
                fill = min(o, max(lo, float(level or lo)))
                qty_before = _qty(pos)
                amount = qty_before * fill
                apply_order(book, {"pair": pair, "symbol": pair.split("/")[0], "side": "sell",
                                   "kind": hit["kind"], "price": fill}, amount)
                book["cash"] -= amount * cost
                record_sell(pair, amount, hit["kind"], day, qty_before, qty_before)
                stopped[pair] = day
                continue
            if risk.PROFIT_TIERS:
                hit = risk.evaluate_position(pair, pos, h)
                if hit and hit["kind"] == "profit_stage":
                    avg = float(pos.get("avg_cost") or 0)
                    fill = min(h, avg * (1 + float(hit["profit_tier"]))) if avg > 0 else h
                    qty_before = _qty(pos)
                    sell_qty = min(qty_before, float(hit["dollars"]) / h)
                    amount = sell_qty * fill
                    apply_order(book, {"pair": pair, "symbol": pair.split("/")[0], "side": "sell",
                                       "kind": "profit_stage", "price": fill,
                                       "profit_tier": hit["profit_tier"]}, amount)
                    book["cash"] -= amount * cost
                    record_sell(pair, amount, "profit_stage", day, sell_qty, qty_before)
            if pair in book["positions"]:
                book["positions"][pair]["peak_price"] = max(
                    float(book["positions"][pair].get("peak_price") or h), h)

        # 3) end of day: completed bars + close as the live quote
        history = {p: df.loc[df.index < day] for p, df in frames.items()}
        history = {p: df for p, df in history.items() if len(df) >= 60}
        live = {p: float(bars[p]["close"]) for p in bars}
        sync_book_daily_risk(book, history)
        equity = book["cash"] + sum(_qty(pos) * live.get(p, 0.0) for p, pos in book["positions"].items())
        curve.append((day, equity))
        orders, _, _ = generate_orders(history, book, live_prices=live, live_quote_fresh=True)
        pending = []
        for order in orders:
            pair = order["pair"]
            if order["side"] == "buy":
                if pair in last_buy and (day - last_buy[pair]).days < 1:
                    continue
                if pair in stopped and (day - stopped[pair]).days < cooldown_days:
                    continue
            pending.append(order)

    values = pd.Series({d: v for d, v in curve}, dtype=float)
    years = max((values.index[-1] - values.index[0]).days / 365.25, 1e-9)
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    return {
        "start": str(values.index[0].date()), "end": str(values.index[-1].date()),
        "capital": capital, "final": round(float(values.iloc[-1]), 2),
        "total_return": round(float(values.iloc[-1] / capital - 1), 4),
        "cagr": round(float((values.iloc[-1] / capital) ** (1 / years) - 1), 4),
        "max_drawdown": round(float((values / values.cummax() - 1).min()), 4),
        "sells": len(trades),
        "win_rate": round(len(wins) / len(pnls), 3) if pnls else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "exit_kinds": dict(sorted(exit_kinds.items())),
        "_curve": values,
        "_trades": trades,
    }


def benchmarks(frames: dict[str, pd.DataFrame], start: str, capital: float) -> dict:
    out = {}
    for pair in ("BTC/USD", "ETH/USD"):
        df = frames[pair].loc[pd.Timestamp(start):]
        out[pair + " hold"] = round(capital * float(df["close"].iloc[-1] / df["close"].iloc[0]), 2)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default="2024-03-01")
    p.add_argument("--capital", type=float, default=8000.0)
    p.add_argument("--cost-bps", type=float, default=50.0)
    p.add_argument("--variant", default="all", choices=["all", *VARIANTS])
    p.add_argument("--refresh", action="store_true", help="re-download bars")
    p.add_argument("--trades", action="store_true", help="print every sell")
    p.add_argument("--set", action="append", default=[], metavar="MOD.KEY=LITERAL",
                   help="extra override on top of the variant, e.g. risk.TRAILING_RANGE_MULT=1.5 "
                        "or adv.ENTRY_UNIVERSE=['BTC/USD']")
    args = p.parse_args()

    import ast
    extra: dict = {"risk": {}, "adv": {}}
    for item in args.set:
        target, _, literal = item.partition("=")
        mod, _, key = target.partition(".")
        extra[mod][key] = ast.literal_eval(literal)

    frames = load_frames(adv.CANDIDATES, refresh=args.refresh)
    names = list(VARIANTS) if args.variant == "all" else [args.variant]
    results = {}
    for name in names:
        spec = {
            "risk": {**VARIANTS[name].get("risk", {}), **extra["risk"]},
            "adv": {**VARIANTS[name].get("adv", {}), **extra["adv"]},
        }
        with overrides(spec):
            results[name] = run(frames, start=args.start, capital=args.capital, cost_bps=args.cost_bps)
        if args.trades:
            for t in results[name].pop("_trades", []):
                print(t)
    print(json.dumps({
        "benchmarks": benchmarks(frames, args.start, args.capital),
        "variants": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                     for k, v in results.items()},
    }, indent=2, ensure_ascii=False))
    for name, res in results.items():
        monthly = res["_curve"].resample("ME").last().pct_change().dropna()
        pos_months = float((monthly > 0).mean()) if len(monthly) else math.nan
        print(f"\n[{name}] positive months {pos_months:.0%} · median month "
              f"{monthly.median():+.1%} · worst month {monthly.min():+.1%}")


if __name__ == "__main__":
    main()
