"""Place Robinhood Crypto marketable-limit orders (semi/auto execution)."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from typing import Any

from .robinhood_client import RobinhoodAPIError, RobinhoodCryptoClient
from .robinhood_config import get_credentials

log = logging.getLogger(__name__)

# A small crossing buffer behaves like a market order while imposing a hard
# worst-price boundary. Risk exits get more room so protection stays primary.
_LIMIT_BUFFER = Decimal("0.0025")
_EMERGENCY_LIMIT_BUFFER = Decimal("0.01")
_POLL_SECONDS = (0.4, 0.8, 1.2, 2.0)
_FILLED_STATES = frozenset({"filled"})
_PENDING_STATES = frozenset({"open", "pending", "partially_filled", ""})
_TERMINAL_STATES = frozenset({"canceled", "cancelled", "failed", "rejected"})


def _qty_str(qty: float, increment: str | float | None = None) -> str:
    """Format asset qty for RH (string decimals, no sci-notation)."""
    if qty <= 0:
        raise ValueError("수량은 0보다 커야 합니다.")
    # Always round down: a sell-all quantity must never exceed the available
    # balance. Preserve fractional quantities even for large-supply coins.
    try:
        tick = Decimal(str(increment or "0.0000000001"))
        if tick <= 0:
            raise InvalidOperation
        value = (
            Decimal(str(qty)) / tick
        ).to_integral_value(rounding=ROUND_DOWN) * tick
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("올바른 수량이 아닙니다.") from exc
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if not s or s == "0":
        raise ValueError("수량이 너무 작습니다.")
    return s


def _pair_to_rh_symbol(pair_or_sym: str) -> str:
    s = str(pair_or_sym or "").upper().strip()
    if "/" in s:
        s = s.split("/")[0]
    s = s.replace("-USD", "")
    return f"{s}-USD"


def _quote(client: RobinhoodCryptoClient, rh_symbol: str) -> tuple[float, float, float, str]:
    quotes = client.get_best_bid_ask(rh_symbol)
    for row in quotes.get("results") or []:
        if str(row.get("symbol") or "").upper() != rh_symbol.upper():
            continue
        quote_at = row.get("timestamp") or row.get("updated_at") or datetime.now(timezone.utc).isoformat()
        bid = row.get("bid_inclusive_of_sell_spread")
        ask = row.get("ask_inclusive_of_buy_spread")
        if bid is not None and ask is not None:
            b, a = float(bid), float(ask)
            if b > 0 and a > 0:
                return b, a, (b + a) / 2.0, str(quote_at)
        raw = row.get("price")
        if raw is not None:
            px = float(raw)
            if px > 0:
                return px, px, px, str(quote_at)
    raise RobinhoodAPIError(f"{rh_symbol} 시세를 가져올 수 없습니다.")


def _limit_price_str(
    price: float, *, side: str, increment: str | float | None = None
) -> str:
    if price <= 0:
        raise ValueError("지정가는 0보다 커야 합니다.")
    try:
        tick = Decimal(str(increment or ("0.01" if price >= 1 else "0.000001")))
        if tick <= 0:
            raise InvalidOperation
        rounding = ROUND_UP if side == "buy" else ROUND_DOWN
        value = (
            Decimal(str(price)) / tick
        ).to_integral_value(rounding=rounding) * tick
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("올바른 지정가가 아닙니다.") from exc
    return format(value, "f")


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
    require_live_quote: bool = False,
    expected_price: float | None = None,
    existing_order_id: str | None = None,
    existing_api_version: str | None = None,
    bypass_price_drift: bool = False,
) -> dict[str, Any]:
    """Place a marketable-limit order sized in USD notional.

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

    if existing_order_id:
        try:
            existing = client.get_order(
                str(existing_order_id), api_version=existing_api_version
            )
            state = str(existing.get("state") or "").lower()
            api_version = str(
                existing.get("_api_version") or existing_api_version or "v1"
            )
            notional = _order_notional(existing)
            if state in _FILLED_STATES and notional > 0:
                return {
                    "ok": True, "order": existing, "dollars": round(notional, 2),
                    "qty": float(existing.get("filled_asset_quantity") or 0),
                    "price": float(existing.get("average_price") or 0),
                    "client_order_id": cid, "rh_order_id": existing_order_id,
                    "state": state, "rh_api_version": api_version,
                }
            if state in _TERMINAL_STATES and notional > 0:
                # Confirm only the executed portion. The refreshed advisor can
                # size any remaining target from the new live balance.
                return {
                    "ok": True, "partial_terminal": True,
                    "order": existing, "dollars": round(notional, 2),
                    "qty": float(existing.get("filled_asset_quantity") or 0),
                    "price": float(existing.get("average_price") or 0),
                    "client_order_id": cid, "rh_order_id": existing_order_id,
                    "state": state, "rh_api_version": api_version,
                }
            if state in _PENDING_STATES or (state in _FILLED_STATES and notional <= 0):
                return {
                    "ok": False,
                    "pending": True,
                    "error": f"기존 Robinhood 주문이 아직 {state or 'unknown'} 상태입니다.",
                    "order": existing,
                    "client_order_id": cid,
                    "rh_order_id": existing_order_id,
                    "rh_api_version": api_version,
                    "state": state,
                }
            return {
                "ok": False,
                "retryable": True,
                "error": f"기존 Robinhood 주문이 {state or 'unknown'} 상태로 종료됐습니다. 새 가격으로 재시도합니다.",
                "client_order_id": cid,
                "rh_order_id": existing_order_id,
                "rh_api_version": api_version,
                "state": state,
            }
        except Exception as exc:
            return {
                "ok": False, "error": f"기존 주문 상태 확인 실패: {exc}",
                "client_order_id": cid,
            }

    try:
        if not client.is_symbol_api_tradable(rh_symbol, side=side):
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
    except Exception as exc:
        return {
            "ok": False, "error": f"주문 사전 점검 실패: {exc}",
            "client_order_id": cid,
        }

    bp = None
    if side == "buy":
        try:
            bp = _buying_power(client)
        except Exception as exc:
            return {
                "ok": False, "error": f"Buying power 조회 실패: {exc}",
                "client_order_id": cid,
            }
        max_buy = round(bp * 0.98, 2)
        if bp <= 0 or dollars > max_buy:
            return {
                "ok": False,
                "error": (
                    "크립토 매수 가능 금액(Buying power)이 없습니다."
                    if bp <= 0 else
                    f"매수 금액 ${dollars:,.0f}이(가) 크립토 Buying power "
                    f"${bp:,.2f}보다 큽니다. ${max_buy:,.0f} 이하로 입력하세요. "
                    "(Investing Cash와 Buying power는 다릅니다.)"
                ),
                "client_order_id": cid,
                "buying_power": bp,
            }

    try:
        bid, ask, price, quote_at = _quote(client, rh_symbol)
    except Exception as exc:
        if not require_live_quote and fallback_price and float(fallback_price) > 0:
            bid = ask = price = float(fallback_price)
            log.warning("live quote failed (%s), using fallback %.6f", exc, price)
        else:
            return {"ok": False, "error": f"시세 조회 실패: {exc}"}
    else:
        if require_live_quote:
            from .crypto_risk import quote_is_fresh
            if not quote_is_fresh(quote_at):
                return {
                    "ok": False,
                    "error": "Robinhood 시세가 2분 이상 오래되어 자동 주문을 중단했습니다.",
                    "client_order_id": cid,
                }
    if not bypass_price_drift and expected_price and float(expected_price) > 0:
        drift = abs(price / float(expected_price) - 1)
        if drift > 0.03:
            return {
                "ok": False,
                "error": f"추천가 대비 시세 변동 {drift:.1%}로 주문을 중단했습니다.",
                "client_order_id": cid,
            }

    buffer = _EMERGENCY_LIMIT_BUFFER if bypass_price_drift and side == "sell" else _LIMIT_BUFFER
    raw_limit = (
        Decimal(str(ask)) * (Decimal("1") + buffer)
        if side == "buy"
        else Decimal(str(bid)) * (Decimal("1") - buffer)
    )
    try:
        pair_meta = client.get_trading_pair(rh_symbol)
    except Exception:
        pair_meta = None
    increment = pair_meta.get("quote_increment") if isinstance(pair_meta, dict) else None
    asset_increment = pair_meta.get("asset_increment") if isinstance(pair_meta, dict) else None
    try:
        limit_price_s = _limit_price_str(
            float(raw_limit), side=side, increment=increment
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "client_order_id": cid}
    limit_price = float(limit_price_s)

    if side == "sell" and sell_all:
        qty = _available_qty(client, asset)
        if qty <= 0:
            return {"ok": False, "error": f"{asset} 매도 가능 수량이 없습니다."}
    else:
        # Buy quantity is based on the cap, so even a worst-price fill cannot
        # exceed the requested notional.
        qty = dollars / (limit_price if side == "buy" else price)
        if side == "sell":
            avail = _available_qty(client, asset)
            if avail <= 0:
                return {
                    "ok": False, "error": f"{asset} 매도 가능 수량이 없습니다.",
                    "client_order_id": cid,
                }
            if qty > avail:
                qty = avail

    try:
        qty_s = _qty_str(qty, asset_increment)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    body = {
        "client_order_id": cid,
        "side": side,
        "type": "limit",
        "symbol": rh_symbol,
        "limit_order_config": {
            "asset_quantity": qty_s,
            "limit_price": limit_price_s,
            "time_in_force": "gtc",
        },
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
            try:
                bp = _buying_power(client)
            except Exception:
                bp = 0.0
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
    api_version = str(placed.get("_api_version") or "v1")
    final = placed
    for wait in _POLL_SECONDS:
        state = str(final.get("state") or "").lower()
        if state in _FILLED_STATES and _order_notional(final) > 0:
            break
        if state in _TERMINAL_STATES:
            break
        time.sleep(wait)
        if order_id:
            try:
                final = client.get_order(
                    str(order_id), api_version=api_version
                ) or final
            except Exception:
                pass

    filled_dollars = _order_notional(final)
    final_state = str(final.get("state") or "").lower()
    completed_fill = (
        final_state in _FILLED_STATES | _TERMINAL_STATES and filled_dollars > 0
    )
    if not completed_fill:
        # Do not leave a zero-fill limit resting indefinitely. Cancel it and
        # let the next scheduler tick create a fresh id at a fresh quote.
        if filled_dollars <= 0 and order_id and final_state in _PENDING_STATES:
            try:
                canceled = client.cancel_order(str(order_id), api_version=api_version)
                canceled_state = str(canceled.get("state") or "").lower()
                if not canceled_state:
                    try:
                        canceled = client.get_order(
                            str(order_id), api_version=api_version
                        ) or canceled
                        canceled_state = str(canceled.get("state") or "").lower()
                    except Exception:
                        pass
                if canceled_state in {"canceled", "cancelled", "failed", "rejected"}:
                    return {
                        "ok": False,
                        "retryable": True,
                        "error": "지정가 주문이 즉시 체결되지 않아 취소했습니다. 다음 실행에서 새 가격으로 재주문합니다.",
                        "order": canceled,
                        "client_order_id": cid,
                        "rh_order_id": order_id,
                        "rh_api_version": api_version,
                        "state": canceled_state,
                    }
            except Exception as exc:
                log.warning("Robinhood cancel %s failed: %s", order_id, exc)
        return {
            "ok": False,
            "pending": True,
            "error": (
                "주문은 접수됐지만 완전 체결을 아직 확인하지 못했습니다 "
                f"(상태: {final.get('state') or 'unknown'}). 다음 실행에서 다시 확인합니다."
            ),
            "order": final,
            "client_order_id": cid,
            "rh_order_id": order_id,
            "rh_api_version": api_version,
            "state": final_state,
        }

    return {
        "ok": True,
        "partial_terminal": final_state in _TERMINAL_STATES,
        "order": final,
        "dollars": round(filled_dollars, 2),
        "qty": float(final.get("filled_asset_quantity") or qty_s),
        "price": float(final.get("average_price") or price),
        "limit_price": limit_price,
        "client_order_id": cid,
        "rh_order_id": order_id,
        "rh_api_version": api_version,
        "state": final.get("state"),
    }
