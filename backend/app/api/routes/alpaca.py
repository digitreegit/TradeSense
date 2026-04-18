"""Alpaca connectivity / quota helpers."""
from fastapi import APIRouter

from app.services.alpaca_service import alpaca_service

router = APIRouter(prefix="/alpaca", tags=["alpaca"])


@router.get("/usage")
async def alpaca_api_usage():
    """REST rate-limit snapshot from Alpaca response headers (light /v2/clock probe)."""
    return alpaca_service.get_api_usage()
