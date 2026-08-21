"""Robinhood Crypto Trading API client (read-only)."""
from __future__ import annotations

import base64
import logging
from typing import Any
from urllib.parse import urlparse

import httpx
from nacl.signing import SigningKey

log = logging.getLogger(__name__)

BASE_URL = "https://trading.robinhood.com"


class RobinhoodAPIError(RuntimeError):
    pass


class RobinhoodCryptoClient:
    """Signed requests per https://docs.robinhood.com/ — no order placement here."""

    def __init__(self, api_key: str, private_key_base64: str):
        self.api_key = api_key.strip()
        seed = base64.b64decode(private_key_base64.strip())
        self._signing_key = SigningKey(seed)

    @staticmethod
    def _query_params(key: str, *values: str) -> str:
        if not values:
            return ""
        return "?" + "&".join(f"{key}={v}" for v in values)

    def _sign(self, method: str, path: str, body: str, timestamp: int) -> dict[str, str]:
        message = f"{self.api_key}{timestamp}{path}{method}{body}"
        signed = self._signing_key.sign(message.encode("utf-8"))
        return {
            "x-api-key": self.api_key,
            "x-signature": base64.b64encode(signed.signature).decode("utf-8"),
            "x-timestamp": str(timestamp),
            "Content-Type": "application/json; charset=utf-8",
        }

    def request(self, method: str, path: str, body: str = "") -> Any:
        import time

        timestamp = int(time.time())
        headers = self._sign(method, path, body, timestamp)
        url = BASE_URL + path
        with httpx.Client(timeout=20.0) as client:
            if method == "GET":
                resp = client.get(url, headers=headers)
            elif method == "POST":
                resp = client.post(url, headers=headers, content=body or None)
            else:
                raise ValueError(f"unsupported method: {method}")
        if resp.status_code >= 400:
            detail = resp.text[:300]
            raise RobinhoodAPIError(f"Robinhood API {resp.status_code}: {detail}")
        return resp.json()

    def get_account(self) -> dict:
        data = self.request("GET", "/api/v1/crypto/trading/accounts/")
        if isinstance(data, dict) and data.get("account_number"):
            return data
        results = (data or {}).get("results") if isinstance(data, dict) else None
        if results:
            return results[0]
        raise RobinhoodAPIError("계좌 정보를 읽을 수 없습니다.")

    def get_all_holdings(self) -> list[dict]:
        path = "/api/v1/crypto/trading/holdings/"
        out: list[dict] = []
        while path:
            data = self.request("GET", path)
            if not isinstance(data, dict):
                break
            out.extend(data.get("results") or [])
            nxt = data.get("next") or ""
            if not nxt:
                break
            parsed = urlparse(nxt)
            path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return out

    def get_best_bid_ask(self, *symbols: str) -> dict:
        """Live mid prices — symbol args like BTC-USD."""
        query = self._query_params("symbol", *symbols) if symbols else ""
        path = f"/api/v1/crypto/marketdata/best_bid_ask/{query}"
        data = self.request("GET", path)
        return data if isinstance(data, dict) else {}

    def get_orders(self, **params: str) -> list[dict]:
        """List crypto orders (paginated). Optional filters: state, symbol, side."""
        q = ""
        if params:
            q = "?" + "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        path = f"/api/v1/crypto/trading/orders/{q}"
        out: list[dict] = []
        while path:
            data = self.request("GET", path)
            if not isinstance(data, dict):
                break
            out.extend(data.get("results") or [])
            nxt = data.get("next") or ""
            if not nxt:
                break
            parsed = urlparse(nxt)
            path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return out

    def get_recent_filled_orders(self, *, limit: int = 50) -> list[dict]:
        """Filled crypto orders, newest first when API provides timestamps."""
        try:
            rows = self.get_orders(state="filled", limit=str(limit))
        except RobinhoodAPIError:
            # Some keys / API versions reject state filter — fall back and filter client-side.
            rows = self.get_orders(limit=str(limit))
            rows = [r for r in rows if str(r.get("state") or "").lower() in ("filled", "partially_filled")]
        rows.sort(key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""), reverse=True)
        return rows
