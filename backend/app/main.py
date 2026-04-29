"""
TradeSense Backend - FastAPI Main Application
AI-Powered Quant Trading Platform
"""
import logging
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import resolved_capital_scale, settings
from app.services.alpaca_service import alpaca_service
from app.services.analysis_agent import analysis_agent
from app.services import streaming_service
from app.api.deps import get_current_engine
from app.services.user_runtime import default_engine, engines_to_run, warm_registered_users
from app.api.routes import agent, alpaca, auth, market, portfolio, regime, tax, trading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tradesense")

# Background task for trading engine
trading_task = None


async def trading_loop():
    """Background loop that runs trading cycles periodically."""
    logger.info("Starting background trading loop...")
    while True:
        try:
            for eng in engines_to_run():
                await eng.run_cycle()
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")

        await asyncio.sleep(settings.scan_interval_seconds)


def _collect_streaming_universe() -> list:
    """Union of all engines' focus symbols, plus an override from env."""
    syms: set = set()
    for eng in engines_to_run():
        try:
            syms.update(eng.focus_symbols or [])
            syms.update(getattr(eng, "SCALP_UNIVERSE", []))
        except Exception:
            continue
    override = (settings.streaming_symbols or "").strip()
    if override:
        syms.update(s.strip().upper() for s in override.split(",") if s.strip())
    return sorted(syms)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info("=" * 60)
    logger.info("🚀 TradeSense Backend Starting...")
    logger.info(f"📊 Trading Mode: {settings.trading_mode.upper()}")
    logger.info(f"💰 Initial Capital: ${settings.initial_capital:,.2f}")
    logger.info(f"🏛️ Capital Scale: {resolved_capital_scale()}")
    logger.info(f"📡 Data Feed: {settings.alpaca_data_feed.upper()}")
    logger.info(f"🤖 AI Provider: {settings.ai_provider}")
    logger.info("=" * 60)

    alpaca_service.initialize()
    analysis_agent.initialize()
    warm_registered_users()

    # Start background trading loop
    global trading_task
    trading_task = asyncio.create_task(trading_loop())

    if alpaca_service.is_ready:
        account = alpaca_service.get_account()
        logger.info(f"✅ Connected to Alpaca — Equity: ${account['equity']:,.2f}")
    else:
        logger.warning("⚠️ Running in demo mode (Alpaca not connected)")

    try:
        from app.db import users_db
        users_db.init_db()
        logger.info("✅ User database ready (Sign up / Sign in)")
    except Exception as e:
        logger.warning("User DB init: %s", e)

    # Start WebSocket market data stream (best-effort; never blocks boot).
    if settings.streaming_enabled and settings.alpaca_api_key and settings.alpaca_secret_key:
        try:
            syms = _collect_streaming_universe()
            if syms:
                streaming_service.start(
                    syms,
                    settings.alpaca_api_key,
                    settings.alpaca_secret_key,
                    feed=settings.alpaca_data_feed,
                )
                logger.info(
                    "📡 Streaming started (feed=%s, symbols=%d, bar_buffer=%d 1m bars/sym)",
                    settings.alpaca_data_feed,
                    len(syms),
                    max(60, settings.streaming_bar_buffer_max),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Streaming failed to start (REST fallback active): %s", exc)
    else:
        logger.info("📡 Streaming disabled (STREAMING_ENABLED=false or keys missing)")

    yield

    logger.info("👋 TradeSense Backend shutting down...")
    if trading_task:
        trading_task.cancel()
    try:
        await streaming_service.stop()
    except Exception:
        pass
    default_engine.stop()


# Create FastAPI app
app = FastAPI(
    title="TradeSense API",
    description="AI-Powered Quant Trading Platform - Paper Trading",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "https://skyface.com",
        "https://www.skyface.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(trading.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(regime.router, prefix="/api")
app.include_router(alpaca.router, prefix="/api")
app.include_router(tax.router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": "TradeSense API",
        "version": "1.1.0",
        "mode": settings.trading_mode,
        "scale": resolved_capital_scale(),
        "feed": settings.alpaca_data_feed,
        "status": "running",
    }


@app.get("/api/account")
async def get_account(engine=Depends(get_current_engine)):
    """Get account information (per-user Alpaca when JWT present)."""
    return engine._alpaca.get_account()


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "v": 2,
        "status": "healthy",
        "alpaca_connected": alpaca_service._initialized,
        "alpaca_key_len": len(settings.alpaca_api_key),
        "ai_ready": analysis_agent._initialized,
        "ai_provider": settings.ai_provider,
        "ai_model": analysis_agent.ai_model_display(),
        "bot_active": default_engine.is_active,
        "mode": settings.trading_mode,
        "scale": resolved_capital_scale(),
        "feed": settings.alpaca_data_feed,
        "scan_interval_seconds": settings.scan_interval_seconds,
        "allow_extended_hours": settings.allow_extended_hours,
        "streaming": streaming_service.state(),
    }


@app.get("/api/health/alpaca-usage")
async def health_alpaca_usage(engine=Depends(get_current_engine)):
    """
    Alpaca REST rate-limit snapshot (same payload as /api/alpaca/usage).

    Registered on the root app next to /api/health so production SPA catch-all
    routes cannot accidentally return index.html for this path.
    """
    return engine._alpaca.get_api_usage()


@app.get("/api/health/streaming")
async def health_streaming():
    """Current WebSocket streaming state (connected, feed, subscribed)."""
    return streaming_service.state()


_app_root = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = _app_root / "frontend" / "dist"
if not STATIC_DIR.is_dir():
    STATIC_DIR = _app_root

if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").is_file():
    _assets_dir = STATIC_DIR / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"detail": "Not Found", "hint": "Unknown API path"},
            )
        file = STATIC_DIR / full_path
        if file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
