"""Place Robinhood Crypto market orders (semi/auto execution)."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from .robinhood_client import RobinhoodAPIError, RobinhoodCryptoClient
from .robinhood_config import get_credentials

log = logging.getLogger(__name__)

# Poll fill briefly after place — market crypto usually fills fast.
_POLL_SECONDS = (0.4, 0.8, 1.2, 2.0)
_FILLED_STATES = frozenset({"filled", "partially_filled"})


def _qty_str(qty: float) -> str:
    """Format asset qty for RH (string decimals, no sci-notation)."""
    if qty <= 0:
        raise ValueError("수량은 0보다 커야 합니다.")
    # SHIB needs many integer digits; BTC needs fine precision.
    if qty >= 1000:
        s = f"{qty:.0f}"
    elif qty >= 1:
        s = f"{qty:.8f}".rstrip("0").rstrip(".")
    else:
        s = f"{qty:.10f}".rstrip("0").rstrip(".")
    if not s or s == "0":
        raise ValueError("수량이 너무 작습니다.")
    return s


def _pair_to_rh_symbol(pair_or_sym: str) -> str:
    s = str(pair_or_sym or "").upper().strip()
    if "/" in s:
        s = s.split("/")[0]
    s = s.replace("-USD", "")
    return f"{s}-USD"


def _mid_price(client: RobinhoodCryptoClient, rh_symbol: str) -> float:
    quotes = client.get_best_bid_ask(rh_symbol)
    for row in quotes.get("results") or []:
        if str(row.get("symbol") or "").upper() != rh_symbol.upper():
            continue
        raw = row.get("price")
        if raw is not None:
            px = float(raw)
            if px > 0:
                return px
        bid = row.get("bid_inclusive_of_sell_spread")
        ask = row.get("ask_inclusive_of_buy_spread")
        if bid is not None and ask is not None:
            b, a = float(bid), float(ask)
            if b > 0 and a > 0:
                return (b + a) / 2.0
    raise RobinhoodAPIError(f"{rh_symbol} 시세를 가져올 수 없습니다.")


def _buying_power(client: RobinhoodCryptoClient) -> float:
    acc = client.get_account()
    return float(acc.get("buying_power") or 0)


def _available_qty(client: RobinhoodCryptoClient, asset_code: str) -> float:
    code = asset_code.upper().replace("-USD", "")
    for row in client.get_all_holdings():
        if str(row.get("asset_code") or "").upper() != code:
            continue
        avail = row.get("quantity_available_for_trading")
        if avail is None:
            avail = row.get("total_quantity")
        return float(avail or 0)
    return 0.0


def _order_notional(row: dict) -> float:
    qty = float(row.get("filled_asset_quantity") or 0)
    avg = float(row.get("average_price") or 0)
    if qty > 0 and avg > 0:
        return qty * avg
    return 0.0


def place_market_dollars(
    *,
    side: str,
    pair: str,
    dollars: float,
    client_order_id: str | None = None,
    fallback_price: float | None = None,
    sell_all: bool = False,
) -> dict[str, Any]:
    """Place a market order sized in USD notional (converted to asset qty).

    Returns dict with keys: ok, order (API row), dollars, qty, client_order_id, error.
    """
    side = side.lower().strip()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "side는 buy 또는 sell이어야 합니다."}
    dollars = float(dollars)
    if dollars <= 0 and not sell_all:
        return {"ok": False, "error": "금액은 0보다 커야 합니다."}

    api_key, private_key = get_credentials()
    if not api_key or not private_key:
        return {"ok": False, "error": "Robinhood API 키가 없습니다."}

    client = RobinhoodCryptoClient(api_key, private_key)
    rh_symbol = _pair_to_rh_symbol(pair)
    asset = rh_symbol.replace("-USD", "")
    cid = client_order_id or str(uuid.uuid4())

    try:
        if not client.is_symbol_api_tradable(rh_symbol):
            return {
                "ok": False,
                "error": (
                    f"{rh_symbol}는 Robinhood API로 주문할 수 없습니다. "
                    "앱에서 수동으로 실행하세요."
                ),
                "client_order_id": cid,
            }
        acc_v2 = client.get_primary_account_v2()
        if acc_v2.get("is_api_tradable") is False:
            return {
                "ok": False,
                "error": "이 크립토 계좌는 API 주문이 꺼져 있습니다. Robinhood 지원에 문의하세요.",
                "client_order_id": cid,
            }
    except RobinhoodAPIError as exc:
        log.warning("order preflight skipped: %s", exc)

    try:
        price = _mid_price(client, rh_symbol)
    except Exception as exc:
        if fallback_price and float(fallback_price) > 0:
            price = float(fallback_price)
            log.warning("live quote failed (%s), using fallback %.6f", exc, price)
        else:
            return {"ok": False, "error": f"시세 조회 실패: {exc}"}

    if side == "sell" and sell_all:
        qty = _available_qty(client, asset)
        if qty <= 0:
            return {"ok": False, "error": f"{asset} 매도 가능 수량이 없습니다."}
    else:
        qty = dollars / price
        if side == "sell":
            avail = _available_qty(client, asset)
            if avail > 0 and qty > avail:
                qty = avail

    try:
        qty_s = _qty_str(qty)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if side == "buy":
        bp = _buying_power(client)
        if bp <= 0:
            return {
                "ok": False,
                "error": "크립토 매수 가능 금액(Buying power)이 없습니다.",
                "client_order_id": cid,
            }
        # Leave a little headroom for spread/fees.
        max_buy = round(bp * 0.98, 2)
        if dollars > max_buy:
            return {
                "ok": False,
                "error": (
                    f"매수 금액 ${dollars:,.0f}이(가) 크립토 Buying power "
                    f"${bp:,.2f}보다 큽니다. ${max_buy:,.0f} 이하로 입력하세요. "
                    "(Investing Cash와 Buying power는 다릅니다.)"
                ),
                "client_order_id": cid,
                "buying_power": bp,
            }

    body = {
        "client_order_id": cid,
        "side": side,
        "type": "market",
        "symbol": rh_symbol,
        "market_order_config": {"asset_quantity": qty_s},
    }
    try:
        placed = client.place_order(body)
    except RobinhoodAPIError as exc:
        log.exception("robinhood place_order failed")
        msg = str(exc)
        if "403" in msg or "permission" in msg.lower():
            from .robinhood_config import keys_from_dashboard, mask_key

            src = "대시보드" if keys_from_dashboard() else "Vercel 환경변수"
            msg = (
                "Robinhood API 주문 권한 거부(403). "
                f"현재 키({mask_key(api_key)}, {src})가 주문용인지 확인하세요. "
                "키 재발급 시 Place crypto orders( fee tiers 포함) 권한을 켜고, "
                "설정에 API Key + Private Key를 다시 저장하세요. "
                f"({exc})"
            )
        elif "400" in msg and "buying power" in msg.lower():
            bp = _buying_power(client)
            msg = (
                f"크립토 Buying power(${bp:,.2f})보다 큰 매수 주문입니다. "
                f"금액을 ${round(bp * 0.98):,.0f} 이하로 줄이거나 Robinhood 앱에서 "
                "Investing Cash → Crypto로 자금을 옮기세요."
            )
        return {"ok": False, "error": msg, "client_order_id": cid}
    except Exception as exc:
        log.exception("robinhood place_order unexpected")
        return {"ok": False, "error": f"주문 실패: {exc}", "client_order_id": cid}

    order_id = placed.get("id")
    final = placed
    for wait in _POLL_SECONDS:
        state = str(final.get("state") or "").lower()
        if state in _FILLED_STATES and _order_notional(final) > 0:
            break
        if state in ("failed", "canceled"):
            return {
                "ok": False,
                "error": f"주문이 {state} 상태입니다.",
                "order": final,
                "client_order_id": cid,
            }
        time.sleep(wait)
        if order_id:
            try:
                final = client.get_order(str(order_id)) or final
            except Exception:
                pass

    filled_dollars = _order_notional(final)
    if filled_dollars <= 0:
        # Market may still be open — use intended notional so book stays consistent;
        # live sync will correct qty shortly.
        filled_dollars = float(qty_s) * price
        log.warning(
            "RH order %s state=%s — using estimated $%.2f",
            order_id, final.get("state"), filled_dollars,
        )

    return {
        "ok": True,
        "order": final,
        "dollars": round(filled_dollars, 2),
        "qty": float(qty_s),
        "price": price,
        "client_order_id": cid,
        "rh_order_id": order_id,
        "state": final.get("state"),
    }
