"""TradeSense v3 entrypoint.

Local / Docker : APScheduler runs jobs in-process.
Vercel         : cron-job.org hits /api/cron/run every ~15 min (RuleFive와 동일).
                 앱이 ET 시간대·주말·중복 실행을 스스로 판단한다.
"""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .alpaca_config import clear_keys, save_keys, status_dict

from .config import settings
from .crypto_advisor import (
    advise_and_apply, confirm_order, deny_order, import_holdings, reset_book,
    run_scheduled, set_investing_total, set_principal, set_stocks_value,
)
from .engine import Engine
from .robinhood_config import clear_keys as clear_robinhood_keys
from .robinhood_config import get_execution_mode, set_execution_mode
from .robinhood_config import save_keys as save_robinhood_keys
from .robinhood_config import status_dict as robinhood_status_dict
from .robinhood_sync import sync_from_robinhood
from .robinhood_vision import analyze_and_advise
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
    # Crypto advisor: awake-hours checks; Telegram only when tips need approval.
    "crypto_advise": lambda: run_scheduled("check"),
}

# (weekdays_only, time predicate, dedupe once per ET day)
GUARDS = {
    "news": (True, lambda h, m: h == 8, True),
    "open": (True, lambda h, m: (h == 9 and m >= 25) or 10 <= h < 16, True),
    # from 09:31 so an opening gap through a stop is cut at the open,
    # not 30-60 minutes later (2026-07-31 AAPL gap sat until 10:00)
    "stops": (True, lambda h, m: (h == 9 and m >= 31) or 10 <= h < 16, False),
    "decision": (True, lambda h, m: (h == 16 and m >= 30) or h == 17, True),
    "crypto": (False, lambda h, m: True, False),
    # Every cron tick (~15m) between 06:00 and 23:59 ET (quiet 00:00–05:59).
    "crypto_advise": (False, lambda h, m: 6 <= h <= 23, False),
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
                  CronTrigger(day_of_week="mon-fri", hour=9, minute=32, timezone=tz))
    sched.add_job(wrap(engine.job_intraday_stops),
                  CronTrigger(day_of_week="mon-fri", hour="10-15", minute="0,30", timezone=tz))
    sched.add_job(wrap(engine.job_daily_decision),
                  CronTrigger(day_of_week="mon-fri", hour=16, minute=35, timezone=tz))
    sched.add_job(wrap(engine.job_crypto), CronTrigger(minute=5, timezone=tz))
    # Crypto advisor: every 15 min while awake (06:00–23:45 ET). Quiet overnight.
    sched.add_job(wrap(lambda: run_scheduled("check")),
                  CronTrigger(hour="6-23", minute="0,15,30,45", timezone=tz))
    sched.start()
    return sched


def _authorized(request: Request) -> bool:
    """Accept cron secrets from headers and query for compatibility.

    Header is preferred (`Authorization: Bearer ...` or `x-cron-secret`), but
    some existing cron-job.org entries still use `?secret=...`. Keep both so
    scheduled jobs (including crypto advise ticks) don't silently
    stop after auth-hardening deploys.
    """
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
    """Protects settings/snapshot routes. Uses ADMIN_TOKEN (or CRON_SECRET as
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
    # Jobs may return False to mean "could not complete yet, retry next tick"
    # (e.g. execute_open called before the 09:30 bell). Only a non-False
    # result may be deduped for the day.
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
    try:
        from .briefing import log_activity
        summary = ", ".join(f"{k}={v}" for k, v in results.items())
        log_activity("cron", f"스케줄러 tick — {summary}")
    except Exception:
        log.exception("activity log failed")
    return {"ok": True, "time": now.isoformat(), "results": results}


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched = None
    if not settings.on_vercel:
        sched = _start_scheduler()
        log.info("TradeSense v3 started with in-process scheduler (mode=live)")
    else:
        log.info("TradeSense v3 on Vercel — cron-job.org → /api/cron/run (mode=live)")
    yield
    if sched is not None:
        sched.shutdown(wait=False)


app = FastAPI(title="TradeSense v3", lifespan=lifespan,
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
    # Browsers often request /favicon.ico by default; serve the PNG mark.
    return FileResponse(STATIC_DIR / "favicon.png", media_type="image/png")


@app.get("/api/health")
def health():
    from .alpaca_config import get_trading_mode
    return {"ok": True, "mode": get_trading_mode(), "vercel": settings.on_vercel}


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
    engine.reset_broker()
    # New keys = potentially a different account: reset drawdown baseline,
    # regime, positions and history so the new balance starts clean.
    store.reset_trading_state()
    return JSONResponse({"ok": True, **status_dict()})


@app.delete("/api/settings/keys")
def delete_settings_keys(request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    clear_keys()
    engine.reset_broker()
    return JSONResponse({"ok": True, **status_dict()})


@app.post("/api/settings/reset")
def post_settings_reset(request: Request):
    """Manually reset drawdown baseline / regime / positions / history.
    Useful after switching accounts to clear a stale drawdown brake."""
    if not _admin_authorized(request):
        return _unauthorized()
    store.reset_trading_state()
    engine.reset_broker()
    return JSONResponse({"ok": True, **status_dict()})


@app.get("/api/snapshot")
def snapshot(request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    return JSONResponse(engine.snapshot())


@app.post("/api/crypto/screenshots")
async def crypto_screenshots(
    request: Request,
    files: list[UploadFile] = File(...),
):
    """로빈후드 스크린샷 → 보유 추출 → 매수/매도 가이드."""
    if not _admin_authorized(request):
        return _unauthorized()
    try:
        images = [await f.read() for f in files]
        images = [b for b in images if b]
        result = analyze_and_advise(images)
        return JSONResponse(result, status_code=200 if result.get("ok") else 400)
    except Exception as exc:
        log.exception("screenshot analysis failed")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.get("/api/crypto/advice")
def crypto_advice(request: Request):
    """크립토 가상 포트폴리오 주문 지시 (실행은 로빈후드에서 수동)."""
    if not _admin_authorized(request):
        return _unauthorized()
    return JSONResponse(advise_and_apply())


@app.post("/api/notify/test")
def notify_test(request: Request):
    """텔레그램 설정 진단 — 테스트 메시지를 실제로 발송해본다."""
    if not _admin_authorized(request):
        return _unauthorized()
    from .notify import send_test
    result = send_test()
    return JSONResponse(result, status_code=200 if result["ok"] else 400)


class CryptoConfirmBody(BaseModel):
    id: str
    dollars: float | None = None


class CryptoDenyBody(BaseModel):
    id: str


@app.post("/api/crypto/confirm")
def crypto_confirm(body: CryptoConfirmBody, request: Request):
    """추천 확인 — manual은 장부만, semi/auto는 Robinhood API 주문 후 장부."""
    if not _admin_authorized(request):
        return _unauthorized()
    result = confirm_order(body.id, body.dollars)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


class CryptoExecModeBody(BaseModel):
    mode: str


@app.get("/api/crypto/execution-mode")
def crypto_exec_mode_get(request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    return JSONResponse({
        "ok": True,
        "mode": get_execution_mode(),
        "modes": ["manual", "semi", "auto"],
    })


@app.post("/api/crypto/execution-mode")
def crypto_exec_mode_set(body: CryptoExecModeBody, request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    try:
        mode = set_execution_mode(body.mode)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    from .briefing import log_activity
    log_activity("crypto", f"실행 모드 → {mode}")
    return JSONResponse({"ok": True, "mode": mode})


@app.post("/api/crypto/deny")
def crypto_deny(body: CryptoDenyBody, request: Request):
    """추천 거부 — 로빈후드에서 실행하지 않음."""
    if not _admin_authorized(request):
        return _unauthorized()
    result = deny_order(body.id)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


class CryptoPrincipalBody(BaseModel):
    principal: float


@app.post("/api/crypto/principal")
def crypto_principal(body: CryptoPrincipalBody, request: Request):
    """원금 회복 목표 금액 설정."""
    if not _admin_authorized(request):
        return _unauthorized()
    result = set_principal(body.principal)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


class CryptoStocksBody(BaseModel):
    stocks_value: float | None = None
    investing_total: float | None = None


@app.post("/api/crypto/stocks")
def crypto_stocks(body: CryptoStocksBody, request: Request):
    """주식·ETF 평가액 또는 Investing 앱 총액으로 잔액 맞춤."""
    if not _admin_authorized(request):
        return _unauthorized()
    if body.investing_total is not None:
        result = set_investing_total(body.investing_total)
    elif body.stocks_value is not None:
        result = set_stocks_value(body.stocks_value)
    else:
        return JSONResponse(
            {"ok": False, "error": "stocks_value 또는 investing_total이 필요합니다."},
            status_code=400,
        )
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


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
    return JSONResponse({"ok": True, **robinhood_status_dict()})


@app.delete("/api/robinhood/keys")
def robinhood_delete_keys(request: Request):
    if not _admin_authorized(request):
        return _unauthorized()
    clear_robinhood_keys()
    return JSONResponse({"ok": True, **robinhood_status_dict()})


@app.post("/api/robinhood/sync")
def robinhood_sync(request: Request):
    """Robinhood API로 보유·현금 동기화 → 매수/매도 가이드."""
    if not _admin_authorized(request):
        return _unauthorized()
    try:
        result = sync_from_robinhood()
        return JSONResponse(result, status_code=200 if result.get("ok") else 400)
    except Exception as exc:
        log.exception("robinhood sync failed")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/crypto/reset")
def crypto_reset(request: Request):
    """가상 크립토 포트폴리오를 $1,000 현금 상태로 초기화."""
    if not _admin_authorized(request):
        return _unauthorized()
    reset_book()
    return JSONResponse(advise_and_apply(force=True))


class CryptoHolding(BaseModel):
    symbol: str
    qty: float
    avg_cost: float | None = None


class CryptoHoldingsBody(BaseModel):
    cash: float = 0.0
    positions: list[CryptoHolding]
    principal: float | None = None


@app.post("/api/crypto/holdings")
def crypto_holdings(body: CryptoHoldingsBody, request: Request):
    """실제 로빈후드 보유 내역으로 장부를 재구성."""
    if not _admin_authorized(request):
        return _unauthorized()
    result = import_holdings(
        body.cash, [h.model_dump() for h in body.positions], body.principal,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


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
    claim = _job_claim_key(job, now)
    if not store.try_job_claim(claim):
        return JSONResponse({"ok": True, "skipped": "concurrent/already claimed"})
    try:
        result = _run_job(job)
        if result["done"] and GUARDS[job][2]:
            store.set(f"job_ran:{job}:{now.date().isoformat()}", True)
        if not result["done"]:
            store.release_job_claim(claim)
        return JSONResponse(result)
    except Exception as exc:
        store.release_job_claim(claim)
        log.exception("job %s failed", job)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
