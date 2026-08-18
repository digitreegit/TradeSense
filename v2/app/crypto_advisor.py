"""Crypto market advisor — analysis and manual-trade signals only.

Alpaca cannot trade crypto in this account's state, so the bot never places
crypto orders. It analyzes the market, ranks high-volatility coins, and gives
RuleFive-style step levels (buy the dip / take profit on the rise) that the
user executes manually on Robinhood.

Signal design (validated intuition from scripts/grid_sim.py on stocks):
a naked grid bleeds in downtrends, so every accumulation signal is gated by
an uptrend (price above 50EMA and 20EMA >= 50EMA). The step size is derived
from each coin's own realized daily range instead of a fixed 5%.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from .indicators import ema, rsi, sma
from .state import store

log = logging.getLogger(__name__)

# Alpaca crypto data pairs that Robinhood also lists (manual execution venue).
CANDIDATES = [
    "BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "XRP/USD",
    "AVAX/USD", "LINK/USD", "LTC/USD", "UNI/USD", "SHIB/USD",
    "BCH/USD", "AAVE/USD",
]

DEFAULT_BUDGET = 1000.0
MAX_PICKS = 4          # concentrated enough that $1000 splits meaningfully
CACHE_KEY = "crypto_advice"
CACHE_TTL = 900.0      # 15 min — crypto moves, but daily bars drive the levels

MIN_STEP = 0.04        # never advise a step tighter than 4%
MAX_STEP = 0.12


def fetch_bars(days: int = 400) -> dict[str, pd.DataFrame]:
    """Public Alpaca crypto data — works without API keys."""
    from alpaca.data.historical import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = CryptoHistoricalDataClient()
    req = CryptoBarsRequest(
        symbol_or_symbols=CANDIDATES,
        timeframe=TimeFrame.Day,
        start=datetime.now(timezone.utc) - timedelta(days=days),
    )
    data = client.get_crypto_bars(req).data
    out: dict[str, pd.DataFrame] = {}
    for sym in CANDIDATES:
        bars = data.get(sym)
        if not bars:
            continue
        df = pd.DataFrame(
            {
                "date": [b.timestamp for b in bars],
                "open": [b.open for b in bars],
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
            }
        ).set_index("date")
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        out[sym] = df
    return out


def _coin_metrics(df: pd.DataFrame) -> dict | None:
    if len(df) < 60:
        return None
    close = df["close"]
    price = float(close.iloc[-1])
    ema20 = float(ema(close, 20).iloc[-1])
    ema50 = float(ema(close, 50).iloc[-1])
    sma200 = float(sma(close, 200).iloc[-1]) if len(df) >= 200 else None
    range30 = float(((df["high"] - df["low"]) / df["close"]).tail(30).mean())
    vol30 = float(close.pct_change().tail(30).std() * (365 ** 0.5))
    if price > ema50 and ema20 >= ema50:
        trend = "up"
    elif price < ema50 and ema20 < ema50:
        trend = "down"
    else:
        trend = "side"
    return {
        "price": price,
        "trend": trend,
        "ema50": ema50,
        "sma200": sma200,
        "range30": range30,
        "vol30": vol30,
        "rsi14": float(rsi(close, 14).iloc[-1]),
        "ret7": float(price / close.iloc[-8] - 1) if len(close) > 8 else 0.0,
        "ret30": float(price / close.iloc[-31] - 1) if len(close) > 31 else 0.0,
    }


def _step_for(range30: float) -> float:
    """RuleFive step sized to the coin's own daily range (~1.5 average days)."""
    return round(min(MAX_STEP, max(MIN_STEP, range30 * 1.5)), 2)


def _action(m: dict) -> tuple[str, str]:
    step_pct = f"{_step_for(m['range30']):.0%}"
    if m["trend"] == "down":
        return "avoid", "관망 — 하락 추세. 50일 EMA 회복 전 신규 매수 금지"
    if m["trend"] == "side":
        return "watch", "관망 — 횡보. 추세 확인(가격·20EMA가 50EMA 위) 후 진입"
    if m["rsi14"] >= 70:
        return "wait_dip", f"과열(RSI {m['rsi14']:.0f}) — {step_pct} 반락 시 1차 매수"
    return "buy", f"분할 매수 — 1차 지금, 2차 {step_pct} 하락 시"


def analyze_frames(
    frames: dict[str, pd.DataFrame], budget: float = DEFAULT_BUDGET
) -> dict:
    """Pure analysis over daily bars (testable without network)."""
    coins = []
    for sym, df in frames.items():
        m = _coin_metrics(df)
        if m is None:
            continue
        step = _step_for(m["range30"])
        action, action_label = _action(m)
        base = m["price"] if action == "buy" else m["price"] * (1 - step)
        coins.append({
            "symbol": sym.split("/")[0],
            "pair": sym,
            **{k: m[k] for k in ("price", "trend", "range30", "vol30",
                                 "rsi14", "ret7", "ret30")},
            "step": step,
            "action": action,
            "action_label": action_label,
            "buy1": base,
            "buy2": base * (1 - step),
            "sell": base * (1 + step),
            "exit_level": m["ema50"],
        })

    # market overview: BTC trend + breadth across the universe
    btc = next((c for c in coins if c["symbol"] == "BTC"), None)
    breadth = (
        sum(1 for c in coins if c["trend"] == "up") / len(coins) if coins else 0.0
    )
    if btc and btc["trend"] == "up" and breadth >= 0.5:
        market = ("BULL", "강세 — BTC 상승 추세, 시장 폭 양호. 분할 매수 유효")
    elif (btc and btc["trend"] == "down") or breadth < 0.25:
        market = ("BEAR", "약세 — BTC 하락 추세. 상승 코인도 절반 예산만, 이탈가 엄수")
    else:
        market = ("CHOP", "혼조 — 상승 추세 코인만 소액 분할 매수, 추격 금지")

    # picks: highest realized range among uptrending coins. In a bear tape an
    # alt uptrend is fragile — halve the deployable budget and flag each pick.
    bear = market[0] == "BEAR"
    ranked = sorted(coins, key=lambda c: c["range30"], reverse=True)
    picks = [c for c in ranked if c["action"] in ("buy", "wait_dip")][:MAX_PICKS]
    deployable = budget * (0.5 if bear else 1.0)
    alloc = round(deployable / len(picks), 0) if picks else 0.0
    pick_syms = set()
    for c in picks:
        c["alloc"] = alloc
        c["unit"] = round(alloc / 2, 0)  # two entries: buy1 + buy2
        if bear:
            c["action_label"] = "약세장 주의 · " + c["action_label"]
        pick_syms.add(c["symbol"])
    watch = [c for c in ranked if c["symbol"] not in pick_syms]

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget": budget,
        "market": {
            "label": market[0],
            "comment": market[1],
            "btc_price": btc["price"] if btc else None,
            "btc_ret30": btc["ret30"] if btc else None,
            "breadth": breadth,
        },
        "picks": picks,
        "watch": watch,
    }


def get_advice(budget: float = DEFAULT_BUDGET, force: bool = False) -> dict:
    """Cached advice (15 min). Analysis only — no orders are ever placed."""
    if not force:
        cached = store.get(CACHE_KEY)
        if cached and time.time() - cached.get("cached_at", 0) < CACHE_TTL:
            return cached["data"]
    try:
        frames = fetch_bars()
        if not frames:
            raise RuntimeError("no crypto bars returned")
        data = analyze_frames(frames, budget)
    except Exception as exc:
        log.exception("crypto advice failed")
        return {"ok": False, "error": f"크립토 데이터 조회 실패: {exc}"}
    store.set(CACHE_KEY, {"cached_at": time.time(), "data": data})
    return data
