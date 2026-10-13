"""Trading-pair listing must follow pagination (v6.1 universe bug)."""
from app.robinhood_client import RobinhoodCryptoClient


def _client(pages):
    c = RobinhoodCryptoClient.__new__(RobinhoodCryptoClient)
    calls = []

    def request(method, path, *a, **kw):
        calls.append(path)
        return pages[path]
    c.request = request
    c.calls = calls
    return c


def test_trading_pairs_v2_follows_next_links():
    pages = {
        "/api/v2/crypto/trading/trading_pairs/": {
            "results": [{"symbol": "LIT-USD"}], "next": "https://trading.robinhood.com/api/v2/crypto/trading/trading_pairs/?cursor=abc",
        },
        "/api/v2/crypto/trading/trading_pairs/?cursor=abc": {
            "results": [{"symbol": "BTC-USD"}, {"symbol": "ETH-USD"}], "next": None,
        },
    }
    c = _client(pages)
    rows = c.get_trading_pairs_v2()
    assert [r["symbol"] for r in rows] == ["LIT-USD", "BTC-USD", "ETH-USD"]
    assert c.calls == list(pages)


def test_trading_pairs_with_symbols_single_page():
    pages = {"/api/v1/crypto/trading/trading_pairs/?symbol=BTC-USD": {"results": [{"symbol": "BTC-USD"}]}}
    c = _client(pages)
    assert c.get_trading_pairs("BTC-USD") == [{"symbol": "BTC-USD"}]
