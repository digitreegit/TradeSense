"""Human-readable daily briefing for the dashboard."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import settings
from .state import store

REGIME_KO = {
    "BULL": "상승장 — 추세 추종 비중 확대",
    "CHOP": "혼조장 — 포지션 축소, 딥바이 위주",
    "BEAR": "하락장 — 방어적 운용, 모멘텀 축소",
}

WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def log_activity(job: str, message: str) -> None:
    """Append a timestamped activity line (kept ~14 days)."""
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    entries = store.get("activity_log", [])
    entries.append({
        "ts": now.isoformat(),
        "job": job,
        "message": message,
    })
    cutoff = (now - timedelta(days=14)).isoformat()
    entries = [e for e in entries if e.get("ts", "") >= cutoff][-200:]
    store.set("activity_log", entries)


def _today_et() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))


def _is_today(ts: str, now: datetime) -> bool:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        local = dt.astimezone(ZoneInfo(settings.timezone))
        return local.date() == now.date()
    except (ValueError, TypeError):
        return False


def _today_trades(trades: list[dict], now: datetime) -> list[dict]:
    return [t for t in trades if _is_today(t.get("ts", ""), now)]


def _today_activities(now: datetime) -> list[dict]:
    return [a for a in store.get("activity_log", []) if _is_today(a.get("ts", ""), now)]


def _week_plan(now: datetime) -> list[str]:
    wd = now.weekday()
    plans = []
    if wd == 0:
        plans.append("월요일 — 주간 모멘텀 리밸런싱 주문 체결 (09:31 ET)")
    if wd == 4:
        plans.append("금요일 — 오늘 16:35 결정 → 월요일 시가에 체결될 주문 예약")
    if wd < 5:
        plans.append("평일 08:45 — 뉴스 오버레이 (LLM 키 있을 때)")
        plans.append("평일 09:31 — 전일 예약 주문 체결")
        plans.append("평일 10:00~15:30 — 30분마다 장중 손절 점검")
        plans.append("평일 16:35 — 종가 기준 신호 계산 → 익일 주문 예약")
    if settings.crypto_enabled:
        plans.append("매시 — 크립토 트렌드 슬리브 (BTC/ETH)")
    else:
        plans.append("방어 슬리브 — GLD/TLT/IEF EMA 추세 (장중 체결, NJ 호환)")
    if wd >= 5:
        plans.append("주말 — 주식 주문 없음, 시장 데이터만 모니터링")
    return plans


def build_briefing(snapshot: dict) -> dict:
    """Build structured briefing from a snapshot dict."""
    now = _today_et()
    reg = snapshot.get("regime", {})
    regime_name = reg.get("regime", "CHOP")
    exposure = reg.get("exposure", 0.6)
    halted = snapshot.get("halted", False)
    dd = snapshot.get("drawdown", 0.0)
    sleeves = snapshot.get("sleeves", ["momentum", "dip", "defensive"])
    crypto_on = snapshot.get("crypto_enabled", False)

    today_trades = _today_trades(snapshot.get("trades", []), now)
    activities = [a for a in _today_activities(now) if a.get("job") != "cron"]
    pending = snapshot.get("pending", [])
    positions = snapshot.get("positions", [])

    # --- 오늘 한 일 ---
    today_lines: list[str] = []
    if not activities and not today_trades:
        today_lines.append("오늘 아직 기록된 활동이 없습니다.")
    for a in activities[-8:]:
        t = datetime.fromisoformat(a["ts"]).strftime("%H:%M")
        today_lines.append(f"{t} [{a['job']}] {a['message']}")
    if today_trades:
        for t in today_trades:
            ts = datetime.fromisoformat(t["ts"].replace("Z", "+00:00"))
            ts = ts.astimezone(ZoneInfo(settings.timezone)).strftime("%H:%M")
            side = "매수" if t["side"] == "buy" else "매도"
            today_lines.append(
                f"{ts} {side} {t['symbol']} ({t.get('sleeve', '?')}) "
                f"${t.get('notional', 0):,.0f} — {t.get('reason', '')}"
            )

    # --- 시장 상황 ---
    market_lines = [
        f"SPY 레짐: {regime_name} — {REGIME_KO.get(regime_name, '')}",
        f"목표 노출 비중: {exposure:.0%}",
        f"현재 드로다운: {dd:.1%}" + (" ⛔ 거래 중단" if halted else ""),
    ]
    tilt = snapshot.get("news_overlay", {}).get("tilt", 1.0)
    news = snapshot.get("news_overlay", {}).get("summary", "")
    if news:
        market_lines.append(f"뉴스 오버레이: {news} (tilt {tilt:.2f})")
    elif tilt != 1.0:
        market_lines.append(f"뉴스 tilt: {tilt:.2f}")

    # --- 현재 전략 ---
    sleeve_desc = " · ".join(sleeves)
    if crypto_on:
        third = "크립토(BTC/ETH) EMA 추세"
    else:
        third = "방어(GLD/TLT/IEF) EMA 추세 — NJ 등 크립토 미지원 지역용"
    strategy_lines = [
        f"3슬리브: 모멘텀 상위 {3}종 · RSI(2) 딥바이 · {third}",
        f"활성 슬리브: {sleeve_desc}",
        f"보유 {len(positions)}종목, 현금 ${snapshot.get('cash', 0):,.0f}",
    ]
    if pending:
        pq = ", ".join(f"{p['side']} {p['symbol']}" for p in pending[:5])
        strategy_lines.append(f"다음 장 시작 예약: {pq}")
    else:
        strategy_lines.append("다음 장 시작 예약 주문 없음")

    # --- 이번 주 ---
    week_lines = _week_plan(now)
    if regime_name == "BEAR":
        week_lines.insert(0, "하락장 — 딥바이·방어 ETF 위주, 신규 모멘텀 진입 제한")
    elif regime_name == "BULL":
        week_lines.insert(0, "상승장 — 모멘텀 리밸런싱 적극, 딥바이 보조")

    headline = f"{now.strftime('%m/%d')} ({WEEKDAY_KO[now.weekday()]}) — {regime_name}"
    if halted:
        headline += " · 거래 중단"

    return {
        "date": now.date().isoformat(),
        "headline": headline,
        "sections": [
            {"title": "오늘 한 일", "lines": today_lines},
            {"title": "시장 상황", "lines": market_lines},
            {"title": "현재 전략", "lines": strategy_lines},
            {"title": "이번 주 일정", "lines": week_lines},
        ],
        "activities_today": len(activities),
        "trades_today": len(today_trades),
    }
