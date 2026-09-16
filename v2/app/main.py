"""TradeSense v4 entrypoint — one-rule grid on Alpaca (stocks) and Robinhood (crypto).

Local / Docker : APScheduler runs the grid tick in-process every 15 minutes.
Vercel         : cron-job.org hits /api/cron/run every ~15 min.
"""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import grid_engine
from .alpaca_config import clear_keys, save_keys, status_dict
from .config import settings
from .robinhood_config import clear_keys as clear_robinhood_keys
from .robinhood_config import save_keys as save_robinhood_keys
from .robinhood_config import status_dict as robinhood_status_dict
from .state import store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("tradesense")

VERSION = "v4"

JOBS = {
    "grid": grid_engine.tick,
}

# (weekdays_only, time predicate, dedupe once per ET day)
# The grid tick decides for itself whether the stock market is open; crypto
# trades around the clock.
GUARDS = {
    "grid": (False, lambda h, m: True, False),
}


def _start_scheduler() -> "object":
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    tz = settings.timezone
    sched = BackgroundScheduler(timezone=tz)

    def runner():
        try:
            grid_engine.tick()
        except Exception:
            log.exception("grid tick failed")

    sched.add_job(runner, CronTrigger(minute="0,15,30,45", timezone=tz))
    sched.start()
    return sched


def _authorized(request: Request) -> bool:
    """Accept cron secrets from headers and query for compatibility."""
    if not settings.cron_secret:
        return False
    secret = settings.cron_secret
    header = request.headers.get("authorization", "")
    bearer = header[7:] if header.startswith("Bearer ") else ""
    x_secret = request.headers.get("x-cron-secret", "")
    q_secret = request.query_params.get("secret", "")
    return (
        secrets.compare_digest(bearer, secret)
        or secrets.compare_digest(x_secret, secret)
        or secrets.compare_digest(q_secret, secret)
    )


def _admin_authorized(request: Request) -> bool:
    """Protects settings/grid routes. Uses ADMIN_TOKEN (or CRON_SECRET as
    fallback). Without any token configured, only non-Vercel (local) is open."""
    token = settings.admin_token or settings.cron_secret
    if not token:
        return not settings.on_vercel
    supplied = request.headers.get("x-admin-token", "")
    header = request.headers.get("authorization", "")
    bearer = header[7:] if header.startswith("Bearer ") else ""
    return (
        secrets.compare_digest(supplied, token)
        or secrets.compare_digest(bearer, token)
    )


def _unauthorized() -> JSONResponse:
    return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)


def _should_run(job: str, now: datetime) -> str | None:
    """None = 실행, str = skip 이유."""
    guard = GUARDS.get(job)
    if guard is None:
        return "unknown job"
    weekdays_only, hour_ok, dedupe = guard
    if weekdays_only and now.weekday() >= 5:
        return "weekend"
    if not hour_ok(now.hour, now.minute):
        return f"outside ET window (now {now:%H:%M} ET)"
    if dedupe and store.get(f"job_ran:{job}:{now.date().isoformat()}"):
        return "already ran today"
    return None


def _run_job(job: str) -> dict:
    fn = JOBS[job]
    done = fn() is not False
    return {"ok": True, "job": job, "done": done}


def _job_claim_key(job: str, now: datetime) -> str:
    """Daily key for once-per-day jobs; 15-minute bucket for recurring jobs."""
    day = now.date().isoformat()
    if GUARDS[job][2]:
        return f"{job}:{day}"
    return f"{job}:{day}:{now.hour:02d}:{now.minute // 15}"


def cron_tick() -> dict:
    """외부 스케줄러(cron-job.org)가 호출. 지금 실행할 잡만 골라 돌린다."""
    now = datetime.now(ZoneInfo(settings.timezone))
    results: dict[str, str] = {}
    for job in JOBS:
        skip = _should_run(job, now)
        if skip:
            results[job] = f"skipped: {skip}"
            continue
        claim = _job_claim_key(job, now)
        if not store.try_job_claim(claim):
            results[job] = "skipped: concurrent/already claimed"
            continue
        try:
            result = _run_job(job)
            if result["done"] and GUARDS[job][2]:
                store.set(f"job_ran:{job}:{now.date().isoformat()}", True)
            if not result["done"]:
                store.release_job_claim(claim)
            results[job] = "ok" if result["done"] else "deferred: will retry next tick"
        except Exception as exc:
            store.release_job_claim(claim)
            log.exception("job %s failed", job)
            results[job] = f"error: {exc}"
    return {"ok": True, "time": now.isoformat(), "results": results}


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched = None
    if not settings.on_vercel:
        sched = _start_scheduler()
        log.info("TradeSense %s started with in-process scheduler", VERSION)
    else:
        log.info("TradeSense %s on Vercel — cron-job.org → /api/cron/run", VERSION)
    yield
    if sched is not None:
        sched.shutdown(wait=False)


app = FastAPI(title=f"TradeSense {VERSION}", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
def dashboard():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/favicon.svg", include_in_schema=False)
def favicon_svg():
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/favicon.png", include_in_schema=False)
def favicon_png():
    return FileResponse(STATIC_DIR / "favicon.png", media_type="image/png")


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    return FileResponse(STATIC_DIR / "favicon.png", media_type="image/png")


@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION, "vercel": settings.on_vercel}


# ── Grid ────────────────────────────────────────────────────────────────────
class GridSettingsBody(BaseModel):
    step_pct: float  # percent, e.g. 5 for 5%


@app.get("/api/grid/status")
def grid_status(request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    return JSONResponse(grid_engine.status())


@app.post("/api/grid/settings")
def grid_settings(body: GridSettingsBody, request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    try:
        step = float(body.step_pct) / 100.0
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "숫자를 입력하세요."}, status_code=400)
    if not (grid_engine.grid.MIN_STEP <= step <= grid_engine.grid.MAX_STEP):
        return JSONResponse({
            "ok": False,
            "error": f"간격은 {grid_engine.grid.MIN_STEP:.0%}~{grid_engine.grid.MAX_STEP:.0%} 사이여야 합니다.",
        }, status_code=400)
    grid_engine.set_step(step)
    return JSONResponse({"ok": True, **grid_engine.status()})


@app.post("/api/grid/start")
def grid_start(request: Request):
    """현금화 후 사다리를 새로 구성하고 자동매매를 켠다."""
    if not _admin_authorized(request):
        return _unauthorized()
    try:
        return JSONResponse({"ok": True, **grid_engine.start()})
    except Exception as exc:
        log.exception("grid start failed")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/api/grid/stop")
def grid_stop(request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    return JSONResponse({"ok": True, **grid_engine.stop()})


@app.post("/api/grid/resume")
def grid_resume(request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    return JSONResponse({"ok": True, **grid_engine.resume()})


@app.post("/api/grid/tick")
def grid_tick_now(request: Request):
    """수동 점검 (디버그·즉시 실행)."""
    if not _admin_authorized(request):
        return _unauthorized()
    try:
        result = grid_engine.tick()
        return JSONResponse({"ok": True, "tick": result, **grid_engine.status()})
    except Exception as exc:
        log.exception("manual grid tick failed")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ── Broker keys ─────────────────────────────────────────────────────────────
class AlpacaKeysBody(BaseModel):
    api_key: str
    secret_key: str


@app.get("/api/settings")
def get_settings(request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    return JSONResponse(status_dict())


@app.post("/api/settings/keys")
def post_settings_keys(body: AlpacaKeysBody, request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    if not body.api_key.strip() or not body.secret_key.strip():
        return JSONResponse({"ok": False, "error": "api_key and secret_key required"}, status_code=400)
    try:
        save_keys(body.api_key, body.secret_key)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:
        log.exception("key save failed")
        return JSONResponse({"ok": False, "error": f"키 저장 실패: {exc}"}, status_code=502)
    grid_engine.set_venues(None)
    return JSONResponse({"ok": True, **status_dict()})


@app.delete("/api/settings/keys")
def delete_settings_keys(request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    clear_keys()
    grid_engine.set_venues(None)
    return JSONResponse({"ok": True, **status_dict()})


class RobinhoodKeysBody(BaseModel):
    api_key: str
    private_key: str


@app.get("/api/robinhood/status")
def robinhood_status(request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    return JSONResponse(robinhood_status_dict())


@app.post("/api/robinhood/keys")
def robinhood_post_keys(body: RobinhoodKeysBody, request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    try:
        save_robinhood_keys(body.api_key, body.private_key)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:
        log.exception("robinhood key save failed")
        return JSONResponse({"ok": False, "error": f"키 저장 실패: {exc}"}, status_code=502)
    grid_engine.set_venues(None)
    return JSONResponse({"ok": True, **robinhood_status_dict()})


@app.delete("/api/robinhood/keys")
def robinhood_delete_keys(request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    clear_robinhood_keys()
    grid_engine.set_venues(None)
    return JSONResponse({"ok": True, **robinhood_status_dict()})


@app.post("/api/notify/test")
def notify_test(request: Request):
    """텔레그램 설정 진단 — 테스트 메시지를 실제로 발송해본다."""
    if not _admin_authorized(request):
        return _unauthorized()
    from .notify import send_test
    result = send_test()
    return JSONResponse(result, status_code=200 if result["ok"] else 400)


# ── Cron ────────────────────────────────────────────────────────────────────
@app.get("/api/cron/run")
@app.post("/api/cron/run")
def cron_run(request: Request):
    """cron-job.org가 10~15분마다 호출."""
    if not _authorized(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    try:
        return JSONResponse(cron_tick())
    except Exception as exc:
        log.exception("cron tick failed")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.get("/api/cron/{job}")
@app.post("/api/cron/{job}")
def cron_job(job: str, request: Request):
    """개별 잡 수동 호출 (디버그용). job=run 은 cron_tick()과 동일."""
    if not _authorized(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    if job == "run":
        try:
            return JSONResponse(cron_tick())
        except Exception as exc:
            log.exception("cron tick failed")
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    if job not in JOBS:
        return JSONResponse({"ok": False, "error": f"unknown job '{job}'"}, status_code=404)
    now = datetime.now(ZoneInfo(settings.timezone))
    skip = _should_run(job, now)
    if skip:
        return JSONResponse({"ok": True, "skipped": skip})
    claim = _job_claim_key(job, now)
    if not store.try_job_claim(claim):
        return JSONResponse({"ok": True, "skipped": "concurrent/already claimed"})
    try:
        result = _run_job(job)
        if not result["done"]:
            store.release_job_claim(claim)
        return JSONResponse(result)
    except Exception as exc:
        store.release_job_claim(claim)
        log.exception("job %s failed", job)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
