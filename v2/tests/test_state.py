from app.state import Store
from app.decisions import PendingOrder


def test_job_claim_is_atomic_and_can_be_released(tmp_path):
    store = Store(sqlite_path=str(tmp_path / "state.db"))
    assert store.try_job_claim("open:2026-08-06")
    assert not store.try_job_claim("open:2026-08-06")
    store.release_job_claim("open:2026-08-06")
    assert store.try_job_claim("open:2026-08-06")


def test_pending_replace_rewrites_queue(tmp_path):
    store = Store(sqlite_path=str(tmp_path / "state.db"))
    store.pending_replace([
        PendingOrder("SPY", "momentum", "buy", 0.3, 3.0, "signal"),
        PendingOrder("QQQ", "dip", "sell", reason="dip-exit"),
    ])
    assert [o["symbol"] for o in store.pending_all()] == ["SPY", "QQQ"]

    store.pending_replace([PendingOrder("XLK", "momentum", "buy", 0.3, 3.0)])
    assert [o["symbol"] for o in store.pending_all()] == ["XLK"]
