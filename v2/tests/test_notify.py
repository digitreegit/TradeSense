import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import notify


def test_send_returns_false_when_credentials_missing():
    with patch.object(notify.settings, "telegram_bot_token", ""):
        assert notify.send("hello") is False


def test_send_returns_true_when_telegram_accepts():
    resp = MagicMock()
    resp.json.return_value = {"ok": True}
    with patch.object(notify.settings, "telegram_bot_token", "tok"), \
         patch.object(notify.settings, "telegram_chat_id", "123"), \
         patch("app.notify.httpx.post", return_value=resp) as post:
        assert notify.send("hello") is True
        assert post.call_args.kwargs["json"]["text"] == "hello"
        assert "parse_mode" not in post.call_args.kwargs["json"]


def test_send_returns_false_when_telegram_rejects():
    resp = MagicMock()
    resp.text = "bad"
    resp.json.return_value = {"ok": False, "description": "Bad Request: can't parse entities"}
    with patch.object(notify.settings, "telegram_bot_token", "tok"), \
         patch.object(notify.settings, "telegram_chat_id", "123"), \
         patch("app.notify.httpx.post", return_value=resp):
        assert notify.send("bad <html>") is False
