"""TradeSense - Trading API Routes"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_engine, get_current_user_id
from app.core.config import settings
from app.services import ml_signal_service
from app.services.tick_backtest_service import (
    TickBacktestParams,
    WalkForwardParams,
    run_tick_backtest,
    run_walk_forward_backtest,
)
from app.services.user_runtime import get_or_create_engine

router = APIRouter(prefix="/trading", tags=["trading"])


class OrderRequest(BaseModel):
    symbol: str
    qty: float
    side: str  # 'buy' or 'sell'
    type: str = "market"  # 'market' (marketable limit) or 'limit'
    limit_price: Optional[float] = None
    tif: Optional[str] = None  # ioc | fok | day | gtc — default from DEFAULT_ORDER_TIF
    extended_hours: Optional[bool] = None  # True → limit + DAY + Alpaca extended session


class BotRequest(BaseModel):
    strategy: str = "scalp"
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    max_position: Optional[float] = None
    risk_level: Optional[str] = None  # 'conservative' | 'moderate' | 'aggressive'


@router.get("/orders")
async def get_orders(engine=Depends(get_current_engine)):
    """Get all orders."""
    orders = engine._alpaca.get_orders()
    return {"orders": orders}


@router.post("/order")
async def submit_order(req: OrderRequest, engine=Depends(get_current_engine)):
    """Submit a new order (no raw market orders — ``market`` uses marketable limit)."""
    ac = engine._alpaca
    tif = (req.tif or settings.default_order_tif or "ioc").lower()
    if req.type == "limit" and req.limit_price:
        ext = settings.allow_extended_hours if req.extended_hours is None else bool(req.extended_hours)
        ltif = "day" if ext else tif
        result = ac.submit_limit_order(
            req.symbol,
            req.qty,
            req.side,
            req.limit_price,
            tif=ltif,
            extended_hours=ext,
        )
    elif req.type == "market":
        snapshot = ac.get_snapshot(req.symbol) or {}
        qty_i = max(1, int(abs(req.qty)))
        wide = 5.0
        ext = settings.allow_extended_hours if req.extended_hours is None else bool(req.extended_hours)
        if (req.side or "").lower() == "buy":
            btif = "day" if ext else tif
            result = engine._executor.buy(
                req.symbol,
                qty_i,
                snapshot,
                wide,
                tif=btif,
                extended_hours=ext,
                reasons=["manual_api"],
            )
        else:
            exit_tif = (req.tif or settings.exit_order_tif or "day").lower()
            stif = "day" if ext else exit_tif
            result = engine._executor.sell(
                req.symbol,
                qty_i,
                snapshot,
                wide,
                tif=stif,
                extended_hours=ext,
                reasons=["manual_api"],
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="type must be 'market' or 'limit' with limit_price",
        )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/order/cancel-all")
async def cancel_all_orders(engine=Depends(get_current_engine)):
    """Cancel all open orders."""
    success = engine._alpaca.cancel_all_orders()
    return {"success": success}


@router.post("/bot/start")
async def start_bot(req: BotRequest, engine=Depends(get_current_engine)):
    """Start the trading bot."""
    engine.start(
        req.strategy,
        stop_loss=req.stop_loss,
        take_profit=req.take_profit,
        max_position=req.max_position,
        risk_level=req.risk_level,
    )
    return {
        "status": "started",
        "strategy": req.strategy,
        "message": f"Trading bot started with {req.strategy} strategy",
    }


@router.post("/bot/stop")
async def stop_bot(engine=Depends(get_current_engine)):
    """Stop the trading bot."""
    engine.stop()
    return {"status": "stopped", "message": "Trading bot stopped"}


@router.get("/bot/status")
async def bot_status(engine=Depends(get_current_engine)):
    """Get trading bot status."""
    return {
        "active": engine.is_active,
        "strategy": engine.active_strategy,
        "regime_data": engine.regime_data,
        "stats": engine.get_stats(),
        "logs": engine.get_logs(20),
    }


class PlaybookConfigRequest(BaseModel):
    auto: Optional[bool] = None
    manual: Optional[List[str]] = None


@router.get("/strategies")
async def get_strategies(engine=Depends(get_current_engine)):
    """Strategy catalog + runtime routing state.

    `enabled` here means "participates in the engine's next scan".
    When AUTO is on, the engine decides which playbooks participate
    based on time-of-day and regime; the manual list is what the user
    has ticked for AUTO-OFF mode.
    """
    cfg = engine.get_playbook_config()
    return {
        "auto": cfg["auto"],
        "manual": cfg["manual"],
        "active": cfg["active"],
        "strategies": [
            {
                "id": p["id"],
                "name": p["name"],
                "description": p["description"],
                "enabled": p["active_now"],
                "manual_enabled": p["manual_enabled"],
            }
            for p in cfg["playbooks"]
        ],
    }


@router.get("/playbooks")
async def get_playbooks(engine=Depends(get_current_engine)):
    """Full playbook routing state (AUTO flag, manual set, currently active)."""
    return engine.get_playbook_config()


@router.post("/playbooks")
async def set_playbooks(req: PlaybookConfigRequest, engine=Depends(get_current_engine)):
    """Update AUTO flag and/or manual enabled set."""
    return engine.set_playbook_config(auto=req.auto, manual=req.manual)


@router.get("/ml-signal")
async def get_ml_signal_status(engine=Depends(get_current_engine)):
    """HistGradientBoosting model: last train, AUC, feature-drift telemetry."""
    return {
        "global": ml_signal_service.get_status_dict(),
        "regime_snapshot": engine.regime_data.get("ml_signal"),
    }


class TickBacktestRequest(BaseModel):
    symbol: str
    start: str  # ISO-8601 date or datetime
    end: str
    source: str = "alpaca_trades"  # alpaca_trades | csv | polygon | databento
    csv_filename: Optional[str] = None
    initial_cash: float = 100_000.0
    bar_seconds: int = 300
    entry_score_threshold: int = 50
    stop_loss_pct: float = 0.3
    take_profit_pct: float = 0.8
    slippage_bps: float = 8.0
    playbooks: Optional[List[str]] = None
    max_ticks: int = 250_000
    latency_rtt_ms: Optional[float] = None


class WalkForwardBacktestRequest(BaseModel):
    symbol: str
    start: str
    end: str
    source: str = "alpaca_trades"
    csv_filename: Optional[str] = None
    initial_cash: float = 100_000.0
    bar_seconds: int = 300
    entry_score_threshold: int = 50
    stop_loss_pct: float = 0.3
    take_profit_pct: float = 0.8
    slippage_bps: float = 8.0
    playbooks: Optional[List[str]] = None
    max_ticks: int = 250_000
    latency_rtt_ms: Optional[float] = None
    in_sample_bars: int = 120
    out_sample_bars: int = 60
    step_bars: int = 60
    optimize_entry_threshold: bool = False
    threshold_grid: Optional[List[int]] = None


@router.post("/backtest/tick")
async def backtest_tick(req: TickBacktestRequest, engine=Depends(get_current_engine)):
    """
    Event-driven tick → bar aggregation → playbook long-only simulation.
    Polygon/Databento: polygon needs ``POLYGON_API_KEY``; databento returns ``not_configured``.
    """
    params = TickBacktestParams(
        symbol=req.symbol,
        start=req.start,
        end=req.end,
        source=req.source,
        csv_filename=req.csv_filename,
        initial_cash=req.initial_cash,
        bar_seconds=req.bar_seconds,
        entry_score_threshold=req.entry_score_threshold,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
        slippage_bps=req.slippage_bps,
        playbooks=req.playbooks,
        max_ticks=req.max_ticks,
        latency_rtt_ms=req.latency_rtt_ms,
    )
    return run_tick_backtest(engine._alpaca, params)


@router.post("/backtest/walkforward")
async def backtest_walkforward(req: WalkForwardBacktestRequest, engine=Depends(get_current_engine)):
    """Rolling IS/OOS windows; optional in-sample-only entry threshold grid search."""
    grid = req.threshold_grid if req.threshold_grid is not None else [40, 50, 60]
    params = TickBacktestParams(
        symbol=req.symbol,
        start=req.start,
        end=req.end,
        source=req.source,
        csv_filename=req.csv_filename,
        initial_cash=req.initial_cash,
        bar_seconds=req.bar_seconds,
        entry_score_threshold=req.entry_score_threshold,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
        slippage_bps=req.slippage_bps,
        playbooks=req.playbooks,
        max_ticks=req.max_ticks,
        latency_rtt_ms=req.latency_rtt_ms,
    )
    wf = WalkForwardParams(
        in_sample_bars=req.in_sample_bars,
        out_sample_bars=req.out_sample_bars,
        step_bars=req.step_bars,
        optimize_entry_threshold=req.optimize_entry_threshold,
        threshold_grid=grid,
    )
    return run_walk_forward_backtest(engine._alpaca, params, wf)


@router.get("/backtest/sources")
async def backtest_tick_sources():
    """Available tick loaders for ``/backtest/tick``."""
    return {
        "sources": [
            {
                "id": "alpaca_trades",
                "description": "Historical trades via Alpaca Data API (keys + feed from env)",
            },
            {
                "id": "csv",
                "description": "Local CSV under BACKTEST_DATA_DIR: timestamp, price, size",
            },
            {
                "id": "polygon",
                "description": "Polygon.io v3 trades (POLYGON_API_KEY)",
            },
            {
                "id": "databento",
                "description": "Not bundled — use CSV export or Alpaca/Polygon",
            },
        ],
        "note": "vectorbt not used; simulator is custom event loop for tick fidelity.",
    }


class BacktestCompatBody(BaseModel):
    strategy: str = "scalp"
    params: Dict[str, Any] = Field(default_factory=dict)


@router.post("/backtest")
async def backtest_compat(body: BacktestCompatBody, engine=Depends(get_current_engine)):
    """Backward-compatible body: forwards to tick engine when params include symbol/start/end."""
    p = body.params
    if p.get("symbol") and p.get("start") and p.get("end"):
        req = TickBacktestRequest.model_validate(
            {
                "symbol": p["symbol"],
                "start": str(p["start"]),
                "end": str(p["end"]),
                "source": p.get("source", "alpaca_trades"),
                "csv_filename": p.get("csv_filename"),
                "initial_cash": float(p.get("initial_cash", 100_000)),
                "bar_seconds": int(p.get("bar_seconds", 300)),
                "entry_score_threshold": int(p.get("entry_score_threshold", 50)),
                "stop_loss_pct": float(p.get("stop_loss_pct", 0.3)),
                "take_profit_pct": float(p.get("take_profit_pct", 0.8)),
                "slippage_bps": float(p.get("slippage_bps", 8)),
                "playbooks": p.get("playbooks"),
                "max_ticks": int(p.get("max_ticks", 250_000)),
                "latency_rtt_ms": p.get("latency_rtt_ms"),
            }
        )
        return await backtest_tick(req, engine)
    raise HTTPException(
        status_code=400,
        detail="params must include symbol, start, end (optional source, bar_seconds, …) for tick backtest",
    )


class CapitalScaleRequest(BaseModel):
    scale: str  # "3k" | "10k" | "30k"


@router.get("/scale")
async def get_scale(engine=Depends(get_current_engine)):
    """Return current capital scale + active preset details."""
    return engine.get_scale_info()


@router.post("/scale")
async def set_scale(req: CapitalScaleRequest, engine=Depends(get_current_engine)):
    """Switch the active preset table (3k / 10k / 30k) at runtime."""
    try:
        info = engine.set_capital_scale(req.scale)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return info


class TradingModeRequest(BaseModel):
    paper: bool  # True = paper-api.alpaca.markets, False = live trading API


@router.post("/mode")
async def set_trading_mode(req: TradingModeRequest, user_id: int = Depends(get_current_user_id)):
    """Switch Alpaca paper vs live API (signed-in users with saved keys only)."""
    engine = get_or_create_engine(user_id)
    try:
        return engine.set_paper_trading(req.paper)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

