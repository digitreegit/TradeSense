"""WhatsApp helper formatting + Twilio config gating (no network)."""
from __future__ import annotations

from unittest.mock import patch

from app.core.config import settings
from app.services.notification_service import NotificationService


def test_whatsapp_to_normalizes_e164():
    assert NotificationService._whatsapp_to("+15551234567") == "whatsapp:+15551234567"
    assert (
        NotificationService._whatsapp_to("whatsapp:+15551234567")
        == "whatsapp:+15551234567"
    )
    assert NotificationService._whatsapp_to("") == ""


def test_whatsapp_text_truncates():
    body = NotificationService._whatsapp_text("title", "x" * 5000, "INFO")
    assert len(body) <= 1500
    assert body.startswith("[INFO] title")


def test_twilio_post_message_short_circuits_without_keys():
    svc = NotificationService()
    with (
        patch.object(settings, "twilio_account_sid", ""),
        patch.object(settings, "twilio_auth_token", ""),
        patch.object(settings, "twilio_whatsapp_from", ""),
    ):
        ok, err = svc._twilio_post_message(body="hi", to="+15551234567")
    assert ok is False
    assert "TWILIO_ACCOUNT_SID" in err


def test_twilio_post_message_rejects_missing_recipient():
    svc = NotificationService()
    with (
        patch.object(settings, "twilio_account_sid", "ACxxx"),
        patch.object(settings, "twilio_auth_token", "secret"),
        patch.object(settings, "twilio_whatsapp_from", "whatsapp:+14155238886"),
    ):
        ok, err = svc._twilio_post_message(body="hi", to="")
    assert ok is False
    assert "recipient" in err.lower()
