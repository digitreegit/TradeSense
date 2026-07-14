"""TradeSense v2 entrypoint.

Local / Docker : APScheduler runs jobs in-process.
Vercel         : cron-job.org hits /api/cron/run every ~15 min (RuleFive와 동일).
                 앱이 ET 시간대·주말·중복 실행을 스스로 판단한다.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from .config import settings
from .engine import Engine
from .state import store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("tradesense")

engine = Engine()

JOBS = {
    "news": engine.job_news_overlay,
    "open": engine.job_execute_open,
    "stops": engine.job_intraday_stops,
    "decision": engine.job_daily_decision,
    "crypto": engine.job_crypto,
}

# (weekdays_only, time predicate, dedupe once per ET day)
GUARDS = {
    "news": (True, lambda h, m: h == 8, True),
    "open": (True, lambda h, m: (h == 9 and m >= 25) or 10 <= h < 16, True),
    "stops": (True, lambda h, m: 10 <= h < 16, False),
    "decision": (True, lambda h, m: (h == 16 and m >= 30) or h == 17, True),
    "crypto": (False, lambda h, m: True, False),
}


def _start_scheduler() -> "object":
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    tz = settings.timezone
    sched = BackgroundScheduler(timezone=tz)

    def wrap(fn):
        def runner():
            try:
                fn()
            except Exception:
                log.exception("job %s failed", fn.__name__)
        return runner

    sched.add_job(wrap(engine.job_news_overlay),
                  CronTrigger(day_of_week="mon-fri", hour=8, minute=45, timezone=tz))
    sched.add_job(wrap(engine.job_execute_open),
                  CronTrigger(day_of_week="mon-fri", hour=9, minute=31, timezone=tz))
    sched.add_job(wrap(engine.job_intraday_stops),
                  CronTrigger(day_of_week="mon-fri", hour="10-15", minute="0,30", timezone=tz))
    sched.add_job(wrap(engine.job_daily_decision),
                  CronTrigger(day_of_week="mon-fri", hour=16, minute=35, timezone=tz))
    sched.add_job(wrap(engine.job_crypto), CronTrigger(minute=5, timezone=tz))
    sched.start()
    return sched


def _authorized(request: Request) -> bool:
    """RuleFive와 동일: Bearer / x-cron-secret / ?secret= 모두 허용."""
    if not settings.cron_secret:
        return False
    secret = settings.cron_secret
    header = request.headers.get("authorization", "")
    bearer = header[7:] if header.startswith("Bearer ") else ""
    x_secret = request.headers.get("x-cron-secret", "")
    qs_secret = request.query_params.get("secret", "")
    return bearer == secret or x_secret == secret or qs_secret == secret


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
    fn()
    return {"ok": True, "job": job}


def cron_tick() -> dict:
    """외부 스케줄러(cron-job.org)가 호출. 지금 실행할 잡만 골라 돌린다."""
    now = datetime.now(ZoneInfo(settings.timezone))
    results: dict[str, str] = {}
    for job in JOBS:
        skip = _should_run(job, now)
        if skip:
            results[job] = f"skipped: {skip}"
            continue
        try:
            _run_job(job)
            if GUARDS[job][2]:
                store.set(f"job_ran:{job}:{now.date().isoformat()}", True)
            results[job] = "ok"
        except Exception as exc:
            log.exception("job %s failed", job)
            results[job] = f"error: {exc}"
    from .briefing import log_activity
    summary = ", ".join(f"{k}={v}" for k, v in results.items())
    log_activity("cron", f"스케줄러 tick — {summary}")
    return {"ok": True, "time": now.isoformat(), "results": results}


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched = None
    if not settings.on_vercel:
        sched = _start_scheduler()
        log.info("TradeSense v2 started with in-process scheduler (mode=%s)", settings.trading_mode)
    else:
        log.info("TradeSense v2 on Vercel — cron-job.org → /api/cron/run (mode=%s)", settings.trading_mode)
    yield
    if sched is not None:
        sched.shutdown(wait=False)


app = FastAPI(title="TradeSense v2", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "mode": settings.trading_mode, "vercel": settings.on_vercel}


@app.get("/api/snapshot")
def snapshot():
    return JSONResponse(engine.snapshot())


@app.get("/api/cron/run")
@app.post("/api/cron/run")
def cron_run(request: Request):
    """RuleFive와 동일 패턴. cron-job.org가 10~15분마다 호출."""
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
    try:
        result = _run_job(job)
        if GUARDS[job][2]:
            store.set(f"job_ran:{job}:{now.date().isoformat()}", True)
        return JSONResponse(result)
    except Exception as exc:
        log.exception("job %s failed", job)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
