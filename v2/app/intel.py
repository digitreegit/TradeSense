"""v6.2 — market intelligence layer for the crypto dip rule.

Once a day (and on demand) recent macro/crypto headlines are scored by an
LLM into one number, `score` in [-1, +1]: how the next 1-3 days look for
crypto (rates, geopolitics, regulation such as the CLARITY Act, oil/dollar,
crypto-specific flows). The rule itself is untouched; the score only tilts
three knobs inside fixed bounds, scaled by a user-set `strength`:

    buy trigger   dip% x [0.7 .. 1.3]   (bullish: buy sooner, bearish: wait for a deeper dip)
    lot size      $    x [0.6 .. 1.3]
    buys per tick      1 .. 3
    tail risk     score <= -0.6 with confidence >= 0.6 -> no new buys for 24h

Sell targets never move. Every buy is stamped with the score so the
scorecard can show whether bearish/neutral/bullish days actually differ —
this layer cannot be replayed (no headline archive), so the evidence has to
come from live trades. Strength 0 reproduces the plain rule exactly.
"""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from .config import settings
from .state import store

log = logging.getLogger(__name__)

LATEST_KEY = "intel_latest"
HISTORY_KEY = "intel_history"
MAX_HISTORY = 180

DEFAULT_STRENGTH = 0.5
MIN_STRENGTH, MAX_STRENGTH = 0.0, 1.0
STALE_HOURS = 36          # older analysis counts as "no opinion"
PAUSE_SCORE = -0.6        # tail risk: at or below this ...
PAUSE_CONFIDENCE = 0.6    # ... with at least this confidence ...
PAUSE_HOURS = 24          # ... stops new buys for this long
DIP_TILT = 0.30           # dip% x (1 - DIP_TILT*w)
DOLLARS_UP, DOLLARS_DOWN = 0.30, 0.40
MAX_BUYS = 3

FACTORS = ("rates", "geopolitics", "regulation", "oil_dollar", "crypto")
FACTOR_KO = {
    "rates": "금리·연준", "geopolitics": "지정학", "regulation": "규제·법안",
    "oil_dollar": "유가·달러", "crypto": "크립토 고유",
}

RSS_QUERIES = (
    "Federal Reserve interest rate decision",
    "bitcoin ETF flows",
    "crypto regulation CLARITY Act SEC",
    "ceasefire OR escalation war markets",
    "crude oil price OPEC",
    "US dollar index treasury yields",
)

PROMPT = """You are the daily macro desk for a systematic crypto bot. The bot buys any
major coin that is 5% under its 24h high and sells 5% higher; it holds through drawdowns.
It cannot predict; you only tilt how eagerly it buys over the NEXT 1-3 DAYS.

From the headlines below (last ~36h), reply with JSON only:
{{
  "score": <float -1..1, expected crypto market direction next 1-3 days; 0 = no edge>,
  "confidence": <float 0..1>,
  "factors": {{"rates": <-1..1>, "geopolitics": <-1..1>, "regulation": <-1..1>,
               "oil_dollar": <-1..1>, "crypto": <-1..1>}},
  "reasons": ["<Korean, one line>", "<Korean>", "<Korean>"],
  "key_headlines": ["<verbatim headline>", ... up to 5],
  "summary": "<one Korean sentence>"
}}
Rules: stay near 0 unless headlines carry NEW, concrete, scheduled or confirmed information
(rate decision dates, actual legislation votes, confirmed ceasefire/escalation, ETF
approvals/outflows, exchange failures). Opinion pieces and price commentary are not evidence.
Negative score for: surprise hikes/hawkish pivot, war escalation, regulatory crackdown,
exchange insolvency, sharp dollar/oil spikes. Positive for: confirmed cuts, de-escalation,
pro-crypto legislation passing, strong ETF inflows.

Headlines:
{headlines}
"""


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------
def clamp(x, lo, hi):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return lo if lo > 0 else 0.0
    return max(lo, min(hi, v))


def clamp_strength(x) -> float:
    return round(clamp(x, MIN_STRENGTH, MAX_STRENGTH), 2)


def bucket(score: float | None) -> str:
    if score is None:
        return "none"
    if score <= -0.2:
        return "bear"
    if score >= 0.2:
        return "bull"
    return "neutral"


BUCKET_KO = {"bear": "약세", "neutral": "중립", "bull": "강세", "none": "판단 없음"}


def _age_hours(iso: str | None, now: datetime) -> float | None:
    if not iso:
        return None
    try:
        at = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (now - at).total_seconds() / 3600.0


def effective(base: dict, latest: dict | None, *, enabled: bool, strength: float,
              now: datetime | None = None) -> dict:
    """Tilt the dip knobs by the latest score. `base` = settings["dip"]."""
    now = now or datetime.now(timezone.utc)
    pct = float(base["pct"])
    dollars = float(base["order_dollars"])
    out = {
        "pct": pct, "order_dollars": dollars, "max_buys": MAX_BUYS,
        "paused": False, "paused_until": None,
        "score": None, "confidence": None, "bucket": "none", "w": 0.0,
        "age_hours": None, "active": False, "note": None,
    }
    if not enabled or strength <= 0 or not latest or latest.get("score") is None:
        out["note"] = "지능 꺼짐" if not enabled or strength <= 0 else "분석 없음"
        return out
    age = _age_hours(latest.get("at"), now)
    out["age_hours"] = round(age, 1) if age is not None else None
    score = clamp(latest.get("score"), -1.0, 1.0)
    conf = clamp(latest.get("confidence", 0.5), 0.0, 1.0)
    out["score"], out["confidence"], out["bucket"] = score, conf, bucket(score)
    if age is None or age > STALE_HOURS:
        out["note"] = f"분석이 {age:.0f}시간 전 — 보정 없음" if age is not None else "분석 시각 없음"
        return out
    w = score * conf * float(strength)
    out["w"] = round(w, 3)
    out["active"] = True
    out["pct"] = round(pct * (1.0 - DIP_TILT * w), 4)
    out["order_dollars"] = round(dollars * (1.0 + (DOLLARS_UP if w > 0 else DOLLARS_DOWN) * w), 2)
    out["max_buys"] = MAX_BUYS if w >= -0.2 else (2 if w > -0.6 else 1)
    if score <= PAUSE_SCORE and conf >= PAUSE_CONFIDENCE:
        until = datetime.fromisoformat(latest["at"])
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        until += timedelta(hours=PAUSE_HOURS)
        if now < until:
            out["paused"] = True
            out["paused_until"] = until.isoformat()
            out["note"] = f"꼬리 위험 — {until.astimezone().strftime('%m/%d %H:%M')}까지 신규 매수 중단"
    return out


def stamp(eff: dict) -> dict | None:
    """What gets written on each buy."""
    if eff.get("score") is None:
        return None
    return {"score": eff["score"], "confidence": eff["confidence"], "bucket": eff["bucket"],
            "w": eff["w"], "active": bool(eff.get("active"))}


# --------------------------------------------------------------------------
# Headlines
# --------------------------------------------------------------------------
def _alpaca_headlines(limit: int = 30) -> list[dict]:
    try:
        from alpaca.data.historical.news import NewsClient
        from alpaca.data.requests import NewsRequest

        from .alpaca_config import get_credentials

        api_key, secret_key, _ = get_credentials()
        if not api_key:
            return []
        client = NewsClient(api_key, secret_key)
        req = NewsRequest(symbols="BTC/USD,ETH/USD,SPY", limit=limit)
        news = client.get_news(req)
        rows = news.data.get("news", []) if isinstance(news.data, dict) else []
        out = []
        for n in rows:
            out.append({"title": str(getattr(n, "headline", "") or ""),
                        "source": str(getattr(n, "source", "") or "alpaca"),
                        "at": getattr(n, "created_at", None) and n.created_at.isoformat()})
        return out
    except Exception as exc:
        log.warning("alpaca news failed: %s", exc)
        return []


def _rss_headlines(query: str, limit: int = 10) -> list[dict]:
    import httpx
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}+when:2d&hl=en-US&gl=US&ceid=US:en"
    try:
        r = httpx.get(url, timeout=15.0, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 TradeSense/6.2"})
        r.raise_for_status()
        root = ET.fromstring(r.text)
    except Exception as exc:
        log.warning("rss %r failed: %s", query, exc)
        return []
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        source = (item.findtext("source") or "").strip()
        title = re.sub(r"\s+-\s+[^-]+$", "", title) if not source else title.replace(f" - {source}", "")
        out.append({"title": title, "source": source or "google", "at": item.findtext("pubDate")})
        if len(out) >= limit:
            break
    return out


def fetch_headlines() -> list[dict]:
    rows = _alpaca_headlines()
    for q in RSS_QUERIES:
        rows.extend(_rss_headlines(q))
    seen, out = set(), []
    for r in rows:
        key = re.sub(r"[^a-z0-9]+", " ", r["title"].lower()).strip()[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out[:70]


# --------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------
def _ask_llm(headlines: list[dict]) -> dict:
    text = "\n".join(f"- [{h.get('source') or '?'}] {h['title']}" for h in headlines)
    prompt = PROMPT.format(headlines=text)
    if settings.google_api_key:
        from .robinhood_vision import _gemini_generate, _gemini_models_to_try
        last: Exception | None = None
        for model in _gemini_models_to_try(settings.google_model):
            try:
                return _gemini_generate(model, [{"text": prompt}])
            except Exception as exc:  # noqa: BLE001
                last = exc
                log.warning("gemini %s failed: %s", model, exc)
        raise RuntimeError(f"Gemini failed: {last}")
    if settings.openai_api_key:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.openai_model, temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)
    raise RuntimeError("GOOGLE_API_KEY 또는 OPENAI_API_KEY가 필요합니다.")


def normalize(data: dict, headlines: list[dict], now: datetime) -> dict:
    factors = data.get("factors") or {}
    return {
        "at": now.isoformat(),
        "score": round(clamp(data.get("score"), -1.0, 1.0), 2),
        "confidence": round(clamp(data.get("confidence", 0.5), 0.0, 1.0), 2),
        "factors": {k: round(clamp(factors.get(k, 0.0), -1.0, 1.0), 2) for k in FACTORS},
        "reasons": [str(r)[:160] for r in (data.get("reasons") or [])][:3],
        "key_headlines": [str(h)[:200] for h in (data.get("key_headlines") or [])][:5],
        "summary": str(data.get("summary") or "")[:300],
        "headline_count": len(headlines),
        "headlines": [{"title": h["title"][:200], "source": h.get("source")} for h in headlines[:40]],
        "error": None,
    }


def run(now: datetime | None = None, *, notify=None) -> dict:
    """Fetch, score, store. Never raises; a failed run stores the error and
    leaves the previous score in place (it ages out after STALE_HOURS)."""
    now = now or datetime.now(timezone.utc)
    headlines = fetch_headlines()
    try:
        if not headlines:
            raise RuntimeError("헤드라인을 하나도 가져오지 못했습니다.")
        result = normalize(_ask_llm(headlines), headlines, now)
    except Exception as exc:  # noqa: BLE001
        log.warning("intel run failed: %s", exc)
        prev = store.get(LATEST_KEY) or {}
        prev = dict(prev)
        prev["error"] = f"{now.isoformat()}: {exc}"
        store.set(LATEST_KEY, prev)
        return prev
    store.set(LATEST_KEY, result)
    hist = store.get(HISTORY_KEY) or []
    hist.append({k: result[k] for k in ("at", "score", "confidence", "factors", "summary")})
    store.set(HISTORY_KEY, hist[-MAX_HISTORY:])
    if notify:
        try:
            b = BUCKET_KO[bucket(result["score"])]
            notify(f"[v6 지능] 오늘 판단 {b} ({result['score']:+.2f}, 확신 {result['confidence']:.0%}) — {result['summary']}")
        except Exception:
            log.exception("intel notify failed")
    return result


def latest() -> dict | None:
    return store.get(LATEST_KEY) or None


def history(limit: int = 60) -> list[dict]:
    return (store.get(HISTORY_KEY) or [])[-limit:]
