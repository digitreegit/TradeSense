# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

TradeSense is an AI-powered quant trading platform (React + FastAPI) for US stock paper trading via Alpaca Markets. There is no database — all persistent state lives in Alpaca's API. See `README.md` for feature details.

### Services

| Service | Command | Port |
|---------|---------|------|
| Backend (FastAPI) | `cd backend && source venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` | 8000 |
| Frontend (Vite) | `cd frontend && npm run dev` | 5173 |

Start the backend **before** the frontend — the Vite dev server proxies `/api` and `/ws` to port 8000.

### Environment variables

Copy `.env.example` to `backend/.env`. The config loader (`backend/app/core/config.py`) searches for `.env` in the `backend/` directory and CWD. Required keys:

- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — paper trading credentials
- `GOOGLE_API_KEY` (if `AI_PROVIDER=gemini`) or `OPENAI_API_KEY` (if `AI_PROVIDER=openai`)

Without valid Alpaca keys the backend starts in demo mode. Without a valid AI key the analysis agent returns errors but all other features work.

### Known issues

- `npm run build` fails due to pre-existing TypeScript errors (`tsc -b` step). The Vite dev server works fine because it uses esbuild which does not enforce strict type checking.
- `TradingClient.get_portfolio_history()` logs a warning about an unexpected `period` keyword argument — this is a non-blocking `alpaca-py` SDK compatibility issue.

### Lint / Test

The codebase has **no ESLint configuration and no automated test suite** (no pytest, no Jest/Vitest). TypeScript checking can be run with `cd frontend && npx tsc --noEmit` but has pre-existing errors.

### Python virtual environment

The backend uses a venv at `backend/venv`. Always activate it before running backend commands: `source backend/venv/bin/activate`.
