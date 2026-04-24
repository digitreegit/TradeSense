import logging
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def _telegram_text(title: str, message: str, level: str) -> str:
    return f"[{level}] {title}\n\n{message}"


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
        """Send alert: log + optional Resend + Telegram."""
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

        body = _telegram_text(title, message, level)
        if len(body) > 4000:
            body = body[:3990] + "\n…"

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            r = httpx.post(
                url,
                json={"chat_id": chat_id, "text": body},
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


notification_service = NotificationService()
