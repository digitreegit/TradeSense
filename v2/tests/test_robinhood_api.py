"""Tests for Robinhood Crypto API client and sync."""
from unittest.mock import MagicMock, patch

import pytest

from app.robinhood_client import RobinhoodAPIError, RobinhoodCryptoClient


# Example from https://docs.robinhood.com/
_DOC_API_KEY = "rh-api-6148effc-c0b1-486c-8940-a1d099456be6"
_DOC_PRIVATE = "xQnTJVeQLmw1/Mg2YimEViSpw/SdJcgNXZ5kQkAXNPU="


def test_sign_produces_required_headers():
    client = RobinhoodCryptoClient(_DOC_API_KEY, _DOC_PRIVATE)
    headers = client._sign("GET", "/api/v1/crypto/trading/accounts/", "", 1700000000)
    assert headers["x-api-key"] == _DOC_API_KEY
    assert headers["x-timestamp"] == "1700000000"
    assert len(headers["x-signature"]) > 20


def test_sync_from_robinhood_maps_holdings():
    from app.robinhood_sync import sync_from_robinhood

    mock_client = MagicMock()
    mock_client.get_account.return_value = {
        "account_number": "123",
        "buying_power": "1586.50",
        "status": "active",
    }
    mock_client.get_all_holdings.return_value = [
        {"asset_code": "XRP", "total_quantity": "1756.2"},
        {"asset_code": "ETH", "total_quantity": "0"},
    ]

    fake_advice = {"ok": True, "summary": {"principal": 11598.0}}

    with patch("app.robinhood_sync.get_credentials", return_value=("key", "priv")), \
         patch("app.robinhood_sync.RobinhoodCryptoClient", return_value=mock_client), \
         patch("app.robinhood_sync.store") as mock_store, \
         patch("app.robinhood_sync.import_holdings", return_value=fake_advice) as imp:
        mock_store.get.return_value = {"principal": 11598.0, "positions": {}}
        result = sync_from_robinhood()

    assert result["ok"] is True
    assert result["parsed"]["source"] == "robinhood_api"
    imp.assert_called_once()
    cash, positions, principal = imp.call_args[0]
    assert cash == 1586.5
    assert len(positions) == 1
    assert positions[0]["symbol"] == "XRP"
    assert positions[0]["qty"] == pytest.approx(1756.2)
    assert principal == 11598.0


def test_sync_without_keys():
    from app.robinhood_sync import sync_from_robinhood

    with patch("app.robinhood_sync.get_credentials", return_value=("", "")):
        result = sync_from_robinhood()
    assert result["ok"] is False


def test_place_order_retries_v2_on_v1_403():
    client = RobinhoodCryptoClient(_DOC_API_KEY, _DOC_PRIVATE)
    body = {
        "client_order_id": "cid-1",
        "side": "buy",
        "type": "market",
        "symbol": "XRP-USD",
        "market_order_config": {"asset_quantity": "10"},
    }
    v2_path = "/api/v2/crypto/trading/orders/?account_number=acct-9"
    with patch.object(client, "request") as req, \
         patch.object(client, "get_account_number", return_value="acct-9"):
        req.side_effect = [
            RobinhoodAPIError('Robinhood API 403: {"errors":[{"detail":"nope"}]}'),
            {"id": "ord-v2", "state": "filled"},
        ]
        out = client.place_order(body)
    assert out["id"] == "ord-v2"
    assert req.call_count == 2
    assert req.call_args_list[1][0][1] == v2_path
