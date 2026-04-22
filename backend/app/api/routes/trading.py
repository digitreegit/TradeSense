"""TradeSense - Trading API Routes"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.api.deps import get_current_engine

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
async def get_orders(engine=Depends(get_current_engine)):
    """Get all orders."""
    orders = engine._alpaca.get_orders()
    return {"orders": orders}


@router.post("/order")
async def submit_order(req: OrderRequest, engine=Depends(get_current_engine)):
    """Submit a new order."""
    ac = engine._alpaca
    if req.type == "limit" and req.limit_price:
        result = ac.submit_limit_order(
            req.symbol, req.qty, req.side, req.limit_price
        )
    else:
        result = ac.submit_market_order(req.symbol, req.qty, req.side)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/order/cancel-all")
async def cancel_all_orders(engine=Depends(get_current_engine)):
    """Cancel all open orders."""
    success = engine._alpaca.cancel_all_orders()
    return {"success": success}


@router.post("/bot/start")
async def start_bot(req: BotRequest, engine=Depends(get_current_engine)):
    """Start the trading bot."""
    engine.start(
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
async def stop_bot(engine=Depends(get_current_engine)):
    """Stop the trading bot."""
    engine.stop()
    return {"status": "stopped", "message": "Trading bot stopped"}


@router.get("/bot/status")
async def bot_status(engine=Depends(get_current_engine)):
    """Get trading bot status."""
    return {
        "active": engine.is_active,
        "strategy": engine.active_strategy,
        "regime_data": engine.regime_data,
        "stats": engine.get_stats(),
        "logs": engine.get_logs(20),
    }


class PlaybookConfigRequest(BaseModel):
    auto: Optional[bool] = None
    manual: Optional[List[str]] = None


@router.get("/strategies")
async def get_strategies(engine=Depends(get_current_engine)):
    """Strategy catalog + runtime routing state.

    `enabled` here means "participates in the engine's next scan".
    When AUTO is on, the engine decides which playbooks participate
    based on time-of-day and regime; the manual list is what the user
    has ticked for AUTO-OFF mode.
    """
    cfg = engine.get_playbook_config()
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
async def get_playbooks(engine=Depends(get_current_engine)):
    """Full playbook routing state (AUTO flag, manual set, currently active)."""
    return engine.get_playbook_config()


@router.post("/playbooks")
async def set_playbooks(req: PlaybookConfigRequest, engine=Depends(get_current_engine)):
    """Update AUTO flag and/or manual enabled set."""
    return engine.set_playbook_config(auto=req.auto, manual=req.manual)


class CapitalScaleRequest(BaseModel):
    scale: str  # "3k" | "10k" | "30k"


@router.get("/scale")
async def get_scale(engine=Depends(get_current_engine)):
    """Return current capital scale + active preset details."""
    return engine.get_scale_info()


@router.post("/scale")
async def set_scale(req: CapitalScaleRequest, engine=Depends(get_current_engine)):
    """Switch the active preset table (3k / 10k / 30k) at runtime."""
    try:
        info = engine.set_capital_scale(req.scale)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return info

