"""Live engine: a handful of scheduled jobs instead of a 1-second loop.

Daily rhythm (America/New_York):
  08:45  news overlay (optional LLM tilt)
  09:31  execute pending orders queued after yesterday's close
  every 30 min in RTH: intraday stop check (wide ATR stops, rarely fires)
  16:35  compute signals on today's closed bars -> queue orders for tomorrow
  hourly (crypto only): 24/7 crypto sleeve when CRYPTO_ENABLED=true
  defensive macro sleeve queues with stocks when crypto disabled (NJ-safe)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from . import config, news_overlay, regime, strategy
from .broker import Broker
from .briefing import build_briefing, log_activity
from .config import settings
from .decisions import CRYPTO, DEFENSIVE, PendingOrder, PosMeta, decide
from .notify import send
from .risk import DrawdownBrake, position_dollars
from .state import store

log = logging.getLogger(__name__)


class Engine:
    """Broker construction is lazy so the app can boot (and serve the
    dashboard with a clear error) before API keys are configured."""

    def __init__(self) -> None:
        self._broker: Broker | None = None

    @property
    def broker(self) -> Broker:
        if self._broker is None:
            self._broker = Broker()
        return self._broker

    def reset_broker(self) -> None:
        self._broker = None

    # ------------------------------------------------------------------
    # shared helpers
    # ------------------------------------------------------------------
    def _features(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        bars = self.broker.daily_bars(symbols)
        return {s: strategy.compute_features(df) for s, df in bars.items() if len(df) >= 60}

    def _brake(self) -> DrawdownBrake:
        st = store.get("brake", {})
        return DrawdownBrake(
            peak_equity=st.get("peak_equity", 0.0),
            halted=st.get("halted", False),
        )

    def _save_brake(self, brake: DrawdownBrake) -> None:
        store.set("brake", {"peak_equity": brake.peak_equity, "halted": brake.halted})

    def _trend_universe(self) -> tuple[list[str], list[str]]:
        """Return (crypto_syms, defensive_syms) based on account licensing."""
        if settings.crypto_enabled:
            return list(config.CRYPTO_UNIVERSE), []
        return [], list(config.DEFENSIVE_UNIVERSE)

    def _immediate_sleeves(self) -> set[str]:
        return {CRYPTO} if settings.crypto_enabled else set()

    def _is_crypto_symbol(self, sym: str) -> bool:
        return "/" in sym

    def _liquidate_crypto_positions(self) -> int:
        """Sell crypto holdings when CRYPTO_ENABLED=false (e.g. NJ)."""
        if settings.crypto_enabled:
            return 0
        broker_positions = self.broker.positions()
        crypto_syms = [s for s in broker_positions if self._is_crypto_symbol(s)]
        if not crypto_syms:
            return 0
        sold = []
        for sym in crypto_syms:
            self._execute_sell(sym, "crypto", "crypto-disabled", broker_positions)
            sold.append(sym)
        log_activity("crypto", f"크립토 미지원 지역 — 청산 시도: {', '.join(sold)}")
        return len(sold)

    def _pos_metas(self, broker_positions: dict[str, dict]) -> dict[str, PosMeta]:
        """Merge broker positions with local stop/sleeve metadata.

        Positions the bot doesn't know about (bought manually) are adopted
        into the momentum sleeve with a fresh stop.
        """
        metas = store.pos_meta_all()
        out: dict[str, PosMeta] = {}
        for sym in broker_positions:
            if not settings.crypto_enabled and self._is_crypto_symbol(sym):
                continue  # legacy crypto — do not adopt; liquidate instead
            m = metas.get(sym)
            if m is None:
                store.pos_meta_upsert(sym, "momentum", None, config.MOMENTUM_STOP_ATR,
                                      datetime.now(timezone.utc).isoformat())
                m = {"sleeve": "momentum", "stop_level": None,
                     "stop_mult": config.MOMENTUM_STOP_ATR, "held_days": 0}
            out[sym] = PosMeta(
                symbol=sym, sleeve=m["sleeve"], held_days=m.get("held_days", 0) or 0,
                stop_level=m.get("stop_level"),
            )
        # clean up metadata for positions that no longer exist at the broker
        for sym in list(metas):
            if sym not in broker_positions:
                store.pos_meta_delete(sym)
        return out

    def _execute_sell(self, sym: str, meta_sleeve: str, reason: str,
                      broker_positions: dict[str, dict]) -> None:
        pos = broker_positions.get(sym)
        if pos is None:
            store.pos_meta_delete(sym)
            return
        if self.broker.sell_all(sym):
            store.pos_meta_delete(sym)
            store.log_trade(sym, meta_sleeve, "sell", pos["market_value"], reason,
                            detail=f"pnl={pos['unrealized_pl']:+.2f}")
            send(f"SELL {sym} ({meta_sleeve}, {reason}) "
                 f"${pos['market_value']:,.0f} pnl {pos['unrealized_pl']:+.2f}")

    def _execute_buy(self, order: dict, features: dict[str, pd.DataFrame],
                     equity: float, cash: float, brake: DrawdownBrake) -> float:
        """Returns dollars spent (0 if skipped)."""
        sym = order["symbol"]
        overlay = news_overlay.current()
        if sym in overlay.get("avoid", []):
            log.info("skip buy %s: news overlay veto", sym)
            return 0.0
        feats = features.get(sym)
        if feats is None or feats.empty:
            return 0.0
        row = feats.iloc[-1]
        price = self.broker.latest_price(sym) or float(row["close"])
        atr_val = float(row["atr"])
        if pd.isna(atr_val) or atr_val <= 0:
            return 0.0
        dollars = position_dollars(
            equity=equity, slot_weight=order["slot_weight"], price=price,
            atr_value=atr_val, stop_mult=order["stop_mult"],
            dd_scale=brake.scale(equity) * overlay.get("tilt", 1.0),
        )
        dollars = min(dollars, cash * 0.98)
        if dollars < config.MIN_ORDER_NOTIONAL:
            return 0.0
        if self.broker.buy_notional(sym, dollars) is None:
            return 0.0
        stop = price - order["stop_mult"] * atr_val
        store.pos_meta_upsert(sym, order["sleeve"], stop, order["stop_mult"],
                              datetime.now(timezone.utc).isoformat())
        store.log_trade(sym, order["sleeve"], "buy", dollars, order.get("reason", "signal"))
        send(f"BUY {sym} ({order['sleeve']}) ${dollars:,.0f} stop≈{stop:,.2f}")
        return dollars

    # ------------------------------------------------------------------
    # scheduled jobs
    # ------------------------------------------------------------------
    def job_daily_decision(self) -> None:
        """16:35 ET — compute signals on closed daily bars, queue orders."""
        crypto_syms, defensive_syms = self._trend_universe()
        symbols = config.EQUITY_UNIVERSE + crypto_syms + defensive_syms
        features = self._features(symbols)
        if config.REGIME_SYMBOL not in features:
            log.error("no SPY data; skipping decision")
            return

        equity = self.broker.equity()
        cash = self.broker.cash()
        brake = self._brake()
        if brake.peak_equity <= 0:
            brake.peak_equity = equity
        brake.update(equity)
        self._save_brake(brake)

        broker_positions = self.broker.positions()
        metas = self._pos_metas(broker_positions)

        # update trailing stops and holding-day counters on today's close
        for sym, meta in metas.items():
            feats = features.get(sym)
            if feats is None or feats.empty:
                continue
            row = feats.iloc[-1]
            close, atr_val = float(row["close"]), float(row["atr"])
            stored = store.pos_meta_all().get(sym, {})
            mult = stored.get("stop_mult") or config.MOMENTUM_STOP_ATR
            new_stop = close - mult * atr_val
            level = max(meta.stop_level or -1e18, new_stop)
            held = meta.held_days + 1
            store.pos_meta_update_stop(sym, level, held)
            meta.stop_level, meta.held_days = level, held

        reg = regime.classify(features[config.REGIME_SYMBOL])
        store.set("regime", {"regime": reg, "exposure": regime.exposure(reg),
                             "ts": datetime.now(timezone.utc).isoformat()})

        if brake.halted:
            send(f"Drawdown hard brake active (dd {brake.drawdown(equity):.1%}) — liquidating")
            for sym, meta in metas.items():
                self._execute_sell(sym, meta.sleeve, "dd-halt", broker_positions)
            store.pending_clear()
            store.log_equity(equity, cash, reg)
            return

        rows = {s: f.iloc[-1] for s, f in features.items()}
        from .config import settings
        now_et = datetime.now(ZoneInfo(settings.timezone))
        week_rollover = now_et.weekday() == 4  # Friday decision -> Monday fill
        orders = decide(
            rows=rows, positions=metas,
            stock_syms=[s for s in config.EQUITY_UNIVERSE if s in rows],
            crypto_syms=[s for s in crypto_syms if s in rows],
            defensive_syms=[s for s in defensive_syms if s in rows],
            reg=reg, week_rollover=week_rollover,
        )
        immediate = self._immediate_sleeves()
        stock_orders = [o for o in orders if o.sleeve not in immediate]
        store.pending_replace(stock_orders)
        store.log_equity(equity, cash, reg)

        summary = ", ".join(f"{o.side} {o.symbol}({o.reason or o.sleeve})" for o in stock_orders) or "none"
        msg = (f"close {datetime.now().date()} | equity ${equity:,.0f} | {reg} "
               f"| dd {brake.drawdown(equity):.1%}\nqueued: {summary}")
        send(msg)
        log_activity("decision", msg)

    def job_execute_open(self) -> None:
        """09:31 ET — execute orders queued after yesterday's close."""
        pending = store.pending_all()
        if not pending:
            log_activity("open", "장 시작 — 예약 주문 없음")
            return
        if not self.broker.market_open_now():
            log.info("market closed; keeping pending orders")
            return
        features = self._features(config.EQUITY_UNIVERSE)
        equity = self.broker.equity()
        cash = self.broker.cash()
        brake = self._brake()
        broker_positions = self.broker.positions()

        for o in [p for p in pending if p["side"] == "sell"]:
            self._execute_sell(o["symbol"], o["sleeve"], o["reason"], broker_positions)
        cash = self.broker.cash()
        for o in [p for p in pending if p["side"] == "buy"]:
            if o["symbol"] in broker_positions:
                continue
            spent = self._execute_buy(o, features, equity, cash, brake)
            cash -= spent
        store.pending_clear()
        log_activity("open", f"장 시작 — {len(pending)}건 예약 주문 처리 완료")

    def job_crypto(self) -> None:
        """Hourly — crypto trend, or liquidate when disabled (NJ)."""
        if not settings.crypto_enabled:
            n = self._liquidate_crypto_positions()
            if n:
                log.info("liquidated %d crypto position(s)", n)
            return
        crypto_syms, _ = self._trend_universe()
        features = self._features(crypto_syms)
        if not features:
            return
        equity = self.broker.equity()
        cash = self.broker.cash()
        brake = self._brake()
        brake.update(equity)
        self._save_brake(brake)
        broker_positions = self.broker.positions()
        metas = {s: m for s, m in self._pos_metas(broker_positions).items()
                 if s in crypto_syms}

        slot = config.CRYPTO_MAX_WEIGHT / max(len(crypto_syms), 1)
        for sym in crypto_syms:
            feats = features.get(sym)
            if feats is None or feats.empty:
                continue
            row = feats.iloc[-1]
            held = sym in metas
            long_ok = strategy.trend_long(row)
            price = self.broker.latest_price(sym) or float(row["close"])
            if held:
                meta = metas[sym]
                stop_hit = meta.stop_level is not None and price <= meta.stop_level
                if not long_ok or stop_hit or brake.halted:
                    reason = "stop" if stop_hit else ("dd-halt" if brake.halted else "trend-off")
                    self._execute_sell(sym, CRYPTO, reason, broker_positions)
            elif long_ok and not brake.halted:
                order = {"symbol": sym, "sleeve": CRYPTO, "slot_weight": slot,
                         "stop_mult": config.MOMENTUM_STOP_ATR, "reason": "trend-on"}
                spent = self._execute_buy(order, features, equity, cash, brake)
                cash -= spent
        log_activity("crypto", "크립토 슬리브 점검 완료")

    def job_intraday_stops(self) -> None:
        """Every 30 min in RTH — sell stock positions that breached their stop."""
        if not self.broker.market_open_now():
            return
        crypto_syms, _ = self._trend_universe()
        broker_positions = self.broker.positions()
        metas = self._pos_metas(broker_positions)
        sold = []
        for sym, meta in metas.items():
            if sym in crypto_syms or meta.stop_level is None:
                continue
            price = broker_positions[sym]["current_price"]
            if price <= meta.stop_level:
                self._execute_sell(sym, meta.sleeve, "intraday-stop", broker_positions)
                sold.append(sym)
        if sold:
            log_activity("stops", f"장중 손절: {', '.join(sold)}")

    def job_news_overlay(self) -> None:
        """08:45 ET — optional LLM tilt from headlines."""
        result = news_overlay.run_overlay(self.broker)
        if result.get("summary"):
            msg = f"{result['summary']} (tilt {result['tilt']:.2f})"
            send(msg)
            log_activity("news", msg)
        else:
            log_activity("news", "뉴스 오버레이 — 특이 헤드라인 없음")

    def snapshot(self) -> dict:
        """Current state for the dashboard."""
        try:
            equity = self.broker.equity()
            cash = self.broker.cash()
            broker_positions = self.broker.positions()
        except Exception as exc:
            return {"error": f"broker unavailable: {exc}"}
        metas = store.pos_meta_all()
        positions = []
        for sym, p in broker_positions.items():
            m = metas.get(sym, {})
            is_legacy_crypto = not settings.crypto_enabled and "/" in sym
            positions.append({
                "symbol": sym,
                "sleeve": "crypto (청산 대기)" if is_legacy_crypto else m.get("sleeve", "?"),
                "qty": p["qty"], "market_value": p["market_value"],
                "avg_entry": p["avg_entry"], "current_price": p["current_price"],
                "unrealized_pl": p["unrealized_pl"],
                "stop_level": m.get("stop_level"),
            })
        brake = self._brake()
        snap = {
            "mode": settings_mode(),
            "equity": equity, "cash": cash,
            "drawdown": brake.drawdown(equity), "halted": brake.halted,
            "regime": store.get("regime", {}),
            "news_overlay": news_overlay.current(),
            "positions": positions,
            "pending": store.pending_all(),
            "trades": store.recent_trades(50),
            "equity_curve": store.equity_curve(),
            "crypto_enabled": settings.crypto_enabled,
            "sleeves": (
                ["momentum", "dip", "crypto"] if settings.crypto_enabled
                else ["momentum", "dip", "defensive (GLD/TLT/IEF)"]
            ),
        }
        snap["briefing"] = build_briefing(snap)
        return snap


def settings_mode() -> str:
    from .alpaca_config import get_trading_mode
    return get_trading_mode()
