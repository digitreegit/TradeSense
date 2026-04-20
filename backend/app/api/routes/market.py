"""TradeSense - Market Data API Routes"""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_engine

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/bars")
async def get_bars(
    symbol: str,
    timeframe: str = "1Day",
    limit: int = 100,
    engine=Depends(get_current_engine),
):
    """Get historical bar data for a symbol."""
    bars = engine._alpaca.get_bars(symbol, timeframe, limit)
    return {"symbol": symbol, "timeframe": timeframe, "bars": bars}


@router.get("/quote")
async def get_quote(symbol: str, engine=Depends(get_current_engine)):
    """Get latest quote for a symbol."""
    quote = engine._alpaca.get_latest_quote(symbol)
    return {"symbol": symbol, "quote": quote}


@router.get("/snapshot")
async def get_snapshot(symbol: str, engine=Depends(get_current_engine)):
    """Get snapshot data for a symbol."""
    snapshot = engine._alpaca.get_snapshot(symbol)
    return {"symbol": symbol, "snapshot": snapshot}
