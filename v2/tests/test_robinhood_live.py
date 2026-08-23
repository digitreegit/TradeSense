"""Tests for live Robinhood balance snapshot and auto-confirm."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.crypto_advisor import (
    auto_confirm_from_robinhood,
    holdings_qty_changed,
    _merge_pending,
)
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
    # Quotes requested for every held symbol, not only advice candidates.
    mock_client.get_best_bid_ask.assert_called_once()
    called_syms = set(mock_client.get_best_bid_ask.call_args[0])
    assert called_syms == {"XRP-USD", "SOL-USD"}


def test_fetch_robinhood_snapshot_includes_non_candidate_holdings():
    """Coins outside CANDIDATES must still count toward total / buying-power sum."""
    mock_client = MagicMock()
    mock_client.get_account.return_value = {"buying_power": "100.00"}
    mock_client.get_all_holdings.return_value = [
        {"asset_code": "XRP", "total_quantity": "100"},
        {"asset_code": "PEPE", "total_quantity": "1000000"},  # not in CANDIDATES
    ]
    mock_client.get_best_bid_ask.return_value = {
        "results": [
            {"symbol": "XRP-USD", "price": "1.50"},
            {
                "symbol": "PEPE-USD",
                "price": None,
                "bid_inclusive_of_sell_spread": "0.000009",
                "ask_inclusive_of_buy_spread": "0.000011",
            },
        ]
    }

    with patch("app.robinhood_live.get_credentials", return_value=("key", "priv")), \
         patch("app.robinhood_live.RobinhoodCryptoClient", return_value=mock_client), \
         patch("app.robinhood_live.fetch_bars", return_value={}):
        snap = fetch_robinhood_snapshot()

    assert snap is not None
    pepe = next(p for p in snap["positions"] if p["symbol"] == "PEPE")
    assert pepe["supported"] is False
    assert pepe["price"] == pytest.approx(0.00001)  # mid of bid/ask
    pepe_val = 1_000_000 * 0.00001
    xrp_val = 100 * 1.50
    assert snap["holdings_value"] == pytest.approx(round(xrp_val + pepe_val, 2))
    assert snap["total"] == pytest.approx(round(100 + xrp_val + pepe_val, 2))
    called_syms = set(mock_client.get_best_bid_ask.call_args[0])
    assert "PEPE-USD" in called_syms


def test_merge_live_into_summary_overrides_totals():
    snap = {
        "buying_power": 1686.47,
        "total": 6941.69,
        "crypto_total": 6941.69,
        "stocks_value": 0,
        "holdings_value": 5255.22,
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


def test_fetch_snapshot_adds_stocks_value_to_total():
    mock_client = MagicMock()
    mock_client.get_account.return_value = {"buying_power": "724.82"}
    mock_client.get_all_holdings.return_value = [
        {"asset_code": "XRP", "total_quantity": "100"},
    ]
    mock_client.get_best_bid_ask.return_value = {
        "results": [{"symbol": "XRP-USD", "price": "1.50"}],
    }
    with patch("app.robinhood_live.get_credentials", return_value=("key", "priv")), \
         patch("app.robinhood_live.RobinhoodCryptoClient", return_value=mock_client), \
         patch("app.robinhood_live.fetch_bars", return_value={}), \
         patch("app.robinhood_live.store") as mock_store:
        mock_store.get.return_value = {"stocks_value": 733.70}
        snap = fetch_robinhood_snapshot()
    assert snap["buying_power"] == pytest.approx(724.82)
    assert snap["holdings_value"] == pytest.approx(150.0)
    assert snap["cash"] == pytest.approx(724.82)  # API BP until brokerage_cash set
    assert snap["stocks_value"] == pytest.approx(733.70)
    assert snap["total"] == pytest.approx(150.0 + 724.82 + 733.70)
    assert snap["cash_incomplete"] is True


def test_fetch_snapshot_uses_brokerage_cash_and_stock_positions():
    mock_client = MagicMock()
    mock_client.get_account.return_value = {"buying_power": "724.82"}
    mock_client.get_all_holdings.return_value = [
        {"asset_code": "XRP", "total_quantity": "100"},
    ]
    mock_client.get_best_bid_ask.return_value = {
        "results": [{"symbol": "XRP-USD", "price": "1.50"}],
    }
    with patch("app.robinhood_live.get_credentials", return_value=("key", "priv")), \
         patch("app.robinhood_live.RobinhoodCryptoClient", return_value=mock_client), \
         patch("app.robinhood_live.fetch_bars", return_value={}), \
         patch("app.robinhood_live._stock_last_price", return_value=44.66), \
         patch("app.robinhood_live.store") as mock_store:
        mock_store.get.return_value = {
            "brokerage_cash": 3124.82,
            "stock_positions": [{"symbol": "IONQ", "qty": 16.47}],
        }
        snap = fetch_robinhood_snapshot()
    assert snap["cash"] == pytest.approx(3124.82)
    assert snap["buying_power"] == pytest.approx(724.82)
    assert snap["stocks_value"] == pytest.approx(round(16.47 * 44.66, 2))
    assert snap["total"] == pytest.approx(150.0 + 3124.82 + round(16.47 * 44.66, 2))
    assert snap["cash_incomplete"] is False

def test_auto_confirm_buy_when_bought_more_than_recommended():
    """User bought $1000 when we recommended $800 — clear the rec."""
    prev = {"SOL/USD": 10.0}
    snap = {
        "positions": [
            {"symbol": "SOL", "pair": "SOL/USD", "qty": 10.0 + (1000 / 82.0), "price": 82.0},
        ],
    }
    pending = [{
        "id": "abc", "side": "buy", "symbol": "SOL", "pair": "SOL/USD",
        "dollars": 800, "status": "pending", "baseline_qty": 10.0,
    }]
    with patch("app.crypto_advisor.store") as mock_store, \
         patch("app.crypto_advisor.log_activity"):
        confirmed = auto_confirm_from_robinhood(prev, snap, pending)

    assert len(confirmed) == 1
    assert confirmed[0]["status"] == "confirmed"
    assert confirmed[0]["auto_confirmed"] is True
    assert confirmed[0]["actual_dollars"] == pytest.approx(1000.0, abs=1)


def test_auto_confirm_uses_baseline_even_if_book_already_synced():
    """After live sync already updated book qty, still clear via baseline_qty."""
    prev = {"SOL/USD": 22.195}  # book already reflects the buy
    snap = {
        "positions": [
            {"symbol": "SOL", "pair": "SOL/USD", "qty": 22.195, "price": 82.0},
        ],
    }
    pending = [{
        "id": "abc", "side": "buy", "symbol": "SOL", "pair": "SOL/USD",
        "dollars": 800, "status": "pending", "baseline_qty": 10.0,
    }]
    with patch("app.crypto_advisor.store"), patch("app.crypto_advisor.log_activity"):
        confirmed = auto_confirm_from_robinhood(prev, snap, pending)
    assert len(confirmed) == 1
    assert confirmed[0]["actual_dollars"] == pytest.approx(1000.0, abs=1)


def test_auto_confirm_from_filled_order_when_qty_already_synced():
    """RH filled-order history clears the tip even if qty watermark is stale."""
    prev = {"SOL/USD": 22.195}
    snap = {
        "positions": [
            {"symbol": "SOL", "pair": "SOL/USD", "qty": 22.195, "price": 82.0},
        ],
    }
    now = datetime.now(timezone.utc)
    pending = [{
        "id": "abc", "side": "buy", "symbol": "SOL", "pair": "SOL/USD",
        "dollars": 800, "status": "pending", "baseline_qty": 22.195,
        "created_at": (now - timedelta(hours=1)).isoformat(),
    }]
    filled = [{
        "id": "rh-1",
        "symbol": "SOL-USD",
        "side": "buy",
        "state": "filled",
        "filled_asset_quantity": "12.195",
        "average_price": "82.0",
        "updated_at": now.isoformat(),
    }]
    with patch("app.crypto_advisor.store"), patch("app.crypto_advisor.log_activity"):
        confirmed = auto_confirm_from_robinhood(prev, snap, pending, filled)
    assert len(confirmed) == 1
    assert confirmed[0]["auto_confirm_source"] == "order"
    assert confirmed[0]["actual_dollars"] == pytest.approx(1000.0, abs=1)


def test_auto_confirm_ignores_tiny_qty_noise():
    prev = {"XRP/USD": 1755.663}
    snap = {
        "positions": [
            {"symbol": "XRP", "pair": "XRP/USD", "qty": 1755.7, "price": 1.07},
        ],
    }
    pending = [{
        "id": "xyz", "side": "buy", "symbol": "XRP", "pair": "XRP/USD",
        "dollars": 800, "status": "pending", "baseline_qty": 1755.663,
    }]
    with patch("app.crypto_advisor.store"):
        confirmed = auto_confirm_from_robinhood(prev, snap, pending)
    assert confirmed == []
    assert pending[0]["status"] == "pending"


def test_merge_pending_does_not_requeue_recently_confirmed():
    confirmed = {
        "id": "old", "side": "buy", "symbol": "SOL", "pair": "SOL/USD",
        "kind": "entry", "dollars": 800, "status": "confirmed",
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }
    fresh = {
        "id": "new", "side": "buy", "symbol": "SOL", "pair": "SOL/USD",
        "kind": "entry", "dollars": 800, "status": "pending",
    }
    out = _merge_pending([confirmed], [fresh])
    assert all(o.get("status") == "confirmed" for o in out if o.get("symbol") == "SOL")
    assert not any(o.get("status") == "pending" and o.get("symbol") == "SOL" for o in out)


def test_merge_pending_requeues_after_cooldown():
    confirmed = {
        "id": "old", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
        "kind": "trim", "dollars": 100, "status": "confirmed",
        "confirmed_at": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
    }
    fresh = {
        "id": "new", "side": "sell", "symbol": "XRP", "pair": "XRP/USD",
        "kind": "trim", "dollars": 120, "status": "pending",
    }
    out = _merge_pending([confirmed], [fresh])
    active = [o for o in out if o.get("status") != "confirmed"]
    assert len(active) == 1
    assert active[0]["dollars"] == 120



def test_holdings_qty_changed():
    prev = {"SOL/USD": 10.0}
    snap = {"positions": [{"pair": "SOL/USD", "qty": 22.0}]}
    assert holdings_qty_changed(prev, snap) is True
    assert holdings_qty_changed(prev, {"positions": [{"pair": "SOL/USD", "qty": 10.0}]}) is False
