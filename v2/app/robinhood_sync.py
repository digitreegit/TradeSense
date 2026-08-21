"""Pull Robinhood crypto holdings into the advisor book."""
from __future__ import annotations

from .crypto_advisor import BOOK_KEY, import_holdings
from .robinhood_client import RobinhoodCryptoClient
from .robinhood_config import get_credentials
from .state import store


def sync_from_robinhood() -> dict:
    """Fetch account + holdings via API and rebuild the crypto book."""
    api_key, private_key = get_credentials()
    if not api_key or not private_key:
        return {"ok": False, "error": "Robinhood API 키가 설정되지 않았습니다."}

    book = store.get(BOOK_KEY) or {}
    principal = float(book["principal"]) if book.get("principal") else None
    avg_by_sym: dict[str, float] = {}
    for pair, pos in (book.get("positions") or {}).items():
        sym = pair.split("/")[0]
        if pos.get("avg_cost"):
            avg_by_sym[sym] = float(pos["avg_cost"])

    client = RobinhoodCryptoClient(api_key, private_key)
    account = client.get_account()
    cash = float(account.get("buying_power") or 0)
    holdings = client.get_all_holdings()

    positions: list[dict] = []
    for row in holdings:
        sym = str(row.get("asset_code") or "").upper().strip()
        qty = float(row.get("total_quantity") or 0)
        if not sym or qty <= 0:
            continue
        positions.append({
            "symbol": sym,
            "qty": qty,
            "avg_cost": avg_by_sym.get(sym),
        })

    data = import_holdings(
        cash, positions,
        principal if principal and principal > 0 else None,
        notify_as="Robinhood 동기화",
    )
    if data.get("ok"):
        data["parsed"] = {
            "notes": (
                f"Robinhood API 동기화 — {len(positions)}종목 · "
                f"매수가능 ${cash:,.0f}"
            ),
            "cash": cash,
            "positions": [{"symbol": p["symbol"], "qty": p["qty"]} for p in positions],
            "principal": data.get("summary", {}).get("principal"),
            "source": "robinhood_api",
        }
    return data
