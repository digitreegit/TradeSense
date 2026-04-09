"""
TradeSense - Alpaca Trading Service
Handles all communication with Alpaca Markets API for paper trading.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

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


class AlpacaService:
    """Service for interacting with Alpaca Markets API."""

    def __init__(self):
        self.trading_client: Optional[TradingClient] = None
        self.data_client: Optional[StockHistoricalDataClient] = None
        self._initialized = False

    def initialize(self):
        """Initialize Alpaca API clients."""
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            logger.warning("Alpaca API keys not configured. Running in demo mode.")
            return

        try:
            # Paper trading client
            self.trading_client = TradingClient(
                api_key=settings.alpaca_api_key,
                secret_key=settings.alpaca_secret_key,
                paper=True,  # Always use paper trading
            )

            self.data_client = StockHistoricalDataClient(
                api_key=settings.alpaca_api_key,
                secret_key=settings.alpaca_secret_key,
            )

            self._initialized = True
            logger.info("✅ Alpaca API clients initialized (Paper Trading)")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Alpaca: {e}")
            self._initialized = False

    @property
    def is_ready(self) -> bool:
        if not self._initialized:
            self.initialize()
        return self._initialized

    # ─── Account ───────────────────────────────────────────────
    def get_account(self) -> dict:
        """Get account information with performance metrics."""
        if not self.is_ready:
            return self._demo_account()

        try:
            import numpy as np
            account = self.trading_client.get_account()
            
            # Use raw Alpaca values directly ($100K base)
            equity = float(account.equity)
            cash = float(account.cash)
            pv = float(account.portfolio_value or account.equity)
            bp = float(account.buying_power)
            initial = 100000.0  # Alpaca paper starting balance
            
            # P&L calculation
            profit_loss = equity - initial
            profit_loss_pct = (profit_loss / initial) * 100 if initial > 0 else 0

            # --- Calculate Advanced Metrics ---
            metrics = {
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 0.0,
                "sharpe_ratio": 0.0
            }

            try:
                # 1. Sharpe Ratio from Portfolio History
                # Try intraday history first for more immediate feedback on new accounts
                history = self.trading_client.get_portfolio_history(
                    period="1D", 
                    timeframe="5Min"
                )
                
                # If intraday fails or is empty, try daily
                if not history or not hasattr(history, "equity") or len(history.equity) < 5:
                    history = self.trading_client.get_portfolio_history()

                if history and hasattr(history, "equity") and len(history.equity) > 2:
                    equities = np.array(history.equity, dtype=float)
                    # Filter out zero/bad entries
                    equities = equities[equities > 0]
                    
                    if len(equities) > 2:
                        # Period-over-period returns
                        returns = np.diff(equities) / equities[:-1]
                        returns = returns[np.isfinite(returns)]
                        
                        if len(returns) > 1:
                            avg_ret = np.mean(returns)
                            std_ret = np.std(returns)
                            
                            if std_ret > 0:
                                # Adjust annualization factor based on history length and timeframe
                                # Standard 1-day/5-min has ~78 points (6.5 hours)
                                # If it's intraday, we use a different annualization factor
                                # but for simple display, we'll use a smoothed daily approximation
                                factor = np.sqrt(252 * 78) if len(equities) < 100 else np.sqrt(252)
                                metrics["sharpe_ratio"] = round((avg_ret / std_ret) * factor, 2)
                                
                                # Cap it at a reasonable range if it's extremely high due to low volatility
                                if metrics["sharpe_ratio"] > 10: 
                                    metrics["sharpe_ratio"] = 9.99
                            elif avg_ret > 0:
                                # If positive return but zero volatility (rare), show 1.0 or similar
                                metrics["sharpe_ratio"] = 1.0

                # 2. Trade-based metrics (Win Rate, etc.)
                # We'll fetch the last 100 orders to approximate trade metrics
                orders = self.get_orders(status="all", limit=100)
                filled_orders = [o for o in orders if o["status"] == "filled" and o["filled_avg_price"]]
                
                # Simple logic: group by symbol and match buy/sell pairs
                trades = []
                # This is a simplification; in a real app we'd use account activities
                symbols = set(o["symbol"] for o in filled_orders)
                for sym in symbols:
                    sym_orders = [o for o in filled_orders if o["symbol"] == sym]
                    # Sort by time
                    sym_orders.sort(key=lambda x: x["filled_at"] or x["submitted_at"])
                    
                    # Match pairs (buy then sell)
                    open_qty = 0
                    entry_value = 0
                    for o in sym_orders:
                        if o["side"] == "buy":
                            open_qty += o["qty"]
                            entry_value += o["qty"] * o["filled_avg_price"]
                        elif o["side"] == "sell" and open_qty > 0:
                            # Closing part of a position
                            close_qty = min(o["qty"], open_qty)
                            rel_entry_value = (entry_value / open_qty) * close_qty
                            realized_pnl = (o["filled_avg_price"] * close_qty) - rel_entry_value
                            trades.append(realized_pnl)
                            
                            # Update remaining
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

            return {
                "equity":          round(equity, 2),
                "cash":            round(cash, 2),
                "buying_power":    round(bp, 2),
                "portfolio_value": round(pv, 2),
                "profit_loss":     round(profit_loss, 2),
                "profit_loss_pct": round(profit_loss_pct, 2),
                "day_trade_count": int(account.daytrade_count or 0),
                "initial_capital": initial,
                **metrics
            }

        except Exception as e:
            logger.error(f"Error getting account: {e}")
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
        """Submit a market order."""
        if not self.is_ready:
            return {"error": "Alpaca not initialized"}

        try:
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
                "status": str(order.status),
                "submitted_at": str(order.submitted_at),
            }
        except Exception as e:
            logger.error(f"Error submitting order: {e}")
            return {"error": str(e)}

    def submit_limit_order(self, symbol: str, qty: float, side: str, limit_price: float) -> dict:
        """Submit a limit order."""
        if not self.is_ready:
            return {"error": "Alpaca not initialized"}

        try:
            order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
            request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
                limit_price=limit_price,
            )
            order = self.trading_client.submit_order(request)
            return {
                "id": str(order.id),
                "symbol": order.symbol,
                "side": side,
                "qty": float(order.qty),
                "limit_price": limit_price,
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
            request = GetOrdersRequest(
                status=QueryOrderStatus.ALL if status == "all" else QueryOrderStatus.OPEN,
                limit=limit,
            )
            orders = self.trading_client.get_orders(request)
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
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return []

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
        """Get historical bar data."""
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
        lookback_days = 7 if is_intraday else 365

        # Try IEX first (free with paper trading), then SIP
        for feed in [DataFeed.IEX, DataFeed.SIP]:
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
                    logger.info(f"Got {len(result)} real bars for {symbol} (feed={feed.value})")
                    return result
            except Exception as e:
                logger.warning(f"Bars attempt failed (feed={feed}): {e}")

        # Last resort: generate demo bars anchored to real current price
        current_price = self._get_current_price(symbol)
        if current_price > 0:
            logger.warning(f"No bars for {symbol}, generating demo from real price ${current_price:.2f}")
            return self._demo_bars(symbol, limit, start_price=current_price)
        else:
            logger.error(f"No bars and no real price for {symbol}, returning empty")
            return []

    def _get_current_price(self, symbol: str) -> float:
        """Get current price from snapshot (reuses get_snapshot which works)."""
        try:
            snap = self.get_snapshot(symbol)
            if snap and 'latest_trade' in snap:
                price = float(snap['latest_trade']['price'])
                if price > 0:
                    logger.info(f"Got real price for {symbol}: ${price:.2f}")
                    return price
        except Exception as e:
            logger.warning(f"Failed to get current price for {symbol}: {e}")
        # Fallback: return 0 to signal no real price available
        logger.warning(f"Using fallback price for {symbol}")
        return 0




    def get_latest_quote(self, symbol: str) -> dict:
        """Get latest quote for a symbol."""
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
                }
            return {}
        except Exception as e:
            logger.error(f"Error getting quote for {symbol}: {e}")
            return {}

    def get_snapshot(self, symbol: str) -> dict:
        """Get snapshot data for a symbol."""
        if not self.is_ready or not self.data_client:
            return {}

        try:
            request = StockSnapshotRequest(symbol_or_symbols=symbol)
            snapshots = self.data_client.get_stock_snapshot(request)
            if symbol in snapshots:
                snap = snapshots[symbol]
                return {
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
            return {}
        except Exception as e:
            logger.error(f"Error getting snapshot for {symbol}: {e}")
            return {}

    # ─── Demo Data ─────────────────────────────────────────────
    def _demo_account(self) -> dict:
        return {
            "equity": settings.initial_capital,
            "cash": settings.initial_capital,
            "buying_power": settings.initial_capital,
            "portfolio_value": settings.initial_capital,
            "profit_loss": 0,
            "profit_loss_pct": 0,
            "day_trade_count": 0,
            "initial_capital": settings.initial_capital,
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
        price = start_price  # most recent close = real current price

        # Build from most-recent → oldest, then reverse
        # so the last element in the array = today's bar = real price
        temp = []
        for i in range(limit):
            day_range = price * 0.018          # ~1.8% intraday range
            close = price
            open_ = close + (random.random() - 0.5) * day_range * 0.4
            high  = max(open_, close) + random.random() * day_range * 0.4
            low   = min(open_, close) - random.random() * day_range * 0.4
            vol   = random.randint(15_000_000, 80_000_000)
            t     = now - timedelta(days=i)

            temp.append({
                "time":   int(t.timestamp()),
                "open":   round(open_, 2),
                "high":   round(high, 2),
                "low":    round(max(low, 0.01), 2),
                "close":  round(close, 2),
                "volume": vol,
            })

            # Walk price backwards (simulate what it was the day before)
            price = price * (1 + (random.random() - 0.50) * 0.018)
            price = max(price, 1.0)

        # Reverse: oldest first, newest (= real price) last
        temp.reverse()
        return temp
    # ─── News ──────────────────────────────────────────────────
    def get_latest_news(self, symbols: list[str], limit: int = 10) -> list:
        """Get latest news for given symbols."""
        if not self.is_ready:
            return []

        try:
            from alpaca.data.requests import NewsRequest
            request = NewsRequest(
                symbols=symbols,
                limit=limit
            )
            news = self.data_client.get_news(request)
            return [
                {
                    "headline": n.headline,
                    "summary":  n.summary,
                    "source":   n.source,
                    "url":      n.url,
                    "time":     n.created_at.strftime("%H:%M:%S")
                }
                for n in news.news
            ]
        except Exception as e:
            logger.warning(f"Error getting news: {e}")
            return []




# Singleton instance
alpaca_service = AlpacaService()
alpaca_service.initialize()  # Initialize immediately at import time
