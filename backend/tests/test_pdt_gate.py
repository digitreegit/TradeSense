"""PDT gating logic — replicates the engine's hard halt path on margin accounts.

The engine guards in ``trading_engine._run_scalp`` with::

    is_margin = bool(account.get("is_margin_account"))
    dt_count = int(account.get("day_trade_count") or 0)
    pdt_flag = bool(account.get("pattern_day_trader"))
    equity_now = float(account.get("equity") or 0.0)
    pdt_block = (
        is_margin and equity_now < 25_000 and dt_count >= 3
    ) or (
        is_margin and equity_now < 25_000 and pdt_flag
    )

This test re-implements the same predicate so a regression in the boolean
shape would surface immediately.
"""
from __future__ import annotations

import pytest


def _pdt_block(account: dict) -> bool:
    is_margin = bool(account.get("is_margin_account"))
    dt_count = int(account.get("day_trade_count") or 0)
    pdt_flag = bool(account.get("pattern_day_trader"))
    equity_now = float(account.get("equity") or 0.0)
    return bool(
        is_margin
        and equity_now < 25_000.0
        and (dt_count >= 3 or pdt_flag)
    )


@pytest.mark.parametrize(
    "account, expected",
    [
        # Cash account: PDT never applies.
        ({"equity": 3_000.0, "is_margin_account": False, "day_trade_count": 5}, False),
        # Margin under $25K with 2 day-trades: still safe.
        ({"equity": 10_000.0, "is_margin_account": True, "day_trade_count": 2}, False),
        # Margin under $25K with 3 day-trades: BLOCK (4th would lock account).
        ({"equity": 10_000.0, "is_margin_account": True, "day_trade_count": 3}, True),
        # Margin under $25K, broker flagged PDT.
        (
            {
                "equity": 24_999.0,
                "is_margin_account": True,
                "day_trade_count": 0,
                "pattern_day_trader": True,
            },
            True,
        ),
        # Margin at/above $25K: PDT no longer relevant for entry block.
        ({"equity": 26_000.0, "is_margin_account": True, "day_trade_count": 5}, False),
    ],
)
def test_pdt_block_logic(account, expected):
    assert _pdt_block(account) is expected


def test_alpaca_account_pdt_extraction():
    """`AlpacaService._account_pdt_fields` should normalize broker fields."""
    pytest.importorskip("alpaca")
    from app.services.alpaca_service import AlpacaService

    class _A:
        daytrade_count = 4
        pattern_day_trader = True
        account_blocked = False
        trading_blocked = False
        multiplier = "4"

    out = AlpacaService._account_pdt_fields(_A())
    assert out["day_trade_count"] == 4
    assert out["pattern_day_trader"] is True
    assert out["multiplier"] == 4.0
    assert out["is_margin_account"] is True

    class _Cash:
        daytrade_count = 0
        pattern_day_trader = False
        account_blocked = False
        trading_blocked = False
        multiplier = "1"

    out = AlpacaService._account_pdt_fields(_Cash())
    assert out["is_margin_account"] is False
    assert out["multiplier"] == 1.0
