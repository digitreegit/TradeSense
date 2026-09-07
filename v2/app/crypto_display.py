"""Read-only account presentation. Never changes trading balances or orders."""
from datetime import datetime, timezone
import math

RECONCILIATION_KEY = 'robinhood_display_reconciliation'


def reconcile(total: float, crypto_total: float, stocks: float) -> dict:
    if not all(math.isfinite(v) and v >= 0 for v in (total, crypto_total, stocks)):
        raise ValueError('잔고는 0 이상의 유한한 숫자여야 합니다.')
    return {'reference_total': total, 'reference_crypto_total': crypto_total,
            'stocks_value': stocks, 'other_value': round(total - crypto_total - stocks, 2),
            'captured_at': datetime.now(timezone.utc).isoformat()}


def account_view(crypto_total: float, reference: dict | None) -> dict:
    if not reference or 'reference_total' not in reference:
        return {'account_total': None, 'reconciliation': None}
    return {'account_total': round(crypto_total + reference['stocks_value'] + reference['other_value'], 2),
            'reconciliation': reference}


def activity_snapshot() -> dict:
    from .state import store
    from .robinhood_config import get_credentials
    from .robinhood_client import RobinhoodCryptoClient
    from .crypto_advisor import PENDING_KEY

    pending = store.get(PENDING_KEY) or []
    rows = []
    matched = set()
    errors = []
    api_key, private_key = get_credentials()
    broker = {}
    if api_key and private_key:
        for version in ('v1', 'v2'):
            try:
                client = RobinhoodCryptoClient(api_key, private_key)
                for row in client.get_orders(api_version=version, limit='50', max_pages=2):
                    if row.get('id'):
                        broker[str(row['id'])] = row
            except Exception:
                errors.append(version)
    for oid, row in broker.items():
        tip = next((o for o in pending if str(o.get('rh_order_id') or '') == oid
                    or (row.get('client_order_id') and o.get('rh_client_order_id') == row['client_order_id'])), None)
        if tip:
            matched.add(tip['id'])
        qty = float(row.get('filled_asset_quantity') or 0)
        price = float(row.get('average_price') or 0)
        rows.append({'id': oid, 'ts': row.get('updated_at') or row.get('created_at'),
                     'symbol': row.get('symbol'), 'side': row.get('side'),
                     'status': row.get('state'), 'qty': qty, 'price': price,
                     'filled_dollars': qty * price if qty and price else None,
                     'source': 'Robinhood', 'reason': (tip or {}).get('reason', '')})
    for tip in pending:
        if tip.get('id') in matched:
            continue
        rows.append({'id': tip.get('id'), 'ts': tip.get('confirmed_at') or tip.get('denied_at') or tip.get('created_at'),
                     'symbol': tip.get('symbol'), 'side': tip.get('side'),
                     'status': tip.get('rh_state') or tip.get('status'),
                     'filled_dollars': tip.get('actual_dollars') if tip.get('status') == 'confirmed' else None,
                     'source': 'TradeSense', 'reason': tip.get('reason', '')})
    rows.sort(key=lambda row: str(row.get('ts') or ''), reverse=True)
    return {'ok': True, 'orders': rows[:100],
            'activity': [a for a in reversed(store.get('activity_log', []) or []) if a.get('job') == 'crypto'][:50],
            'warning': ('Robinhood ' + ', '.join(errors) + ' 조회 실패 — 일부 내역이 누락될 수 있습니다.') if errors else None}
