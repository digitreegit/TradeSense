import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self):
        # Load optional SMTP settings from .env (alerts still log if unset).
        self.smtp_server   = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port     = int(os.getenv("SMTP_PORT", "587"))
        self.sender_email  = os.getenv("SENDER_EMAIL", "")
        self.sender_pwd    = os.getenv("SENDER_PASSWORD", "")
        self.receiver_email = os.getenv("RECEIVER_EMAIL", "")

    def send_alert(self, title: str, message: str, level: str = "INFO"):
        """Send alert (log + optional email)."""
        full_msg = f"[{level}] {title}\n\n{message}"
        
        # 1. Always log
        logger.info(f"🔔 ALERT: {title} - {message}")
        
        # 2. Email when SMTP is configured
        if self.sender_email and self.sender_pwd and self.receiver_email:
            try:
                self._send_email(title, full_msg)
            except Exception as e:
                logger.error(f"Email alert failed: {e}")

    def _send_email(self, subject: str, content: str):
        msg = MIMEMultipart()
        msg['From']    = self.sender_email
        msg['To']      = self.receiver_email
        msg['Subject'] = f"🚀 TradeSense Alert: {subject}"
        
        msg.attach(MIMEText(content, 'plain'))
        
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.sender_email, self.sender_pwd)
            server.send_message(msg)
            logger.info("📧 Email sent successfully.")

# Singleton
notification_service = NotificationService()
