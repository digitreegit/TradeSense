"""Alpaca connectivity / quota helpers."""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_engine

router = APIRouter(prefix="/alpaca", tags=["alpaca"])


@router.get("/usage")
async def alpaca_api_usage(engine=Depends(get_current_engine)):
    """REST rate-limit snapshot from Alpaca response headers (light /v2/clock probe)."""
    return engine._alpaca.get_api_usage()
