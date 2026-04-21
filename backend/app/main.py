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

from app.core.config import settings
from app.services.alpaca_service import alpaca_service
from app.services.analysis_agent import analysis_agent
from app.api.deps import get_current_engine
from app.services.user_runtime import default_engine, engines_to_run, warm_registered_users
from app.api.routes import agent, alpaca, auth, market, portfolio, regime, trading

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
            # Even when the bot is IDLE, run_cycle checks auto-start conditions each interval.
            for eng in engines_to_run():
                await eng.run_cycle()
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
        
        await asyncio.sleep(settings.scan_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("=" * 60)
    logger.info("🚀 TradeSense Backend Starting...")
    logger.info(f"📊 Trading Mode: {settings.trading_mode.upper()}")
    logger.info(f"💰 Initial Capital: ${settings.initial_capital:,.2f}")
    logger.info(f"🤖 AI Provider: {settings.ai_provider}")
    logger.info("=" * 60)

    # Initialize services
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

    yield

    # Shutdown
    logger.info("👋 TradeSense Backend shutting down...")
    if trading_task:
        trading_task.cancel()
    default_engine.stop()


# Create FastAPI app
app = FastAPI(
    title="TradeSense API",
    description="AI-Powered Quant Trading Platform - Paper Trading",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
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

# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(trading.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(regime.router, prefix="/api")
app.include_router(alpaca.router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": "TradeSense API",
        "version": "1.0.0",
        "mode": settings.trading_mode,
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
        "bot_active": default_engine.is_active,
        "mode": settings.trading_mode,
    }


@app.get("/api/health/alpaca-usage")
async def health_alpaca_usage(engine=Depends(get_current_engine)):
    """
    Alpaca REST rate-limit snapshot (same payload as /api/alpaca/usage).

    Registered on the root app next to /api/health so production SPA catch-all
    routes cannot accidentally return index.html for this path.
    """
    return engine._alpaca.get_api_usage()


# --- Serve frontend static files in production ---
# In deployment, frontend files sit alongside backend (not in frontend/dist)
_app_root = Path(__file__).resolve().parent.parent.parent  # project root
STATIC_DIR = _app_root / "frontend" / "dist"
if not STATIC_DIR.is_dir():
    # Flat deployment: index.html and assets/ are at project root
    STATIC_DIR = _app_root

if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").is_file():
    _assets_dir = STATIC_DIR / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA; fall back to index.html for client-side routes.

        Never swallow real API routes: the catch-all is registered after routers,
        but some ASGI stacks still prefer this handler for unknown paths. If the
        path looks like an API call, return 404 JSON instead of index.html so
        clients don't get HTML where they expect JSON.
        """
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
