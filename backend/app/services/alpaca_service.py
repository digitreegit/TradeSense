"""
TradeSense - Alpaca Trading Service
Handles all communication with Alpaca Markets API for paper trading.
Streaming-aware: prefers the WebSocket cache when available (see
``app.services.streaming_service``); falls back to REST snapshots.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest,
    GetOrdersRequest
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed

from app.core.config import settings

logger = logging.getLogger(__name__)


def _parse_alpaca_ratelimit_headers(h: httpx.Headers) -> Dict[str, Optional[int]]:
    """Parse Alpaca X-Ratelimit-* (or RFC8594) headers from a REST response."""
    norm = {k.lower(): v for k, v in h.items()}
    limit_raw = norm.get("x-ratelimit-limit") or norm.get("ratelimit-limit")
    remain_raw = norm.get("x-ratelimit-remaining") or norm.get("ratelimit-remaining")
    reset_raw = norm.get("x-ratelimit-reset") or norm.get("ratelimit-reset")

    def _to_int(val: Optional[str]) -> Optional[int]:
        if val is None or val == "":
            return None
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return None

    lim = _to_int(limit_raw)
    rem = _to_int(remain_raw)
    rst = _to_int(reset_raw)
    if rst and rst > 10_000_000_000:
        rst = rst // 1000
    return {"limit": lim, "remaining": rem, "reset_epoch": rst}


def _rate_limit_usage_block(
    limit: Optional[int],
    remaining: Optional[int],
    reset_epoch: Optional[int],
) -> Dict[str, Any]:
    used = None
    if limit is not None and remaining is not None:
        used = max(0, limit - remaining)
    pct_used = None
    if limit and limit > 0 and remaining is not None:
        pct_used = round((1.0 - remaining / limit) * 100.0, 1)
    now = datetime.now(timezone.utc).timestamp()
    reset_in_s = None
    if reset_epoch:
        reset_in_s = max(0, int(reset_epoch - now))
    return {
        "limit": limit,
        "remaining": remaining,
        "used": used,
        "reset_epoch": reset_epoch,
        "reset_in_seconds": reset_in_s,
        "percent_used": pct_used,
    }


def _resolve_feed() -> DataFeed:
    """Pick the Alpaca data feed based on configuration."""
    feed = (getattr(settings, "alpaca_data_feed", "") or "iex").lower()
    if feed == "sip":
        return DataFeed.SIP
    return DataFeed.IEX


class AlpacaService:
    """Service for interacting with Alpaca Markets API."""

    def __init__(self):
        self.trading_client: Optional[TradingClient] = None
        self.data_client: Optional[StockHistoricalDataClient] = None
        self._initialized = False
        self.paper_trading: bool = True
        self.initial_capital_override: Optional[float] = None
        self.virtual_base_equity: float = 0.0  # Used for virtual re-base to $30k
        self.is_virtual_reset = False

    def _reset_virtual_account_state(self) -> None:
        self.virtual_base_equity = 0.0
        if hasattr(self, "virtual_daily_open"):
            self.virtual_daily_open = 0.0

    def reset_paper_virtual_baseline(self) -> None:
        """Re-anchor paper virtual equity after scale or initial-capital change."""
        self._reset_virtual_account_state()

    def set_paper_trading(self, paper: bool) -> None:
        """Switch paper vs live API endpoint; clears virtual baseline on change."""
        if paper == self.paper_trading:
            return
        self.paper_trading = bool(paper)
        self._reset_virtual_account_state()
        self.trading_client = None
        self.data_client = None
        self._initialized = False

    def initialize(self):
        """Initialize Alpaca API clients from global settings (.env)."""
        _paper = (settings.trading_mode or "paper").strip().lower() != "live"
        return self.initialize_with_keys(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper_trading=_paper,
        )

    def initialize_with_keys(
        self,
        api_key: str,
        secret_key: str,
        *,
        paper_trading: bool = True,
    ) -> bool:
        """Initialize clients from explicit keys (per-user or env)."""
        self.trading_client = None
        self.data_client = None
        self._initialized = False
        self.paper_trading = bool(paper_trading)
        if not api_key or not secret_key:
            logger.warning("Alpaca API keys not configured. Running in demo mode.")
            return False
        try:
            self.trading_client = TradingClient(
                api_key=api_key,
                secret_key=secret_key,
                paper=self.paper_trading,
            )
            self.data_client = StockHistoricalDataClient(
                api_key=api_key,
                secret_key=secret_key,
            )
            self._initialized = True
            mode = "Paper Trading" if self.paper_trading else "Live Trading"
            logger.info("✅ Alpaca API clients initialized (%s)", mode)
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize Alpaca: {e}")
            self._initialized = False
            return False

    @property
    def is_ready(self) -> bool:
        if not self._initialized:
            self.initialize()
        return self._initialized

    def _initial_capital_for_display(self) -> float:
        if self.initial_capital_override is not None:
            return float(self.initial_capital_override)
        return float(settings.initial_capital)

    def _live_balances_unavailable(self, reason: str = "not_connected") -> dict:
        """Never use paper demo balances for live mode when broker data is missing."""
        return {
            "equity": 0.0,
            "cash": 0.0,
            "buying_power": 0.0,
            "portfolio_value": 0.0,
            "profit_loss": 0.0,
            "profit_loss_pct": 0.0,
            "daily_profit_loss": 0.0,
            "daily_profit_loss_pct": 0.0,
            "day_trade_count": 0,
            "pattern_day_trader": False,
            "account_blocked": False,
            "trading_blocked": False,
            "multiplier": 1.0,
            "is_margin_account": False,
            "paper_trading": self.paper_trading,
            "trading_mode": "paper" if self.paper_trading else "live",
            # Raw broker equity (e.g. UI/debug); PDT uses displayed ``equity`` + live-only PDT flag.
            "broker_equity_for_pdt": 0.0,
            "initial_capital": 0.0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "sharpe_ratio": 0.0,
            "live_balances_unavailable": True,
            "live_balances_reason": reason,
        }

    @staticmethod
    def _account_pdt_fields(account) -> dict:
        """Extract PDT / margin fields from an Alpaca account object.

        Alpaca exposes:
        - ``daytrade_count``: int (trailing 5 business days, real value only matters on margin)
        - ``pattern_day_trader``: bool — broker-side PDT flag
        - ``multiplier``: '1' (cash) | '2' (Reg-T) | '4' (PDT margin)
        - ``account_blocked`` / ``trading_blocked``: account-level halts
        """
        try:
            mult_raw = getattr(account, "multiplier", None)
            multiplier = float(mult_raw) if mult_raw is not None else 1.0
        except (TypeError, ValueError):
            multiplier = 1.0
        return {
            "day_trade_count": int(getattr(account, "daytrade_count", 0) or 0),
            "pattern_day_trader": bool(getattr(account, "pattern_day_trader", False) or False),
            "account_blocked": bool(getattr(account, "account_blocked", False) or False),
            "trading_blocked": bool(getattr(account, "trading_blocked", False) or False),
            "multiplier": multiplier,
            "is_margin_account": multiplier > 1.0,
        }

    # ─── Account ───────────────────────────────────────────────
    def get_account(self) -> dict:
        """Get account information with performance metrics."""
        if not self.is_ready:
            return self._demo_account() if self.paper_trading else self._live_balances_unavailable("not_connected")

        try:
            import numpy as np
            account = self.trading_client.get_account()

            real_equity = float(account.equity)
            real_cash = float(account.cash)

            # Live: show broker balances and P&L vs Alpaca last_equity (prior close).
            if not self.paper_trading:
                last_eq = float(getattr(account, "last_equity", None) or real_equity)
                if last_eq <= 0:
                    last_eq = real_equity
                bp = float(getattr(account, "buying_power", None) or real_cash)
                pv = float(getattr(account, "portfolio_value", None) or real_equity)
                daily_pl = real_equity - last_eq
                daily_pl_pct = (daily_pl / last_eq * 100) if last_eq > 0 else 0.0
                initial = last_eq

                metrics = {
                    "win_rate": 0.0,
                    "avg_win": 0.0,
                    "avg_loss": 0.0,
                    "profit_factor": 0.0,
                    "sharpe_ratio": 0.0,
                }
                try:
                    try:
                        from alpaca.trading.requests import GetPortfolioHistoryRequest  # type: ignore
                        history = self.trading_client.get_portfolio_history(
                            GetPortfolioHistoryRequest(period="1D", timeframe="5Min")
                        )
                    except Exception:
                        history = self.trading_client.get_portfolio_history()

                    if history and hasattr(history, "equity") and len(history.equity) > 2:
                        equities = np.array(history.equity, dtype=float)
                        equities = equities[equities > 0]
                        if len(equities) > 2:
                            returns = np.diff(equities) / equities[:-1]
                            returns = returns[np.isfinite(returns)]
                            if len(returns) > 1:
                                avg_ret = np.mean(returns)
                                std_ret = np.std(returns)
                                if std_ret > 0:
                                    factor = np.sqrt(252 * 78) if len(equities) < 100 else np.sqrt(252)
                                    metrics["sharpe_ratio"] = round((avg_ret / std_ret) * factor, 2)
                                    if metrics["sharpe_ratio"] > 10:
                                        metrics["sharpe_ratio"] = 9.99
                                elif avg_ret > 0:
                                    metrics["sharpe_ratio"] = 1.0

                    orders = self.get_orders(status="all", limit=100)
                    filled_orders = [o for o in orders if o["status"] == "filled" and o["filled_avg_price"]]

                    trades = []
                    symbols = set(o["symbol"] for o in filled_orders)
                    for sym in symbols:
                        sym_orders = [o for o in filled_orders if o["symbol"] == sym]
                        sym_orders.sort(key=lambda x: x["filled_at"] or x["submitted_at"])
                        open_qty = 0
                        entry_value = 0
                        for o in sym_orders:
                            if o["side"] == "buy":
                                open_qty += o["qty"]
                                entry_value += o["qty"] * o["filled_avg_price"]
                            elif o["side"] == "sell" and open_qty > 0:
                                close_qty = min(o["qty"], open_qty)
                                rel_entry_value = (entry_value / open_qty) * close_qty
                                realized_pnl = (o["filled_avg_price"] * close_qty) - rel_entry_value
                                trades.append(realized_pnl)
                                entry_value -= rel_entry_value
                                open_qty -= close_qty

                    if trades:
                        wins = [t for t in trades if t > 0]
                        losses = [t for t in trades if t <= 0]
                        metrics["win_rate"] = round(len(wins) / len(trades) * 100, 1)
                        metrics["avg_win"] = round(np.mean(wins), 2) if wins else 0.0
                        metrics["avg_loss"] = round(np.mean(losses), 2) if losses else 0.0
                        sum_win = sum(wins)
                        sum_loss = abs(sum(losses))
                        metrics["profit_factor"] = (
                            round(sum_win / sum_loss, 2) if sum_loss > 0 else (round(sum_win, 2) if sum_win > 0 else 0.0)
                        )
                except Exception as me:
                    logger.warning(f"Error calculating live account metrics: {me}")

                total_pl = real_equity - initial
                total_pl_pct = (total_pl / initial * 100) if initial > 0 else 0.0

                pdt_fields = self._account_pdt_fields(account)
                return {
                    "equity": round(real_equity, 2),
                    "cash": round(real_cash, 2),
                    "buying_power": round(bp, 2),
                    "portfolio_value": round(pv, 2),
                    "profit_loss": round(total_pl, 2),
                    "profit_loss_pct": round(total_pl_pct, 2),
                    "daily_profit_loss": round(daily_pl, 2),
                    "daily_profit_loss_pct": round(daily_pl_pct, 2),
                    "initial_capital": round(initial, 2),
                    "paper_trading": self.paper_trading,
                    "trading_mode": "paper" if self.paper_trading else "live",
                    # Same as ``equity`` on live; on paper = raw Alpaca equity (UI/debug only).
                    "broker_equity_for_pdt": round(real_equity, 2),
                    **pdt_fields,
                    **metrics,
                }

            initial_cfg = self._initial_capital_for_display()

            if self.virtual_base_equity == 0:
                self.virtual_base_equity = real_equity
                logger.info(
                    "🔄 Virtual Portfolio Reset: Real Equity $%s -> Displayed Start at $%s",
                    real_equity, initial_cfg,
                )

            pl_since_reset = real_equity - self.virtual_base_equity
            equity = initial_cfg + pl_since_reset

            if not hasattr(self, 'virtual_daily_open') or self.virtual_daily_open == 0:
                self.virtual_daily_open = initial_cfg

            daily_profit_loss = equity - self.virtual_daily_open
            daily_profit_loss_pct = (
                (daily_profit_loss / self.virtual_daily_open * 100)
                if self.virtual_daily_open > 0 else 0
            )

            real_market_value = real_equity - real_cash
            capped_market_value = min(real_market_value, equity * 0.95)
            displayed_cash = equity - capped_market_value
            displayed_bp = displayed_cash

            pv = equity
            initial = initial_cfg

            total_profit_loss = equity - initial
            total_profit_loss_pct = (total_profit_loss / initial) * 100 if initial > 0 else 0

            v_scaling = initial / self.virtual_base_equity if self.virtual_base_equity > 0 else 1.0

            metrics = {
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 0.0,
                "sharpe_ratio": 0.0,
            }

            try:
                # Alpaca SDK dropped the ``period`` kwarg; wrap the import so a
                # single bad signature doesn't flood the logs every scan.
                try:
                    from alpaca.trading.requests import GetPortfolioHistoryRequest  # type: ignore
                    history = self.trading_client.get_portfolio_history(
                        GetPortfolioHistoryRequest(period="1D", timeframe="5Min")
                    )
                except Exception:
                    history = self.trading_client.get_portfolio_history()

                if history and hasattr(history, "equity") and len(history.equity) > 2:
                    equities = np.array(history.equity, dtype=float)
                    equities = equities[equities > 0]
                    if len(equities) > 2:
                        returns = np.diff(equities) / equities[:-1]
                        returns = returns[np.isfinite(returns)]
                        if len(returns) > 1:
                            avg_ret = np.mean(returns)
                            std_ret = np.std(returns)
                            if std_ret > 0:
                                factor = np.sqrt(252 * 78) if len(equities) < 100 else np.sqrt(252)
                                metrics["sharpe_ratio"] = round((avg_ret / std_ret) * factor, 2)
                                if metrics["sharpe_ratio"] > 10:
                                    metrics["sharpe_ratio"] = 9.99
                            elif avg_ret > 0:
                                metrics["sharpe_ratio"] = 1.0

                orders = self.get_orders(status="all", limit=100)
                filled_orders = [o for o in orders if o["status"] == "filled" and o["filled_avg_price"]]

                trades = []
                symbols = set(o["symbol"] for o in filled_orders)
                for sym in symbols:
                    sym_orders = [o for o in filled_orders if o["symbol"] == sym]
                    sym_orders.sort(key=lambda x: x["filled_at"] or x["submitted_at"])
                    open_qty = 0
                    entry_value = 0
                    for o in sym_orders:
                        if o["side"] == "buy":
                            open_qty += o["qty"]
                            entry_value += o["qty"] * o["filled_avg_price"]
                        elif o["side"] == "sell" and open_qty > 0:
                            close_qty = min(o["qty"], open_qty)
                            rel_entry_value = (entry_value / open_qty) * close_qty
                            realized_pnl = (o["filled_avg_price"] * close_qty) - rel_entry_value
                            trades.append(realized_pnl * v_scaling)
                            entry_value -= rel_entry_value
                            open_qty -= close_qty

                if trades:
                    wins = [t for t in trades if t > 0]
                    losses = [t for t in trades if t <= 0]
                    metrics["win_rate"] = round(len(wins) / len(trades) * 100, 1)
                    metrics["avg_win"] = round(np.mean(wins), 2) if wins else 0.0
                    metrics["avg_loss"] = round(np.mean(losses), 2) if losses else 0.0
                    sum_win = sum(wins)
                    sum_loss = abs(sum(losses))
                    metrics["profit_factor"] = round(sum_win / sum_loss, 2) if sum_loss > 0 else (round(sum_win, 2) if sum_win > 0 else 0.0)

            except Exception as me:
                logger.warning(f"Error calculating detailed metrics: {me}")

            pdt_fields = self._account_pdt_fields(account)
            return {
                "equity":                round(equity, 2),
                "cash":                  round(displayed_cash, 2),
                "buying_power":          round(displayed_bp, 2),
                "portfolio_value":       round(pv, 2),
                "profit_loss":           round(total_profit_loss, 2),
                "profit_loss_pct":       round(total_profit_loss_pct, 2),
                "daily_profit_loss":     round(daily_profit_loss, 2),
                "daily_profit_loss_pct": round(daily_profit_loss_pct, 2),
                "initial_capital":       initial,
                "paper_trading":         self.paper_trading,
                "trading_mode":          "paper" if self.paper_trading else "live",
                # Raw Alpaca equity while ``equity`` is scaled for paper capital slider.
                "broker_equity_for_pdt": round(real_equity, 2),
                **pdt_fields,
                **metrics,
            }

        except Exception as e:
            logger.error(f"Error getting account: {e}")
            if not self.paper_trading:
                return self._live_balances_unavailable("fetch_error")
            return self._demo_account()

    # ─── Positions ─────────────────────────────────────────────
    def get_positions(self) -> list:
        """Get all open positions."""
        if not self.is_ready:
            return []

        try:
            positions = self.trading_client.get_all_positions()
            return [
                {
                    "symbol": p.symbol,
                    "qty": int(p.qty),
                    "avg_entry_price": float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "market_value": float(p.market_value),
                    "unrealized_pl": float(p.unrealized_pl),
                    "unrealized_plpc": float(p.unrealized_plpc),
                    "side": "long" if int(p.qty) > 0 else "short",
                }
                for p in positions
            ]
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []

    # ─── Orders ────────────────────────────────────────────────
    def submit_market_order(self, symbol: str, qty: float, side: str) -> dict:
        """Submit a market order (escape hatch). Prefer :class:`Executor` marketable limits."""
        if not self.is_ready:
            return {"error": "Alpaca not initialized"}

        try:
            if side == "sell":
                positions = self.get_positions()
                pos = next((p for p in positions if p["symbol"] == symbol), None)
                if not pos or pos["qty"] <= 0:
                    logger.warning(f"🚫 Blocked 'sell' order for {symbol}: No long position held (Cash Account)")
                    return {"error": f"Cannot sell {symbol}: No long position held (Cash Account)"}
                if qty > pos["qty"]:
                    logger.warning(f"⚠️ Adjusted 'sell' order for {symbol}: {qty} -> {pos['qty']} (Cannot over-sell)")
                    qty = pos["qty"]

            order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
            )
            order = self.trading_client.submit_order(request)
            logger.info(f"📦 Order submitted: {side.upper()} {qty} {symbol}")
            return {
                "id": str(order.id),
                "symbol": order.symbol,
                "side": side,
                "qty": float(order.qty),
                "type": "market",
                "status": str(order.status),
                "submitted_at": str(order.submitted_at),
            }
        except Exception as e:
            logger.error(f"Error submitting order: {e}")
            return {"error": str(e)}

    def submit_limit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        limit_price: float,
        tif: str = "day",
        *,
        extended_hours: bool = False,
    ) -> dict:
        """Submit a limit order with cash-account protection.

        ``tif`` may be ``"day"``, ``"ioc"``, ``"fok"`` (Fill-Or-Kill), or ``"gtc"``.
        IOC/FOK are preferred for marketable-limit scalps: no full unfilled
        rests locking cash (FOK is all-or-nothing).

        Alpaca only supports ``extended_hours`` with **limit** orders and
        ``time_in_force=day`` — callers must pass ``tif="day"`` when
        ``extended_hours`` is true.
        """
        if not self.is_ready:
            return {"error": "Alpaca not initialized"}

        try:
            if side == "sell":
                positions = self.get_positions()
                pos = next((p for p in positions if p["symbol"] == symbol), None)
                if not pos or pos["qty"] <= 0:
                    logger.warning(f"🚫 Blocked 'limit sell' for {symbol}: No long position held")
                    return {"error": f"Cannot sell {symbol}: No long position held"}
                if qty > pos["qty"]:
                    logger.warning(f"⚠️ Adjusted 'limit sell' for {symbol}: {qty} -> {pos['qty']}")
                    qty = pos["qty"]

            order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
            tif_map = {
                "day": TimeInForce.DAY,
                "ioc": TimeInForce.IOC,
                "gtc": TimeInForce.GTC,
            }
            if hasattr(TimeInForce, "FOK"):
                tif_map["fok"] = getattr(TimeInForce, "FOK")
            tif_key = (tif or "day").lower()
            tif_enum = tif_map.get(tif_key, TimeInForce.DAY)
            req_kw = dict(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif_enum,
                limit_price=limit_price,
            )
            if extended_hours:
                req_kw["extended_hours"] = True
            request = LimitOrderRequest(**req_kw)
            order = self.trading_client.submit_order(request)
            return {
                "id": str(order.id),
                "symbol": order.symbol,
                "side": side,
                "qty": float(order.qty),
                "type": "limit",
                "tif": (tif or "day").lower(),
                "limit_price": limit_price,
                "extended_hours": bool(extended_hours),
                "status": str(order.status),
                "submitted_at": str(order.submitted_at),
            }
        except Exception as e:
            logger.error(f"Error submitting limit order: {e}")
            return {"error": str(e)}

    def get_orders(self, status: str = "all", limit: int = 50) -> list:
        """Get orders."""
        if not self.is_ready:
            return []

        try:
            from datetime import datetime
            import pytz
            ET = pytz.timezone("America/New_York")
            today_start = ET.localize(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))

            request = GetOrdersRequest(
                status=QueryOrderStatus.ALL if status == "all" else QueryOrderStatus.OPEN,
                limit=limit,
            )
            orders = self.trading_client.get_orders(request)

            if status == "open":
                return [
                    {
                        "id": str(o.id),
                        "symbol": o.symbol,
                        "side": str(o.side).split(".")[-1].lower(),
                        "qty": float(o.qty),
                        "type": str(o.order_type).split(".")[-1].lower(),
                        "status": str(o.status).split(".")[-1].lower(),
                        "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
                        "filled_at": str(o.filled_at) if o.filled_at else None,
                        "submitted_at": str(o.submitted_at),
                        "limit_price": float(o.limit_price) if o.limit_price else None,
                    }
                    for o in orders
                ]
            else:
                return [
                    {
                        "id": str(o.id),
                        "symbol": o.symbol,
                        "side": str(o.side).split(".")[-1].lower(),
                        "qty": float(o.qty),
                        "type": str(o.order_type).split(".")[-1].lower(),
                        "status": str(o.status).split(".")[-1].lower(),
                        "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
                        "filled_at": str(o.filled_at) if o.filled_at else None,
                        "submitted_at": str(o.submitted_at),
                        "limit_price": float(o.limit_price) if o.limit_price else None,
                    }
                    for o in orders
                    if o.submitted_at and o.submitted_at.astimezone(ET) >= today_start
                ]
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return []

    def get_order(self, order_id: str) -> dict:
        """Fetch a single order for fill-price reconciliation."""
        if not self.is_ready or not order_id:
            return {}
        try:
            o = self.trading_client.get_order_by_id(order_id)
            return {
                "id": str(o.id),
                "symbol": o.symbol,
                "side": str(o.side).split(".")[-1].lower(),
                "qty": float(o.qty),
                "type": str(o.order_type).split(".")[-1].lower(),
                "status": str(o.status).split(".")[-1].lower(),
                "filled_avg_price": float(o.filled_avg_price) if o.filled_avg_price else None,
                "filled_qty": float(o.filled_qty) if getattr(o, "filled_qty", None) else 0.0,
                "filled_at": str(o.filled_at) if o.filled_at else None,
                "submitted_at": str(o.submitted_at),
                "limit_price": float(o.limit_price) if o.limit_price else None,
            }
        except Exception as e:
            logger.warning("get_order failed for %s: %s", order_id, e)
            return {}

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders."""
        if not self.is_ready:
            return False

        try:
            self.trading_client.cancel_orders()
            logger.info("🚫 All open orders cancelled")
            return True
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")
            return False

    # ─── Market Data ───────────────────────────────────────────
    def get_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100) -> list:
        """
        Historical bar data. Intraday ``1Min`` / ``5Min`` prefer the WebSocket
        minute buffer when warm; otherwise REST (IEX or SIP per config).
        """
        if not self.is_ready or not self.data_client:
            return self._demo_bars(symbol, limit)

        tf_map = {
            "1Min":  TimeFrame(1,  TimeFrameUnit.Minute),
            "5Min":  TimeFrame(5,  TimeFrameUnit.Minute),
            "15Min": TimeFrame(15, TimeFrameUnit.Minute),
            "1H":    TimeFrame(1,  TimeFrameUnit.Hour),
            "4H":    TimeFrame(4,  TimeFrameUnit.Hour),
            "1Day":  TimeFrame(1,  TimeFrameUnit.Day),
            "1Week": TimeFrame(1,  TimeFrameUnit.Week),
        }
        tf = tf_map.get(timeframe, TimeFrame(1, TimeFrameUnit.Day))
        is_intraday = timeframe in ("1Min", "5Min", "15Min", "1H", "4H")
        lookback_days = 3 if is_intraday else 365

        if is_intraday and timeframe in ("1Min", "5Min"):
            try:
                from app.services import streaming_service as _stream
                min_need = 14 if timeframe == "1Min" else 20
                cached = _stream.intraday_bars_from_buffer(
                    symbol, timeframe, limit, min_rows=min_need
                )
                if cached is not None:
                    logger.debug(
                        "bars %s %s limit=%d source=ws (minute buffer)",
                        symbol,
                        timeframe,
                        limit,
                    )
                    return cached
            except Exception:
                pass

        feed = _resolve_feed()
        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=datetime.now() - timedelta(days=lookback_days),
                limit=limit,
                feed=feed,
            )
            bars = self.data_client.get_stock_bars(request)
            if symbol in bars and len(bars[symbol]) > 0:
                result = [
                    {
                        "time":   int(bar.timestamp.timestamp()),
                        "open":   float(bar.open),
                        "high":   float(bar.high),
                        "low":    float(bar.low),
                        "close":  float(bar.close),
                        "volume": int(bar.volume),
                    }
                    for bar in bars[symbol]
                ]
                if is_intraday and timeframe in ("1Min", "5Min"):
                    logger.debug(
                        "bars %s %s limit=%d source=rest n=%d",
                        symbol,
                        timeframe,
                        limit,
                        len(result),
                    )
                return result
        except Exception as e:
            logger.warning("Bars attempt failed (feed=%s): %s", feed, e)

        current_price = self._get_current_price(symbol)
        if current_price > 0:
            logger.warning(f"No bars for {symbol}, generating demo from real price ${current_price:.2f}")
            return self._demo_bars(symbol, limit, start_price=current_price)
        logger.error(f"No bars and no real price for {symbol}, returning empty")
        return []

    def _get_current_price(self, symbol: str) -> float:
        """Prefer WebSocket cache; fall back to REST snapshot."""
        try:
            from app.services import streaming_service as _stream
            tick = _stream.latest_trade(symbol)
            if tick and tick.price > 0:
                return float(tick.price)
        except Exception:
            pass
        try:
            snap = self.get_snapshot(symbol)
            if snap and 'latest_trade' in snap:
                price = float(snap['latest_trade']['price'])
                if price > 0:
                    return price
        except Exception as e:
            logger.warning(f"Failed to get current price for {symbol}: {e}")
        return 0.0

    def get_latest_quote(self, symbol: str) -> dict:
        """Get latest quote for a symbol (prefers WebSocket cache)."""
        try:
            from app.services import streaming_service as _stream
            q = _stream.latest_quote(symbol)
            if q and q.bid > 0 and q.ask > 0:
                return {
                    "bid": float(q.bid),
                    "ask": float(q.ask),
                    "bid_size": int(q.bid_size),
                    "ask_size": int(q.ask_size),
                    "source": "ws",
                }
        except Exception:
            pass

        if not self.is_ready or not self.data_client:
            return {"bid": 0, "ask": 0, "last": 0}

        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quotes = self.data_client.get_stock_latest_quote(request)
            if symbol in quotes:
                q = quotes[symbol]
                return {
                    "bid": float(q.bid_price),
                    "ask": float(q.ask_price),
                    "bid_size": int(q.bid_size),
                    "ask_size": int(q.ask_size),
                    "source": "rest",
                }
            return {}
        except Exception as e:
            logger.error(f"Error getting quote for {symbol}: {e}")
            return {}

    def get_snapshot(self, symbol: str) -> dict:
        """Get snapshot data for a symbol (prefers WebSocket cache)."""
        stream_tick = None
        stream_quote = None
        try:
            from app.services import streaming_service as _stream
            stream_tick = _stream.latest_trade(symbol)
            stream_quote = _stream.latest_quote(symbol)
        except Exception:
            pass

        def _with_stream(snap: dict) -> dict:
            # Patch over potentially stale REST latest_trade/quote with the
            # fresher WebSocket cache entries, if we have them.
            if stream_tick:
                snap["latest_trade"] = {
                    "price": float(stream_tick.price),
                    "size": int(stream_tick.size),
                }
            if stream_quote and stream_quote.bid > 0 and stream_quote.ask > 0:
                snap["latest_quote"] = {
                    "bid": float(stream_quote.bid),
                    "ask": float(stream_quote.ask),
                    "bid_size": int(stream_quote.bid_size),
                    "ask_size": int(stream_quote.ask_size),
                }
            return snap

        if not self.is_ready or not self.data_client:
            if stream_tick or stream_quote:
                return _with_stream({})
            return {}

        try:
            request = StockSnapshotRequest(symbol_or_symbols=symbol)
            snapshots = self.data_client.get_stock_snapshot(request)
            if symbol in snapshots:
                snap = snapshots[symbol]
                out = {
                    "latest_trade": {
                        "price": float(snap.latest_trade.price),
                        "size": int(snap.latest_trade.size),
                    },
                    "latest_quote": {
                        "bid": float(snap.latest_quote.bid_price),
                        "ask": float(snap.latest_quote.ask_price),
                    },
                    "daily_bar": {
                        "open": float(snap.daily_bar.open),
                        "high": float(snap.daily_bar.high),
                        "low": float(snap.daily_bar.low),
                        "close": float(snap.daily_bar.close),
                        "volume": int(snap.daily_bar.volume),
                    },
                    "prev_daily_bar": {
                        "close": float(snap.previous_daily_bar.close),
                    },
                }
                return _with_stream(out)
            return _with_stream({}) if (stream_tick or stream_quote) else {}
        except Exception as e:
            logger.error(f"Error getting snapshot for {symbol}: {e}")
            if stream_tick or stream_quote:
                return _with_stream({})
            return {}

    # ─── Demo Data ─────────────────────────────────────────────
    def _demo_account(self) -> dict:
        ic = self._initial_capital_for_display()
        return {
            "equity": ic,
            "cash": ic,
            "buying_power": ic,
            "portfolio_value": ic,
            "profit_loss": 0,
            "profit_loss_pct": 0,
            "day_trade_count": 0,
            "initial_capital": ic,
            "paper_trading": self.paper_trading,
            "broker_equity_for_pdt": ic,
        }

    def _demo_bars(self, symbol: str, limit: int, start_price: float = None) -> list:
        import random
        if start_price is None:
            fallback = {
                "AAPL": 258, "MSFT": 373, "NVDA": 177, "GOOGL": 300,
                "AMZN": 213, "TSLA": 353, "META": 574, "AMD": 220,
            }
            start_price = fallback.get(symbol, 150)

        now = datetime.now()
        price = start_price
        temp = []
        for i in range(limit):
            day_range = price * 0.018
            close = price
            open_ = close + (random.random() - 0.5) * day_range * 0.4
            high = max(open_, close) + random.random() * day_range * 0.4
            low = min(open_, close) - random.random() * day_range * 0.4
            vol = random.randint(15_000_000, 80_000_000)
            t = now - timedelta(days=i)
            temp.append({
                "time": int(t.timestamp()),
                "open": round(open_, 2),
                "high": round(high, 2),
                "low": round(max(low, 0.01), 2),
                "close": round(close, 2),
                "volume": vol,
            })
            price = price * (1 + (random.random() - 0.50) * 0.018)
            price = max(price, 1.0)
        temp.reverse()
        return temp

    # ─── News ──────────────────────────────────────────────────
    def get_latest_news(self, symbols: list, limit: int = 10) -> list:
        """Get latest news for given symbols.

        The ``alpaca-py`` NewsRequest validator expects ``symbols`` as a
        comma-separated string on some versions, a list on others. We pass a
        string defensively to avoid the ``string_type`` validation error.
        """
        if not self.is_ready:
            return []

        try:
            from alpaca.data.requests import NewsRequest
            if isinstance(symbols, (list, tuple, set)):
                sym_arg = ",".join(sorted({str(s).upper() for s in symbols if s}))
            else:
                sym_arg = str(symbols or "")
            if not sym_arg:
                return []
            request = NewsRequest(symbols=sym_arg, limit=limit)
            news = self.data_client.get_news(request)
            return [
                {
                    "headline": n.headline,
                    "summary":  n.summary,
                    "source":   n.source,
                    "url":      n.url,
                    "time":     n.created_at.strftime("%H:%M:%S"),
                }
                for n in news.news
            ]
        except Exception as e:
            logger.warning(f"Error getting news: {e}")
            return []

    # ─── REST API usage (rate-limit headers) ───────────────────
    def get_api_usage(self) -> Dict[str, Any]:
        """Broker (paper/live API) and Market Data API rate limits are separate per-minute buckets."""
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            return {
                "ok": False,
                "connected": False,
                "error": "Alpaca keys not configured",
            }

        base = (settings.alpaca_base_url or "").rstrip("/")
        clock_url = f"{base}/v2/clock"
        headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        }

        parsed: Dict[str, Optional[int]] = {
            "limit": None,
            "remaining": None,
            "reset_epoch": None,
        }
        data_parsed: Dict[str, Optional[int]] = {
            "limit": None,
            "remaining": None,
            "reset_epoch": None,
        }
        http_error: Optional[str] = None
        data_probe_error: Optional[str] = None

        try:
            with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                resp = client.get(clock_url, headers=headers)
                resp.raise_for_status()
                parsed = _parse_alpaca_ratelimit_headers(resp.headers)
                if parsed["limit"] is None and parsed["remaining"] is None:
                    acc_url = f"{base}/v2/account"
                    r2 = client.get(acc_url, headers=headers)
                    r2.raise_for_status()
                    parsed = _parse_alpaca_ratelimit_headers(r2.headers)

                dbase = (settings.alpaca_data_url or "https://data.alpaca.markets").rstrip("/")
                durl = f"{dbase}/v2/stocks/AAPL/trades/latest"
                try:
                    dr = client.get(durl, headers=headers)
                    dr.raise_for_status()
                    data_parsed = _parse_alpaca_ratelimit_headers(dr.headers)
                except Exception as de:
                    data_probe_error = str(de)
                    logger.debug("Alpaca data API usage probe failed: %s", de)
        except Exception as e:
            http_error = str(e)
            logger.warning("Alpaca usage HTTP probe failed: %s", e)

        usage_scope_note = (
            "Broker (orders/account) and Market Data REST use separate per-minute limits. "
            "Algo Trader+ / SIP is for consolidated market data; it does not remove broker REST throttles."
        )

        if parsed["limit"] is None and parsed["remaining"] is None:
            if self.trading_client and self._initialized:
                try:
                    self.trading_client.get_clock()
                    return {
                        "ok": True,
                        "connected": True,
                        "limit": None,
                        "remaining": None,
                        "used": None,
                        "reset_epoch": None,
                        "reset_in_seconds": None,
                        "percent_used": None,
                        "headers_available": False,
                        "trading_api": None,
                        "data_api": None,
                        "data_probe_error": data_probe_error,
                        "usage_scope_note": usage_scope_note,
                        "note": (
                            "Trading API reachable (SDK get_clock). "
                            "Rate-limit headers not returned on this path. "
                            "See usage_scope_note for broker vs data limits."
                        ),
                        "http_probe_error": http_error,
                    }
                except Exception as sdk_e:
                    logger.warning("Alpaca get_clock fallback failed: %s", sdk_e)
                    return {
                        "ok": False,
                        "connected": self._initialized,
                        "error": f"HTTP: {http_error or 'unknown'}; SDK: {sdk_e}",
                    }

            return {
                "ok": False,
                "connected": self._initialized,
                "error": http_error or "Alpaca not initialized",
            }

        tr = _rate_limit_usage_block(parsed["limit"], parsed["remaining"], parsed["reset_epoch"])
        data_block: Optional[Dict[str, Any]] = None
        if data_parsed["limit"] is not None or data_parsed["remaining"] is not None:
            data_block = _rate_limit_usage_block(
                data_parsed["limit"],
                data_parsed["remaining"],
                data_parsed["reset_epoch"],
            )

        return {
            "ok": True,
            "connected": self._initialized,
            "limit": tr["limit"],
            "remaining": tr["remaining"],
            "used": tr["used"],
            "reset_epoch": tr["reset_epoch"],
            "reset_in_seconds": tr["reset_in_seconds"],
            "percent_used": tr["percent_used"],
            "headers_available": tr["limit"] is not None or tr["remaining"] is not None,
            "trading_api": tr,
            "data_api": data_block,
            "data_probe_error": data_probe_error,
            "usage_scope_note": usage_scope_note,
        }


# Singleton instance (paper vs live follows ``TRADING_MODE`` in settings)
alpaca_service = AlpacaService()
alpaca_service.initialize()
