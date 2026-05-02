# TradeSense backend container.
#
# Builds the FastAPI app + scalp engine for ECS Fargate / EC2 / docker compose.
# Frontend is served as static assets when ``frontend/dist`` is mounted into
# ``backend/app/static`` (the FastAPI app already mounts that path when it
# exists). For ECS, build the SPA in CI and copy it in here, or front it
# separately with CloudFront + S3.

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

# Persist trade logs + SQLite to a dedicated volume / EFS mount. Mount this
# at /data on Fargate (EFS) so engine restarts keep open lots, GFV history,
# and wash-loss carries (ComplianceService persistence).
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

WORKDIR /app/backend

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
