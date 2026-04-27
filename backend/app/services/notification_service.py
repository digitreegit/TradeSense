import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

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
    ):
        """Send alert (log + optional Resend email)."""
        full_msg = f"[{level}] {title}\n\n{message}"
        
        # 1. Always log
        logger.info(f"🔔 ALERT: {title} - {message}")
        
        # 2. Email when Resend is configured
        recipient = (to_email or "").strip() or settings.receiver_email
        if self.resend_api_key and self.resend_from_email and recipient:
            self._send_resend_email(
                subject=f"TradeSense Alert: {title}",
                text=full_msg,
                to_email=recipient,
            )

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
    ) -> None:
        """Send end-of-day summary via Resend."""
        if not to_email:
            return
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
        self._send_resend_email(subject=subject, text=text, to_email=to_email)

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

# Singleton
notification_service = NotificationService()
