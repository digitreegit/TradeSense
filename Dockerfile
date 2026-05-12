# TradeSense: FastAPI + scalp engine + production SPA (optional multi-stage frontend build).
#
# Static UI is served from ``/app/frontend/dist`` when present (see ``backend/app/main.py``).

# --- Frontend (Vite) ---------------------------------------------------------
FROM node:20-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# Same-origin Docker / EC2 (:8000): VITE_PUBLIC_BASE=/  VITE_API_BASE=/api
# Legacy cPanel under /quant/: pass /quant/ and /quant/api instead.
ARG VITE_PUBLIC_BASE=/
ARG VITE_API_BASE=/api
ARG VITE_SUPABASE_URL=
ARG VITE_SUPABASE_ANON_KEY=
ENV VITE_PUBLIC_BASE=$VITE_PUBLIC_BASE \
    VITE_API_BASE=$VITE_API_BASE \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY

RUN npm run build

# --- Backend -----------------------------------------------------------------
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    TRADESENSE_LOG_DIR=/data/trade_logs \
    TRADESENSE_DB_PATH=/data/tradesense.db

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/ ./backend/

COPY --from=frontend-build /build/frontend/dist ./frontend/dist

# Persist trade logs + SQLite to a dedicated volume / EFS mount. Mount this
# at /data on Fargate (EFS) so engine restarts keep open lots, GFV history,
# and wash-loss carries (ComplianceService persistence).
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

WORKDIR /app/backend

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
