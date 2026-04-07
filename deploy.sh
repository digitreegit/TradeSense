#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  TradeSense — InMotion Hosting (cPanel) Deployment Script
#  URL: skyface.com/tradesense
# ═══════════════════════════════════════════════════════════
#
# ★ IMPORTANT: Before running this script, you must FIRST
#   create the Python App in cPanel:
#
#   1. cPanel → Setup Python App → Create Application
#      • Python version : 3.10 (or latest available)
#      • App root       : public_html/tradesense
#      • App URL        : /tradesense
#      • Startup file   : passenger_wsgi.py
#      • Entry point    : application
#      → Click "Create"
#
#   2. cPanel will show a command like:
#      source /home/skyfac5/virtualenv/public_html/tradesense/3.10/bin/activate
#      Copy & paste that command in Terminal FIRST, then run:
#      cd ~/public_html/tradesense && bash deploy.sh
# ═══════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════"
echo " TradeSense Deployment Setup"
echo "═══════════════════════════════════════════════════"

# 1. Check that we're inside a virtualenv (created by cPanel)
echo ""
if [ -z "$VIRTUAL_ENV" ]; then
    echo "✗ ERROR: No Python virtualenv detected."
    echo ""
    echo "  You must first create a Python App in cPanel and"
    echo "  activate its virtualenv. Look for a command like:"
    echo ""
    echo "    source /home/skyfac5/virtualenv/public_html/tradesense/3.10/bin/activate"
    echo ""
    echo "  Run that command first, then re-run: bash deploy.sh"
    exit 1
fi
echo "✓ Virtualenv active: $VIRTUAL_ENV"

# 2. Install Python dependencies
echo ""
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
echo "✓ Frontend build found."

echo ""
echo "═══════════════════════════════════════════════════"
echo " ✓ Deployment complete!"
echo "═══════════════════════════════════════════════════"
echo ""
echo " Next steps:"
echo "  1. Edit .env with your Alpaca & AI API keys:"
echo "     nano $SCRIPT_DIR/.env"
echo "  2. In cPanel → Setup Python App → click 'Restart'"
echo "  3. Visit https://skyface.com/tradesense"
echo ""
