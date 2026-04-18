"""TradeSense - Regime & compliance API routes."""
from fastapi import APIRouter

from app.core.risk_presets import RISK_PRESETS
from app.services.compliance_service import compliance_service
from app.services.trading_engine import trading_engine

router = APIRouter(prefix="/regime", tags=["regime"])


@router.get("/presets")
async def list_presets():
    return {name: preset.as_dict() for name, preset in RISK_PRESETS.items()}


@router.get("/status")
async def regime_status():
    """Market Status + active risk preset + compliance summary."""
    return {
        "regime": trading_engine.regime_data,
        "active_preset": trading_engine._preset.as_dict(),  # noqa: SLF001
        "compliance": compliance_service.status(),
    }
