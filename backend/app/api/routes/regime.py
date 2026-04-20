"""TradeSense - Regime & compliance API routes."""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_engine
from app.core.risk_presets import RISK_PRESETS

router = APIRouter(prefix="/regime", tags=["regime"])


@router.get("/presets")
async def list_presets():
    return {name: preset.as_dict() for name, preset in RISK_PRESETS.items()}


@router.get("/status")
async def regime_status(engine=Depends(get_current_engine)):
    """Market Status + active risk preset + compliance summary."""
    stats = engine.get_stats()
    return {
        "regime": engine.regime_data,
        "active_preset": engine._preset.as_dict(),  # noqa: SLF001
        "compliance": stats.get("compliance", {}),
    }
