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

    result = broker.buy_notional(
        "SPY", 200, client_order_id="stable-cid", limit_price=100.25
    )

    assert result["status"] == "filled"
    assert result["client_order_id"] == "stable-cid"
    assert broker.trading.submit_order.call_count == 1


def test_existing_client_order_is_not_submitted_again():
    broker = Broker.__new__(Broker)
    broker.trading = MagicMock()
    broker.trading.get_order_by_client_id.return_value = _filled_order("stable-cid")

    result = broker.buy_notional(
        "SPY", 200, client_order_id="stable-cid", limit_price=100.25
    )

    assert result["status"] == "filled"
    broker.trading.submit_order.assert_not_called()


def test_buy_submits_fractional_day_limit_order():
    broker = Broker.__new__(Broker)
    broker.trading = MagicMock()
    broker.trading.get_order_by_client_id.side_effect = NotFoundError("404")
    broker.trading.submit_order.return_value = _filled_order("limit-cid")

    result = broker.buy_notional(
        "SPY", 123.45, client_order_id="limit-cid", limit_price=501.25
    )

    assert result["status"] == "filled"
    request = broker.trading.submit_order.call_args.args[0]
    assert float(request.limit_price) == 501.25
    assert float(request.notional) == 123.45
    assert request.type.value == "limit"
    assert request.time_in_force.value == "day"


def test_marketable_limit_uses_quote_side_buffer_and_valid_tick():
    broker = Broker.__new__(Broker)
    broker.latest_quote = MagicMock(return_value=(100.01, 100.03))

    buy = broker.marketable_limit_price("SPY", "buy", reference_price=100)
    sell = broker.marketable_limit_price("SPY", "sell", reference_price=100)
    emergency = broker.marketable_limit_price(
        "SPY", "sell", reference_price=100, emergency=True
    )

    assert buy == 100.29
    assert sell == 99.75
    assert emergency == 99.00
