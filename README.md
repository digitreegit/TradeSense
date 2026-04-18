# TradeSense 🚀
## AI-Powered Quant Trading Platform

TradeSense is a web platform for AI-assisted US equity analysis and automated quant-style trading (paper trading by default).

### ✨ Features
- **📊 Live charts**: Candlesticks + technical indicators (MA, RSI, MACD, Bollinger Bands)
- **🤖 AI analyst**: GPT-4o / Gemini-powered stock commentary
- **⚡ Auto trading**: Rule-based / bot-driven execution via Alpaca
- **💼 Portfolio**: Positions and P&L tracking
- **📝 Paper trading**: Alpaca Markets API (sandbox-friendly workflow)

### 🛠️ Stack
- **Frontend**: React 18 + Vite + TypeScript
- **Backend**: Python FastAPI
- **Broker API**: Alpaca Markets (paper)
- **AI**: OpenAI GPT-4o / Google Gemini
- **State**: Zustand

---

## 🚀 Quick Start

### 1. Environment
```bash
# Create .env (repo root or backend/ — both are supported)
cp .env.example backend/.env

# Edit keys:
# - ALPACA_API_KEY / ALPACA_SECRET_KEY
# - OPENAI_API_KEY and/or GOOGLE_API_KEY
```

### 2. Backend
```bash
cd backend
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend
```bash
cd frontend
npm install
npm run dev
```

### 4. Open in browser
```
http://localhost:5173
```

---

## ⚠️ Important Notes
- **Paper trading**: Confirm API keys are for Alpaca **paper** before going live.
- **PDT**: Accounts under $25k are subject to the Pattern Day Trader rule on margin accounts; cash accounts have different constraints (e.g. GFV).
- **Risk**: Automation can lose money. Test thoroughly.

## ⚙️ Scalping safeguards (v4)

Before live trading, review:

- **Cash-account GFV tracking** — `compliance_service` tags buys and blocks selling lots bought with unsettled proceeds. Rolling 12-month GFV counter at `/api/regime/status` (`gfv_level`: OK → NOTICE → WARNING → RESTRICTED).
- **Wash-sale cooldown** — 30-day block on re-entering the same symbol after a realized loss. Realized trades JSONL under `TRADESENSE_LOG_DIR` for tax reconciliation.
- **Event blackout** — 2026 FOMC / CPI / NFP schedule in `event_calendar`, plus opening (9:30–9:35 ET) and closing (15:58–16:00 ET) auction windows.
- **Quantitative Market Status** — `regime_service` uses VIXY / TLT / UUP / GLD / XLE / BITO / SPY to produce a 0–100 score mapped to risk presets (`core.risk_presets`).
- **Risk presets** — Conservative / Moderate / Aggressive. Override: `POST /api/trading/bot/start` with `{"risk_level": "conservative"}`.
- **Trailing high-water mark** — per-position peak P&L for trail exits.
- **Marketable-limit + spread filter** — `execution_service` caps spread risk.
- **Loss-streak cooldown** — three consecutive losses → 15-minute pause on new entries.
- **Streaming scaffold** — `streaming_service.start_streaming(...)` for low-latency `us-east` + SIP deployments.

### Extra API routes
- `GET /api/regime/status` — market regime + active preset + compliance
- `GET /api/regime/presets` — full preset parameter table
- `GET /api/health/alpaca-usage` — Alpaca REST rate-limit snapshot

## 📄 License
MIT
