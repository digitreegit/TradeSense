"""Alpaca broker wrapper: account, daily bars, market orders.

Uses the free IEX feed for stocks and the free crypto feed. Fractional
notional orders keep a $3K account fully investable.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from .alpaca_config import get_credentials, is_paper_key

log = logging.getLogger(__name__)

_ORDER_TERMINAL = frozenset({
    "filled", "canceled", "expired", "rejected", "replaced", "suspended",
    "calculated", "done_for_day",
})


def _enum_value(value) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").lower()


def _order_snapshot(order) -> dict:
    """Small, JSON-safe order view shared by the live engine and tests."""
    if order is None:
        return {}
    if isinstance(order, dict):
        source = order
        get = source.get
    else:
        get = lambda key, default=None: getattr(order, key, default)
    return {
        "id": str(get("id") or ""),
        "client_order_id": str(get("client_order_id") or ""),
        "status": _enum_value(get("status")),
        "symbol": str(get("symbol") or ""),
        "side": _enum_value(get("side")),
        "qty": float(get("qty") or 0),
        "filled_qty": float(get("filled_qty") or 0),
        "filled_avg_price": float(get("filled_avg_price") or 0),
    }


def _is_not_found(exc: Exception) -> bool:
    code = getattr(exc, "status_code", None)
    return code == 404 or "404" in str(exc)


def _bars_to_df(bars) -> pd.DataFrame:
    rows = [
        {
            "date": b.timestamp,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]
    df = pd.DataFrame(rows).set_index("date")
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


class Broker:
    def __init__(self) -> None:
        from alpaca.data.historical import CryptoHistoricalDataClient, StockHistoricalDataClient
        from alpaca.trading.client import TradingClient

        api_key, secret_key, paper = get_credentials()
        if not api_key or not secret_key:
            raise RuntimeError(
                "Alpaca API keys not configured (set ALPACA_API_KEY / ALPACA_SECRET_KEY "
                "or save keys in Settings)"
            )
        if is_paper_key(api_key):
            # A paper key against the live endpoint returns an opaque 401.
            raise RuntimeError(
                "페이퍼 키(PK…)가 설정되어 있습니다 — 실거래 전용입니다. "
                "설정에서 라이브 키(AK…)를 저장하세요."
            )
        self.trading = TradingClient(api_key, secret_key, paper=paper)
        self.stock_data = StockHistoricalDataClient(api_key, secret_key)
        self.crypto_data = CryptoHistoricalDataClient()

    # -- account ------------------------------------------------------------
    def equity(self) -> float:
        return float(self.trading.get_account().equity)

    def cash(self) -> float:
        return float(self.trading.get_account().cash)

    def positions(self) -> dict[str, dict]:
        out = {}
        for p in self.trading.get_all_positions():
            # Alpaca reports crypto positions as e.g. "BTCUSD" -> "BTC/USD"
            sym = p.symbol
            is_crypto = "crypto" in str(getattr(p, "asset_class", "")).lower()
            if is_crypto and "/" not in sym and sym.endswith("USD"):
                sym = f"{sym[:-3]}/USD"
            out[sym] = {
                "qty": float(p.qty),
                "market_value": float(p.market_value),
                "avg_entry": float(p.avg_entry_price),
                "unrealized_pl": float(p.unrealized_pl),
                "current_price": float(p.current_price),
            }
        return out

    # -- market data --------------------------------------------------------
    def daily_bars(self, symbols: list[str], days: int = 320) -> dict[str, pd.DataFrame]:
        from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        start = datetime.now(timezone.utc) - timedelta(days=int(days * 1.6))
        stocks = [s for s in symbols if "/" not in s]
        cryptos = [s for s in symbols if "/" in s]
        out: dict[str, pd.DataFrame] = {}

        if stocks:
            req = StockBarsRequest(
                symbol_or_symbols=stocks, timeframe=TimeFrame.Day, start=start, feed="iex"
            )
            data = self.stock_data.get_stock_bars(req).data
            for sym in stocks:
                if sym in data and data[sym]:
                    out[sym] = _bars_to_df(data[sym])
        if cryptos:
            req = CryptoBarsRequest(
                symbol_or_symbols=cryptos, timeframe=TimeFrame.Day, start=start
            )
            data = self.crypto_data.get_crypto_bars(req).data
            for sym in cryptos:
                if sym in data and data[sym]:
                    out[sym] = _bars_to_df(data[sym])
        return out

    def latest_price(self, symbol: str) -> float | None:
        try:
            if "/" in symbol:
                from alpaca.data.requests import CryptoLatestTradeRequest

                t = self.crypto_data.get_crypto_latest_trade(
                    CryptoLatestTradeRequest(symbol_or_symbols=symbol)
                )
                return float(t[symbol].price)
            from alpaca.data.requests import StockLatestTradeRequest

            t = self.stock_data.get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=symbol, feed="iex")
            )
            return float(t[symbol].price)
        except Exception as exc:
            log.warning("latest_price(%s) failed: %s", symbol, exc)
            return None

    def market_open_now(self) -> bool:
        try:
            return bool(self.trading.get_clock().is_open)
        except Exception:
            return False

    def next_market_open(self) -> datetime | None:
        """Return Alpaca's next official market open (holiday-aware)."""
        try:
            return self.trading.get_clock().next_open
        except Exception as exc:
            log.warning("next_market_open failed: %s", exc)
            return None

    # -- orders -------------------------------------------------------------
    def get_order_by_client_id(self, client_order_id: str) -> dict | None:
        try:
            order = self.trading.get_order_by_client_id(client_order_id)
            return _order_snapshot(order)
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise

    def get_order(self, order_id: str) -> dict | None:
        try:
            return _order_snapshot(self.trading.get_order_by_id(order_id))
        except Exception as exc:
            log.warning("get_order(%s) failed: %s", order_id, exc)
            return None

    def wait_for_order(self, order_id: str, timeout: float = 12.0) -> dict | None:
        """Return the latest order once terminal, or the latest open snapshot."""
        deadline = time.time() + timeout
        latest: dict | None = None
        while time.time() < deadline:
            row = self.get_order(order_id)
            if row:
                latest = row
                if row.get("status") in _ORDER_TERMINAL:
                    return row
            time.sleep(1)
        return latest

    def buy_notional(
        self, symbol: str, dollars: float, *, client_order_id: str
    ) -> dict | None:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        tif = TimeInForce.GTC if "/" in symbol else TimeInForce.DAY
        try:
            existing = self.get_order_by_client_id(client_order_id)
        except Exception as exc:
            log.error("buy %s idempotency lookup failed: %s", symbol, exc)
            return {
                "client_order_id": client_order_id,
                "status": "unknown",
                "error": str(exc),
            }
        if existing:
            return existing
        try:
            order = self.trading.submit_order(MarketOrderRequest(
                symbol=symbol, notional=round(dollars, 2), side=OrderSide.BUY, time_in_force=tif,
                client_order_id=client_order_id,
            ))
            return _order_snapshot(order)
        except Exception as exc:
            # The HTTP response can time out after Alpaca accepted the order.
            # Reconcile by the durable client id before reporting a failure.
            try:
                existing = self.get_order_by_client_id(client_order_id)
            except Exception:
                existing = None
            if existing:
                return existing
            log.error("buy %s $%.2f failed: %s", symbol, dollars, exc)
            return {
                "client_order_id": client_order_id,
                "status": "unknown",
                "error": str(exc),
            }

    def sell_all(
        self, symbol: str, *, qty: float, client_order_id: str
    ) -> dict | None:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        try:
            existing = self.get_order_by_client_id(client_order_id)
        except Exception as exc:
            log.error("sell %s idempotency lookup failed: %s", symbol, exc)
            return {
                "client_order_id": client_order_id,
                "status": "unknown",
                "error": str(exc),
            }
        if existing:
            return existing
        tif = TimeInForce.GTC if "/" in symbol else TimeInForce.DAY
        try:
            order = self.trading.submit_order(MarketOrderRequest(
                symbol=symbol.replace("/", ""), qty=abs(float(qty)),
                side=OrderSide.SELL, time_in_force=tif,
                client_order_id=client_order_id,
            ))
            return _order_snapshot(order)
        except Exception as exc:
            try:
                existing = self.get_order_by_client_id(client_order_id)
            except Exception:
                existing = None
            if existing:
                return existing
            log.error("sell %s failed: %s", symbol, exc)
            return {
                "client_order_id": client_order_id,
                "status": "unknown",
                "error": str(exc),
            }

    def open_orders_count(self) -> int:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        try:
            orders = self.trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
            return len(orders)
        except Exception as exc:
            log.warning("open_orders_count failed: %s", exc)
            return -1

    def wait_for_fills(self, timeout: float = 30.0) -> bool:
        """Block until no open orders remain (or timeout). Used between the
        morning sells and buys so freed-up cash is actually available.
        Returns False on timeout or when order status cannot be read."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            count = self.open_orders_count()
            if count == 0:
                return True
            if count < 0:
                return False
            time.sleep(2)
        log.warning("wait_for_fills: open orders still pending after %.0fs", timeout)
        return False
