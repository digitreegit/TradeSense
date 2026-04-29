"""
Passenger WSGI entry point for shared hosting (cPanel).
Converts the FastAPI ASGI app to WSGI for Phusion Passenger.
"""
import logging
import os
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("passenger")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(APP_DIR, "backend")

os.chdir(APP_DIR)
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv

env_path = os.path.join(APP_DIR, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path, override=True)
    logger.info("Loaded .env from %s", env_path)
else:
    logger.warning(".env not found at %s", env_path)

from app.main import app as fastapi_app
from a2wsgi import ASGIMiddleware

application = ASGIMiddleware(fastapi_app)
