"""TradeSense - Portfolio API Routes"""
from fastapi import APIRouter

from app.services.alpaca_service import alpaca_service

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/positions")
async def get_positions():
    """Get all open positions."""
    positions = alpaca_service.get_positions()
    return {"positions": positions}


@router.get("/summary")
async def get_portfolio_summary():
    """Get portfolio summary."""
    account = alpaca_service.get_account()
    positions = alpaca_service.get_positions()
    return {
        "account": account,
        "positions": positions,
        "position_count": len(positions),
    }
