"""Internal service helpers for the notifications module.

Two responsibilities:

1. ``create()`` — insert an in-app ``Notification`` row in the same
   transaction as the caller's business write. Thin and synchronous
   with the caller's ``commit()``.

2. ``record_email_digest()`` — the email side-channel audit trail.
   Every review-workflow event that *would* email a user (assignment /
   reminder / decision / claim result) writes an
   ``email_digest_records`` row. When SMTP is configured and the
   switch is on it actually sends; otherwise it records the honest
   skip reason. It never raises into the business flow — the in-app
   notification is the source of truth, email is best-effort.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.notifications.models import EmailDigestRecord, Notification

if TYPE_CHECKING:
    from uuid import UUID

logger = get_logger("rubbish.notifications")


async def create(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: int,
    type_: str,
    title: str,
    body: str | None = None,
    related_type: str | None = None,
    related_id: str | None = None,
) -> Notification:
    """Insert a notification row and flush so the caller's transaction owns it.

    The caller is responsible for ``commit()`` — this helper only adds
    and flushes, so the notification rides on the caller's transaction
    (rollback cancels both the business write and the notification).
    """
    notification = Notification(
        tenant_id=tenant_id,
        user_id=user_id,
        type=type_,
        title=title,
        body=body,
        related_type=related_type,
        related_id=related_id,
    )
    db.add(notification)
    await db.flush()
    return notification


async def record_email_digest(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: int,
    event_type: str,
    recipient_email: str,
    subject: str,
    text: str,
    html: str | None = None,
    related_type: str | None = None,
    related_id: str | None = None,
) -> str:
    """Write one email-digest record and best-effort send when configured.

    Returns the final ``status`` so callers/tests can assert the real
    outcome. Never raises: a broken mail transport must not roll back
    the business transaction (the in-app notification already happened).
    """
    record = EmailDigestRecord(
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        recipient_email=recipient_email,
        subject=subject[:255],
        body=text,
        status="skipped_no_smtp",
        related_type=related_type,
        related_id=related_id,
    )
    db.add(record)
    await db.flush()

    # 开关关闭：记录为 skipped_disabled，不尝试发送。
    if not settings.email_review_digest_enabled:
        record.status = "skipped_disabled"
        await db.flush()
        return record.status

    from app.core.email import get_email_sender, smtp_configured

    if not smtp_configured():
        # 未配置 SMTP：保持 skipped_no_smtp，落库但不假装已发。
        return record.status

    try:
        await get_email_sender().send(
            to=recipient_email, subject=subject, body=text, html=html
        )
        record.status = "sent"
    except Exception:  # noqa: BLE001 — email is best-effort by contract
        logger.warning(
            "email_digest_send_failed",
            user_id=user_id,
            event_type=event_type,
            recipient=recipient_email,
            exc_info=True,
        )
        record.status = "failed"
    await db.flush()
    return record.status


__all__ = ["create", "record_email_digest"]
