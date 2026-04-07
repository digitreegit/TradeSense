"""
Passenger WSGI entry point for InMotion Hosting (cPanel).
This file should be placed in the application root directory
configured via cPanel → Setup Python App.
"""
import sys
import os

# Set the application directory
APP_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(APP_DIR, "backend")

# Add backend to Python path
sys.path.insert(0, BACKEND_DIR)

# Load environment variables from .env if present
from dotenv import load_dotenv
env_path = os.path.join(APP_DIR, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)

# Import the FastAPI app and wrap with ASGI-to-WSGI adapter
from app.main import app as fastapi_app

try:
    # If a]syncio-compatible Passenger (supports ASGI)
    application = fastapi_app
except Exception:
    pass
