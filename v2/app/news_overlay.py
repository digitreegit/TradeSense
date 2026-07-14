"""Optional LLM news overlay.

Once a day, feed recent market headlines to an LLM and get back:
- an exposure tilt in [0.7, 1.2] applied to NEW position sizes
- a list of symbols to avoid today (e.g. fraud news, halted, blow-up)

The strategy works without this (backtested without it); the overlay only
nudges sizing. If no OPENAI_API_KEY is configured this is a no-op.
"""
from __future__ import annotations

import json
import logging

from .config import settings
from .state import store

log = logging.getLogger(__name__)

DEFAULT = {"tilt": 1.0, "avoid": [], "summary": ""}

PROMPT = """You are the risk overlay of a systematic swing-trading bot
(momentum rotation + dip buying on US ETFs/megacaps + BTC/ETH trend).
Based on the following recent market headlines, reply with JSON only:
{{"tilt": <float 0.7-1.2>, "avoid": [<symbols to avoid buying today>],
"summary": "<one sentence in Korean>"}}
tilt < 1 means reduce new position sizes (elevated tail risk: war escalation,
credit event, surprise Fed action). tilt > 1 means conditions are unusually
benign. Stay at 1.0 unless there is a clear reason.

Headlines:
{headlines}
"""


def fetch_headlines(broker) -> list[str]:
    try:
        from alpaca.data.historical.news import NewsClient
        from alpaca.data.requests import NewsRequest

        client = NewsClient(settings.alpaca_api_key, settings.alpaca_secret_key)
        req = NewsRequest(symbols="SPY,QQQ,BTC/USD", limit=25)
        news = client.get_news(req)
        return [n.headline for n in news.data.get("news", [])]
    except Exception as exc:
        log.warning("news fetch failed: %s", exc)
        return []


def run_overlay(broker) -> dict:
    if not settings.openai_api_key:
        store.set("news_overlay", DEFAULT)
        return DEFAULT
    headlines = fetch_headlines(broker)
    if not headlines:
        store.set("news_overlay", DEFAULT)
        return DEFAULT
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": PROMPT.format(headlines="\n".join(f"- {h}" for h in headlines))}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(resp.choices[0].message.content)
        result = {
            "tilt": max(0.7, min(1.2, float(data.get("tilt", 1.0)))),
            "avoid": [str(s).upper() for s in data.get("avoid", [])][:10],
            "summary": str(data.get("summary", ""))[:300],
        }
    except Exception as exc:
        log.warning("LLM overlay failed: %s", exc)
        result = DEFAULT
    store.set("news_overlay", result)
    return result


def current() -> dict:
    return store.get("news_overlay", DEFAULT)
