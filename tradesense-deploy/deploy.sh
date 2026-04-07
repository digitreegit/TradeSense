#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  TradeSense — InMotion Hosting Deployment Script
#  URL: skyface.com/tradesense
# ═══════════════════════════════════════════════════════════
#
# Usage:
#   1. Upload tradesense-deploy.zip to your InMotion server
#   2. SSH into your server (or use cPanel Terminal)
#   3. cd ~/public_html  (or wherever your document root is)
#   4. unzip tradesense-deploy.zip
#   5. bash tradesense/deploy.sh
#
# Prerequisites:
#   - Python 3.10+ installed (or set up via cPanel → Setup Python App)
#   - Node.js is NOT needed on the server (frontend is pre-built)
# ═══════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════"
echo " TradeSense Deployment Setup"
echo "═══════════════════════════════════════════════════"

# 1. Set up Python virtual environment
echo ""
echo "► Creating Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 2. Install Python dependencies
echo "► Installing Python dependencies..."
pip install --upgrade pip
pip install -r backend/requirements.txt

# 3. Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo "► Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "  ⚠  IMPORTANT: Edit .env with your API keys:"
    echo "     nano $SCRIPT_DIR/.env"
    echo ""
fi

# 4. Verify frontend build exists
if [ ! -f "frontend/dist/index.html" ]; then
    echo "✗ ERROR: frontend/dist/ not found. The frontend should be pre-built."
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo " ✓ Deployment complete!"
echo "═══════════════════════════════════════════════════"
echo ""
echo " Next steps:"
echo "  1. Edit .env with your Alpaca & AI API keys"
echo "  2. In cPanel → Setup Python App:"
echo "     • Python version: 3.10+"
echo "     • App root:       $(pwd)"
echo "     • App URL:        /tradesense"
echo "     • Startup file:   passenger_wsgi.py"
echo "     • Entry point:    application"
echo "  3. Click 'Create' and then 'Restart'"
echo "  4. Visit https://skyface.com/tradesense"
echo ""
