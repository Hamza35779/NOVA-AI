"""SMTP email sender — wraps smtplib for sending replies and new emails.

Supports Gmail (SSL port 465), standard SMTP/TLS (port 587),
and generic IMAP/SMTP servers.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)


class SmtpSender:
    """Thin wrapper around smtplib supporting SSL (port 465) and STARTTLS (port 587)."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl

    def send(
        self,
        to: str | list[str],
        subject: str,
        body: str,
        reply_to_message_id: Optional[str] = None,
        html_body: Optional[str] = None,
    ) -> bool:
        """Send an email. Returns True on success."""
        recipients = [to] if isinstance(to, str) else to

        msg = MIMEMultipart("alternative")
        msg["From"] = self.username
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        if reply_to_message_id:
            msg["In-Reply-To"] = reply_to_message_id
            msg["References"] = reply_to_message_id

        msg.attach(MIMEText(body, "plain"))
        if html_body:
            msg.attach(MIMEText(html_body, "html"))

        try:
            if self.use_ssl or self.port == 465:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.host, self.port, context=context) as smtp:
                    smtp.login(self.username, self.password)
                    smtp.sendmail(self.username, recipients, msg.as_string())
            else:
                with smtplib.SMTP(self.host, self.port) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.login(self.username, self.password)
                    smtp.sendmail(self.username, recipients, msg.as_string())
            logger.info("Email sent to %s: %s", recipients, subject)
            return True
        except Exception as exc:
            logger.error("SMTP send failed: %s", exc)
            raise
