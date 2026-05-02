"""Earnings service: file overrides + universe filter."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.services import earnings_service


def _set_repo_root(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(earnings_service, "_repo_root", lambda: root)


def test_keyed_map_filters_to_today(monkeypatch, tmp_path: Path):
    _set_repo_root(monkeypatch, tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "earnings.json").write_text(
        json.dumps({"AAPL": ["2026-05-01"], "NVDA": ["2026-05-22"]}),
        encoding="utf-8",
    )
    out = earnings_service.earnings_today_map(today=date(2026, 5, 1))
    assert out == {"AAPL": ["2026-05-01"]}


def test_date_scoped_list_file(monkeypatch, tmp_path: Path):
    _set_repo_root(monkeypatch, tmp_path)
    daydir = tmp_path / "data" / "earnings"
    daydir.mkdir(parents=True)
    (daydir / "2026-05-01.json").write_text(json.dumps(["AAPL", "tsla"]), encoding="utf-8")
    out = earnings_service.earnings_today_map(today=date(2026, 5, 1))
    assert set(out.keys()) == {"AAPL", "TSLA"}


def test_universe_pre_filter_returns_subset(monkeypatch, tmp_path: Path):
    _set_repo_root(monkeypatch, tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "earnings.json").write_text(
        json.dumps({"AAPL": ["2026-05-01"], "MSFT": ["2026-05-01"]}),
        encoding="utf-8",
    )
    out = earnings_service.earnings_today_map(symbols=["AAPL"], today=date(2026, 5, 1))
    assert out == {"AAPL": ["2026-05-01"]}


def test_no_files_returns_empty(monkeypatch, tmp_path: Path):
    _set_repo_root(monkeypatch, tmp_path)
    out = earnings_service.earnings_today_map(today=date(2026, 5, 1))
    assert out == {}
