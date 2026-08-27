"""Alpaca order submission safety and idempotency."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.broker import Broker


class NotFoundError(RuntimeError):
    status_code = 404


def _filled_order(client_order_id: str):
    return SimpleNamespace(
        id="alpaca-1",
        client_order_id=client_order_id,
        status=SimpleNamespace(value="filled"),
        symbol="SPY",
        side=SimpleNamespace(value="buy"),
        qty="2",
        filled_qty="2",
        filled_avg_price="100",
    )


def test_buy_timeout_reconciles_by_client_order_id():
    broker = Broker.__new__(Broker)
    broker.trading = MagicMock()
    broker.trading.get_order_by_client_id.side_effect = [
        NotFoundError("404 not found"),
        _filled_order("stable-cid"),
    ]
    broker.trading.submit_order.side_effect = TimeoutError("response timed out")

    result = broker.buy_notional("SPY", 200, client_order_id="stable-cid")

    assert result["status"] == "filled"
    assert result["client_order_id"] == "stable-cid"
    assert broker.trading.submit_order.call_count == 1


def test_existing_client_order_is_not_submitted_again():
    broker = Broker.__new__(Broker)
    broker.trading = MagicMock()
    broker.trading.get_order_by_client_id.return_value = _filled_order("stable-cid")

    result = broker.buy_notional("SPY", 200, client_order_id="stable-cid")

    assert result["status"] == "filled"
    broker.trading.submit_order.assert_not_called()
