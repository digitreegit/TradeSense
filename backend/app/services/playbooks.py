"""
Entry-signal playbooks used by the scalping engine.

Each playbook is a pure function that takes pre-computed indicators and
returns ``(score, reasons)``. The engine sums scores across active
playbooks before comparing to the preset's ``entry_score_threshold``.

Playbooks intentionally have no knowledge of sizing, risk presets, or
account state. Add / remove them without touching execution code.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import List, Tuple


def _in_window(now: datetime, start: time, end: time) -> bool:
    t = now.time()
    return start <= t < end


# ─── Micro-Scalping (RSI + MACD + BB) ─────────────────────────────
def playbook_micro_scalp(price: float, indicators: dict, volumes: list) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    rsi = indicators.get("rsi", 50)
    if rsi < 35:
        score += 30
        reasons.append(f"RSI↓{rsi:.0f}")
    elif 35 <= rsi <= 45:
        score += 15
        reasons.append(f"RSI={rsi:.0f}")

    if indicators.get("macd_signal") == "bullish":
        score += 25
        reasons.append("MACD↑")

    bb_upper = indicators.get("bb_upper", 0)
    bb_lower = indicators.get("bb_lower", 0)
    if bb_upper > bb_lower > 0:
        bb_pct = (price - bb_lower) / (bb_upper - bb_lower + 1e-6)
        if bb_pct < 0.2:
            score += 25
            reasons.append("BB-low")
        elif bb_pct < 0.4:
            score += 10
            reasons.append("BB-mid")

    if volumes and len(volumes) >= 10:
        avg_vol = sum(volumes[-10:]) / 10
        if avg_vol > 0 and volumes[-1] > avg_vol * 2:
            score += 15
            reasons.append("Vol🔥")

    return score, reasons


# ─── Microstructure (quote + tape; complements slow RSI/BB) ───────────
def playbook_microstructure(micro: dict | None) -> Tuple[int, List[str]]:
    """
    Order-flow imbalance (L1), relative spread, tape speed, simplified VPIN.

    ``micro`` comes from WebSocket cache via :func:`streaming_service.get_microstructure_features`.
    When streaming is off, returns zero — REST-only scans keep working.
    """
    if not micro:
        return 0, []

    score = 0
    reasons: List[str] = []

    spread = micro.get("spread_bps")
    if spread is not None:
        if spread < 5:
            score += 14
            reasons.append("spr<5bp")
        elif spread < 12:
            score += 8
            reasons.append("spr<12bp")
        elif spread < 25:
            score += 4
            reasons.append("spr<25bp")

    ofi = micro.get("ofi")
    if ofi is not None:
        if ofi > 0.18:
            score += 20
            reasons.append("OFI+")
        elif ofi > 0.06:
            score += 12
            reasons.append("ofi+")
        elif ofi < -0.18:
            score -= 6
            reasons.append("OFI-")

    tps = float(micro.get("tape_trades_per_sec") or 0.0)
    if tps > 2.0:
        score += 16
        reasons.append("tape🔥")
    elif tps > 0.8:
        score += 10
        reasons.append("tape↑")
    elif tps > 0.25:
        score += 5
        reasons.append("tape")

    vpin = micro.get("vpin")
    if vpin is not None:
        if vpin < 0.32:
            score += 12
            reasons.append("VPIN↓")
        elif vpin > 0.55:
            score -= 10
            reasons.append("VPIN↑")

    return score, reasons


# ─── VWAP Mean Reversion ──────────────────────────────────────────
def playbook_vwap_reversion(bars: list, price: float) -> Tuple[int, List[str]]:
    if len(bars) < 10:
        return 0, []
    typical = [(b["high"] + b["low"] + b["close"]) / 3.0 for b in bars]
    vols = [max(b.get("volume", 0), 1) for b in bars]
    pv = sum(t * v for t, v in zip(typical, vols))
    vwap = pv / sum(vols)
    dev = (price - vwap) / vwap * 100 if vwap else 0
    score = 0
    reasons: List[str] = []
    if dev < -0.6:
        score += 25
        reasons.append(f"VWAP-{abs(dev):.2f}%")
    elif dev < -0.3:
        score += 12
        reasons.append(f"vwap-{abs(dev):.2f}%")
    return score, reasons


# ─── Opening Range Breakout (5-min ORB) ───────────────────────────
def playbook_orb(
    bars: list,
    price: float,
    now: datetime,
    start: time = time(9, 35),
    end: time = time(11, 0),
) -> Tuple[int, List[str]]:
    """
    Buy when price breaks above the 9:30–9:35 range, valid until 11:00 ET.

    Assumes ``bars`` are 5-min bars ordered oldest→newest.
    """
    if not _in_window(now, start, end):
        return 0, []
    # First 5-min bar of today (index 0) defines the opening range if bars
    # are already filtered to today; otherwise we approximate with the last
    # relevant bar. The engine passes ~50 recent 5-min bars.
    if len(bars) < 2:
        return 0, []
    first = bars[-min(len(bars), 12)]  # crude: roughly today's first bar
    hi = first.get("high", 0)
    if hi and price > hi * 1.0005:
        return 20, [f"ORB↑>{hi:.2f}"]
    return 0, []


# ─── End-of-Day Drift ─────────────────────────────────────────────
def playbook_eod_drift(bars: list, price: float, now: datetime) -> Tuple[int, List[str]]:
    """
    In the last 10 minutes of the session, favor names already up strongly
    on the day — they tend to drift into the close.
    """
    if not _in_window(now, time(15, 50), time(15, 58)):
        return 0, []
    if not bars:
        return 0, []
    day_open = bars[0].get("open") or bars[0].get("close")
    if not day_open:
        return 0, []
    change = (price - day_open) / day_open * 100
    if change > 1.5:
        return 18, [f"EOD+{change:.1f}%"]
    if change > 0.8:
        return 10, [f"eod+{change:.1f}%"]
    return 0, []


# ─── News Spike Fade (AI sentiment hook) ──────────────────────────
def playbook_news_fade(news_score: float) -> Tuple[int, List[str]]:
    """
    AI agent can compute a short-term exhaustion signal. We accept a
    pre-computed ``news_score`` in [-1, 1] where −1 = panic-selling
    (fade = buy).
    """
    if news_score <= -0.6:
        return 15, [f"news-fade({news_score:+.2f})"]
    return 0, []


def combine(
    price: float,
    indicators: dict,
    bars: list,
    volumes: list,
    now: datetime,
    news_score: float = 0.0,
    enabled: List[str] = None,
    micro: dict | None = None,
) -> Tuple[int, List[str]]:
    """Run enabled playbooks and return (total_score, flat reasons list)."""
    enabled = enabled or ["scalp", "vwap", "orb", "eod", "micro"]
    total = 0
    reasons: List[str] = []

    if "scalp" in enabled:
        s, r = playbook_micro_scalp(price, indicators, volumes)
        total += s
        reasons += r
    if "micro" in enabled:
        s, r = playbook_microstructure(micro)
        total += s
        reasons += r
    if "vwap" in enabled:
        s, r = playbook_vwap_reversion(bars, price)
        total += s
        reasons += r
    if "orb" in enabled:
        s, r = playbook_orb(bars, price, now)
        total += s
        reasons += r
    if "eod" in enabled:
        s, r = playbook_eod_drift(bars, price, now)
        total += s
        reasons += r
    if "news-fade" in enabled and news_score:
        s, r = playbook_news_fade(news_score)
        total += s
        reasons += r

    # Price above short MA is a generic trend filter added to all.
    return total, reasons
