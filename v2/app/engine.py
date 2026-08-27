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
import uuid
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

_ALPACA_ATTEMPTS_KEY = "alpaca_order_attempts"
_ALPACA_FILLED = frozenset({"filled"})
_ALPACA_TERMINAL_FAILURE = frozenset({
    "canceled", "expired", "rejected", "replaced", "suspended",
    "calculated", "done_for_day",
})
_EMERGENCY_SELL_REASONS = frozenset({
    "stop", "intraday-stop", "opening-stop", "dd-halt",
})


def _alpaca_status(order) -> str:
    if isinstance(order, dict):
        value = order.get("status")
    else:
        value = getattr(order, "status", "")
    return str(getattr(value, "value", value) or "").lower()


def _carry_unexecuted_sells(
    new_orders: list[PendingOrder],
    old_pending: list[dict],
    broker_positions: dict[str, dict],
) -> list[PendingOrder]:
    """Carry held-position exits; discard stale buys and duplicate decisions."""
    new_symbols = {o.symbol for o in new_orders}
    carried = [
        PendingOrder(
            o["symbol"], o["sleeve"], "sell",
            reason=o.get("reason") or "carried-exit",
        )
        for o in old_pending
        if o["side"] == "sell"
        and o["symbol"] in broker_positions
        and o["symbol"] not in new_symbols
    ]
    return carried + new_orders


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
    def _features(
        self, symbols: list[str], *, completed_only: bool = False
    ) -> dict[str, pd.DataFrame]:
        bars = self.broker.daily_bars(symbols)
        if completed_only:
            # At 09:31 Alpaca may include a partial bar for today. Using that
            # bar's one-minute ATR/close to size an order is look-ahead versus
            # the backtest and can create unstable stops. Opening orders must
            # use indicators through the previous completed session.
            today_et = pd.Timestamp(datetime.now(ZoneInfo(settings.timezone)).date())
            bars = {s: df.loc[df.index < today_et] for s, df in bars.items()}
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
            if self._execute_sell(sym, "crypto", "crypto-disabled", broker_positions):
                sold.append(sym)
        log_activity("crypto", f"크립토 미지원 지역 — 청산 시도: {', '.join(sold)}")
        return len(sold)

    def _pos_metas(self, broker_positions: dict[str, dict]) -> dict[str, PosMeta]:
        """Merge broker positions with local stop/sleeve metadata.

        Positions the bot doesn't know about are deliberately left unmanaged;
        silently adopting a manual holding would let weekly rotation sell it.
        """
        metas = store.pos_meta_all()
        out: dict[str, PosMeta] = {}
        for sym in broker_positions:
            if not settings.crypto_enabled and self._is_crypto_symbol(sym):
                continue  # legacy crypto — do not adopt; liquidate instead
            m = metas.get(sym)
            if m is None:
                continue
            out[sym] = PosMeta(
                symbol=sym, sleeve=m["sleeve"], held_days=m.get("held_days", 0) or 0,
                stop_level=m.get("stop_level"),
                entry_price=broker_positions[sym].get("avg_entry"),
            )
        # clean up metadata for positions that no longer exist at the broker
        for sym in list(metas):
            if sym not in broker_positions:
                store.pos_meta_delete(sym)
        return out

    def _attempt_key(self, side: str, sym: str, sleeve: str, reason: str) -> str:
        return "|".join((side, sym, sleeve or "", reason or "signal"))

    def _ensure_attempt(
        self, side: str, sym: str, sleeve: str, reason: str
    ) -> tuple[str, dict]:
        attempts = store.get(_ALPACA_ATTEMPTS_KEY, {}) or {}
        key = self._attempt_key(side, sym, sleeve, reason)
        attempt = attempts.get(key)
        if not isinstance(attempt, dict) or not attempt.get("client_order_id"):
            attempt = {
                "client_order_id": str(uuid.uuid4()),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "prepared",
            }
            attempts[key] = attempt
            # Persist before the network call. A timeout after broker acceptance
            # can then be reconciled instead of submitted again.
            store.set(_ALPACA_ATTEMPTS_KEY, attempts)
        return key, dict(attempt)

    def _existing_attempt(
        self, side: str, sym: str, sleeve: str, reason: str
    ) -> tuple[str, dict | None]:
        key = self._attempt_key(side, sym, sleeve, reason)
        attempts = store.get(_ALPACA_ATTEMPTS_KEY, {}) or {}
        attempt = attempts.get(key)
        return key, dict(attempt) if isinstance(attempt, dict) else None

    def _update_attempt(self, key: str, **changes) -> None:
        attempts = store.get(_ALPACA_ATTEMPTS_KEY, {}) or {}
        if key not in attempts:
            return
        attempts[key] = {**attempts[key], **changes}
        store.set(_ALPACA_ATTEMPTS_KEY, attempts)

    def _clear_attempt(self, key: str) -> None:
        attempts = store.get(_ALPACA_ATTEMPTS_KEY, {}) or {}
        if key in attempts:
            del attempts[key]
            store.set(_ALPACA_ATTEMPTS_KEY, attempts)

    def _latest_order(self, result):
        """Poll briefly, then cancel a resting limit for fresh-price retry."""
        if not isinstance(result, dict):
            return result
        status = _alpaca_status(result)
        order_id = str(result.get("id") or "")
        if status not in _ALPACA_FILLED | _ALPACA_TERMINAL_FAILURE and order_id:
            waiter = getattr(self.broker, "wait_for_order", None)
            if callable(waiter):
                latest = waiter(order_id, timeout=12)
                if latest:
                    result = latest
                    status = _alpaca_status(result)
            if status not in _ALPACA_FILLED | _ALPACA_TERMINAL_FAILURE:
                cancel = getattr(self.broker, "cancel_order", None)
                if callable(cancel) and cancel(order_id):
                    waiter = getattr(self.broker, "wait_for_order", None)
                    if callable(waiter):
                        canceled = waiter(order_id, timeout=5)
                        if canceled:
                            return canceled
        return result

    def _marketable_limit_price(
        self, sym: str, side: str, reference: float, *, emergency: bool = False
    ) -> float:
        calculator = getattr(self.broker, "marketable_limit_price", None)
        if callable(calculator):
            return float(calculator(
                sym, side, reference_price=reference, emergency=emergency
            ))
        # Compatibility for simple dry-run/test brokers.
        factor = 0.99 if emergency and side == "sell" else (
            1.0025 if side == "buy" else 0.9975
        )
        return round(float(reference) * factor, 4 if reference < 1 else 2)

    def _execute_sell(self, sym: str, meta_sleeve: str, reason: str,
                      broker_positions: dict[str, dict]) -> bool:
        """Returns True when the position is gone (sold or already absent)."""
        pos = broker_positions.get(sym)
        if pos is None:
            store.pos_meta_delete(sym)
            key = self._attempt_key("sell", sym, meta_sleeve, reason)
            self._clear_attempt(key)
            return True
        key, attempt = self._ensure_attempt("sell", sym, meta_sleeve, reason)
        cid = attempt["client_order_id"]
        limit_price = float(attempt.get("limit_price") or 0)
        if limit_price <= 0:
            reference = float(pos.get("current_price") or 0)
            if reference <= 0 and float(pos.get("qty") or 0) != 0:
                reference = abs(
                    float(pos.get("market_value") or 0) / float(pos["qty"])
                )
            try:
                limit_price = self._marketable_limit_price(
                    sym, "sell", reference,
                    emergency=reason in _EMERGENCY_SELL_REASONS,
                )
            except Exception as exc:
                log.error("sell %s limit price failed: %s", sym, exc)
                self._update_attempt(key, status="quote-failed")
                return False
            attempt["limit_price"] = limit_price
            self._update_attempt(key, limit_price=limit_price)
        try:
            submitted = self.broker.sell_all(
                sym, qty=pos["qty"], client_order_id=cid,
                limit_price=limit_price,
            )
        except TypeError:
            # Backward-compatible test/dry-run broker.
            try:
                submitted = self.broker.sell_all(
                    sym, qty=pos["qty"], client_order_id=cid
                )
            except TypeError:
                submitted = self.broker.sell_all(sym)
        if submitted is True:
            final = {"status": "filled"}
        elif not submitted:
            self._update_attempt(key, status="unknown")
            return False
        else:
            final = self._latest_order(submitted)
        status = _alpaca_status(final)
        if isinstance(final, dict):
            self._update_attempt(
                key,
                broker_order_id=final.get("id"),
                status=status or "unknown",
            )
        gone = False
        try:
            gone = sym not in self.broker.positions()
        except Exception:
            pass
        if status in _ALPACA_FILLED or gone:
            store.pos_meta_delete(sym)
            filled_qty = float(final.get("filled_qty") or 0) if isinstance(final, dict) else 0
            filled_avg = float(final.get("filled_avg_price") or 0) if isinstance(final, dict) else 0
            notional = filled_qty * filled_avg if filled_qty > 0 and filled_avg > 0 else pos["market_value"]
            store.log_trade(sym, meta_sleeve, "sell", notional, reason,
                            detail=f"pnl={pos['unrealized_pl']:+.2f}")
            send(f"SELL {sym} ({meta_sleeve}, {reason}) "
                 f"${notional:,.0f} pnl {pos['unrealized_pl']:+.2f}")
            self._clear_attempt(key)
            return True
        if status in _ALPACA_TERMINAL_FAILURE:
            # A partial/canceled sell leaves a smaller live position; the next
            # tick gets a fresh id and sells the remaining broker quantity.
            self._clear_attempt(key)
        return False

    def _execute_buy(self, order: dict, features: dict[str, pd.DataFrame],
                     equity: float, cash: float, brake: DrawdownBrake) -> float | None:
        """Returns dollars spent. 0.0 means intentionally skipped (do not
        retry); None means the order submit failed (caller may retry)."""
        sym = order["symbol"]
        reason = order.get("reason", "signal") or "signal"
        key, existing_attempt = self._existing_attempt(
            "buy", sym, order["sleeve"], reason
        )
        feats = features.get(sym)
        if feats is None or feats.empty:
            # Never discard an already-submitted order just because market data
            # is temporarily unavailable; keep it queued for reconciliation.
            return None if existing_attempt else 0.0
        row = feats.iloc[-1]
        price = self.broker.latest_price(sym) or float(row["close"])
        atr_val = float(
            (existing_attempt or {}).get("atr_value") or row["atr"]
        )
        if pd.isna(atr_val) or atr_val <= 0:
            return None if existing_attempt else 0.0
        if existing_attempt:
            dollars = float(existing_attempt.get("requested_dollars") or 0)
            attempt = existing_attempt
            if dollars <= 0:
                # Legacy/incomplete attempt state: fail closed until an operator
                # clears it instead of guessing a second order size.
                return None
        else:
            overlay = news_overlay.current()
            if sym in overlay.get("avoid", []):
                log.info("skip buy %s: news overlay veto", sym)
                return 0.0
            dollars = position_dollars(
                equity=equity, slot_weight=order["slot_weight"], price=price,
                atr_value=atr_val, stop_mult=order["stop_mult"],
                dd_scale=brake.scale(equity) * overlay.get("tilt", 1.0),
            )
            dollars = min(dollars, cash * 0.98)
            if dollars < config.MIN_ORDER_NOTIONAL:
                return 0.0
            key, attempt = self._ensure_attempt(
                "buy", sym, order["sleeve"], reason
            )
            self._update_attempt(
                key,
                requested_dollars=dollars,
                atr_value=atr_val,
                reference_price=price,
            )
        limit_price = float(attempt.get("limit_price") or 0)
        if limit_price <= 0:
            try:
                limit_price = self._marketable_limit_price(sym, "buy", price)
            except Exception as exc:
                log.error("buy %s limit price failed: %s", sym, exc)
                self._update_attempt(key, status="quote-failed")
                return None
            attempt["limit_price"] = limit_price
            self._update_attempt(key, limit_price=limit_price)
        cid = attempt["client_order_id"]
        try:
            submitted = self.broker.buy_notional(
                sym, dollars, client_order_id=cid,
                limit_price=limit_price,
            )
        except TypeError:
            # Backward-compatible test/dry-run broker.
            try:
                submitted = self.broker.buy_notional(
                    sym, dollars, client_order_id=cid
                )
            except TypeError:
                submitted = self.broker.buy_notional(sym, dollars)
        if submitted is None:
            self._update_attempt(key, status="unknown")
            return None
        if isinstance(submitted, str):
            final = {"id": submitted, "status": "filled"}
        else:
            final = self._latest_order(submitted)
        status = _alpaca_status(final)
        if isinstance(final, dict):
            self._update_attempt(
                key,
                broker_order_id=final.get("id"),
                status=status or "unknown",
            )
        filled_qty = float(final.get("filled_qty") or 0) if isinstance(final, dict) else 0
        filled_avg = float(final.get("filled_avg_price") or 0) if isinstance(final, dict) else 0
        partial_terminal = status in _ALPACA_TERMINAL_FAILURE and filled_qty > 0
        if status not in _ALPACA_FILLED and not partial_terminal:
            if status in _ALPACA_TERMINAL_FAILURE:
                self._clear_attempt(key)
            return None
        actual_dollars = (
            filled_qty * filled_avg
            if filled_qty > 0 and filled_avg > 0
            else dollars
        )
        fill_price = filled_avg if filled_avg > 0 else price
        stop = fill_price - order["stop_mult"] * atr_val
        store.pos_meta_upsert(sym, order["sleeve"], stop, order["stop_mult"],
                              datetime.now(timezone.utc).isoformat())
        store.log_trade(sym, order["sleeve"], "buy", actual_dollars, reason)
        send(f"BUY {sym} ({order['sleeve']}) ${actual_dollars:,.0f} stop≈{stop:,.2f}")
        self._clear_attempt(key)
        return actual_dollars

    # ------------------------------------------------------------------
    # scheduled jobs
    # ------------------------------------------------------------------
    def job_daily_decision(self) -> bool:
        """16:35 ET — compute signals on closed daily bars, queue orders.

        Returns False when the job could not complete and should be retried
        on the next cron tick (the caller must NOT mark it as done)."""
        crypto_syms, defensive_syms = self._trend_universe()
        symbols = config.EQUITY_UNIVERSE + crypto_syms + defensive_syms
        features = self._features(symbols)
        if config.REGIME_SYMBOL not in features:
            log.error("no SPY data; will retry decision on next tick")
            return False

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
            failed_liquidations: list[PendingOrder] = []
            for sym, meta in metas.items():
                if not self._execute_sell(
                    sym, meta.sleeve, "dd-halt", broker_positions
                ):
                    failed_liquidations.append(PendingOrder(
                        sym, meta.sleeve, "sell", reason="dd-halt"
                    ))
            store.pending_replace(failed_liquidations)
            store.log_equity(equity, cash, reg)
            if failed_liquidations:
                log_activity(
                    "decision",
                    "드로다운 청산 미확인 — 재시도: "
                    + ", ".join(o.symbol for o in failed_liquidations),
                )
                return False
            return True

        rows = {s: f.iloc[-1] for s, f in features.items()}
        now_et = datetime.now(ZoneInfo(settings.timezone))
        next_open = self.broker.next_market_open()
        # Holiday-aware: rebalance on the session before Monday, which can be
        # Thursday when Friday is a market holiday.
        week_rollover = (
            next_open.astimezone(ZoneInfo(settings.timezone)).weekday()
            == config.MOMENTUM_REBALANCE_WEEKDAY
            if next_open is not None
            else now_et.weekday() == 4
        )
        orders = decide(
            rows=rows, positions=metas,
            stock_syms=[s for s in config.MOMENTUM_UNIVERSE if s in rows],
            crypto_syms=[s for s in crypto_syms if s in rows],
            defensive_syms=[s for s in defensive_syms if s in rows],
            reg=reg, week_rollover=week_rollover,
        )
        manual_symbols = set(broker_positions) - set(metas)
        orders = [
            o for o in orders
            if not (o.side == "buy" and o.symbol in manual_symbols)
        ]
        immediate = self._immediate_sleeves()
        stock_orders = [o for o in orders if o.sleeve not in immediate]

        # If the open executor was unavailable all day, do not let the close
        # decision silently erase an unexecuted exit. Old buys are deliberately
        # discarded (the signal is stale); sells for positions still held are
        # carried forward unless today's fresh decision already covers them.
        # Buys that already reached Alpaca are also carried so their durable
        # client id can be reconciled rather than orphaned at the close.
        old_pending = store.pending_all()
        attempts = store.get(_ALPACA_ATTEMPTS_KEY, {}) or {}
        submitted_buys = [
            PendingOrder(
                o["symbol"], o["sleeve"], "buy",
                slot_weight=float(o.get("slot_weight") or 0),
                stop_mult=float(o.get("stop_mult") or 0),
                reason=o.get("reason") or "signal",
            )
            for o in old_pending
            if o["side"] == "buy"
            and self._attempt_key(
                "buy", o["symbol"], o["sleeve"], o.get("reason") or "signal"
            ) in attempts
        ]
        submitted_symbols = {o.symbol for o in submitted_buys}
        stock_orders = [
            o for o in stock_orders
            if not (o.side == "buy" and o.symbol in submitted_symbols)
        ]
        stock_orders = submitted_buys + stock_orders
        merged_orders = _carry_unexecuted_sells(
            stock_orders, old_pending, broker_positions
        )
        carried_sells = merged_orders[:len(merged_orders) - len(stock_orders)]
        if carried_sells:
            log_activity(
                "decision",
                "미체결 매도 승계: " + ", ".join(o.symbol for o in carried_sells),
            )
        stock_orders = merged_orders
        store.pending_replace(stock_orders)
        store.log_equity(equity, cash, reg)

        summary = ", ".join(f"{o.side} {o.symbol}({o.reason or o.sleeve})" for o in stock_orders) or "none"
        msg = (f"close {datetime.now().date()} | equity ${equity:,.0f} | {reg} "
               f"| dd {brake.drawdown(equity):.1%}\nqueued: {summary}")
        send(msg)
        log_activity("decision", msg)
        return True

    def job_execute_open(self) -> bool:
        """09:31 ET — execute orders queued after yesterday's close.

        Returns False when the market is not open yet so the cron caller
        retries on the next tick instead of marking the job done for the day
        (that bug silently dropped a whole day's queued orders)."""
        if not self.broker.market_open_now():
            log.info("market not open yet; keeping pending orders, will retry")
            return False

        pending = store.pending_all()
        equity = self.broker.equity()
        broker_positions = self.broker.positions()

        # Re-evaluate the drawdown brake on opening equity. An overnight gap
        # can breach the hard limit after yesterday's 16:35 check; without
        # this, queued buys would still execute at half size.
        brake = self._brake()
        if brake.peak_equity <= 0:
            brake.peak_equity = equity
        brake.update(equity)
        self._save_brake(brake)
        if brake.halted:
            send(f"Drawdown hard brake at open (dd {brake.drawdown(equity):.1%}) "
                 f"— liquidating, queued buys cancelled")
            metas = self._pos_metas(broker_positions)
            failed_liquidations: list[dict] = []
            for sym, meta in metas.items():
                if not self._execute_sell(
                    sym, meta.sleeve, "dd-halt", broker_positions
                ):
                    failed_liquidations.append({
                        "symbol": sym,
                        "sleeve": meta.sleeve,
                        "side": "sell",
                        "slot_weight": 0.0,
                        "stop_mult": 0.0,
                        "reason": "dd-halt",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
            if failed_liquidations:
                store.pending_replace_dicts(failed_liquidations)
                log_activity(
                    "open",
                    "드로다운 하드 브레이크 — 예약 매수 취소, 청산 재시도: "
                    + ", ".join(o["symbol"] for o in failed_liquidations),
                )
                return False
            store.pending_clear()
            log_activity("open", "드로다운 하드 브레이크 — 전량 청산, 예약 매수 취소")
            return True

        # Enforce stored stops immediately after the opening bell, even when
        # there are no queued orders. The separate stops job may not be called
        # until 09:45 with a 15-minute external scheduler.
        queued_sells = {o["symbol"] for o in pending if o["side"] == "sell"}
        opening_stops: list[str] = []
        for sym, meta in self._pos_metas(broker_positions).items():
            pos = broker_positions.get(sym)
            if (
                pos is not None
                and meta.stop_level is not None
                and pos["current_price"] <= meta.stop_level
                and sym not in queued_sells
            ):
                if self._execute_sell(
                    sym, meta.sleeve, "opening-stop", broker_positions
                ):
                    opening_stops.append(sym)
        if opening_stops:
            self.broker.wait_for_fills(timeout=45)
            log_activity("stops", f"개장 손절: {', '.join(opening_stops)}")

        if not pending:
            log_activity("open", "장 시작 — 예약 주문 없음")
            return True

        features = self._features(config.EQUITY_UNIVERSE, completed_only=True)
        failed: list[dict] = []

        sells = [p for p in pending if p["side"] == "sell"]
        for o in sells:
            try:
                ok = self._execute_sell(o["symbol"], o["sleeve"], o["reason"], broker_positions)
            except Exception:
                log.exception("open sell %s failed", o["symbol"])
                ok = False
            if not ok:
                failed.append(o)
        if sells:
            # Market sells take a few seconds to fill; without this wait the
            # cash read below is stale and buys get skipped or undersized.
            fills_done = self.broker.wait_for_fills(timeout=45)
            broker_positions = self.broker.positions()
            unresolved = [
                o for o in sells
                if o["symbol"] in broker_positions
                and not any(f.get("id") == o.get("id") for f in failed)
            ]
            failed.extend(unresolved)
            if not fills_done or failed:
                # Never spend against unconfirmed sale proceeds. Keep every
                # buy plus unresolved sells for the next scheduler tick.
                retry = failed + [p for p in pending if p["side"] == "buy"]
                store.pending_replace_dicts(retry)
                names = ", ".join(o["symbol"] for o in failed) or "fill confirmation"
                log_activity(
                    "open",
                    f"매도 미완료({names}) — 예약 매수 {len(retry) - len(failed)}건 보류",
                )
                return False
        cash = self.broker.cash()
        for o in [p for p in pending if p["side"] == "buy"]:
            _, existing_attempt = self._existing_attempt(
                "buy", o["symbol"], o["sleeve"], o.get("reason") or "signal"
            )
            if o["symbol"] in broker_positions and not existing_attempt:
                continue
            try:
                spent = self._execute_buy(o, features, equity, cash, brake)
            except Exception:
                log.exception("open buy %s failed", o["symbol"])
                spent = None
            if spent is None:
                failed.append(o)
            else:
                cash -= spent

        if failed:
            # Keep ONLY the failed orders queued and retry on the next tick.
            # Previously pending_clear() ran unconditionally, so one broker
            # error silently dropped the rest of the day's orders.
            store.pending_replace_dicts(failed)
            names = ", ".join(o["symbol"] for o in failed)
            log_activity("open", f"장 시작 — {len(pending) - len(failed)}건 처리, "
                                 f"실패 {len(failed)}건 재시도 예정: {names}")
            return False
        store.pending_clear()
        log_activity("open", f"장 시작 — {len(pending)}건 예약 주문 처리 완료")
        return True

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
            if sym in broker_positions and sym not in metas:
                continue
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
                cash -= spent or 0.0  # None = submit failed; hourly job retries
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
                if self._execute_sell(
                    sym, meta.sleeve, "intraday-stop", broker_positions
                ):
                    sold.append(sym)
        if sold:
            log_activity("stops", f"장중 손절: {', '.join(sold)}")
        # Intraday equity point so the dashboard curve moves during the day
        # (previously only one point per day at the 16:35 decision).
        reg = store.get("regime", {}).get("regime", "CHOP")
        store.log_equity(self.broker.equity(), self.broker.cash(), reg)

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
        # Unknown broker positions remain visible but unmanaged. This prevents
        # a manually purchased holding from being sold by weekly rotation.
        try:
            adopted = self._pos_metas(broker_positions)
        except Exception:
            adopted = {}
        metas = store.pos_meta_all()
        positions = []
        for sym, p in broker_positions.items():
            m = metas.get(sym) or {}
            ad = adopted.get(sym)
            is_legacy_crypto = not settings.crypto_enabled and "/" in sym
            sleeve = (
                "crypto (청산 대기)" if is_legacy_crypto
                else (m.get("sleeve") or (ad.sleeve if ad else "manual (미관리)"))
            )
            positions.append({
                "symbol": sym,
                "sleeve": sleeve,
                "qty": p["qty"], "market_value": p["market_value"],
                "avg_entry": p["avg_entry"], "current_price": p["current_price"],
                "unrealized_pl": p["unrealized_pl"],
                "stop_level": m.get("stop_level") if m else (ad.stop_level if ad else None),
            })
        brake = self._brake()
        storage = store.storage_health()
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
            "storage": storage,
            "sleeves": (
                ["momentum", "dip", "crypto"] if settings.crypto_enabled
                else ["momentum", "dip", "defensive (GLD/TLT/IEF)"]
            ),
        }
        if not storage.get("ok"):
            snap["error"] = (
                "상태 저장소 장애 — 주문/차트/활동이 저장되지 않습니다. "
                f"{storage.get('error', '')}"
            )
        snap["briefing"] = build_briefing(snap)
        return snap


def settings_mode() -> str:
    from .alpaca_config import get_trading_mode
    return get_trading_mode()
