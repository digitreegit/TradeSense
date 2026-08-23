"""Parse Robinhood mobile screenshots and sync the crypto advisor book."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from .briefing import log_activity
from .config import settings
from .crypto_advisor import (
    BOOK_KEY, CACHE_KEY, advise_and_apply, import_holdings,
)
from .state import store

log = logging.getLogger(__name__)

# Retired preview/stable IDs → current vision-capable models (Aug 2026).
_GOOGLE_MODEL_ALIASES = {
    "gemini-2.0-flash-exp": "gemini-2.5-flash",
    "gemini-2.0-flash": "gemini-2.5-flash",
    "gemini-2.0-flash-lite-exp": "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite": "gemini-2.5-flash-lite",
    "gemini-1.5-flash-exp": "gemini-2.5-flash",
    "gemini-1.5-flash": "gemini-2.5-flash",
    "gemini-1.5-pro-exp": "gemini-2.5-flash",
    "gemini-1.5-pro": "gemini-2.5-flash",
}

_GOOGLE_VISION_FALLBACKS = (
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
)


def _resolve_google_model(name: str) -> str:
    model = (name or "gemini-2.5-flash").strip()
    if model.startswith("models/"):
        model = model[7:]
    return _GOOGLE_MODEL_ALIASES.get(model, model)


def _gemini_models_to_try(preferred: str) -> list[str]:
    first = _resolve_google_model(preferred)
    chain = [first]
    for model in _GOOGLE_VISION_FALLBACKS:
        if model not in chain:
            chain.append(model)
    return chain


def _image_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and len(data) > 12 and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


PROMPT = """You extract a Robinhood Investing portfolio from mobile/web screenshots.

Return JSON only:
{
  "cash": <"Cash" or "Cash eligible to earn interest" amount — NOT buying power>,
  "buying_power": <Buying power if visible, else null>,
  "principal": <original invested amount if visible, else null>,
  "positions": [
    {"symbol": "XRP", "qty": 5004.162, "avg_cost": 1.80, "asset_class": "crypto"}
  ],
  "stocks": [
    {"symbol": "IONQ", "qty": 16.47, "price": 44.66, "asset_class": "stock"}
  ],
  "notes": "<one Korean sentence summarizing what you saw>"
}

Rules:
- cash: prefer the Investing "Cash" / "Cash eligible to earn interest" line. Do NOT use Buying power for cash when Cash is visible (Cash is often larger).
- positions: CRYPTO only (XRP, ETH, BTC, DOGE, SHIB, LINK, SOL, AVAX, AAVE, etc.)
- stocks: stocks and ETFs only (IONQ, SPY, TSLA, etc.) with share qty; include price if shown
- symbol: uppercase ticker only
- qty: exact quantity from holdings list
- avg_cost: from "Avg cost" if visible, else null
- Ignore watchlists / "Lists" (no quantity) — only real holdings
- Merge duplicates across screenshots
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


def _gemini_generate(model: str, parts: list[dict]) -> dict[str, Any]:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
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


def _vision_via_gemini(images: list[bytes]) -> dict[str, Any]:
    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY가 설정되지 않았습니다.")
    parts: list[dict] = [{"text": PROMPT}]
    for img in images:
        parts.append({
            "inline_data": {
                "mime_type": _image_mime(img),
                "data": base64.standard_b64encode(img).decode(),
            }
        })
    errors: list[str] = []
    for model in _gemini_models_to_try(settings.google_model):
        try:
            return _gemini_generate(model, parts)
        except RuntimeError as exc:
            msg = str(exc)
            errors.append(f"{model}: {msg}")
            if "no longer available" not in msg.lower() and "not found" not in msg.lower():
                raise
            log.warning("Gemini model %s unavailable, trying fallback", model)
    raise RuntimeError(errors[-1] if errors else "Gemini vision failed")


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
    """Vision → holdings import → buy/sell guide.

    When Robinhood Crypto API is linked, crypto qty/prices stay live from the
    API; the screenshot is used only to capture Investing Cash + stock qtys
    (which the Crypto API does not expose).
    """
    parsed = parse_screenshots(images)
    positions = []
    for p in parsed.get("positions") or []:
        sym = str(p.get("symbol", "")).upper().strip()
        qty = float(p.get("qty") or 0)
        if not sym or qty <= 0:
            continue
        asset = str(p.get("asset_class") or "crypto").lower()
        if asset in ("stock", "etf", "equity"):
            continue
        avg = p.get("avg_cost")
        positions.append({
            "symbol": sym,
            "qty": qty,
            "avg_cost": float(avg) if avg not in (None, "", 0) else None,
        })
    stocks = []
    for p in parsed.get("stocks") or []:
        sym = str(p.get("symbol", "")).upper().strip()
        qty = float(p.get("qty") or 0)
        if not sym or qty <= 0:
            continue
        row = {"symbol": sym, "qty": qty}
        if p.get("price") not in (None, "", 0):
            try:
                row["price"] = float(p["price"])
            except (TypeError, ValueError):
                pass
        stocks.append(row)
    crypto_syms = {
        "BTC", "ETH", "SOL", "DOGE", "XRP", "AVAX", "LINK", "LTC", "UNI",
        "SHIB", "BCH", "AAVE", "ADA", "DOT", "MATIC", "POL", "PEPE", "BONK",
    }
    kept = []
    for p in positions:
        if p["symbol"] in crypto_syms or "/" in p["symbol"]:
            kept.append(p)
        else:
            stocks.append({"symbol": p["symbol"], "qty": p["qty"]})
    positions = kept

    cash = float(parsed.get("cash") or 0)
    if not positions and not cash and not stocks:
        raise ValueError("스크린샷에서 보유·현금을 찾지 못했습니다.")

    principal = parsed.get("principal")
    principal_f = float(principal) if principal not in (None, "", 0) else None

    log_activity(
        "crypto",
        f"스크린샷 분석 — 크립토 {len(positions)} · 주식 {len(stocks)} · Cash ${cash:,.0f}"
        + (f" · {parsed.get('notes', '')}" if parsed.get("notes") else ""),
    )

    from .robinhood_config import is_configured

    if is_configured() and (cash > 0 or stocks):
        # Live API owns crypto; screenshot only fills Cash + equities.
        book = store.get(BOOK_KEY) or {}
        if cash > 0:
            book["brokerage_cash"] = round(cash, 2)
            book["stocks_value"] = 0.0 if stocks else book.get("stocks_value", 0.0)
        if stocks:
            book["stock_positions"] = stocks
            book["stocks_value"] = 0.0
        if principal_f and principal_f > 0:
            book["principal"] = principal_f
        from datetime import datetime, timezone
        book["updated_at"] = datetime.now(timezone.utc).isoformat()
        store.set(BOOK_KEY, book)
        store.set(CACHE_KEY, None)
        data = advise_and_apply(force=True)
    else:
        data = import_holdings(
            cash, positions, principal_f,
            brokerage_cash=cash if cash > 0 else None,
            stock_positions=stocks or None,
        )
    if data.get("ok"):
        data["parsed"] = {
            "cash": cash,
            "principal": principal_f,
            "positions": positions,
            "stocks": stocks,
            "notes": parsed.get("notes", ""),
        }
    return data
