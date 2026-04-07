"""
TradeSense Backend - FastAPI Main Application
AI-Powered Quant Trading Platform
"""
import logging
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.config import settings
from app.services.alpaca_service import alpaca_service
from app.services.analysis_agent import analysis_agent
from app.services.trading_engine import trading_engine
from app.api.routes import trading, market, agent, portfolio

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
    """Background task that runs the trading engine periodically."""
    while True:
        try:
            if trading_engine.is_active:
                await trading_engine.run_cycle()
        except Exception as e:
            logger.error(f"Trading loop error: {e}")
        await asyncio.sleep(30)  # Run every 30 seconds


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

    # Start background trading loop
    global trading_task
    trading_task = asyncio.create_task(trading_loop())

    if alpaca_service.is_ready:
        account = alpaca_service.get_account()
        logger.info(f"✅ Connected to Alpaca — Equity: ${account['equity']:,.2f}")
    else:
        logger.warning("⚠️ Running in demo mode (Alpaca not connected)")

    yield

    # Shutdown
    logger.info("👋 TradeSense Backend shutting down...")
    if trading_task:
        trading_task.cancel()
    trading_engine.stop()


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
app.include_router(trading.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": "TradeSense API",
        "version": "1.0.0",
        "mode": settings.trading_mode,
        "status": "running",
    }


@app.get("/api/account")
async def get_account():
    """Get account information."""
    return alpaca_service.get_account()


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
        "bot_active": trading_engine.is_active,
        "mode": settings.trading_mode,
    }


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
        """Serve the SPA; fall back to index.html for client-side routes."""
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
