# TradeSense - Agent Instructions

## Cursor Cloud specific instructions

### Architecture
- **Backend**: Python 3.12 + FastAPI on port 8000 (`/workspace/backend/`)
- **Frontend**: React 18 + Vite + TypeScript on port 5173 (`/workspace/frontend/`)
- No database; all state is in-memory + Alpaca API. No Docker required.

### Running the services

**Backend** (from `/workspace/backend/`):
```bash
source venv/bin/activate
uvicorn app.main:app --reload --port 8000 --host 0.0.0.0
```

**Frontend** (from `/workspace/frontend/`):
```bash
npm run dev
```
The Vite dev server proxies `/api` and `/ws` to `localhost:8000`.

### Environment
- `.env` must be at `/workspace/backend/.env`. Copy from `/workspace/.env.example` if missing.
- The `.env.example` ships with working Alpaca paper-trading keys and a Gemini API key. Without valid keys, the backend runs in "demo mode" with fake data.

### Gotchas
- The frontend `tsc -b` has pre-existing TS strict errors (e.g., missing `RegimeData` type, `className` on an intrinsic). `vite build` succeeds regardless because Vite uses esbuild (not tsc) for transpilation.
- The backend trading loop starts automatically on boot and begins placing paper trades. This is expected behavior.
- There is a non-critical warning: `TradingClient.get_portfolio_history() got an unexpected keyword argument 'period'`. This comes from an `alpaca-py` API change and does not affect core functionality.
- No linter (ESLint/pylint) is configured in the project. `tsc -b` is the closest to a lint check for the frontend.
- No automated test suite exists in this codebase.

### Verification
- Backend health: `curl http://localhost:8000/api/health`
- Frontend proxy: `curl http://127.0.0.1:5173/api/health`
