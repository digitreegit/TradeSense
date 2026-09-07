from unittest.mock import MagicMock, patch
import pytest
from app.crypto_display import reconcile, account_view, activity_snapshot


def test_screenshot_reconciliation_keeps_trading_subtotal_separate():
    ref = reconcile(8447.12, 6792.77, 654.35)
    assert ref['other_value'] == 1000.0
    view = account_view(6792.77, ref)
    assert view['account_total'] == 8447.12
    assert account_view(6802.77, ref)['account_total'] == 8457.12
    assert ref['reference_total'] == 8447.12
    assert account_view(6792.77, None)['account_total'] is None


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1])
def test_invalid_reference_rejected(value):
    with pytest.raises(ValueError):
        reconcile(value, 100, 50)


def test_history_dedupes_broker_versions_and_retains_denied_recommendations():
    tips = [{'id': 'tip1', 'rh_order_id': 'rh1', 'status': 'confirmed', 'reason': 'stop'},
            {'id': 'tip2', 'status': 'denied', 'symbol': 'ETH', 'dollars': 100}]
    st = MagicMock()
    st.get.side_effect = lambda key, *args: tips if key == 'crypto_pending' else []
    client = MagicMock()
    client.get_orders.return_value = [{'id': 'rh1', 'symbol': 'BTC-USD', 'side': 'sell',
                                      'state': 'partially_filled', 'filled_asset_quantity': '0.01',
                                      'average_price': '60000', 'updated_at': '2026-09-06T00:00:00Z'}]
    with patch('app.state.store', st), patch('app.robinhood_config.get_credentials', return_value=('key', 'private')), patch('app.robinhood_client.RobinhoodCryptoClient', return_value=client):
        result = activity_snapshot()
    assert len(result['orders']) == 2
    filled = next(o for o in result['orders'] if o['id'] == 'rh1')
    assert filled['filled_dollars'] == 600
    assert filled['status'] == 'partially_filled'
    denied = next(o for o in result['orders'] if o['id'] == 'tip2')
    assert denied['filled_dollars'] is None
    client.place_order.assert_not_called()
