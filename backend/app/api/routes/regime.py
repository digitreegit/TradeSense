"""TradeSense - Regime & compliance API routes."""
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_engine
from app.core.risk_presets import RISK_PRESETS, RISK_PRESETS_FOR

router = APIRouter(prefix="/regime", tags=["regime"])


@router.get("/presets")
async def list_presets(scale: str = Query(default="")):
    """Risk preset table. ``?scale=3k|10k|30k`` selects a table; empty
    returns the legacy 3k table for back-compat."""
    table = RISK_PRESETS_FOR(scale) if scale else RISK_PRESETS
    return {name: preset.as_dict() for name, preset in table.items()}


@router.get("/status")
async def regime_status(engine=Depends(get_current_engine)):
    """Market Status + active risk preset + compliance summary."""
    stats = engine.get_stats()
    return {
        "regime": engine.regime_data,
        "active_preset": engine._preset.as_dict(),  # noqa: SLF001
        "compliance": stats.get("compliance", {}),
    }
