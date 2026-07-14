"""Alpaca broker wrapper: account, daily bars, market orders.

Uses the free IEX feed for stocks and the free crypto feed. Fractional
notional orders keep a $3K account fully investable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import settings

log = logging.getLogger(__name__)


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

        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            raise RuntimeError(
                "Alpaca API keys not configured (set ALPACA_API_KEY / ALPACA_SECRET_KEY)"
            )
        self.trading = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=not settings.is_live,
        )
        self.stock_data = StockHistoricalDataClient(
            settings.alpaca_api_key, settings.alpaca_secret_key
        )
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

    # -- orders -------------------------------------------------------------
    def buy_notional(self, symbol: str, dollars: float) -> str | None:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        tif = TimeInForce.GTC if "/" in symbol else TimeInForce.DAY
        try:
            order = self.trading.submit_order(MarketOrderRequest(
                symbol=symbol, notional=round(dollars, 2), side=OrderSide.BUY, time_in_force=tif,
            ))
            return str(order.id)
        except Exception as exc:
            log.error("buy %s $%.2f failed: %s", symbol, dollars, exc)
            return None

    def sell_all(self, symbol: str) -> bool:
        try:
            self.trading.close_position(symbol.replace("/", ""))
            return True
        except Exception as exc:
            log.error("sell %s failed: %s", symbol, exc)
            return False
