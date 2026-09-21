"""
Notification dispatch — the Power Automate notification flows' replacement.

Every dispatch attempt is written to NotificationLog regardless of outcome,
so "I was never told" is always answerable (NFR-12). If SMTP is not
configured (the zero-config default), messages are logged as
SKIPPED_NO_SMTP rather than silently dropped, and are still visible in the
admin Notification Log screen.
"""
import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import NotificationChannel, NotificationStatus
from app.models.misc import NotificationLog

logger = logging.getLogger("efdp.notifications")


async def send(
    db: AsyncSession,
    *,
    recipient_email: str,
    subject: str,
    body: str,
    template_key: str,
) -> None:
    status = NotificationStatus.SKIPPED_NO_SMTP
    if settings.SMTP_HOST:
        try:
            msg = EmailMessage()
            msg["From"] = settings.SMTP_FROM
            msg["To"] = recipient_email
            msg["Subject"] = subject
            msg.set_content(body)
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
                server.starttls()
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            status = NotificationStatus.SENT
        except Exception as exc:  # noqa: BLE001 — never let notification failure break the transaction
            logger.warning("Notification dispatch failed for %s: %s", recipient_email, exc)
            status = NotificationStatus.FAILED
    else:
        logger.info("[notify:no-smtp] to=%s subject=%s", recipient_email, subject)

    db.add(
        NotificationLog(
            recipient_email=recipient_email,
            channel=NotificationChannel.EMAIL,
            template_key=template_key,
            subject=subject,
            body=body,
            status=status,
        )
    )
