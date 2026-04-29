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
- **PDT rule applies to *margin* accounts only.** A cash account can day-trade freely at any size (including \$10k or \$30k), as long as it respects T+1 settlement and the GFV/free-riding rules enforced by `compliance_service`.
- **Risk**: Automation can lose money. Test thoroughly.

## ⚙️ Scalping safeguards (v4)

Before live trading, review:

- **Cash-account GFV tracking** — `compliance_service` tags buys and blocks selling lots bought with unsettled proceeds. Rolling 12-month GFV counter at `/api/regime/status` (`gfv_level`: OK → NOTICE → WARNING → RESTRICTED).
- **Wash-sale cooldown** — 30-day block on re-entering the same symbol after a realized loss. Realized trades JSONL under `TRADESENSE_LOG_DIR` for tax reconciliation.
- **Event blackout** — 2026 FOMC / CPI / NFP schedule in `event_calendar`, plus opening (9:30–9:35 ET) and closing (15:58–16:00 ET) auction windows.
- **Quantitative Market Status** — `regime_service` uses VIXY / TLT / UUP / GLD / XLE / BITO / SPY to produce a 0–100 score mapped to risk presets (`core.risk_presets`).
- **Risk presets** — Conservative / Moderate / Aggressive across three capital scales (3k / 10k / 30k). Override: `POST /api/trading/bot/start` with `{"risk_level": "conservative"}`.
- **Trailing high-water mark** — per-position peak P&L for trail exits.
- **Marketable-limit + spread filter** — `execution_service` caps spread risk; `DEFAULT_ORDER_TIF=ioc` discards unfilled remainders so settled cash recycles each scan.
- **Loss-streak cooldown** — three consecutive losses → 15-minute pause on new entries.

## 🏎 Capital scales

Three cash-only preset tables are shipped. The active scale is controlled
by `CAPITAL_SCALE` (`auto | 3k | 10k | 30k`). `auto` picks based on
`INITIAL_CAPITAL`: `<\$6,500 → 3k`, `<\$20,000 → 10k`, otherwise 30k.

| Knob                        | 3k cons → aggr          | 10k cons → aggr         | 30k cons → aggr         |
|-----------------------------|-------------------------|-------------------------|-------------------------|
| `max_concurrent_positions`  | 2 → 8                   | 4 → 10                  | 6 → 14                  |
| `max_trades_per_day`        | 20 → 160                | 40 → 280                | 80 → **500**            |
| `entry_score_threshold`     | 65 → 28                 | 62 → 28                 | 60 → 26                 |
| `stop_loss_percent`         | 0.20 → 0.35             | 0.18 → 0.28             | 0.15 → 0.22             |
| `take_profit_percent`       | 0.50 → 0.70             | 0.45 → 0.55             | 0.35 → 0.40             |
| `min_notional_fast`         | \$300                   | \$600–\$1,000           | \$1,500–\$1,800         |
| `settled_cash_trade_cap`    | 0.50–0.60               | 0.45–0.55               | 0.35–0.45               |
| Default TIF                 | DAY                     | DAY (aggr = IOC)        | **IOC**                 |

The cash-utilization cap drops as capital grows because there's more
absolute GFV headroom — smaller per-trade % of settled cash with more
slots improves turnover without breaching cash-account rules.

### Enabling HFT mode (30k + SIP + cloud)

```bash
# .env
INITIAL_CAPITAL=30000
CAPITAL_SCALE=30k            # or "auto"
ALPACA_DATA_FEED=sip         # requires $99/mo Algo Trader Plus
STREAMING_ENABLED=true
DEFAULT_ORDER_TIF=ioc
```

Deploy the backend to AWS `us-east-1` (or GCP `us-east4`) for sub-3 ms
broker RTT; the `submit_to_fill_ms` column in the execution log will
confirm it.

### WebSocket streaming

When `STREAMING_ENABLED=true` and Alpaca keys are present, the backend
subscribes to trades + quotes via `StockDataStream` on boot. The stream
is **best-effort**: `AlpacaService` prefers the in-memory cache over
REST, but every path has a REST fallback. Inspect live state via:

```
GET /api/health/streaming
```

Returns `{connected, feed, subscribed, cached_symbols, last_error}`.

### Execution-quality logs

When `EXECUTION_LOG_ENABLED=true` (default), every outgoing order writes
a JSONL record under `trade_logs/execution-YYYY-MM-DD.jsonl` (per user at
`trade_logs/user_<id>/`). Each order produces four event types:

- `signal` — strategy decided to enter; includes `ref_price`, bid/ask, score, reasons, playbook
- `order` — submitted to broker; includes TIF, limit price, `signal_to_submit_ms`
- `fill` — reconciled after fill; includes `filled_avg_price`, `slippage_bps`, `submit_to_fill_ms`
- `reject` — quote/spread rejection or broker error

Use these files to measure real slippage vs signal price and tune the
marketable-limit buffer or spread filter.

### Extra API routes
- `GET /api/regime/status` — market regime + active preset + compliance
- `GET /api/regime/presets` — full preset parameter table
- `GET /api/health/alpaca-usage` — Alpaca REST rate-limit snapshot
- `GET /api/health/streaming` — WebSocket stream health
- `GET /api/trading/bot/status` — includes `stats.avg_slippage_bps`, `stats.capital_scale`

## 📄 License
MIT
