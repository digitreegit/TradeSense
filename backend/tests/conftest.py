"""Shared pytest fixtures.

The trading-critical modules (compliance, earnings, calendar, notification)
are pure Python and easy to import. The trading_engine itself touches
Alpaca + the LLM agent, so we exercise its sizing + gating helpers via
focused unit-style fixtures rather than spinning up the full FastAPI app.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make sure ``backend`` is importable as the package root for ``app.*``.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Pin a clean log/db path before any module imports settings.
os.environ.setdefault("TRADESENSE_LOG_DIR", str(_BACKEND / "tests" / "_tmp_logs"))
os.environ.setdefault(
    "TRADESENSE_DB_PATH", str(_BACKEND / "tests" / "_tmp_logs" / "tradesense-test.db")
)
Path(os.environ["TRADESENSE_LOG_DIR"]).mkdir(parents=True, exist_ok=True)
