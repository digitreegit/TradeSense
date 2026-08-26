"""Robinhood Crypto Trading API client."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any
from urllib.parse import urlparse

import httpx
from nacl.signing import SigningKey

log = logging.getLogger(__name__)

BASE_URL = "https://trading.robinhood.com"


class RobinhoodAPIError(RuntimeError):
    pass


def pair_allows_api_orders(row: dict, *, side: str | None = None) -> bool:
    """Robinhood v2 sets is_api_tradable; v1 only has status (tradable/sellonly)."""
    status = str(row.get("status") or "").lower()
    flag = row.get("is_api_tradable")
    if flag is False:
        return False
    if side and str(side).lower() == "buy" and status == "sellonly":
        return False
    if flag is True:
        return True
    if status == "tradable":
        return True
    if status == "sellonly" and (side is None or str(side).lower() != "buy"):
        return True
    return False


class RobinhoodCryptoClient:
    """Signed requests per https://docs.robinhood.com/crypto/trading/."""

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
        if not resp.content:
            return {}
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}

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

    def get_order(self, order_id: str) -> dict:
        """Fetch one order by id (list filter — path form is undocumented)."""
        rows = self.get_orders(id=order_id)
        if rows:
            return rows[0]
        data = self.request("GET", f"/api/v1/crypto/trading/orders/{order_id}/")
        return data if isinstance(data, dict) else {}

    def get_trading_pairs(self, *symbols: str) -> list[dict]:
        query = self._query_params("symbol", *symbols) if symbols else ""
        path = f"/api/v1/crypto/trading/trading_pairs/{query}"
        data = self.request("GET", path)
        if isinstance(data, dict):
            return list(data.get("results") or [])
        return []

    def get_trading_pairs_v2(self, *symbols: str) -> list[dict]:
        """v2 pairs include is_api_tradable; v1 does not."""
        query = self._query_params("symbol", *symbols) if symbols else ""
        path = f"/api/v2/crypto/trading/trading_pairs/{query}"
        data = self.request("GET", path)
        if isinstance(data, dict):
            return list(data.get("results") or [])
        return []

    def _trading_pair(self, rh_symbol: str) -> dict | None:
        sym = rh_symbol.upper()
        for getter in (self.get_trading_pairs_v2, self.get_trading_pairs):
            try:
                rows = getter(sym)
            except Exception:
                continue
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and str(row.get("symbol") or "").upper() == sym:
                    return row
        return None

    def is_symbol_api_tradable(self, rh_symbol: str, *, side: str | None = None) -> bool:
        row = self._trading_pair(rh_symbol)
        if not row:
            return False
        return pair_allows_api_orders(row, side=side)

    def api_tradable_map(self, *asset_codes: str) -> dict[str, bool]:
        """asset_code (XRP) → whether Crypto API can place orders."""
        rh_syms = tuple(
            f"{str(code).upper().replace('-USD', '')}-USD"
            for code in asset_codes if code
        )
        if not rh_syms:
            return {}
        rows: list = []
        try:
            raw = self.get_trading_pairs_v2(*rh_syms)
            if isinstance(raw, list):
                rows = raw
        except Exception:
            rows = []
        if not rows:
            try:
                raw = self.get_trading_pairs(*rh_syms)
                if isinstance(raw, list):
                    rows = raw
            except Exception:
                rows = []
        out: dict[str, bool] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").replace("-USD", "").upper()
            if sym:
                out[sym] = pair_allows_api_orders(row)
        return out

    def get_accounts_v2(self) -> list[dict]:
        data = self.request("GET", "/api/v2/crypto/trading/accounts/")
        if isinstance(data, dict):
            return list(data.get("results") or [])
        return []

    def get_primary_account_v2(self) -> dict:
        rows = self.get_accounts_v2()
        if not rows:
            raise RobinhoodAPIError("크립토 계좌를 찾을 수 없습니다.")
        return rows[0]

    def get_account_number(self) -> str:
        acc = self.get_account()
        num = acc.get("account_number")
        if num:
            return str(num)
        v2 = self.get_primary_account_v2()
        num = v2.get("account_number")
        if num:
            return str(num)
        raise RobinhoodAPIError("account_number를 찾을 수 없습니다.")

    def place_order(self, body: dict) -> dict:
        """Place order via v1; on 403 retry v2 (fee-tier keys)."""
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        v1_err: RobinhoodAPIError | None = None
        try:
            data = self.request("POST", "/api/v1/crypto/trading/orders/", body=payload)
            if isinstance(data, dict):
                return data
            raise RobinhoodAPIError("주문 응답을 읽을 수 없습니다.")
        except RobinhoodAPIError as exc:
            if "403" not in str(exc):
                raise
            v1_err = exc
        account_number = self.get_account_number()
        path = f"/api/v2/crypto/trading/orders/?account_number={account_number}"
        try:
            data = self.request("POST", path, body=payload)
        except RobinhoodAPIError:
            if v1_err:
                raise v1_err
            raise
        if not isinstance(data, dict):
            if v1_err:
                raise v1_err
            raise RobinhoodAPIError("주문 응답을 읽을 수 없습니다.")
        return data

    def get_recent_filled_orders(self, *, limit: int = 50) -> list[dict]:
        """Filled crypto orders, newest first when API provides timestamps."""
        try:
            rows = self.get_orders(state="filled", limit=str(limit))
        except RobinhoodAPIError:
            rows = self.get_orders(limit=str(limit))
            rows = [
                r for r in rows
                if str(r.get("state") or "").lower() in ("filled", "partially_filled")
            ]
        rows.sort(
            key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""),
            reverse=True,
        )
        return rows
