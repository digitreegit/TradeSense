import html
import logging
import re
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Strip pictograph-style icons from Telegram copy (alerts use emoji in titles elsewhere).
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001FAFF"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "]+",
    flags=re.UNICODE,
)


def _strip_telegram_icons(text: str) -> str:
    if not text:
        return text
    cleaned = _EMOJI_RE.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _markdown_bold_to_telegram_html(text: str) -> str:
    """Turn ``**segments**`` into <b>; escape the rest for Telegram HTML parse_mode."""
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    out: list[str] = []
    for part in parts:
        if part.startswith("**") and part.endswith("**") and len(part) >= 4:
            inner = html.escape(part[2:-2], quote=True)
            out.append(f"<b>{inner}</b>")
        else:
            out.append(html.escape(part, quote=True))
    return "".join(out)


def _telegram_html_body(title: str, message: str, level: str, *, max_len: int = 4096) -> str:
    title_t = _strip_telegram_icons(title)
    message_t = _strip_telegram_icons(message)
    raw = f"[{level}] {title_t}\n\n{message_t}"
    html_body = _markdown_bold_to_telegram_html(raw)
    if len(html_body) > max_len:
        html_body = html_body[: max_len - 4] + "…"
    return html_body


def _load_user_notify_row(user_id: int) -> Optional[dict[str, Any]]:
    from app.db import users_db

    row = users_db.get_user_by_id(user_id)
    if not row:
        return None
    return row


class NotificationService:
    def __init__(self):
        self.resend_api_key = settings.resend_api_key
        self.resend_from_email = settings.resend_from_email

    def send_alert(
        self,
        title: str,
        message: str,
        level: str = "INFO",
        to_email: Optional[str] = None,
        user_id: Optional[int] = None,
    ):
        """Send alert: log + optional Resend + Telegram + WhatsApp."""
        full_msg = f"[{level}] {title}\n\n{message}"

        logger.info(f"🔔 ALERT: {title} - {message}")

        recipient = (to_email or "").strip() or settings.receiver_email
        if self.resend_api_key and self.resend_from_email and recipient:
            self._send_resend_email(
                subject=f"TradeSense Alert: {title}",
                text=full_msg,
                to_email=recipient,
            )

        self._send_telegram_alert(title, message, level, user_id=user_id)
        self._send_whatsapp_alert(title, message, level, user_id=user_id)

    def send_daily_summary(
        self,
        *,
        to_email: str,
        trading_date: str,
        daily_pnl: float,
        daily_pnl_pct: float,
        equity: float,
        portfolio_value: float,
        cash: float,
        trades: int,
        win_rate_pct: float,
        user_id: Optional[int] = None,
    ) -> None:
        subject = f"TradeSense Daily Summary — {trading_date}"
        text = (
            f"Date: {trading_date}\n"
            f"Daily P&L: ${daily_pnl:+,.2f} ({daily_pnl_pct:+.2f}%)\n"
            f"Portfolio Value: ${portfolio_value:,.2f}\n"
            f"Equity: ${equity:,.2f}\n"
            f"Cash Available: ${cash:,.2f}\n"
            f"Total Trades: {trades}\n"
            f"Win Rate: {win_rate_pct:.1f}%\n"
        )
        if to_email:
            self._send_resend_email(subject=subject, text=text, to_email=to_email)
        body = text.strip()
        self._send_telegram_alert(subject, body, "INFO", user_id=user_id)
        self._send_whatsapp_alert(subject, body, "INFO", user_id=user_id)

    def _send_resend_email(self, *, subject: str, text: str, to_email: str) -> None:
        if not self.resend_api_key or not self.resend_from_email:
            logger.info("Resend not configured; skip email send.")
            return
        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self.resend_from_email,
                    "to": [to_email],
                    "subject": subject,
                    "text": text,
                },
                timeout=15.0,
            )
            if response.status_code >= 400:
                logger.error("Email alert failed: %s %s", response.status_code, response.text)
                return
            logger.info("📧 Email sent successfully via Resend.")
        except Exception as exc:  # noqa: BLE001
            logger.error("Email alert failed: %s", exc)

    def _send_telegram_alert(
        self,
        title: str,
        message: str,
        level: str,
        *,
        user_id: Optional[int],
    ) -> None:
        token = (settings.telegram_bot_token or "").strip()
        if not token:
            return

        chat_id = ""
        if user_id is not None:
            row = _load_user_notify_row(user_id)
            if not row:
                return
            if not bool(int(row.get("notify_telegram") or 0)):
                return
            chat_id = (row.get("telegram_chat_id") or "").strip()
        else:
            chat_id = (settings.telegram_default_chat_id or "").strip()

        if not chat_id:
            return

        body = _telegram_html_body(title, message, level)

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            r = httpx.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": body,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15.0,
            )
            if r.status_code >= 400:
                logger.error("Telegram send failed: %s %s", r.status_code, r.text)
                return
            data = r.json()
            if not data.get("ok"):
                logger.error("Telegram API error: %s", data)
                return
            logger.info("📱 Telegram alert sent.")
        except Exception as exc:  # noqa: BLE001
            logger.error("Telegram send failed: %s", exc)

    # ─── WhatsApp via Twilio ────────────────────────────────────
    @staticmethod
    def _whatsapp_text(title: str, message: str, level: str, *, max_len: int = 1500) -> str:
        title_t = _strip_telegram_icons(title)
        message_t = _strip_telegram_icons(message)
        body = f"[{level}] {title_t}\n\n{message_t}"
        if len(body) > max_len:
            body = body[: max_len - 1] + "…"
        return body

    @staticmethod
    def _whatsapp_to(addr: str) -> str:
        s = (addr or "").strip()
        if not s:
            return ""
        return s if s.lower().startswith("whatsapp:") else f"whatsapp:{s}"

    def _twilio_post_message(self, *, body: str, to: str) -> tuple[bool, str]:
        """POST one Twilio Messages API call. Returns (ok, error_text)."""
        sid = (settings.twilio_account_sid or "").strip()
        token = (settings.twilio_auth_token or "").strip()
        sender = self._whatsapp_to(settings.twilio_whatsapp_from or "")
        if not sid or not token or not sender:
            return False, (
                "Server has no TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / "
                "TWILIO_WHATSAPP_FROM. Add them to .env (e.g. "
                "TWILIO_WHATSAPP_FROM=whatsapp:+14155238886) and restart."
            )
        recipient = self._whatsapp_to(to)
        if not recipient:
            return False, "Missing WhatsApp recipient (E.164, e.g. +15551234567)."
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        try:
            r = httpx.post(
                url,
                data={"From": sender, "To": recipient, "Body": body},
                auth=(sid, token),
                timeout=15.0,
            )
            if r.status_code >= 400:
                logger.error("WhatsApp send failed: %s %s", r.status_code, r.text)
                try:
                    j = r.json()
                    return False, str(j.get("message") or r.text)
                except Exception:  # noqa: BLE001
                    return False, r.text
            return True, ""
        except Exception as exc:  # noqa: BLE001
            logger.error("WhatsApp send failed: %s", exc)
            return False, f"Network error calling Twilio: {exc}"

    def _send_whatsapp_alert(
        self,
        title: str,
        message: str,
        level: str,
        *,
        user_id: Optional[int],
    ) -> None:
        if user_id is None:
            return  # WhatsApp opt-in is per-user; no anonymous fan-out
        row = _load_user_notify_row(user_id)
        if not row:
            return
        if not bool(int(row.get("notify_whatsapp") or 0)):
            return
        e164 = (row.get("whatsapp_e164") or "").strip()
        if not e164:
            return
        body = self._whatsapp_text(title, message, level)
        ok, err = self._twilio_post_message(body=body, to=e164)
        if ok:
            logger.info("📱 WhatsApp alert sent.")
        elif err:
            logger.error("WhatsApp send failed: %s", err)

    def try_send_whatsapp_test(self, user_id: int) -> dict:
        """Send a one-off WhatsApp test; returns ``{ok, message?}`` or ``{ok: False, error}``."""
        row = _load_user_notify_row(user_id)
        if not row:
            return {"ok": False, "error": "User not found."}
        if not bool(int(row.get("notify_whatsapp") or 0)):
            return {
                "ok": False,
                "error": "Turn on “Send alerts to WhatsApp”, enter your WhatsApp number, then click Save before Send test.",
            }
        e164 = (row.get("whatsapp_e164") or "").strip()
        if not e164:
            return {"ok": False, "error": "Enter your WhatsApp number in E.164 (e.g. +15551234567) and click Save."}
        body = self._whatsapp_text(
            "TradeSense test",
            "If you see this, WhatsApp alerts are configured correctly.",
            "INFO",
        )
        ok, err = self._twilio_post_message(body=body, to=e164)
        if ok:
            return {"ok": True, "message": "Message delivered to WhatsApp."}
        return {"ok": False, "error": err or "WhatsApp send failed."}

    def try_send_telegram_test(self, user_id: int) -> dict:
        """Send a one-off test message; return {ok, message?} or {ok: False, error}."""
        token = (settings.telegram_bot_token or "").strip()
        if not token:
            return {
                "ok": False,
                "error": (
                    "Server has no TELEGRAM_BOT_TOKEN. Put it in backend/.env (or repo root .env), "
                    "then restart uvicorn so the process reloads environment variables."
                ),
            }

        row = _load_user_notify_row(user_id)
        if not row:
            return {"ok": False, "error": "User not found."}

        if not bool(int(row.get("notify_telegram") or 0)):
            return {
                "ok": False,
                "error": "Turn on “Send alerts to Telegram”, enter your chat ID, then click Save before Send test.",
            }

        chat_id = (row.get("telegram_chat_id") or "").strip()
        if not chat_id:
            return {
                "ok": False,
                "error": "Enter your Telegram chat ID and click Save first.",
            }

        title = "TradeSense test"
        message = "If you see this, Telegram alerts are configured correctly."
        body = _telegram_html_body(title, message, "INFO")

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            r = httpx.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": body,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15.0,
            )
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        except Exception as exc:  # noqa: BLE001
            logger.error("Telegram test failed: %s", exc)
            return {"ok": False, "error": f"Network error calling Telegram: {exc}"}

        if not data.get("ok"):
            desc = data.get("description") or data.get("error_code") or r.text or "unknown error"
            hint = ""
            low = str(desc).lower()
            if "chat not found" in low or "chat_id" in low:
                hint = " Check the chat ID (digits only for private chats). Open @userinfobot in Telegram to copy your id."
            elif "forbidden" in low or "blocked" in low:
                hint = " Open your bot in Telegram and tap Start (/start) so it can message you."
            logger.error("Telegram test API error: %s", data)
            return {"ok": False, "error": f"Telegram: {desc}.{hint}"}

        logger.info("📱 Telegram test message sent to chat_id=%s", chat_id)
        return {"ok": True, "message": "Message delivered to Telegram."}


notification_service = NotificationService()
