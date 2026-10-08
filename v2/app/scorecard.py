"""Honest scoring of the live rules — pure functions, no broker calls.

Borrowed from the Phil experiment's score.py: a rule is only as good as its
baseline (buy-and-hold, cash), results are split by the parameter revision
that produced them, and "luck" (how much of realized P/L the best two trades
account for) is reported next to the total so one jackpot never reads as skill.
"""
from __future__ import annotations

import hashlib
import json

BENCHMARKS = {
    "robinhood": ("BTC/USD", "ETH/USD"),
    "alpaca": ("SPY",),
}


def settings_rev(s: dict) -> str:
    """Short, stable id of the parameters that drive decisions."""
    core = {
        "steps": {k: round(float(v), 4) for k, v in sorted((s.get("steps") or {}).items())},
        "dip": {k: round(float(v), 4) for k, v in sorted((s.get("dip") or {}).items())},
    }
    return hashlib.sha1(json.dumps(core, sort_keys=True).encode()).hexdigest()[:7]


def max_drawdown(values: list[float]) -> float | None:
    peak, worst = None, 0.0
    for v in values:
        if v is None:
            continue
        peak = v if peak is None else max(peak, v)
        if peak and peak > 0:
            worst = min(worst, v / peak - 1)
    return round(worst, 4) if peak is not None else None


def _series(history: list[dict], key: str) -> list[tuple[str, float]]:
    out = []
    for p in history:
        v = p.get(key)
        if v is not None:
            out.append((p["date"], float(v)))
    return out


def _bench_series(history: list[dict], symbol: str) -> list[tuple[str, float]]:
    out = []
    for p in history:
        v = (p.get("bench") or {}).get(symbol)
        if v:
            out.append((p["date"], float(v)))
    return out


def _ret(series: list[tuple[str, float]]) -> float | None:
    if len(series) < 2 or not series[0][1]:
        return None
    return round(series[-1][1] / series[0][1] - 1, 4)


def venue_scorecard(venue: str, history: list[dict], trades: list[dict],
                    *, since: str | None = None) -> dict:
    """Strategy vs baselines over the stored daily history, plus trade quality."""
    hist = [p for p in history if (since is None or p.get("date", "") >= since)]
    eq = _series(hist, venue)
    start = eq[0][0] if eq else None
    # Baselines measured over the same dates the venue has equity for.
    bench = {}
    for sym in BENCHMARKS.get(venue, ()):
        bs = [(d, v) for d, v in _bench_series(hist, sym) if start is None or d >= start]
        r = _ret(bs)
        if r is not None:
            bench[sym] = r
    strat = _ret(eq)
    vt = [t for t in trades if t.get("venue") == venue]
    sells = [t for t in vt if t.get("side") == "sell" and t.get("pl") is not None]
    realized = round(sum(float(t["pl"]) for t in sells), 2)
    wins = sum(1 for t in sells if float(t["pl"]) > 0)
    gains = sorted((float(t["pl"]) for t in sells if float(t["pl"]) > 0), reverse=True)
    luck = round(sum(gains[:2]) / realized, 3) if realized > 0 and gains else None
    by_rev: dict[str, dict] = {}
    for t in vt:
        rev = t.get("rev") or "—"
        row = by_rev.setdefault(rev, {"rev": rev, "trades": 0, "closed": 0, "realized": 0.0,
                                      "first": t.get("at"), "last": t.get("at")})
        row["trades"] += 1
        if t.get("side") == "sell" and t.get("pl") is not None:
            row["closed"] += 1
            row["realized"] = round(row["realized"] + float(t["pl"]), 2)
        row["first"] = min(row["first"] or t.get("at"), t.get("at") or row["first"])
        row["last"] = max(row["last"] or t.get("at"), t.get("at") or row["last"])
    return {
        "since": start,
        "days": len(eq),
        "start_equity": eq[0][1] if eq else None,
        "equity": eq[-1][1] if eq else None,
        "strategy": strat,
        "cash": 0.0,
        "bench": bench,                      # {symbol: return over the same window}
        "vs_bench": ({k: round(strat - v, 4) for k, v in bench.items()} if strat is not None else {}),
        "maxdd": max_drawdown([v for _, v in eq]),
        "trades": len(vt),
        "closed": len(sells),
        "win_rate": round(wins / len(sells), 3) if sells else None,
        "realized": realized,
        "luck_top2": luck,
        "by_rev": sorted(by_rev.values(), key=lambda r: r["last"] or "", reverse=True),
    }
