"""Review reminders and workflow email notifications.

Two responsibilities:

1. ``send_assignment_email`` / ``send_decision_email`` — best-effort email
   side-channels for events that already produce in-app notifications. Every
   call is wrapped so a broken/unconfigured SMTP never breaks the business
   transaction (the in-app notification is the source of truth).

2. ``run_overdue_reminders`` — periodic sweep: assignments that are still
   ``pending`` (invited but not accepted) or ``accepted`` but not completed
   past the reminder window get an in-app notification (and email when
   configured). Idempotent per assignment per window via
   ``last_reminded_at``, and always writes an audit row so editors can see
   what the system chased.

Both are safe to call with the console email backend: they log and move on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import get_email_sender, smtp_configured
from app.core.email_templates import decision_notice, review_assigned, review_reminder
from app.core.logging import get_logger
from app.domain.notifications import services as notifications
from app.domain.review.models import ReviewAssignment
from app.domain.submission.models import Submission
from app.models import AuditLog, User

logger = get_logger("rubbish.review_reminders")

# 指派后多久未接受 → 第一次催办；之后每隔这么久再催一次。
REMIND_AFTER_DAYS = 3
REMIND_EVERY_DAYS = 3
# 已接受但超过这个天数仍未提交 → 催办。
REVIEW_DUE_DAYS = 14

_DECISION_LABELS = {
    "accept": "录用",
    "accepted": "录用",
    "approved": "录用",
    "minor_revision": "小修",
    "major_revision": "大修",
    "reject": "拒稿",
    "rejected": "拒稿",
}


def decision_label(value: str) -> str:
    return _DECISION_LABELS.get(value, value)


async def send_assignment_email(
    reviewer: User, *, submission_title: str, assignment_id: int
) -> None:
    """Best-effort 'you have a paper to review' email."""
    if not smtp_configured():
        return
    base = settings.frontend_base_url.rstrip("/")
    link = f"{base}/review/assignments"
    subject, text, html = review_assigned(
        reviewer.username, submission_title, link, REVIEW_DUE_DAYS
    )
    try:
        await get_email_sender().send(to=reviewer.email, subject=subject, body=text, html=html)
    except Exception:
        logger.warning("review_assignment_email_failed", reviewer_id=reviewer.id, exc_info=True)


async def send_decision_email(
    author: User, *, submission_title: str, decision: str, note: str | None
) -> None:
    """Best-effort decision email to the author.

    录用/接收（accept / approved）走**恭喜邮件专用通道**（主编单独授权，
    不受外发总闸约束）；其余决定仍受总闸管控（总闸关闭时只写日志）。
    """
    if not smtp_configured():
        # smtp_configured 受总闸约束；恭喜通道绕过它，单独判断 SMTP 配置
        from app.core.email import configured_accounts

        if decision not in ("accept", "approved") or not configured_accounts():
            return
    base = settings.frontend_base_url.rstrip("/")
    is_accept = decision in ("accept", "approved")
    subject, text, html = decision_notice(
        author.username,
        submission_title,
        decision_label(decision),
        note,
        f"{base}/submissions",
    )
    if is_accept:
        # 主编口径：录用即恭喜，主题突出祝贺
        subject = f"🎉 恭喜！您的稿件《{submission_title[:60]}》已被 Rubbish 录用并发布"
        try:
            from app.core.email import get_congrat_sender

            await get_congrat_sender().send(to=author.email, subject=subject, body=text, html=html)
            logger.info("congrat_email_sent", author_id=author.id, decision=decision)
            return
        except Exception:
            logger.warning("congrat_email_failed", author_id=author.id, exc_info=True)
            return
    try:
        await get_email_sender().send(to=author.email, subject=subject, body=text, html=html)
    except Exception:
        logger.warning("decision_email_failed", author_id=author.id, exc_info=True)


async def run_overdue_reminders(db: AsyncSession, *, tenant_id: Any) -> dict[str, int]:
    """Sweep stale assignments and nudge reviewers.

    Returns a small stats dict for logging/monitoring. Idempotent: an
    assignment is reminded at most once per ``REMIND_EVERY_DAYS`` window.
    """
    now = datetime.now(UTC)
    stats = {"checked": 0, "reminded": 0, "emailed": 0}

    rows = list(
        (
            await db.execute(
                select(ReviewAssignment, Submission, User)
                .join(Submission, Submission.id == ReviewAssignment.submission_id)
                .join(User, User.id == ReviewAssignment.reviewer_id)
                .where(
                    ReviewAssignment.tenant_id == tenant_id,
                    ReviewAssignment.status.in_(("pending", "accepted")),
                )
            )
        ).all()
    )
    stats["checked"] = len(rows)

    for assignment, submission, reviewer in rows:
        age_days = _age_days(assignment, now)
        threshold = REMIND_AFTER_DAYS if assignment.status == "pending" else 0
        if assignment.status == "accepted":
            threshold = REVIEW_DUE_DAYS
        if age_days < threshold:
            continue
        last = assignment.last_reminded_at
        if last is not None:
            last_aware = last if last.tzinfo else last.replace(tzinfo=UTC)
            if (now - last_aware).days < REMIND_EVERY_DAYS:
                continue

        days_pending = age_days
        stage = "接受邀请" if assignment.status == "pending" else "提交评审意见"
        await notifications.create(
            db,
            tenant_id=tenant_id,
            user_id=reviewer.id,
            type_="review.reminder",
            title=f"审稿提醒：{submission.title}",
            body=f"该任务已等待 {days_pending} 天，请尽快{stage}。",
            related_type="review_assignment",
            related_id=str(assignment.id),
        )
        assignment.last_reminded_at = now
        reminder_count = (assignment.reminder_count or 0) + 1
        assignment.reminder_count = reminder_count

        if smtp_configured():
            base = settings.frontend_base_url.rstrip("/")
            subject, text, html = review_reminder(
                reviewer.username,
                submission.title,
                f"{base}/review/assignments",
                days_pending,
            )
            try:
                await get_email_sender().send(
                    to=reviewer.email, subject=subject, body=text, html=html
                )
                stats["emailed"] += 1
            except Exception:
                logger.warning("review_reminder_email_failed", assignment_id=assignment.id)

        db.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=None,
                action="review.reminder_sent",
                target_type="review_assignment",
                target_id=str(assignment.id),
                payload={
                    "days_pending": days_pending,
                    "reminder_count": reminder_count,
                    "stage": assignment.status,
                },
            )
        )
        stats["reminded"] += 1

    await db.commit()
    return stats


def _age_days(assignment: ReviewAssignment, now: datetime) -> int:
    """Days since the relevant clock started (invite or acceptance)."""
    anchor = assignment.invited_at
    if assignment.status == "accepted" and assignment.responded_at is not None:
        anchor = assignment.responded_at
    if anchor is None:
        return 0
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    return max(0, (now - anchor).days)


__all__ = [
    "REMIND_AFTER_DAYS",
    "REMIND_EVERY_DAYS",
    "REVIEW_DUE_DAYS",
    "decision_label",
    "run_overdue_reminders",
    "send_assignment_email",
    "send_decision_email",
]


def _unused_timedelta_marker() -> timedelta:  # pragma: no cover - keeps import honest
    return timedelta(days=1)
