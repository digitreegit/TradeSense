import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import robinhood_vision as rv


def test_parse_screenshots_requires_image():
    with pytest.raises(ValueError, match="1장 이상"):
        rv.parse_screenshots([])


def test_parse_screenshots_requires_api_key(monkeypatch):
    monkeypatch.setattr(rv.settings, "openai_api_key", "")
    monkeypatch.setattr(rv.settings, "google_api_key", "")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY|GOOGLE_API_KEY"):
        rv.parse_screenshots([b"fake"])


def test_resolve_google_model_maps_deprecated_exp():
    assert rv._resolve_google_model("gemini-2.0-flash-exp") == "gemini-2.5-flash"
    assert rv._resolve_google_model("models/gemini-2.0-flash") == "gemini-2.5-flash"
    assert rv._resolve_google_model("gemini-2.5-flash") == "gemini-2.5-flash"


def test_gemini_models_to_try_includes_fallbacks():
    chain = rv._gemini_models_to_try("gemini-2.0-flash")
    assert chain[0] == "gemini-2.5-flash"
    assert "gemini-flash-latest" in chain


def test_image_mime_detects_png():
    assert rv._image_mime(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20) == "image/png"


@patch("app.robinhood_vision.import_holdings")
@patch("app.robinhood_vision.parse_screenshots")
def test_analyze_and_advise_merges_parsed(mock_parse, mock_import):
    mock_parse.return_value = {
        "cash": 745.02,
        "principal": 13500,
        "positions": [
            {"symbol": "XRP", "qty": 5004.162, "avg_cost": 1.80},
            {"symbol": "ETH", "qty": 0.052, "avg_cost": 1921.65},
        ],
        "notes": "XRP 비중이 큽니다.",
    }
    mock_import.return_value = {"ok": True, "summary": {"total": 6700}, "orders": []}

    out = rv.analyze_and_advise([b"img1", b"img2"])

    assert out["ok"] is True
    mock_import.assert_called_once()
    cash, positions, principal = mock_import.call_args[0]
    assert cash == 745.02
    assert principal == 13500
    assert len(positions) == 2
    assert positions[0]["symbol"] == "XRP"
    assert out["parsed"]["notes"] == "XRP 비중이 큽니다."


@patch("app.robinhood_vision.parse_screenshots")
def test_analyze_and_advise_rejects_empty_holdings(mock_parse):
    mock_parse.return_value = {"cash": 0, "positions": [], "notes": ""}
    with pytest.raises(ValueError, match="찾지 못했습니다"):
        rv.analyze_and_advise([b"img"])
