from unittest.mock import MagicMock
import pytest
from app import robinhood_config as config


@pytest.mark.parametrize('connection', [
    {'connected': False},
    {'connected': True, 'account': {'status': 'disabled', 'is_api_tradable': True}},
    {'connected': True, 'account': {'status': 'active', 'is_api_tradable': False}},
    {'connected': True, 'account': {'status': 'active'}},
])
def test_auto_preflight_failure_preserves_mode(monkeypatch, connection):
    store = MagicMock()
    monkeypatch.setattr(config, 'store', store)
    monkeypatch.setattr(config, 'test_connection', lambda: connection)
    with pytest.raises(ValueError):
        config.set_execution_mode('auto')
    store.set.assert_not_called()


def test_switch_on_only_saves_mode_after_readonly_preflight(monkeypatch):
    store = MagicMock()
    monkeypatch.setattr(config, 'store', store)
    monkeypatch.setattr(config, 'test_connection', lambda: {
        'connected': True, 'account': {'status': 'active', 'is_api_tradable': True}})
    assert config.set_execution_mode('auto') == 'auto'
    store.set.assert_called_once_with(config.EXEC_MODE_KEY, 'auto')


def test_switch_off_works_even_if_broker_is_down(monkeypatch):
    store = MagicMock()
    monkeypatch.setattr(config, 'store', store)
    check = MagicMock(side_effect=RuntimeError('offline'))
    monkeypatch.setattr(config, 'test_connection', check)
    assert config.set_execution_mode('manual') == 'manual'
    check.assert_not_called()
    store.set.assert_called_once_with(config.EXEC_MODE_KEY, 'manual')
