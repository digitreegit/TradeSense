#!/bin/bash
# TradeSense — deployment helper (Passenger / shared hosting)
#
# Layout: this folder lives next to the canonical backend in the repo:
#   repo/
#     backend/           ← single source of truth (synced into ./backend)
#     tradesense-deploy/
#       deploy.sh
#       passenger_wsgi.py
#       frontend/dist/   ← build output (npm run build in ../frontend)
#
# Usage (from repo root or after unzip that preserves this structure):
#   bash tradesense-deploy/deploy.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_SRC="$REPO_ROOT/backend"
BACKEND_DST="$SCRIPT_DIR/backend"

echo "═══════════════════════════════════════════════════"
echo " TradeSense deployment setup"
echo "═══════════════════════════════════════════════════"

if [ ! -d "$BACKEND_SRC/app" ]; then
  echo "✗ ERROR: Canonical backend not found at $BACKEND_SRC"
  echo "  Run this script from a checkout where ../backend exists,"
  echo "  or copy the backend tree to $BACKEND_DST manually."
  exit 1
fi

echo ""
echo "► Syncing Python backend from repo..."
rm -rf "$BACKEND_DST"
mkdir -p "$BACKEND_DST"
cp -a "$BACKEND_SRC"/. "$BACKEND_DST"/

echo "► Creating Python virtual environment..."
cd "$SCRIPT_DIR"
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi
# shellcheck source=/dev/null
source venv/bin/activate

echo "► Installing Python dependencies..."
pip install --upgrade pip
pip install -r "$BACKEND_DST/requirements.txt"

if [ ! -f ".env" ]; then
  echo "► Creating .env from template..."
  cp .env.example .env
  echo ""
  echo "  ⚠  Edit .env with your API keys: $SCRIPT_DIR/.env"
  echo ""
fi

if [ ! -f "frontend/dist/index.html" ] && [ -f "$REPO_ROOT/frontend/dist/index.html" ]; then
  echo "► Copying frontend build from $REPO_ROOT/frontend/dist ..."
  mkdir -p frontend/dist
  rm -rf frontend/dist/*
  cp -a "$REPO_ROOT/frontend/dist"/. frontend/dist/
fi

if [ ! -f "frontend/dist/index.html" ]; then
  echo "✗ ERROR: frontend/dist/index.html not found."
  echo "  From the repo: cd frontend && npm install && npm run build"
  echo "  Or copy dist/ into $SCRIPT_DIR/frontend/dist"
  exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo " ✓ Ready for Passenger"
echo "═══════════════════════════════════════════════════"
echo ""
echo " cPanel → Setup Python App (example for https://example.com/quant/):"
echo "   • App root:     $SCRIPT_DIR"
echo "   • App URL:      /quant"
echo "   • Startup:      passenger_wsgi.py"
echo "   • Entry point:  application"
echo ""
