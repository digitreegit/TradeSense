"""
Passenger WSGI entry point for InMotion Hosting (cPanel).
Converts the FastAPI ASGI app to WSGI for Phusion Passenger.
"""
import sys
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("passenger")

# Set the application directory
APP_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(APP_DIR, "backend")

# Ensure CWD is the app directory
os.chdir(APP_DIR)

# Add backend to Python path
sys.path.insert(0, BACKEND_DIR)

# Load environment variables from .env BEFORE any imports
from dotenv import load_dotenv
env_path = os.path.join(APP_DIR, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path, override=True)
    logger.info(f"Loaded .env from {env_path}")
    # Verify key env vars are set
    alpaca_key = os.environ.get("ALPACA_API_KEY", "")
    logger.info(f"ALPACA_API_KEY loaded: {'YES' if alpaca_key else 'NO'} (len={len(alpaca_key)})")
    logger.info(f"AI_PROVIDER: {os.environ.get('AI_PROVIDER', 'not set')}")
else:
    logger.warning(f".env NOT FOUND at {env_path}")

# Import the FastAPI app
from app.main import app as fastapi_app
from a2wsgi import ASGIMiddleware

application = ASGIMiddleware(fastapi_app)
