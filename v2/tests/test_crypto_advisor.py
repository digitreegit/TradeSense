import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crypto_advisor import MAX_STEP, MIN_STEP, _step_for, analyze_frames


def make_frame(closes: np.ndarray, daily_range: float = 0.05) -> pd.DataFrame:
    idx = pd.date_range("2025-06-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * (1 + daily_range / 2),
            "low": closes * (1 - daily_range / 2),
            "close": closes,
        },
        index=idx,
    )


def test_step_is_bounded():
    assert _step_for(0.001) == MIN_STEP
    assert _step_for(0.5) == MAX_STEP
    assert MIN_STEP <= _step_for(0.05) <= MAX_STEP


def test_uptrend_coin_is_picked_and_downtrend_avoided():
    n = 250
    up = make_frame(np.linspace(100, 200, n), daily_range=0.06)
    down = make_frame(np.linspace(200, 100, n), daily_range=0.08)
    btc = make_frame(np.linspace(50_000, 80_000, n), daily_range=0.03)

    out = analyze_frames({"SOL/USD": up, "DOGE/USD": down, "BTC/USD": btc},
                         budget=1000.0)

    picked = {c["symbol"] for c in out["picks"]}
    assert "SOL" in picked
    assert "DOGE" not in picked
    doge = next(c for c in out["watch"] if c["symbol"] == "DOGE")
    assert doge["action"] == "avoid"
    assert out["market"]["label"] == "BULL"


def test_levels_are_ordered_and_budget_split():
    n = 250
    frames = {
        "SOL/USD": make_frame(np.linspace(100, 200, n), daily_range=0.06),
        "BTC/USD": make_frame(np.linspace(50_000, 80_000, n), daily_range=0.03),
    }
    out = analyze_frames(frames, budget=1000.0)
    assert out["picks"]
    total = 0.0
    for c in out["picks"]:
        assert c["buy2"] < c["buy1"] < c["sell"]
        assert c["unit"] * 2 == c["alloc"]
        total += c["alloc"]
    assert total == 1000.0


def test_bear_market_halves_budget_for_surviving_uptrends():
    n = 250
    frames = {
        "BTC/USD": make_frame(np.linspace(80_000, 50_000, n), daily_range=0.03),
        "SOL/USD": make_frame(np.linspace(100, 200, n), daily_range=0.06),
    }
    out = analyze_frames(frames, budget=1000.0)
    assert out["market"]["label"] == "BEAR"
    assert len(out["picks"]) == 1
    sol = out["picks"][0]
    assert sol["alloc"] == 500.0
    assert sol["action_label"].startswith("약세장 주의")


def test_bear_market_yields_no_picks():
    n = 250
    frames = {
        "BTC/USD": make_frame(np.linspace(80_000, 50_000, n), daily_range=0.03),
        "SOL/USD": make_frame(np.linspace(200, 100, n), daily_range=0.06),
    }
    out = analyze_frames(frames, budget=1000.0)
    assert out["picks"] == []
    assert out["market"]["label"] == "BEAR"
