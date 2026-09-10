"""Tests for Robinhood marketable-limit order placement helpers."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.robinhood_orders import _qty_str, place_market_dollars


def test_qty_str_formatting():
    assert float(_qty_str(0.00123456789)) > 0
    assert _qty_str(12.5) == "12.5"
    assert _qty_str(1000000) == "1000000"
    assert _qty_str(12345678.9) == "12345678.9"
    assert _qty_str(100, "1") == "100"
    assert _qty_str(10.27, "0.05") == "10.25"
    with pytest.raises(ValueError):
        _qty_str(0)


def test_place_market_dollars_buy():
    mock = MagicMock()
    mock.get_best_bid_ask.return_value = {
        "results": [{"symbol": "XRP-USD", "price": "1.50"}],
    }
    mock.get_trading_pairs.return_value = [{"symbol": "XRP-USD", "is_api_tradable": True}]
    mock.get_primary_account_v2.return_value = {"is_api_tradable": True}
    mock.get_account.return_value = {"buying_power": "500"}
    mock.place_order.return_value = {
        "id": "ord-1",
        "state": "filled",
        "filled_asset_quantity": "66.66666666",
        "average_price": "1.50",
    }
    with patch("app.robinhood_orders.get_credentials", return_value=("k", "p")), \
         patch("app.robinhood_orders.RobinhoodCryptoClient", return_value=mock), \
         patch("app.robinhood_orders.time.sleep"):
        out = place_market_dollars(side="buy", pair="XRP/USD", dollars=100)
    assert out["ok"] is True
    assert out["dollars"] == pytest.approx(100.0)
    body = mock.place_order.call_args[0][0]
    assert body["side"] == "buy"
    assert body["type"] == "limit"
    assert body["symbol"] == "XRP-USD"
    assert "asset_quantity" in body["limit_order_config"]
    assert float(body["limit_order_config"]["limit_price"]) > 1.50
    assert body["limit_order_config"]["time_in_force"] == "gtc"


def test_place_market_dollars_sell_all_uses_available():
    mock = MagicMock()
    mock.get_best_bid_ask.return_value = {
        "results": [{"symbol": "XRP-USD", "price": "1.50"}],
    }
    mock.get_trading_pairs.return_value = [{"symbol": "XRP-USD", "is_api_tradable": True}]
    mock.get_primary_account_v2.return_value = {"is_api_tradable": True}
    mock.get_account.return_value = {"buying_power": "5000"}
    mock.get_all_holdings.return_value = [
        {"asset_code": "XRP", "total_quantity": "100", "quantity_available_for_trading": "90"},
    ]
    mock.place_order.return_value = {
        "id": "ord-2",
        "state": "filled",
        "filled_asset_quantity": "90",
        "average_price": "1.50",
    }
    with patch("app.robinhood_orders.get_credentials", return_value=("k", "p")), \
         patch("app.robinhood_orders.RobinhoodCryptoClient", return_value=mock), \
         patch("app.robinhood_orders.time.sleep"):
        out = place_market_dollars(
            side="sell", pair="XRP/USD", dollars=9999, sell_all=True,
        )
    assert out["ok"] is True
    body = mock.place_order.call_args[0][0]
    assert body["limit_order_config"]["asset_quantity"] == "90"
    assert float(body["limit_order_config"]["limit_price"]) < 1.50


def test_place_market_dollars_buy_rejects_over_buying_power():
    mock = MagicMock()
    mock.get_trading_pairs.return_value = [{"symbol": "XRP-USD", "is_api_tradable": True}]
    mock.get_primary_account_v2.return_value = {"is_api_tradable": True}
    mock.get_account.return_value = {"buying_power": "100"}
    with patch("app.robinhood_orders.get_credentials", return_value=("k", "p")), \
         patch("app.robinhood_orders.RobinhoodCryptoClient", return_value=mock):
        out = place_market_dollars(side="buy", pair="XRP/USD", dollars=200)
    assert out["ok"] is False
    assert "Buying power" in out["error"]
    mock.place_order.assert_not_called()


def test_auto_order_refuses_daily_fallback_quote():
    mock = MagicMock()
    mock.get_trading_pairs.return_value = [{"symbol": "XRP-USD", "is_api_tradable": True}]
    mock.get_primary_account_v2.return_value = {"is_api_tradable": True}
    mock.get_account.return_value = {"buying_power": "500"}
    mock.get_best_bid_ask.side_effect = RuntimeError("quote unavailable")
    with patch("app.robinhood_orders.get_credentials", return_value=("k", "p")), \
         patch("app.robinhood_orders.RobinhoodCryptoClient", return_value=mock):
        out = place_market_dollars(
            side="buy", pair="XRP/USD", dollars=100,
            fallback_price=1.5, require_live_quote=True,
        )
    assert out["ok"] is False
    assert "시세 조회 실패" in out["error"]
    mock.place_order.assert_not_called()


def test_auto_order_refuses_stale_robinhood_quote():
    mock = MagicMock()
    mock.get_trading_pairs.return_value = [{"symbol": "XRP-USD", "is_api_tradable": True}]
    mock.get_primary_account_v2.return_value = {"is_api_tradable": True}
    mock.get_account.return_value = {"buying_power": "500"}
    mock.get_best_bid_ask.return_value = {"results": [{
        "symbol": "XRP-USD", "price": "1.50",
        "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(),
    }]}
    with patch("app.robinhood_orders.get_credentials", return_value=("k", "p")), \
         patch("app.robinhood_orders.RobinhoodCryptoClient", return_value=mock):
        out = place_market_dollars(
            side="buy", pair="XRP/USD", dollars=100, require_live_quote=True,
        )
    assert out["ok"] is False
    assert "2분" in out["error"]
    mock.place_order.assert_not_called()


def _tradable_client(**overrides):
    mock = MagicMock()
    mock.get_trading_pairs.return_value = [{"symbol": "XRP-USD", "is_api_tradable": True}]
    mock.get_primary_account_v2.return_value = {"is_api_tradable": True}
    mock.get_account.return_value = {"buying_power": "500"}
    mock.get_best_bid_ask.return_value = {"results": [{
        "symbol": "XRP-USD", "price": "1.50",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }]}
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


def _place(mock, **kw):
    with patch("app.robinhood_orders.get_credentials", return_value=("k", "p")), \
         patch("app.robinhood_orders.RobinhoodCryptoClient", return_value=mock), \
         patch("app.robinhood_orders.time.sleep"):
        return place_market_dollars(side="buy", pair="XRP/USD", dollars=100, **kw)


def test_price_drift_is_transient_not_hard_failure():
    out = _place(_tradable_client(), expected_price=1.0, require_live_quote=True)
    assert out["ok"] is False
    assert "시세 변동" in out["error"]
    assert out["transient"] is True


def test_stale_quote_and_quote_error_are_transient():
    stale = _tradable_client()
    stale.get_best_bid_ask.return_value = {"results": [{
        "symbol": "XRP-USD", "price": "1.50",
        "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(),
    }]}
    assert _place(stale, require_live_quote=True)["transient"] is True
    down = _tradable_client()
    down.get_best_bid_ask.side_effect = RuntimeError("connection reset")
    assert _place(down, require_live_quote=True)["transient"] is True


def test_robinhood_5xx_is_transient_but_4xx_is_hard():
    from app.robinhood_client import RobinhoodAPIError

    server = _tradable_client()
    server.place_order.side_effect = RobinhoodAPIError("Robinhood API 503: upstream")
    assert _place(server)["transient"] is True

    forbidden = _tradable_client()
    forbidden.place_order.side_effect = RobinhoodAPIError("Robinhood API 403: no permission")
    with patch("app.robinhood_config.keys_from_dashboard", return_value=False):
        out = _place(forbidden)
    assert out["ok"] is False
    assert out["transient"] is False

    precheck = _tradable_client()
    precheck.get_primary_account_v2.side_effect = RobinhoodAPIError("Robinhood API 401: bad key")
    assert _place(precheck)["transient"] is False


def test_insufficient_buying_power_is_hard_failure():
    poor = _tradable_client()
    poor.get_account.return_value = {"buying_power": "10"}
    out = _place(poor)
    assert out["ok"] is False
    assert not out.get("transient")


def test_unfilled_order_is_not_applied_as_success():
    mock = MagicMock()
    mock.get_trading_pairs.return_value = [{"symbol": "XRP-USD", "is_api_tradable": True}]
    mock.get_primary_account_v2.return_value = {"is_api_tradable": True}
    mock.get_account.return_value = {"buying_power": "500"}
    mock.get_best_bid_ask.return_value = {
        "results": [{"symbol": "XRP-USD", "price": "1.50"}],
    }
    mock.place_order.return_value = {"id": "ord-open", "state": "open"}
    mock.get_order.return_value = {"id": "ord-open", "state": "open"}
    mock.cancel_order.return_value = {"id": "ord-open", "state": "canceled"}
    with patch("app.robinhood_orders.get_credentials", return_value=("k", "p")), \
         patch("app.robinhood_orders.RobinhoodCryptoClient", return_value=mock), \
         patch("app.robinhood_orders.time.sleep"):
        out = place_market_dollars(side="buy", pair="XRP/USD", dollars=100)
    assert out["ok"] is False
    assert out["retryable"] is True
    assert out["rh_order_id"] == "ord-open"
    assert "재주문" in out["error"]
    mock.cancel_order.assert_called_once_with("ord-open", api_version="v1")


def test_partial_fill_stays_pending_until_fully_filled():
    mock = MagicMock()
    mock.get_trading_pairs.return_value = [{"symbol": "XRP-USD", "is_api_tradable": True}]
    mock.get_primary_account_v2.return_value = {"is_api_tradable": True}
    mock.get_account.return_value = {"buying_power": "500"}
    mock.get_best_bid_ask.return_value = {
        "results": [{"symbol": "XRP-USD", "price": "1.50"}],
    }
    partial = {
        "id": "ord-partial", "state": "partially_filled",
        "filled_asset_quantity": "10", "average_price": "1.50",
    }
    mock.place_order.return_value = partial
    mock.get_order.return_value = partial
    with patch("app.robinhood_orders.get_credentials", return_value=("k", "p")), \
         patch("app.robinhood_orders.RobinhoodCryptoClient", return_value=mock), \
         patch("app.robinhood_orders.time.sleep"):
        out = place_market_dollars(side="buy", pair="XRP/USD", dollars=100)
    assert out["ok"] is False
    assert out["pending"] is True
    assert out["state"] == "partially_filled"
    mock.cancel_order.assert_not_called()


def test_canceled_partial_fill_confirms_only_executed_notional():
    mock = MagicMock()
    mock.get_primary_account_v2.return_value = {"is_api_tradable": True}
    mock.get_account.return_value = {"buying_power": "500"}
    mock.get_best_bid_ask.return_value = {
        "results": [{"symbol": "XRP-USD", "price": "1.50"}],
    }
    partial = {
        "id": "ord-partial-canceled", "state": "canceled",
        "filled_asset_quantity": "10", "average_price": "1.50",
    }
    mock.place_order.return_value = partial
    with patch("app.robinhood_orders.get_credentials", return_value=("k", "p")), \
         patch("app.robinhood_orders.RobinhoodCryptoClient", return_value=mock):
        out = place_market_dollars(side="buy", pair="XRP/USD", dollars=100)

    assert out["ok"] is True
    assert out["partial_terminal"] is True
    assert out["dollars"] == 15.0


def test_emergency_sell_can_bypass_recommendation_price_drift():
    mock = MagicMock()
    mock.get_trading_pairs.return_value = [{"symbol": "XRP-USD", "is_api_tradable": True}]
    mock.get_primary_account_v2.return_value = {"is_api_tradable": True}
    mock.get_best_bid_ask.return_value = {
        "results": [{"symbol": "XRP-USD", "price": "1.00"}],
    }
    mock.get_all_holdings.return_value = [
        {"asset_code": "XRP", "quantity_available_for_trading": "100"},
    ]
    mock.place_order.return_value = {
        "id": "ord-stop", "state": "filled",
        "filled_asset_quantity": "100", "average_price": "1.00",
    }
    with patch("app.robinhood_orders.get_credentials", return_value=("k", "p")), \
         patch("app.robinhood_orders.RobinhoodCryptoClient", return_value=mock), \
         patch("app.robinhood_orders.time.sleep"):
        out = place_market_dollars(
            side="sell", pair="XRP/USD", dollars=200, sell_all=True,
            expected_price=1.50, bypass_price_drift=True,
        )
    assert out["ok"] is True
    body = mock.place_order.call_args.args[0]
    assert float(body["limit_order_config"]["limit_price"]) == 0.99
