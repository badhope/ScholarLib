"""Email side-channel paths of review reminders (SMTP configured / failing)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import FakeEmailSender
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import email as email_module
from app.domain.review.models import ReviewAssignment
from app.domain.submission import review_reminders as rr
from app.domain.submission.review_reminders import (
    REMIND_AFTER_DAYS,
    _age_days,
    run_overdue_reminders,
    send_assignment_email,
    send_decision_email,
)
from app.models import Tenant, User


class _RaisingSender:
    async def send(self, **kwargs: object) -> None:
        raise RuntimeError("smtp down")


@pytest.fixture
def smtp_on(monkeypatch: pytest.MonkeyPatch, fake_email_sender: FakeEmailSender) -> FakeEmailSender:
    monkeypatch.setattr(rr, "smtp_configured", lambda: True)
    return fake_email_sender


@pytest.fixture
def smtp_on_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rr, "smtp_configured", lambda: True)
    monkeypatch.setattr(email_module, "_sender", _RaisingSender())


async def _get_user(db_session: AsyncSession, user_id: int) -> User:
    user = await db_session.get(User, user_id)
    assert user is not None
    return user


@pytest.mark.asyncio
async def test_assignment_email_sent_when_smtp_configured(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: dict,
    smtp_on: FakeEmailSender,
) -> None:
    reviewer = await _get_user(db_session, test_user["user_id"])
    await send_assignment_email(reviewer, submission_title="Assignment Mail Paper", assignment_id=7)
    assert len(smtp_on.outbox) == 1
    assert smtp_on.outbox[0]["to"] == reviewer.email


@pytest.mark.asyncio
async def test_assignment_email_failure_is_swallowed(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: dict,
    smtp_on_raising: None,
) -> None:
    reviewer = await _get_user(db_session, test_user["user_id"])
    await send_assignment_email(reviewer, submission_title="Assignment Mail Paper", assignment_id=7)


@pytest.mark.asyncio
async def test_decision_email_sent_when_smtp_configured(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: dict,
    smtp_on: FakeEmailSender,
) -> None:
    author = await _get_user(db_session, test_user["user_id"])
    await send_decision_email(
        author, submission_title="Decision Mail Paper", decision="major_revision", note="revise"
    )
    assert len(smtp_on.outbox) == 1
    assert "大修" in smtp_on.outbox[0]["body"] or "大修" in (smtp_on.outbox[0]["html"] or "")


@pytest.mark.asyncio
async def test_decision_email_failure_is_swallowed(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: dict,
    smtp_on_raising: None,
) -> None:
    author = await _get_user(db_session, test_user["user_id"])
    await send_decision_email(
        author, submission_title="Decision Mail Paper", decision="reject", note=None
    )


async def _seed_stale_assignment(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: dict,
    admin_user: dict,
) -> None:
    tenant = (
        await db_session.execute(select(Tenant.id).where(Tenant.slug == "default"))
    ).scalar_one()
    r = await client.post(
        "/api/submissions",
        json={
            "title": "Reminder Email Paper",
            "type": "paper",
            "authors": ["催办邮件作者"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "用于验证催办邮件链路。",
        },
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert r.status_code == 201
    anchor = datetime.now(UTC) - timedelta(days=REMIND_AFTER_DAYS + 2)
    db_session.add(
        ReviewAssignment(
            tenant_id=tenant,
            submission_id=r.json()["id"],
            reviewer_id=test_user["user_id"],
            assigned_by=admin_user["user_id"],
            status="pending",
            invited_at=anchor,
            reminder_count=0,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_reminder_sweep_sends_email_when_configured(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: dict,
    admin_user: dict,
    smtp_on: FakeEmailSender,
) -> None:
    await _seed_stale_assignment(client, db_session, test_user, admin_user)
    tenant = (
        await db_session.execute(select(Tenant.id).where(Tenant.slug == "default"))
    ).scalar_one()
    stats = await run_overdue_reminders(db_session, tenant_id=tenant)
    assert stats["reminded"] >= 1
    assert stats["emailed"] >= 1
    assert smtp_on.outbox


@pytest.mark.asyncio
async def test_reminder_sweep_email_failure_still_reminds(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: dict,
    admin_user: dict,
    smtp_on_raising: None,
) -> None:
    await _seed_stale_assignment(client, db_session, test_user, admin_user)
    tenant = (
        await db_session.execute(select(Tenant.id).where(Tenant.slug == "default"))
    ).scalar_one()
    stats = await run_overdue_reminders(db_session, tenant_id=tenant)
    assert stats["reminded"] >= 1
    assert stats["emailed"] == 0


def test_age_days_zero_when_no_anchor() -> None:
    assignment = ReviewAssignment(status="pending", invited_at=None)
    assert _age_days(assignment, datetime.now(UTC)) == 0
