"""Replay the v5 dip rule (app/dip.py semantics) and its candidate fixes on
real bars, side by side with buy-and-hold, so parameter choices are evidence.

Crypto: hourly bars from Alpaca's free crypto feed (no key), cached under
data/cache_dip/. Stocks: daily bars from data/cache_grid (refreshed with
yfinance when stale). Nothing here touches the live engine or any broker.

Fill model (conservative, mirrors the engine):
  * one tick per bar; the 24h/20d high is the rolling max of CLOSES, like the
    engine's sampled mids (bar highs would be more aggressive);
  * buys are marketable at close*(1+cost); the +dip sell is a resting limit
    that fills when the bar's high touches it, at the limit price;
  * one open lot per symbol, at most 3 new lots per tick, cash-guarded.

Usage:
  python scripts/dip_replay.py crypto                       # 180d, dips 3/5/8/10, all variants
  python scripts/dip_replay.py crypto --dips 5 --variants base,regime7,breadth
  python scripts/dip_replay.py stocks --universe etf        # daily bars, 20d lookback
  python scripts/dip_replay.py stocks --universe current --grid   # also v4 grid steps
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

CACHE_DIP = ROOT / "data" / "cache_dip"
CACHE_GRID = ROOT / "data" / "cache_grid"

# Coins Alpaca serves bars for that overlap Robinhood's API-tradable set.
CRYPTO_UNIVERSE = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD", "LINK/USD", "AVAX/USD",
    "LTC/USD", "BCH/USD", "UNI/USD", "AAVE/USD", "DOT/USD", "SHIB/USD", "PEPE/USD",
    "CRV/USD", "SUSHI/USD", "GRT/USD", "MKR/USD", "XTZ/USD", "YFI/USD", "BAT/USD", "TRUMP/USD",
]
STOCK_UNIVERSES = {
    "current": ["AMD", "COIN", "MSTR", "SMCI", "PLTR", "TSLA"],
    "etf": ["TQQQ", "SOXL", "SPY", "QQQ", "IWM", "ARKK", "XBI"],
    "large": ["AAPL", "AMZN", "AVGO", "GOOGL", "META", "MSFT", "NVDA", "NFLX", "TSLA", "AMD"],
}
STOCK_UNIVERSES["all"] = sorted({s for v in STOCK_UNIVERSES.values() for s in v})

COST = {"crypto": 0.005, "stocks": 0.0005}  # taker side: spread + slippage


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def load_crypto_hourly(symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
    CACHE_DIP.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    frames: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    for s in symbols:
        p = CACHE_DIP / f"{s.replace('/', '-')}-1H.csv"
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            if len(df) and df.index[0] <= start + timedelta(hours=2) and df.index[-1] >= now - timedelta(hours=3):
                frames[s] = df.loc[start:]
                continue
        missing.append(s)
    if missing:
        try:
            from alpaca.data.historical import CryptoHistoricalDataClient
            from alpaca.data.requests import CryptoBarsRequest
            from alpaca.data.timeframe import TimeFrame
            client = CryptoHistoricalDataClient()
            req = CryptoBarsRequest(symbol_or_symbols=missing, timeframe=TimeFrame.Hour,
                                    start=start - timedelta(hours=2))
            data = client.get_crypto_bars(req).data
        except Exception as exc:  # noqa: BLE001
            print(f"  ! alpaca crypto bars failed: {exc}", file=sys.stderr)
            data = {}
        for s in missing:
            bars = data.get(s) if isinstance(data, dict) else None
            if not bars:
                print(f"  skip {s}: no bars", file=sys.stderr)
                continue
            df = pd.DataFrame({
                "open": [b.open for b in bars], "high": [b.high for b in bars],
                "low": [b.low for b in bars], "close": [b.close for b in bars],
                "volume": [b.volume for b in bars],
            }, index=pd.to_datetime([b.timestamp for b in bars], utc=True))
            df = df[~df.index.duplicated()].sort_index()
            df.to_csv(CACHE_DIP / f"{s.replace('/', '-')}-1H.csv")
            frames[s] = df.loc[start:]
    return frames


def load_stock_daily(symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    start = pd.Timestamp.now(tz=None).normalize() - pd.Timedelta(days=days)
    for s in symbols:
        p = CACHE_GRID / f"{s}.csv"
        df = None
        if p.exists():
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df.columns = [c.lower() for c in df.columns]
            df = df.dropna(subset=["close"])
        stale = df is None or df.empty or (pd.Timestamp.now() - df.index[-1]).days > 4
        if stale:
            try:
                import yfinance as yf
                since = (df.index[-1] + pd.Timedelta(days=1)).date() if df is not None and len(df) else "2016-01-01"
                new = yf.download(s, start=str(since), auto_adjust=True, progress=False)
                if isinstance(new.columns, pd.MultiIndex):
                    new.columns = [c[0] for c in new.columns]
                new.columns = [str(c).lower() for c in new.columns]
                new = new[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
                df = pd.concat([df, new]) if df is not None else new
                df = df[~df.index.duplicated(keep="last")].sort_index()
                CACHE_GRID.mkdir(parents=True, exist_ok=True)
                df.rename(columns=str.capitalize).to_csv(p, index_label="Date")
            except Exception as exc:  # noqa: BLE001
                print(f"  ! refresh {s} failed ({exc}); using cache", file=sys.stderr)
        if df is None or df.empty:
            print(f"  skip {s}: no bars", file=sys.stderr)
            continue
        frames[s] = df.loc[start:]
    return frames


# --------------------------------------------------------------------------
# Simulator
# --------------------------------------------------------------------------
@dataclass
class Params:
    dip: float = 0.05
    dollars: float = 1000.0
    cash: float = 8500.0
    cost: float = 0.005
    lookback: int = 24          # bars in the "24h" window (24 hourly / 20 daily)
    max_buys_per_tick: int = 3
    regime_sma: int | None = None       # bars; buy only when proxy close > its SMA
    regime_symbol: str | None = None    # defaults to the first symbol (BTC / SPY)
    breadth_max: float | None = None    # skip buys when > this share of universe is armed
    bounce: float | None = None         # require close >= window low * (1 + bounce)
    cap_frac: float | None = None       # deployed dollars <= cap_frac * equity
    underwater: str = "hold"            # hold | stop | avg | time
    stop_pct: float = 0.15
    avg_pct: float = 0.10
    time_bars: int = 24 * 14
    label: str = "base"


@dataclass
class Result:
    label: str
    dip: float
    equity: pd.Series
    closed: list[dict] = field(default_factory=list)
    open_lots: dict = field(default_factory=dict)
    deployed_frac: float = 0.0
    buys: int = 0


def simulate(frames: dict[str, pd.DataFrame], p: Params) -> Result:
    syms = list(frames)
    closes = pd.DataFrame({s: frames[s]["close"] for s in syms}).sort_index()
    highs = pd.DataFrame({s: frames[s]["high"] for s in syms}).reindex(closes.index)
    closes = closes.ffill().dropna(how="all")
    highs = highs.ffill()
    roll_hi = closes.rolling(p.lookback, min_periods=2).max()
    roll_lo = closes.rolling(p.lookback, min_periods=2).min()
    proxy = p.regime_symbol or syms[0]
    sma = closes[proxy].rolling(p.regime_sma).mean() if p.regime_sma else None

    cash = p.cash
    lots: dict[str, dict] = {}
    closed: list[dict] = []
    eq = []
    deployed_hist = []
    buys = 0
    C = closes.to_numpy()
    H = highs.to_numpy()
    RH = roll_hi.to_numpy()
    RL = roll_lo.to_numpy()
    idx = closes.index
    for i in range(len(idx)):
        # 1) resting sells / underwater handling
        for j, s in enumerate(syms):
            lot = lots.get(s)
            if not lot:
                continue
            c, h = C[i, j], H[i, j]
            if np.isnan(c):
                continue
            # A resting sell fills when the BID reaches the limit; bar highs are
            # trade prices, so demand the high clear the limit by the spread.
            if h >= lot["target"] * (1 + p.cost):
                px = lot["target"]
                cash += lot["qty"] * px
                closed.append({"symbol": s, "pnl": lot["qty"] * px - lot["dollars"],
                               "bars": i - lot["i"], "at": idx[i], "how": "target"})
                del lots[s]
                continue
            if p.underwater == "stop" and c <= lot["price"] * (1 - p.stop_pct):
                px = c * (1 - p.cost)
                cash += lot["qty"] * px
                closed.append({"symbol": s, "pnl": lot["qty"] * px - lot["dollars"],
                               "bars": i - lot["i"], "at": idx[i], "how": "stop"})
                del lots[s]
            elif p.underwater == "reanchor" and c <= lot["ref"] * (1 - p.stop_pct):
                # Keep the coins, give up on the old target: measure the next
                # +dip from here. No round-trip cost, loss stays unrealized.
                lot["ref"] = c
                lot["target"] = c * (1 + p.dip)
                lot["reanchors"] = lot.get("reanchors", 0) + 1
            elif p.underwater == "time" and i - lot["i"] >= p.time_bars:
                px = c * (1 - p.cost)
                cash += lot["qty"] * px
                closed.append({"symbol": s, "pnl": lot["qty"] * px - lot["dollars"],
                               "bars": i - lot["i"], "at": idx[i], "how": "time"})
                del lots[s]
            elif (p.underwater == "avg" and not lot.get("averaged")
                  and c <= lot["price"] * (1 - p.avg_pct) and cash >= p.dollars * 1.005):
                px = c * (1 + p.cost)
                q = p.dollars / px
                lot["qty"] += q
                lot["dollars"] += p.dollars
                lot["price"] = lot["dollars"] / lot["qty"]
                lot["ref"] = lot["price"]
                lot["target"] = lot["price"] * (1 + p.dip)
                lot["averaged"] = True
                cash -= p.dollars
                buys += 1
        # 2) new lots
        if i >= 2:
            allow = True
            if sma is not None:
                v = sma.iloc[i]
                allow = not np.isnan(v) and C[i, syms.index(proxy)] > v
            cands = []
            armed_n = 0
            for j, s in enumerate(syms):
                c, hi = C[i, j], RH[i, j]
                if np.isnan(c) or np.isnan(hi) or hi <= 0:
                    continue
                chg = c / hi - 1
                if chg <= -p.dip:
                    armed_n += 1
                    if s in lots:
                        continue
                    if p.bounce is not None and not (c >= RL[i, j] * (1 + p.bounce)):
                        continue
                    cands.append((chg, s, c))
            if p.breadth_max is not None and syms and armed_n / len(syms) > p.breadth_max:
                allow = False
            if allow:
                cands.sort()
                n = 0
                for chg, s, c in cands:
                    if n >= p.max_buys_per_tick or cash < p.dollars * 1.005:
                        break
                    if p.cap_frac is not None:
                        deployed = sum(l["dollars"] for l in lots.values())
                        equity = cash + sum(l["qty"] * C[i, syms.index(k)] for k, l in lots.items())
                        if deployed + p.dollars > p.cap_frac * equity:
                            break
                    px = c * (1 + p.cost)
                    lots[s] = {"qty": p.dollars / px, "price": px, "ref": px, "dollars": p.dollars,
                               "target": px * (1 + p.dip), "i": i, "at": idx[i]}
                    cash -= p.dollars
                    buys += 1
                    n += 1
        value = cash + sum(l["qty"] * C[i, syms.index(k)] for k, l in lots.items())
        eq.append(value)
        deployed_hist.append(1 - cash / value if value > 0 else 0)
    last = {s: C[-1, syms.index(s)] for s in syms}
    open_lots = {s: {**l, "unreal": l["qty"] * last[s] - l["dollars"],
                     "pct": last[s] / l["price"] - 1} for s, l in lots.items()}
    return Result(p.label, p.dip, pd.Series(eq, index=idx), closed, open_lots,
                  float(np.mean(deployed_hist)) if deployed_hist else 0.0, buys)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def maxdd(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0


def segments(eq: pd.Series, n: int = 3) -> list[float]:
    cuts = np.linspace(0, len(eq) - 1, n + 1).astype(int)
    out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        out.append(eq.iloc[b] / eq.iloc[a] - 1 if eq.iloc[a] else float("nan"))
    return out


def summarize(r: Result, cash0: float) -> dict:
    realized = sum(c["pnl"] for c in r.closed)
    unreal = sum(l["unreal"] for l in r.open_lots.values())
    wins = sum(1 for c in r.closed if c["pnl"] > 0)
    top2 = sorted((c["pnl"] for c in r.closed), reverse=True)[:2]
    luck = sum(top2) / realized if realized > 0 and top2 else float("nan")
    worst = min((l["pct"] for l in r.open_lots.values()), default=float("nan"))
    segs = segments(r.equity)
    return {
        "label": r.label, "dip": r.dip,
        "total": r.equity.iloc[-1] / cash0 - 1, "maxdd": maxdd(r.equity),
        "buys": r.buys, "closed": len(r.closed), "win": wins / len(r.closed) if r.closed else float("nan"),
        "hold_h": float(np.mean([c["bars"] for c in r.closed])) if r.closed else float("nan"),
        "realized": realized, "unreal": unreal, "open": len(r.open_lots), "worst_open": worst,
        "deployed": r.deployed_frac, "luck": luck, "segs": segs,
    }


def fmt_pct(x: float, w: int = 7) -> str:
    return f"{x:>+{w}.1%}" if x == x else f"{'—':>{w}}"


def print_table(rows: list[dict], bars_per_day: float) -> None:
    hdr = (f"   {'variant':<12} {'dip':>4} | {'total':>7} {'maxDD':>7} {'buys':>4} {'closed':>6} {'win':>5} "
           f"{'hold':>6} {'realized':>9} {'unreal':>9} {'open':>4} {'worst':>7} {'deploy':>6} {'luck':>5} | "
           f"{'seg1':>7} {'seg2':>7} {'seg3':>7}")
    print(hdr)
    print("   " + "-" * (len(hdr) - 3))
    for m in rows:
        hold = f"{m['hold_h'] / bars_per_day:>5.1f}d" if m["hold_h"] == m["hold_h"] else "     —"
        luck = f"{m['luck']:>5.0%}" if m["luck"] == m["luck"] else "    —"
        print(f"   {m['label']:<12} {m['dip']:>4.0%} | {fmt_pct(m['total'])} {fmt_pct(m['maxdd'])} "
              f"{m['buys']:>4} {m['closed']:>6} {fmt_pct(m['win'], 5) if m['win'] == m['win'] else '    —'} "
              f"{hold} {m['realized']:>+9.0f} {m['unreal']:>+9.0f} {m['open']:>4} {fmt_pct(m['worst_open'])} "
              f"{m['deployed']:>6.0%} {luck} | " + " ".join(fmt_pct(s) for s in m["segs"]))


VARIANTS = {
    "base": {},
    "regime7": {"regime_sma": 7},      # multiplied by bars/day below
    "regime30": {"regime_sma": 30},
    "breadth": {"breadth_max": 0.5},
    "bounce": {"bounce": 0.01},
    "cap50": {"cap_frac": 0.5},
    "avg": {"underwater": "avg"},
    "stop15": {"underwater": "stop", "stop_pct": 0.15},
    "time14": {"underwater": "time", "time_bars": 14},  # days, scaled below
    "time7": {"underwater": "time", "time_bars": 7},
    "time21": {"underwater": "time", "time_bars": 21},
    "stop10": {"underwater": "stop", "stop_pct": 0.10},
    "reanchor10": {"underwater": "reanchor", "stop_pct": 0.10},
    "reanchor15": {"underwater": "reanchor", "stop_pct": 0.15},
    "time14cap70": {"underwater": "time", "time_bars": 14, "cap_frac": 0.7},
    "time14reg7": {"underwater": "time", "time_bars": 14, "regime_sma": 7},
    "combo": {"regime_sma": 7, "bounce": 0.01, "cap_frac": 0.5},
}


def build_params(name: str, *, dip: float, dollars: float, cash: float, cost: float,
                 lookback: int, bars_per_day: int, proxy: str) -> Params:
    kw = dict(VARIANTS[name])
    if kw.get("regime_sma"):
        kw["regime_sma"] = int(kw["regime_sma"] * bars_per_day)
    if kw.get("time_bars"):
        kw["time_bars"] = int(kw["time_bars"] * bars_per_day)
    return Params(dip=dip, dollars=dollars, cash=cash, cost=cost, lookback=lookback,
                  regime_symbol=proxy, label=name, **kw)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("venue", choices=["crypto", "stocks"])
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--dips", default="3,5,8,10")
    ap.add_argument("--dollars", type=float, default=None, help="per-lot dollars (crypto 1000 / stocks cash/5)")
    ap.add_argument("--cash", type=float, default=None, help="starting cash (crypto 8500 / stocks 1050)")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--universe", default="current", help=f"stocks: {', '.join(STOCK_UNIVERSES)}")
    ap.add_argument("--symbols", default=None, help="override universe, comma separated")
    ap.add_argument("--grid", action="store_true", help="stocks: also replay the v4 grid (scripts/grid_replay.py)")
    args = ap.parse_args()

    dips = [float(x) / 100 for x in args.dips.split(",")]
    variants = [v for v in args.variants.split(",") if v in VARIANTS]
    if args.venue == "crypto":
        syms = args.symbols.split(",") if args.symbols else CRYPTO_UNIVERSE
        frames = load_crypto_hourly(syms, args.days)
        cash = args.cash or 8500.0
        dollars = args.dollars or 1000.0
        lookback, bars_per_day, proxy, cost = 24, 24, "BTC/USD", COST["crypto"]
    else:
        syms = args.symbols.split(",") if args.symbols else STOCK_UNIVERSES[args.universe]
        frames = load_stock_daily(syms, args.days)
        cash = args.cash or 1050.0
        dollars = args.dollars or round(cash / 5, 0)
        lookback, bars_per_day, cost = 20, 1, COST["stocks"]
        proxy = "SPY" if "SPY" in frames else next(iter(frames), None)
    if not frames:
        print("no data")
        return
    if proxy not in frames and args.venue == "crypto":
        proxy = next(iter(frames))

    closes = pd.DataFrame({s: f["close"] for s, f in frames.items()}).ffill().dropna(how="all")
    first, last = closes.index[0], closes.index[-1]
    bh = {s: closes[s].dropna().iloc[-1] / closes[s].dropna().iloc[0] - 1 for s in closes}
    ew = float(np.mean(list(bh.values())))
    print(f"\n== {args.venue}: {len(frames)} symbols, {first:%Y-%m-%d} → {last:%Y-%m-%d %H:%M}, "
          f"cash ${cash:,.0f}, lot ${dollars:,.0f}, taker cost {cost:.2%}")
    bench = [f"{s.split('/')[0]} {bh[s]:+.1%}" for s in list(closes)[:3] if s in bh]
    print(f"   buy&hold: equal-weight {ew:+.1%} · " + " · ".join(bench))
    if args.venue == "crypto":
        print(f"   segments = thirds of the window; 'luck' = share of realized P/L from the best 2 trades")

    rows = []
    for name in variants:
        for dip in dips:
            p = build_params(name, dip=dip, dollars=dollars, cash=cash, cost=cost,
                             lookback=lookback, bars_per_day=bars_per_day, proxy=proxy)
            r = simulate(frames, p)
            rows.append(summarize(r, cash))
    print_table(rows, bars_per_day)

    if args.venue == "stocks" and args.grid:
        import grid_replay  # noqa: PLC0415
        from app import grid  # noqa: PLC0415
        gframes = {s: f.rename(columns=str.lower) for s, f in frames.items()}
        print(f"\n   v4 grid on the same bars (cash ${cash:,.0f}, {len(gframes)} ladders):")
        for step in (0.03, 0.05, 0.08):
            eq, tr = grid_replay.replay(gframes, step=step, cash=cash, cost=COST["stocks"])
            m = grid_replay.metrics(eq)
            print(f"   grid {step:>3.0%} | total {m['total']:+.1%}  maxDD {m['maxdd']:.1%}  trades {tr}  "
                  f"unit ${grid.unit_size(cash, len(gframes)):.0f}")


if __name__ == "__main__":
    main()
