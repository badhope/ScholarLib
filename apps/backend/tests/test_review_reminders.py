"""Review reminder + scheduler tests.

Covers: age computation, idempotent reminder windows, in-app notification
creation, audit trail, and the admin manual-trigger endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import auth_headers
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications.models import Notification
from app.domain.review.models import ReviewAssignment
from app.domain.submission.review_reminders import (
    REMIND_AFTER_DAYS,
    REVIEW_DUE_DAYS,
    decision_label,
    run_overdue_reminders,
)
from app.models import AuditLog, Tenant


def test_decision_labels_cover_both_vocabularies() -> None:
    assert decision_label("accept") == "录用"
    assert decision_label("approved") == "录用"
    assert decision_label("major_revision") == "大修"
    assert decision_label("rejected") == "拒稿"
    assert decision_label("unknown-value") == "unknown-value"


async def _tenant_id(db: AsyncSession):
    return (await db.execute(select(Tenant.id).where(Tenant.slug == "default"))).scalar_one()


async def _seed_assignment(
    db: AsyncSession,
    *,
    tenant_id,
    submission_id: int,
    reviewer_id: int,
    assigner_id: int,
    status: str,
    age_days: int,
    last_reminded_days_ago: int | None = None,
) -> ReviewAssignment:
    anchor = datetime.now(UTC) - timedelta(days=age_days)
    assignment = ReviewAssignment(
        tenant_id=tenant_id,
        submission_id=submission_id,
        reviewer_id=reviewer_id,
        assigned_by=assigner_id,
        status=status,
        invited_at=anchor,
        responded_at=anchor if status == "accepted" else None,
        last_reminded_at=(
            datetime.now(UTC) - timedelta(days=last_reminded_days_ago)
            if last_reminded_days_ago is not None
            else None
        ),
        reminder_count=0,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def _create_submission(client: AsyncClient, token: str, title: str) -> int:
    r = await client.post(
        "/api/submissions",
        json={
            "title": title,
            "type": "paper",
            "authors": ["催办测试作者"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "用于验证催办逻辑的测试稿件。",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    return r.json()["id"]


async def test_reminder_skips_fresh_assignment(
    client: AsyncClient, db_session: AsyncSession, test_user: dict, admin_user: dict
) -> None:
    sid = await _create_submission(client, test_user["token"], "Fresh Assignment")
    tenant = await _tenant_id(db_session)
    assignment = await _seed_assignment(
        db_session,
        tenant_id=tenant,
        submission_id=sid,
        reviewer_id=test_user["user_id"],
        assigner_id=admin_user["user_id"],
        status="pending",
        age_days=0,
    )
    stats = await run_overdue_reminders(db_session, tenant_id=tenant)
    # 新任务不该被催
    refreshed = await db_session.get(ReviewAssignment, assignment.id)
    assert refreshed is not None
    assert refreshed.reminder_count == 0
    assert stats["checked"] >= 0


async def test_reminder_fires_after_threshold_and_is_idempotent(
    client: AsyncClient, db_session: AsyncSession, test_user: dict, admin_user: dict
) -> None:
    tenant = await _tenant_id(db_session)
    sid = await _create_submission(client, test_user["token"], "Stale Assignment")
    assignment = await _seed_assignment(
        db_session,
        tenant_id=tenant,
        submission_id=sid,
        reviewer_id=test_user["user_id"],
        assigner_id=admin_user["user_id"],
        status="pending",
        age_days=REMIND_AFTER_DAYS + 2,
    )

    stats = await run_overdue_reminders(db_session, tenant_id=tenant)
    assert stats["reminded"] >= 1

    refreshed = await db_session.get(ReviewAssignment, assignment.id)
    assert refreshed is not None
    assert refreshed.reminder_count == 1
    assert refreshed.last_reminded_at is not None

    # 站内通知已产生
    notes = (
        (
            await db_session.execute(
                select(Notification).where(
                    Notification.user_id == test_user["user_id"],
                    Notification.type == "review.reminder",
                )
            )
        )
        .scalars()
        .all()
    )
    assert notes, "expected an in-app reminder notification"

    # 审计留痕
    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "review.reminder_sent")
            )
        )
        .scalars()
        .all()
    )
    assert audits

    # 同一窗口内再跑：不应重复催
    stats2 = await run_overdue_reminders(db_session, tenant_id=tenant)
    refreshed2 = await db_session.get(ReviewAssignment, assignment.id)
    assert refreshed2 is not None
    assert refreshed2.reminder_count == 1
    assert stats2["reminded"] == 0


async def test_reminder_refires_after_window(
    client: AsyncClient, db_session: AsyncSession, test_user: dict, admin_user: dict
) -> None:
    tenant = await _tenant_id(db_session)
    sid = await _create_submission(client, test_user["token"], "Window Assignment")
    assignment = await _seed_assignment(
        db_session,
        tenant_id=tenant,
        submission_id=sid,
        reviewer_id=test_user["user_id"],
        assigner_id=admin_user["user_id"],
        status="pending",
        age_days=REMIND_AFTER_DAYS + 10,
        last_reminded_days_ago=5,  # 超过 3 天窗口
    )
    await run_overdue_reminders(db_session, tenant_id=tenant)
    refreshed = await db_session.get(ReviewAssignment, assignment.id)
    assert refreshed is not None
    assert refreshed.reminder_count == 1


async def test_accepted_assignment_uses_review_due_window(
    client: AsyncClient, db_session: AsyncSession, test_user: dict, admin_user: dict
) -> None:
    tenant = await _tenant_id(db_session)
    sid = await _create_submission(client, test_user["token"], "Accepted Long Ago")
    assignment = await _seed_assignment(
        db_session,
        tenant_id=tenant,
        submission_id=sid,
        reviewer_id=test_user["user_id"],
        assigner_id=admin_user["user_id"],
        status="accepted",
        age_days=REVIEW_DUE_DAYS + 3,
    )
    await run_overdue_reminders(db_session, tenant_id=tenant)
    refreshed = await db_session.get(ReviewAssignment, assignment.id)
    assert refreshed is not None
    assert refreshed.reminder_count == 1


async def test_admin_can_trigger_reminders(client: AsyncClient, admin_user: dict) -> None:
    r = await client.post(
        "/api/admin/maintenance/review-reminders", headers=auth_headers(admin_user)
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"checked", "reminded", "emailed"}


async def test_admin_email_status_endpoint(client: AsyncClient, admin_user: dict) -> None:
    r = await client.get("/api/admin/maintenance/email-status", headers=auth_headers(admin_user))
    assert r.status_code == 200
    body = r.json()
    assert "configured" in body and "reachable" in body


async def test_non_admin_cannot_trigger_reminders(client: AsyncClient, test_user: dict) -> None:
    r = await client.post(
        "/api/admin/maintenance/review-reminders", headers=auth_headers(test_user)
    )
    assert r.status_code == 403


@pytest.mark.parametrize("status_value", ["accepted", "pending"])
def test_reminder_thresholds_are_sane(status_value: str) -> None:
    assert REMIND_AFTER_DAYS >= 1
    assert REVIEW_DUE_DAYS >= REMIND_AFTER_DAYS
