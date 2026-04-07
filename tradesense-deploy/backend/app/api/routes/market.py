"""TradeSense - Market Data API Routes"""
from fastapi import APIRouter

from app.services.alpaca_service import alpaca_service

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/bars")
async def get_bars(symbol: str, timeframe: str = "1Day", limit: int = 100):
    """Get historical bar data for a symbol."""
    bars = alpaca_service.get_bars(symbol, timeframe, limit)
    return {"symbol": symbol, "timeframe": timeframe, "bars": bars}


@router.get("/quote")
async def get_quote(symbol: str):
    """Get latest quote for a symbol."""
    quote = alpaca_service.get_latest_quote(symbol)
    return {"symbol": symbol, "quote": quote}


@router.get("/snapshot")
async def get_snapshot(symbol: str):
    """Get snapshot data for a symbol."""
    snapshot = alpaca_service.get_snapshot(symbol)
    return {"symbol": symbol, "snapshot": snapshot}
