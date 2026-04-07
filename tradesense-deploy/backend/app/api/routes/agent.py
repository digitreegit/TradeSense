"""TradeSense - AI Agent API Routes"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.analysis_agent import analysis_agent
from app.services.alpaca_service import alpaca_service

router = APIRouter(prefix="/agent", tags=["agent"])


class ChatRequest(BaseModel):
    message: str


@router.get("/analyze")
async def analyze_stock(symbol: str):
    """Get AI analysis for a stock."""
    market_data = {}
    try:
        bars = alpaca_service.get_bars(symbol, "1Day", 30)
        quote = alpaca_service.get_latest_quote(symbol)
        market_data = {"bars": bars[-10:] if bars else [], "quote": quote}
    except Exception:
        pass

    analysis = await analysis_agent.analyze_stock(symbol, market_data)
    return {"symbol": symbol, "analysis": analysis}


@router.post("/chat")
async def chat(req: ChatRequest):
    """Chat with the AI agent."""
    account = alpaca_service.get_account()
    positions = alpaca_service.get_positions()

    context = {
        "account": account,
        "positions": positions,
    }

    response = await analysis_agent.chat(req.message, context)
    return {"response": response}
