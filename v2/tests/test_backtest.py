import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import backtest as backtest_mod
from app import strategy
from app.backtest import Backtester
from app.decisions import PendingOrder


def test_open_sizing_uses_previous_completed_atr(monkeypatch):
    idx = pd.bdate_range("2025-01-01", periods=214)
    close = np.full(len(idx), 100.0)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000_000,
        },
        index=idx,
    )
    # The fill-day range is unknowable at its open and must not affect sizing.
    df.iloc[211, df.columns.get_loc("high")] = 150.0
    df.iloc[211, df.columns.get_loc("low")] = 50.0

    calls = 0

    def fake_decide(**kwargs):
        nonlocal calls
        calls += 1
        return (
            [PendingOrder("SPY", "momentum", "buy", 0.3, 3.0)]
            if calls == 1 else []
        )

    seen_atr = []

    def fake_position_dollars(**kwargs):
        seen_atr.append(kwargs["atr_value"])
        return 100.0

    monkeypatch.setattr(backtest_mod, "decide", fake_decide)
    monkeypatch.setattr(backtest_mod, "position_dollars", fake_position_dollars)
    Backtester({"SPY": df}, {}, 1000.0).run()

    feats = strategy.compute_features(df)
    assert seen_atr
    assert seen_atr[0] == pytest.approx(float(feats.iloc[210]["atr"]))
    assert seen_atr[0] != pytest.approx(float(feats.iloc[211]["atr"]))
