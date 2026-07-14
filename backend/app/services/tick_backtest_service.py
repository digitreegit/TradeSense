"""
Tick-level event backtester: aggregate ticks → OHLCV bars → playbook scores → long-only PnL.

Data sources:

- **alpaca_trades** — historical trades via Alpaca Data API (paper keys; SIP/IEX per config).
- **csv** — ``timestamp`` (unix sec or ms), ``price``, ``size`` under ``BACKTEST_DATA_DIR``.
- **polygon** — Polygon.io v3 trades when ``POLYGON_API_KEY`` is set.
- **databento** — reserved; returns a clear ``not_configured`` payload (SDK not bundled).

This is an **event simulator** (not vectorbt): fills at bar close + slippage bps after each
closed bar, while bar edges are driven by tick stream timestamps.

**Walk-forward:** rolling in-sample / out-of-sample windows; optional entry-threshold grid search
on in-sample only, evaluated on OOS to reduce single-window overfit.

**Latency:** ``latency_rtt_ms`` (or env ``BACKTEST_LATENCY_RTT_MS``) defers fills until the first
trade at or after ``signal_time + RTT`` — inject production-measured RTT for live-parity.

**Regulatory (sell side):** Section 31 fee on sale proceeds and FINRA TAF per share on sells —
Alpaca has no equity commission but these pass through; see ``BACKTEST_SEC_FEE_PER_MILLION_USD``,
``BACKTEST_FINRA_TAF_*``, ``BACKTEST_REGULATORY_FEES_ENABLED``.
"""
from __future__ import annotations

import csv
import logging
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

import httpx
import numpy as np
import pytz

from app.core.config import settings
from app.services.playbooks import combine as combine_playbooks

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

@dataclass
class Tick:
    ts: float  # unix seconds
    price: float
    size: float


@dataclass
class _PendingBuy:
    due_ts: float
    score: int
    reasons: List[str]


@dataclass
class _PendingSell:
    due_ts: float
    qty: int
    reason: str


def _rsi(arr: np.ndarray, period: int = 14) -> float:
    if len(arr) < 2:
        return 50.0
    deltas = np.diff(arr)
    p = min(period, len(deltas))
    gains = np.where(deltas[-p:] > 0, deltas[-p:], 0.0)
    losses = np.where(deltas[-p:] < 0, -deltas[-p:], 0.0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss < 1e-12:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _ema(data: np.ndarray, period: int) -> np.ndarray:
    if len(data) == 0:
        return np.array([0.0])
    alpha = 2.0 / (period + 1)
    ema = np.zeros_like(data, dtype=float)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = alpha * data[i] + (1.0 - alpha) * ema[i - 1]
    return ema


def _indicators_from_closes(closes: List[float]) -> dict:
    arr = np.array(closes, dtype=float)
    rsi = _rsi(arr, 14)
    ema12 = _ema(arr, 12)
    ema26 = _ema(arr, 26) if len(arr) >= 26 else _ema(arr, max(len(arr), 2))
    mlen = min(len(ema12), len(ema26))
    macd = ema12[-mlen:] - ema26[-mlen:]
    sig = _ema(macd, 9) if len(macd) >= 9 else _ema(macd, max(len(macd), 1))
    macd_signal = "bullish" if len(macd) > 0 and len(sig) > 0 and macd[-1] > sig[-1] else "bearish"
    n = min(20, len(arr))
    ma20 = float(np.mean(arr[-n:]))
    std20 = float(np.std(arr[-n:]))
    bb_upper = ma20 + 2 * std20
    bb_lower = ma20 - 2 * std20
    ma50 = float(np.mean(arr[-min(50, len(arr)):])) if len(arr) >= 10 else float(np.mean(arr))
    return {
        "rsi": rsi,
        "macd_line": float(macd[-1]) if len(macd) > 0 else 0.0,
        "macd_signal": macd_signal,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_middle": ma20,
        "ma20": ma20,
        "ma50": ma50,
        "current_price": float(arr[-1]),
    }


class BarBuilder:
    """Fixed-interval OHLCV from tick stream."""

    def __init__(self, bar_seconds: int) -> None:
        self.sec = max(1, int(bar_seconds))
        self._bucket: Optional[int] = None
        self._o = self._h = self._l = self._c = 0.0
        self._v = 0

    def on_tick(self, ts: float, price: float, size: float) -> Optional[Dict[str, Any]]:
        t = int(ts)
        bucket = t - (t % self.sec)
        sz = int(max(0, size))
        if self._bucket is None:
            self._bucket = bucket
            self._o = self._h = self._l = self._c = float(price)
            self._v = sz
            return None
        if bucket != self._bucket:
            bar = {
                "time": self._bucket,
                "open": self._o,
                "high": self._h,
                "low": self._l,
                "close": self._c,
                "volume": self._v,
            }
            self._bucket = bucket
            self._o = self._h = self._l = self._c = float(price)
            self._v = sz
            return bar
        self._h = max(self._h, price)
        self._l = min(self._l, price)
        self._c = float(price)
        self._v += sz
        return None

    def flush(self) -> Optional[Dict[str, Any]]:
        if self._bucket is None:
            return None
        return {
            "time": self._bucket,
            "open": self._o,
            "high": self._h,
            "low": self._l,
            "close": self._c,
            "volume": self._v,
        }


def load_ticks_csv(symbol: str, filename: str) -> List[Tick]:
    base = Path(settings.backtest_data_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    path = (base / filename).resolve()
    if not str(path).startswith(str(base)):
        raise ValueError("csv path must stay under BACKTEST_DATA_DIR")
    if not path.is_file():
        raise FileNotFoundError(str(path))
    ticks: List[Tick] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ts_raw = float(row.get("timestamp") or row.get("ts") or row.get("time") or 0)
            if ts_raw > 1e12:
                ts_raw /= 1000.0
            pr = float(row.get("price") or row.get("p") or 0)
            sz = float(row.get("size") or row.get("s") or row.get("volume") or 0)
            sym = (row.get("symbol") or row.get("sym") or "").upper()
            if sym and sym != symbol.upper():
                continue
            if pr > 0 and ts_raw > 0:
                ticks.append(Tick(ts=ts_raw, price=pr, size=sz))
    ticks.sort(key=lambda x: x.ts)
    return ticks


def load_ticks_polygon(symbol: str, start: datetime, end: datetime, limit: int) -> List[Tick]:
    key = (settings.polygon_api_key or "").strip()
    if not key:
        raise ValueError("POLYGON_API_KEY not set")
    sym = symbol.upper()
    start_s = int(start.replace(tzinfo=timezone.utc).timestamp() * 1e9)
    end_s = int(end.replace(tzinfo=timezone.utc).timestamp() * 1e9)
    url: Optional[str] = f"https://api.polygon.io/v3/trades/{sym}"
    ticks: List[Tick] = []
    first = True
    with httpx.Client(timeout=60.0) as client:
        params: Dict[str, Any] = {
            "timestamp.gte": start_s,
            "timestamp.lt": end_s,
            "order": "asc",
            "limit": min(50000, limit),
            "apiKey": key,
        }
        while url and len(ticks) < limit:
            r = client.get(url, params=params if first else None)
            first = False
            r.raise_for_status()
            data = r.json()
            for row in data.get("results") or []:
                ns = int(row.get("sip_timestamp") or row.get("participant_timestamp") or 0)
                if ns <= 0:
                    continue
                ticks.append(
                    Tick(ts=ns / 1e9, price=float(row.get("price", 0)), size=float(row.get("size", 0)))
                )
                if len(ticks) >= limit:
                    break
            url = data.get("next_url")
    return ticks[:limit]


def load_ticks_alpaca(alpaca: Any, symbol: str, start: datetime, end: datetime, limit: int) -> List[Tick]:
    if not getattr(alpaca, "is_ready", False) or not getattr(alpaca, "data_client", None):
        raise RuntimeError("Alpaca data client not ready")
    try:
        from alpaca.data.requests import StockTradesRequest
    except ImportError as exc:
        raise RuntimeError("alpaca-py StockTradesRequest unavailable") from exc

    from app.services.alpaca_service import _resolve_feed

    feed = _resolve_feed()
    cap = min(10000, limit)
    try:
        req = StockTradesRequest(
            symbol_or_symbols=symbol.upper(),
            start=start,
            end=end,
            limit=cap,
            feed=feed,
        )
    except TypeError:
        req = StockTradesRequest(
            symbol_or_symbols=symbol.upper(),
            start=start,
            end=end,
            limit=cap,
        )
    resp = alpaca.data_client.get_stock_trades(req)
    raw = getattr(resp, "data", None)
    if raw is None and isinstance(resp, dict):
        raw = resp
    rows: List[Any] = []
    if isinstance(raw, dict):
        rows = list(raw.get(symbol.upper()) or next(iter(raw.values()), []) or [])
    elif isinstance(raw, list):
        rows = raw
    ticks: List[Tick] = []
    for tr in rows:
        ts_obj = getattr(tr, "timestamp", None)
        ts = ts_obj.timestamp() if ts_obj else 0.0
        price = float(getattr(tr, "price", 0) or 0.0)
        size = float(getattr(tr, "size", 0) or 0.0)
        if ts > 0 and price > 0:
            ticks.append(Tick(ts=ts, price=price, size=size))
    ticks.sort(key=lambda x: x.ts)
    return ticks[:limit]


def ticks_to_bars(ticks: List[Tick], bar_seconds: int) -> List[Dict[str, Any]]:
    builder = BarBuilder(bar_seconds)
    out: List[Dict[str, Any]] = []
    for tk in ticks:
        b = builder.on_tick(tk.ts, tk.price, tk.size)
        if b:
            out.append(b)
    lb = builder.flush()
    if lb:
        out.append(lb)
    return out


def _resolve_latency_ms(explicit: Optional[float]) -> float:
    if explicit is not None and explicit >= 0:
        return float(explicit)
    return float(getattr(settings, "backtest_latency_rtt_ms", 0.0) or 0.0)


def _regulatory_sell_fees_usd(sale_proceeds: float, qty: int) -> Tuple[float, float, float]:
    """US sell-side regulatory costs: (total, sec_fee, finra_taf)."""
    if qty <= 0 or sale_proceeds <= 0:
        return 0.0, 0.0, 0.0
    if not getattr(settings, "backtest_regulatory_fees_enabled", True):
        return 0.0, 0.0, 0.0
    sec_per_mil = max(0.0, float(getattr(settings, "backtest_sec_fee_per_million_usd", 0.0) or 0.0))
    sec = sale_proceeds * (sec_per_mil / 1_000_000.0)
    taf_ps = max(0.0, float(getattr(settings, "backtest_finra_taf_per_share", 0.0) or 0.0))
    taf_min = max(0.0, float(getattr(settings, "backtest_finra_taf_min_usd", 0.0) or 0.0))
    taf_max = max(taf_min, float(getattr(settings, "backtest_finra_taf_max_usd", 0.0) or 0.0))
    n = abs(int(qty))
    taf_raw = n * taf_ps
    taf = max(taf_min, min(taf_max, taf_raw))
    total = sec + taf
    return float(total), float(sec), float(taf)


def run_bar_backtest(
    bars: List[Dict[str, Any]],
    *,
    initial_cash: float,
    entry_score_threshold: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    slippage_bps: float,
    playbooks: List[str],
    latency_bars: int = 0,
) -> Dict[str, Any]:
    """
    Fast path on pre-built bars (walk-forward inner loop). Fills scheduled on bar index:
    ``fill_idx = min(signal_idx + latency_bars, n-1)`` approximates RTT in bar units.
    """
    n = len(bars)
    if n < 25:
        return {"ok": False, "error": "insufficient_bars", "n_bars": n}

    slip = float(slippage_bps) / 10000.0
    lag = max(0, int(latency_bars))
    cash = float(initial_cash)
    pos_qty = 0
    entry_px = 0.0
    fills: List[Dict[str, Any]] = []
    equity_peak = cash
    max_dd = 0.0
    equity_curve: List[Dict[str, Any]] = []
    total_reg_fees = 0.0

    orders_at: DefaultDict[int, List[Tuple[str, Any]]] = defaultdict(list)

    def record_sell_fill(qty: int, px: float, time_val: Any, reason: str) -> None:
        nonlocal cash, total_reg_fees
        if qty <= 0:
            return
        proceeds = float(qty) * float(px)
        fees, sec_c, taf_c = _regulatory_sell_fees_usd(proceeds, qty)
        total_reg_fees += fees
        cash += proceeds - fees
        fills.append(
            {
                "side": "sell",
                "qty": qty,
                "price": round(px, 4),
                "time": time_val,
                "reason": reason,
                "reg_fees_usd": round(fees, 4),
                "sec_fee_usd": round(sec_c, 4),
                "finra_taf_usd": round(taf_c, 4),
            }
        )

    def has_pending_sell_from(idx: int) -> bool:
        for j, batch in orders_at.items():
            if j >= idx and any(kind == "sell" for kind, _ in batch):
                return True
        return False

    def has_pending_buy_from(idx: int) -> bool:
        for j, batch in orders_at.items():
            if j >= idx and any(kind == "buy" for kind, _ in batch):
                return True
        return False

    def mark_eq(idx: int) -> None:
        nonlocal equity_peak, max_dd
        px = float(bars[idx]["close"])
        eq = cash + pos_qty * px
        equity_peak = max(equity_peak, eq)
        if equity_peak > 0:
            max_dd = max(max_dd, (equity_peak - eq) / equity_peak)
        equity_curve.append({"t": int(bars[idx]["time"]), "equity": round(eq, 2)})

    def execute_orders_at(i: int) -> None:
        nonlocal cash, pos_qty, entry_px
        batch = orders_at.pop(i, [])
        for kind, meta in sorted(batch, key=lambda x: 0 if x[0] == "sell" else 1):
            close = float(bars[i]["close"])
            if kind == "sell" and pos_qty > 0:
                px = close * (1.0 - slip)
                q = pos_qty
                record_sell_fill(q, px, bars[i]["time"], str(meta.get("reason", "sell")))
                pos_qty = 0
                entry_px = 0.0
            elif kind == "buy" and pos_qty == 0:
                px = close * (1.0 + slip)
                qty = int(cash * 0.98 / px)
                if qty > 0:
                    cost = qty * px
                    cash -= cost
                    pos_qty = qty
                    entry_px = px
                    fills.append(
                        {
                            "side": "buy",
                            "qty": qty,
                            "price": round(px, 4),
                            "time": bars[i]["time"],
                            "score": meta.get("score", 0),
                            "reasons": meta.get("reasons", []),
                        }
                    )

    for i in range(n):
        execute_orders_at(i)
        bar = bars[i]
        close = float(bar["close"])
        t = int(bar["time"])
        now_et = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(ET)

        hist = bars[: i + 1]
        if pos_qty > 0 and not has_pending_sell_from(i):
            ret = (close - entry_px) / entry_px * 100.0
            if ret <= -stop_loss_pct or ret >= take_profit_pct:
                fi = min(i + lag, n - 1)
                reason = "stop" if ret <= -stop_loss_pct else "tp"
                orders_at[fi].append(("sell", {"reason": reason}))

        if pos_qty == 0:
            if not has_pending_buy_from(i) and len(hist) >= 20:
                closes = [b["close"] for b in hist]
                vols = [b.get("volume", 0) for b in hist]
                indicators = _indicators_from_closes(closes)
                price = closes[-1]
                total, reasons = combine_playbooks(
                    price=price,
                    indicators=indicators,
                    bars=hist,
                    volumes=vols,
                    now=now_et,
                    news_score=0.0,
                    enabled=playbooks,
                    micro=None,
                )
                if len(closes) >= 10:
                    ma10 = sum(closes[-10:]) / 10.0
                    if price > ma10:
                        total += 10
                        reasons.append("P>MA10")
                if total >= entry_score_threshold:
                    fi = min(i + lag, n - 1)
                    orders_at[fi].append(
                        ("buy", {"score": total, "reasons": reasons[:8]})
                    )

        if lag == 0:
            execute_orders_at(i)

        mark_eq(i)

    # flush position
    if pos_qty > 0:
        li = n - 1
        px = float(bars[li]["close"]) * (1.0 - slip)
        record_sell_fill(pos_qty, px, bars[li]["time"], "eod_flush")
        pos_qty = 0

    final_eq = cash
    ret_pct = (final_eq / initial_cash - 1.0) * 100.0 if initial_cash > 0 else 0.0

    return {
        "ok": True,
        "n_bars": n,
        "initial_cash": initial_cash,
        "final_equity": round(final_eq, 2),
        "return_pct": round(ret_pct, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "n_fills": len(fills),
        "fills": fills[-200:],
        "equity_curve_tail": equity_curve[-500:],
        "latency_bars": lag,
        "entry_score_threshold": entry_score_threshold,
        "regulatory_fees_total_usd": round(total_reg_fees, 4),
    }


@dataclass
class WalkForwardParams:
    in_sample_bars: int = 120
    out_sample_bars: int = 60
    step_bars: int = 60
    optimize_entry_threshold: bool = False
    threshold_grid: List[int] = field(default_factory=lambda: [40, 50, 60])


def run_walk_forward_backtest(
    alpaca: Any,
    params: TickBacktestParams,
    wf: WalkForwardParams,
) -> Dict[str, Any]:
    """Load ticks once, build bars, roll IS/OOS windows; optional IS grid search for threshold."""
    sym = params.symbol.upper()
    start = datetime.fromisoformat(params.start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(params.end.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    max_t = min(int(params.max_ticks), int(settings.tick_backtest_max_ticks))
    if params.source == "databento":
        return {"ok": False, "error": "databento_not_bundled", "symbol": sym}

    try:
        if params.source == "alpaca_trades":
            ticks = load_ticks_alpaca(alpaca, sym, start, end, max_t)
        elif params.source == "csv":
            if not params.csv_filename:
                raise ValueError("csv_filename required")
            ticks = load_ticks_csv(sym, params.csv_filename)[:max_t]
        elif params.source == "polygon":
            ticks = load_ticks_polygon(sym, start, end, max_t)
        else:
            raise ValueError(f"unknown source {params.source}")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "symbol": sym}

    bars = ticks_to_bars(ticks, params.bar_seconds)
    lat_ms = _resolve_latency_ms(params.latency_rtt_ms)
    latency_bars = int(lat_ms // max(1, params.bar_seconds * 1000)) if lat_ms > 0 else 0

    need = wf.in_sample_bars + wf.out_sample_bars + 25
    if len(bars) < need:
        return {
            "ok": False,
            "error": "insufficient_bars_for_walkforward",
            "n_bars": len(bars),
            "need": need,
        }

    playbooks = params.playbooks or ["scalp", "vwap", "orb", "eod"]
    window = wf.in_sample_bars + wf.out_sample_bars
    folds: List[Dict[str, Any]] = []

    for start_i in range(0, len(bars) - window + 1, max(1, wf.step_bars)):
        is_bars = bars[start_i : start_i + wf.in_sample_bars]
        oos_bars = bars[start_i + wf.in_sample_bars : start_i + window]
        th = params.entry_score_threshold
        if wf.optimize_entry_threshold and wf.threshold_grid:
            best: Tuple[float, int] = (-1e9, th)
            for cand in wf.threshold_grid:
                r = run_bar_backtest(
                    is_bars,
                    initial_cash=params.initial_cash,
                    entry_score_threshold=int(cand),
                    stop_loss_pct=params.stop_loss_pct,
                    take_profit_pct=params.take_profit_pct,
                    slippage_bps=params.slippage_bps,
                    playbooks=playbooks,
                    latency_bars=latency_bars,
                )
                score = float(r.get("return_pct", -1e9)) if r.get("ok") else -1e9
                if score > best[0]:
                    best = (score, int(cand))
            th = best[1]
        oos = run_bar_backtest(
            oos_bars,
            initial_cash=params.initial_cash,
            entry_score_threshold=th,
            stop_loss_pct=params.stop_loss_pct,
            take_profit_pct=params.take_profit_pct,
            slippage_bps=params.slippage_bps,
            playbooks=playbooks,
            latency_bars=latency_bars,
        )
        folds.append(
            {
                "fold_start_bar": start_i,
                "in_sample_bars": len(is_bars),
                "out_sample_bars": len(oos_bars),
                "chosen_threshold": th,
                "in_sample_tuned": wf.optimize_entry_threshold,
                "oos": oos,
            }
        )

    oos_returns = [
        float(f["oos"]["return_pct"])
        for f in folds
        if f.get("oos") and f["oos"].get("ok")
    ]
    oos_reg_fees = [
        float(f["oos"].get("regulatory_fees_total_usd", 0) or 0)
        for f in folds
        if f.get("oos") and f["oos"].get("ok")
    ]
    agg: Dict[str, Any] = {
        "n_folds": len(folds),
        "oos_return_mean": round(statistics.mean(oos_returns), 4) if oos_returns else None,
        "oos_return_stdev": round(statistics.stdev(oos_returns), 4) if len(oos_returns) > 1 else None,
        "oos_return_min": round(min(oos_returns), 4) if oos_returns else None,
        "oos_return_max": round(max(oos_returns), 4) if oos_returns else None,
        "oos_regulatory_fees_total_usd": round(sum(oos_reg_fees), 4) if oos_reg_fees else None,
    }

    return {
        "ok": True,
        "symbol": sym,
        "source": params.source,
        "n_ticks": len(ticks),
        "n_bars": len(bars),
        "latency_rtt_ms": lat_ms,
        "latency_bars": latency_bars,
        "walk_forward": {
            "in_sample_bars": wf.in_sample_bars,
            "out_sample_bars": wf.out_sample_bars,
            "step_bars": wf.step_bars,
            "optimize_entry_threshold": wf.optimize_entry_threshold,
            "threshold_grid": list(wf.threshold_grid),
        },
        "folds": folds,
        "aggregate": agg,
    }


@dataclass
class TickBacktestParams:
    """Tick backtest inputs.

    ``latency_rtt_ms``: if ``None``, uses ``settings.backtest_latency_rtt_ms`` (e.g. measured RTT).
    """

    symbol: str
    start: str
    end: str
    source: str = "alpaca_trades"
    csv_filename: Optional[str] = None
    initial_cash: float = 100_000.0
    bar_seconds: int = 300
    entry_score_threshold: int = 50
    stop_loss_pct: float = 0.3
    take_profit_pct: float = 0.8
    slippage_bps: float = 8.0
    playbooks: Optional[List[str]] = None
    max_ticks: int = 250_000
    latency_rtt_ms: Optional[float] = None


def run_tick_backtest(alpaca: Any, params: TickBacktestParams) -> Dict[str, Any]:
    sym = params.symbol.upper()
    start = datetime.fromisoformat(params.start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(params.end.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    max_t = min(int(params.max_ticks), int(settings.tick_backtest_max_ticks))

    warnings: List[str] = []
    if params.source == "databento":
        return {
            "ok": False,
            "error": "databento_not_bundled",
            "message": "Databento tick ingest is not bundled; use alpaca_trades, csv, or polygon.",
            "symbol": sym,
        }

    try:
        if params.source == "alpaca_trades":
            ticks = load_ticks_alpaca(alpaca, sym, start, end, max_t)
        elif params.source == "csv":
            if not params.csv_filename:
                raise ValueError("csv_filename required for source=csv")
            ticks = load_ticks_csv(sym, params.csv_filename)
            ticks = ticks[:max_t]
        elif params.source == "polygon":
            ticks = load_ticks_polygon(sym, start, end, max_t)
        else:
            raise ValueError(f"unknown source {params.source}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("tick load failed: %s", exc)
        return {
            "ok": False,
            "error": str(exc),
            "symbol": sym,
            "source": params.source,
        }

    if len(ticks) < 50:
        return {
            "ok": False,
            "error": "insufficient_ticks",
            "n_ticks": len(ticks),
            "symbol": sym,
            "source": params.source,
        }

    enabled = params.playbooks or ["scalp", "vwap", "orb", "eod"]
    slip = float(params.slippage_bps) / 10000.0
    lat_ms = _resolve_latency_ms(params.latency_rtt_ms)
    latency_sec = max(0.0, lat_ms / 1000.0)

    builder = BarBuilder(params.bar_seconds)
    bars: List[Dict[str, Any]] = []
    cash = float(params.initial_cash)
    pos_qty = 0
    entry_px = 0.0
    fills: List[Dict[str, Any]] = []
    equity_peak = cash
    max_dd = 0.0
    equity_curve: List[Dict[str, Any]] = []
    pending_buys: deque[_PendingBuy] = deque()
    pending_sells: deque[_PendingSell] = deque()
    total_reg_fees = 0.0

    def mark_equity(bar_time: int, px: float) -> None:
        nonlocal equity_peak, max_dd, equity_curve
        eq = cash + pos_qty * px
        equity_peak = max(equity_peak, eq)
        if equity_peak > 0:
            max_dd = max(max_dd, (equity_peak - eq) / equity_peak)
        equity_curve.append({"t": bar_time, "equity": round(eq, 2)})
        if len(equity_curve) > 4000:
            equity_curve = equity_curve[-2500:]

    def process_pending(tk: Tick) -> None:
        nonlocal cash, pos_qty, entry_px, total_reg_fees
        eps = 1e-12
        while pending_sells and tk.ts + eps >= pending_sells[0].due_ts:
            ps = pending_sells.popleft()
            if pos_qty <= 0:
                continue
            px = tk.price * (1.0 - slip)
            q = pos_qty if ps.qty < 0 else min(ps.qty, pos_qty)
            if q <= 0:
                continue
            proceeds = q * px
            fees, sec_c, taf_c = _regulatory_sell_fees_usd(proceeds, q)
            total_reg_fees += fees
            cash += proceeds - fees
            fills.append(
                {
                    "side": "sell",
                    "qty": q,
                    "price": round(px, 4),
                    "time": int(tk.ts),
                    "reason": ps.reason,
                    "reg_fees_usd": round(fees, 4),
                    "sec_fee_usd": round(sec_c, 4),
                    "finra_taf_usd": round(taf_c, 4),
                }
            )
            pos_qty -= q
            if pos_qty <= 0:
                pos_qty = 0
                entry_px = 0.0
        while pending_buys and tk.ts + eps >= pending_buys[0].due_ts:
            pb = pending_buys.popleft()
            if pos_qty > 0:
                continue
            px = tk.price * (1.0 + slip)
            qty = int(cash * 0.98 / px)
            if qty > 0:
                cost = qty * px
                cash -= cost
                pos_qty = qty
                entry_px = px
                fills.append(
                    {
                        "side": "buy",
                        "qty": qty,
                        "price": round(px, 4),
                        "time": int(tk.ts),
                        "score": pb.score,
                        "reasons": pb.reasons[:8],
                    }
                )

    for tk in ticks:
        bar = builder.on_tick(tk.ts, tk.price, tk.size)
        process_pending(tk)
        if bar is None:
            continue
        bars.append(bar)
        close = float(bar["close"])
        now_et = datetime.fromtimestamp(bar["time"], tz=timezone.utc).astimezone(ET)

        if pos_qty > 0:
            ret = (close - entry_px) / entry_px * 100.0
            if (ret <= -params.stop_loss_pct or ret >= params.take_profit_pct) and not pending_sells:
                reason = "stop" if ret <= -params.stop_loss_pct else "tp"
                pending_sells.append(_PendingSell(due_ts=tk.ts + latency_sec, qty=-1, reason=reason))

        if len(bars) < 20:
            mark_equity(int(bar["time"]), close)
            continue

        if pos_qty == 0 and not pending_buys and not pending_sells:
            closes = [b["close"] for b in bars]
            vols = [b.get("volume", 0) for b in bars]
            indicators = _indicators_from_closes(closes)
            price = closes[-1]
            total, reasons = combine_playbooks(
                price=price,
                indicators=indicators,
                bars=bars,
                volumes=vols,
                now=now_et,
                news_score=0.0,
                enabled=enabled,
                micro=None,
            )
            if len(closes) >= 10:
                ma10 = sum(closes[-10:]) / 10.0
                if price > ma10:
                    total += 10
                    reasons.append("P>MA10")
            if total >= params.entry_score_threshold:
                pending_buys.append(
                    _PendingBuy(due_ts=tk.ts + latency_sec, score=total, reasons=reasons[:8])
                )
        mark_equity(int(bar["time"]), close)
        process_pending(tk)

    if ticks:
        lt = ticks[-1]
        far = Tick(ts=lt.ts + 86400.0 * 365.0, price=lt.price, size=0.0)
        process_pending(far)

    last_bar = builder.flush()
    if last_bar:
        bars.append(last_bar)
        close = float(last_bar["close"])
        if pos_qty > 0:
            px = close * (1.0 - slip)
            proceeds = pos_qty * px
            fees, sec_c, taf_c = _regulatory_sell_fees_usd(proceeds, pos_qty)
            total_reg_fees += fees
            cash += proceeds - fees
            fills.append(
                {
                    "side": "sell",
                    "qty": pos_qty,
                    "price": round(px, 4),
                    "time": last_bar["time"],
                    "reason": "eod_flush",
                    "reg_fees_usd": round(fees, 4),
                    "sec_fee_usd": round(sec_c, 4),
                    "finra_taf_usd": round(taf_c, 4),
                }
            )
            pos_qty = 0
        mark_equity(int(last_bar["time"]), close)

    final_eq = cash + pos_qty * float(bars[-1]["close"] if bars else 0.0)
    ret_pct = (final_eq / params.initial_cash - 1.0) * 100.0 if params.initial_cash > 0 else 0.0

    return {
        "ok": True,
        "symbol": sym,
        "source": params.source,
        "n_ticks": len(ticks),
        "n_bars": len(bars),
        "initial_cash": params.initial_cash,
        "final_equity": round(final_eq, 2),
        "return_pct": round(ret_pct, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "n_fills": len(fills),
        "fills": fills[-200:],
        "equity_curve_tail": equity_curve[-500:],
        "bar_seconds": params.bar_seconds,
        "playbooks": enabled,
        "warnings": warnings,
        "latency_rtt_ms": lat_ms,
        "regulatory_fees_total_usd": round(total_reg_fees, 4),
    }
