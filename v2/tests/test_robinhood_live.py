"""Tests for live Robinhood balance snapshot."""
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.robinhood_live import fetch_robinhood_snapshot, merge_live_into_summary


def _bars(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes, "high": closes, "low": closes})


def test_fetch_robinhood_snapshot_totals_and_sparkline():
    mock_client = MagicMock()
    mock_client.get_account.return_value = {"buying_power": "1686.47"}
    mock_client.get_all_holdings.return_value = [
        {"asset_code": "XRP", "total_quantity": "1755.663"},
        {"asset_code": "SOL", "total_quantity": "21.82817"},
    ]
    mock_client.get_best_bid_ask.return_value = {
        "results": [
            {"symbol": "XRP-USD", "price": "1.07"},
            {"symbol": "SOL-USD", "price": "82.32"},
        ]
    }
    frames = {
        "XRP/USD": _bars([0.9 + i * 0.01 for i in range(25)]),
        "SOL/USD": _bars([70 + i for i in range(25)]),
    }

    with patch("app.robinhood_live.get_credentials", return_value=("key", "priv")), \
         patch("app.robinhood_live.RobinhoodCryptoClient", return_value=mock_client), \
         patch("app.robinhood_live.fetch_bars", return_value=frames):
        snap = fetch_robinhood_snapshot()

    assert snap is not None
    xrp = next(p for p in snap["positions"] if p["symbol"] == "XRP")
    assert xrp["qty"] == pytest.approx(1755.663)
    assert xrp["price"] == pytest.approx(1.07)
    assert len(xrp["sparkline"]) == 20
    assert snap["buying_power"] == pytest.approx(1686.47)
    holdings = 1755.663 * 1.07 + 21.82817 * 82.32
    assert snap["holdings_value"] == pytest.approx(round(holdings, 2))
    assert snap["total"] == pytest.approx(round(1686.47 + holdings, 2))


def test_merge_live_into_summary_overrides_totals():
    snap = {
        "buying_power": 1686.47,
        "total": 6941.69,
        "positions": [
            {"symbol": "XRP", "qty": 100, "price": 1.07, "value": 107.0},
        ],
    }
    summary = {
        "cash": 500,
        "total": 5000,
        "principal": 11598,
        "gap": 6598,
        "recovered_pct": 5000 / 11598,
        "positions": [
            {"symbol": "XRP", "value": 90, "invested": 80, "pl": 10, "avg_cost": 0.9},
        ],
    }
    out = merge_live_into_summary(summary, snap)
    assert out["cash"] == pytest.approx(1686.47)
    assert out["total"] == pytest.approx(6941.69)
    assert out["gap"] == pytest.approx(11598 - 6941.69)
    assert out["positions"][0]["value"] == pytest.approx(107.0)
    assert out["positions"][0]["price"] == pytest.approx(1.07)
