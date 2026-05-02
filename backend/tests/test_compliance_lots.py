"""ComplianceService: FIFO lots, hold_term split, wash basis carry, persistence."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.services import compliance_service as cs_mod
from app.services.compliance_service import (
    LONG_TERM_HOLD_DAYS,
    ComplianceService,
    _hold_term_for,
)


@pytest.fixture
def svc(tmp_path: Path) -> ComplianceService:
    return ComplianceService(log_dir=tmp_path)


def test_hold_term_split_short_vs_long():
    today = date(2026, 5, 1)
    # Held 365 days exactly → still short under "more than 1 year" rule.
    assert _hold_term_for(today - timedelta(days=LONG_TERM_HOLD_DAYS), today) == "short"
    # Held 366 days → long-term capital gain.
    assert _hold_term_for(today - timedelta(days=LONG_TERM_HOLD_DAYS + 1), today) == "long"


def test_record_buy_sell_short_term_fifo(svc: ComplianceService):
    svc.record_buy("AAPL", 10, 200.0, settled_before=10_000.0)
    svc.record_sell("AAPL", 10, 210.0, cost_basis=2_000.0)

    assert len(svc._realized) == 1
    rec = svc._realized[-1]
    assert rec["symbol"] == "AAPL"
    assert rec["qty"] == 10
    assert rec["pnl"] == pytest.approx(100.0, abs=0.01)
    assert rec["hold_term"] == "short"
    assert rec["slice_terms"] == ["short"]


def test_wash_basis_carry_into_replacement_lot(svc: ComplianceService, monkeypatch):
    """Loss disposal should add the disallowed loss to the next buy's basis."""
    fixed_today = date(2026, 5, 1)
    monkeypatch.setattr(cs_mod, "_today_et", lambda: fixed_today)

    svc.record_buy("AAPL", 10, 200.0, settled_before=10_000.0)  # cost 2000
    svc.record_sell("AAPL", 10, 190.0, cost_basis=2_000.0)       # loss 100

    assert "AAPL" in svc._wash_sale_cooldown
    assert any(c.symbol == "AAPL" and c.disallowed_loss == 100.0 for c in svc._wash_loss_carries)

    # Replacement buy within 30 days inherits the disallowed loss.
    svc.record_buy("AAPL", 5, 195.0, settled_before=10_000.0)
    new_lot = svc._tax_lots[-1]
    assert new_lot.symbol == "AAPL"
    assert new_lot.qty == 5
    raw_cost = 5 * 195.0
    assert new_lot.total_cost == pytest.approx(raw_cost + 100.0, abs=0.01)
    assert new_lot.wash_basis_adjustment == pytest.approx(100.0, abs=0.01)
    assert new_lot.unit_cost == pytest.approx((raw_cost + 100.0) / 5, abs=0.01)

    # Selling the replacement at break-even on the *adjusted* basis must
    # leave realized P/L at zero — i.e. the wash rule deferred the loss.
    svc.record_sell("AAPL", 5, new_lot.unit_cost, cost_basis=new_lot.total_cost)
    assert svc._realized[-1]["pnl"] == pytest.approx(0.0, abs=0.01)


def test_wash_carry_partial_consumption_across_two_buys(svc: ComplianceService, monkeypatch):
    fixed_today = date(2026, 5, 1)
    monkeypatch.setattr(cs_mod, "_today_et", lambda: fixed_today)

    svc.record_buy("MSFT", 10, 400.0, settled_before=10_000.0)  # cost 4000
    svc.record_sell("MSFT", 10, 380.0, cost_basis=4_000.0)        # loss 200

    svc.record_buy("MSFT", 4, 390.0, settled_before=10_000.0)
    first = svc._tax_lots[-1]
    assert first.wash_basis_adjustment == pytest.approx(200.0, abs=0.01)

    # Second replacement on same day: previous carry was already fully consumed.
    svc.record_buy("MSFT", 6, 392.0, settled_before=10_000.0)
    second = svc._tax_lots[-1]
    assert second.wash_basis_adjustment == pytest.approx(0.0, abs=0.01)


def test_partial_sell_keeps_proportional_wash_basis(svc: ComplianceService, monkeypatch):
    fixed_today = date(2026, 5, 1)
    monkeypatch.setattr(cs_mod, "_today_et", lambda: fixed_today)

    svc.record_buy("NVDA", 4, 100.0, settled_before=10_000.0)
    svc.record_sell("NVDA", 4, 90.0, cost_basis=400.0)  # loss 40

    svc.record_buy("NVDA", 4, 95.0, settled_before=10_000.0)
    full_lot = svc._tax_lots[-1]
    assert full_lot.wash_basis_adjustment == pytest.approx(40.0, abs=0.01)

    # Sell half — remaining slice should carry half the wash adjustment.
    svc.record_sell("NVDA", 2, 96.0, cost_basis=full_lot.total_cost / 2)
    remaining = [lot for lot in svc._tax_lots if lot.symbol == "NVDA"]
    assert len(remaining) == 1
    assert remaining[0].qty == 2
    assert remaining[0].wash_basis_adjustment == pytest.approx(20.0, abs=0.01)


def test_state_persists_across_restart(tmp_path: Path):
    svc1 = ComplianceService(log_dir=tmp_path)
    svc1.record_buy("TSLA", 3, 250.0, settled_before=10_000.0)
    assert (tmp_path / "compliance_state.json").exists()

    svc2 = ComplianceService(log_dir=tmp_path)
    assert len(svc2._tax_lots) == 1
    assert svc2._tax_lots[0].symbol == "TSLA"
    assert svc2._tax_lots[0].qty == 3


def test_gfv_restricted_after_three_events(svc: ComplianceService, monkeypatch):
    """3 GFV events in 12mo → ``is_gfv_restricted`` returns True."""
    today = date(2026, 5, 1)
    monkeypatch.setattr(cs_mod, "_today_et", lambda: today)
    svc._gfv_events = [today, today, today]
    assert svc.gfv_warning_level() == "RESTRICTED"
    assert svc.is_gfv_restricted() is True
