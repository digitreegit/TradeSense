"""TradeSense - Trading API Routes"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.services.alpaca_service import alpaca_service
from app.services.trading_engine import trading_engine

router = APIRouter(prefix="/trading", tags=["trading"])


class OrderRequest(BaseModel):
    symbol: str
    qty: float
    side: str  # 'buy' or 'sell'
    type: str = "market"  # 'market' or 'limit'
    limit_price: Optional[float] = None


class BotRequest(BaseModel):
    strategy: str = "momentum"
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    max_position: Optional[float] = None


@router.get("/orders")
async def get_orders():
    """Get all orders."""
    orders = alpaca_service.get_orders()
    return {"orders": orders}


@router.post("/order")
async def submit_order(req: OrderRequest):
    """Submit a new order."""
    if req.type == "limit" and req.limit_price:
        result = alpaca_service.submit_limit_order(
            req.symbol, req.qty, req.side, req.limit_price
        )
    else:
        result = alpaca_service.submit_market_order(req.symbol, req.qty, req.side)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/order/cancel-all")
async def cancel_all_orders():
    """Cancel all open orders."""
    success = alpaca_service.cancel_all_orders()
    return {"success": success}


@router.post("/bot/start")
async def start_bot(req: BotRequest):
    """Start the trading bot."""
    trading_engine.start(
        req.strategy,
        stop_loss=req.stop_loss,
        take_profit=req.take_profit,
        max_position=req.max_position
    )
    return {
        "status": "started",
        "strategy": req.strategy,
        "message": f"Trading bot started with {req.strategy} strategy",
    }


@router.post("/bot/stop")
async def stop_bot():
    """Stop the trading bot."""
    trading_engine.stop()
    return {"status": "stopped", "message": "Trading bot stopped"}


@router.get("/bot/status")
async def bot_status():
    """Get trading bot status."""
    return {
        "active": trading_engine.is_active,
        "strategy": trading_engine.active_strategy,
        "regime_data": trading_engine.regime_data,
        "stats": trading_engine.get_stats(),
        "logs": trading_engine.get_logs(20),
    }


@router.get("/strategies")
async def get_strategies():
    """Get available strategies."""
    return {
        "strategies": [
            {
                "id": "momentum",
                "name": "Momentum Breakout",
                "description": "RSI + MACD crossover momentum strategy",
                "win_rate": 62.5,
            },
            {
                "id": "mean-reversion",
                "name": "Mean Reversion",
                "description": "Bollinger Bands mean reversion strategy",
                "win_rate": 58.3,
            },
            {
                "id": "ml-predict",
                "name": "ML Prediction",
                "description": "Gradient Boosting price prediction model",
                "win_rate": 55.8,
            },
        ]
    }
