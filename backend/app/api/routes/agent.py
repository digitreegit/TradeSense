"""TradeSense - AI Agent API Routes"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_engine
from app.services.analysis_agent import analysis_agent

router = APIRouter(prefix="/agent", tags=["agent"])


class ChatRequest(BaseModel):
    message: str


@router.get("/analyze")
async def analyze_stock(symbol: str, engine=Depends(get_current_engine)):
    """Get AI analysis for a stock."""
    market_data = {}
    try:
        ac = engine._alpaca
        bars = ac.get_bars(symbol, "1Day", 30)
        quote = ac.get_latest_quote(symbol)
        market_data = {"bars": bars[-10:] if bars else [], "quote": quote}
    except Exception:
        pass

    analysis = await analysis_agent.analyze_stock(symbol, market_data)
    return {"symbol": symbol, "analysis": analysis}


@router.post("/chat")
async def chat(req: ChatRequest, engine=Depends(get_current_engine)):
    """Chat with the AI agent."""
    account = engine._alpaca.get_account()
    positions = engine._alpaca.get_positions()

    context = {
        "account": account,
        "positions": positions,
    }

    response = await analysis_agent.chat(req.message, context)
    return {"response": response}
