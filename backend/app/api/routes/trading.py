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
    strategy: str = "scalp"
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    max_position: Optional[float] = None
    risk_level: Optional[str] = None  # 'conservative' | 'moderate' | 'aggressive'


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
        max_position=req.max_position,
        risk_level=req.risk_level,
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
    """Active scalping playbooks (composed within the engine)."""
    return {
        "strategies": [
            {
                "id": "scalp",
                "name": "Micro-Scalping v4",
                "description": "RSI/MACD/BB + volume surge on 5-min bars",
                "enabled": True,
            },
            {
                "id": "vwap",
                "name": "VWAP Mean-Reversion",
                "description": "Fade deviations below VWAP during RTH",
                "enabled": True,
            },
            {
                "id": "orb",
                "name": "Opening Range Breakout",
                "description": "Buy break above 9:30–9:35 range, valid until 11:00 ET",
                "enabled": True,
            },
            {
                "id": "eod",
                "name": "End-of-Day Drift",
                "description": "Favor up-trending names into 15:50–15:58 close",
                "enabled": True,
            },
            {
                "id": "news-fade",
                "name": "News Spike Fade",
                "description": "Fade exhaustion after AI-detected panic",
                "enabled": False,
            },
        ]
    }
