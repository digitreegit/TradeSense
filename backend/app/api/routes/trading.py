"""TradeSense - Trading API Routes"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

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


class PlaybookConfigRequest(BaseModel):
    auto: Optional[bool] = None
    manual: Optional[List[str]] = None


@router.get("/strategies")
async def get_strategies():
    """Strategy catalog + runtime routing state.

    `enabled` here means "participates in the engine's next scan".
    When AUTO is on, the engine decides which playbooks participate
    based on time-of-day and regime; the manual list is what the user
    has ticked for AUTO-OFF mode.
    """
    cfg = trading_engine.get_playbook_config()
    return {
        "auto": cfg["auto"],
        "manual": cfg["manual"],
        "active": cfg["active"],
        "strategies": [
            {
                "id": p["id"],
                "name": p["name"],
                "description": p["description"],
                "enabled": p["active_now"],
                "manual_enabled": p["manual_enabled"],
            }
            for p in cfg["playbooks"]
        ],
    }


@router.get("/playbooks")
async def get_playbooks():
    """Full playbook routing state (AUTO flag, manual set, currently active)."""
    return trading_engine.get_playbook_config()


@router.post("/playbooks")
async def set_playbooks(req: PlaybookConfigRequest):
    """Update AUTO flag and/or manual enabled set."""
    return trading_engine.set_playbook_config(auto=req.auto, manual=req.manual)
