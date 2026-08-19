"""Parse Robinhood mobile screenshots and sync the crypto advisor book."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from .briefing import log_activity
from .config import settings
from .crypto_advisor import advise_and_apply, import_holdings

log = logging.getLogger(__name__)

PROMPT = """You extract a Robinhood crypto portfolio from mobile app screenshots.

Return JSON only:
{
  "cash": <buying power or available cash as number, 0 if unknown>,
  "principal": <original invested amount if visible, else null>,
  "positions": [
    {"symbol": "XRP", "qty": 5004.162, "avg_cost": 1.80}
  ],
  "notes": "<one Korean sentence summarizing what you saw>"
}

Rules:
- symbol: uppercase ticker only (XRP, ETH, BTC, DOGE, SHIB, LINK, SOL, etc.)
- qty: exact quantity from "Your position" or holdings list
- avg_cost: from "Avg cost" field; null if not visible
- If total portfolio value is shown but cash isn't, estimate cash as 0
- Ignore stock/ETF positions (IONQ, SPY, etc.) — crypto only
- Merge duplicate symbols across multiple screenshots
- Do not invent positions not visible in the images
"""


def _vision_via_openai(images: list[bytes]) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
    from openai import OpenAI

    content: list[dict] = [{"type": "text", "text": PROMPT}]
    for img in images:
        b64 = base64.standard_b64encode(img).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    return json.loads(resp.choices[0].message.content)


def _vision_via_gemini(images: list[bytes]) -> dict[str, Any]:
    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다.")
    parts: list[dict] = [{"text": PROMPT}]
    for img in images:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.standard_b64encode(img).decode(),
            }
        })
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.google_model}:generateContent"
    )
    r = httpx.post(
        url,
        params={"key": settings.google_api_key},
        json={
            "contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=60.0,
    )
    body = r.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message", str(body["error"])))
    text = body["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def parse_screenshots(images: list[bytes]) -> dict[str, Any]:
    if not images:
        raise ValueError("스크린샷을 1장 이상 업로드하세요.")
    if settings.openai_api_key:
        return _vision_via_openai(images)
    if settings.google_api_key:
        return _vision_via_gemini(images)
    raise RuntimeError(
        "스크린샷 분석을 위해 OPENAI_API_KEY 또는 GOOGLE_API_KEY가 필요합니다."
    )


def analyze_and_advise(images: list[bytes]) -> dict:
    """Vision → holdings import → buy/sell guide."""
    parsed = parse_screenshots(images)
    positions = []
    for p in parsed.get("positions") or []:
        sym = str(p.get("symbol", "")).upper().strip()
        qty = float(p.get("qty") or 0)
        if not sym or qty <= 0:
            continue
        avg = p.get("avg_cost")
        positions.append({
            "symbol": sym,
            "qty": qty,
            "avg_cost": float(avg) if avg not in (None, "", 0) else None,
        })
    if not positions and not float(parsed.get("cash") or 0):
        raise ValueError("스크린샷에서 크립토 보유를 찾지 못했습니다.")

    cash = float(parsed.get("cash") or 0)
    principal = parsed.get("principal")
    principal_f = float(principal) if principal not in (None, "", 0) else None

    log_activity(
        "crypto",
        f"스크린샷 분석 — {len(positions)}종목, 현금 ${cash:,.0f}"
        + (f" · {parsed.get('notes', '')}" if parsed.get("notes") else ""),
    )
    data = import_holdings(cash, positions, principal_f)
    if data.get("ok"):
        data["parsed"] = {
            "cash": cash,
            "principal": principal_f,
            "positions": positions,
            "notes": parsed.get("notes", ""),
        }
    return data
