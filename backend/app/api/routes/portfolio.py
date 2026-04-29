"""TradeSense - Portfolio API Routes"""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_engine

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/positions")
async def get_positions(engine=Depends(get_current_engine)):
    """Get all open positions."""
    positions = engine._alpaca.get_positions()
    return {"positions": positions}


@router.get("/summary")
async def get_portfolio_summary(engine=Depends(get_current_engine)):
    """Get portfolio summary."""
    account = engine._alpaca.get_account()
    positions = engine._alpaca.get_positions()
    return {
        "account": account,
        "positions": positions,
        "position_count": len(positions),
    }
