"""Integration tests for the split reviewer/editor workbenches.

Covers:
- Reviewer workbench: only 待审 / 已审 two columns, due countdown, overdue flag.
- Editor workbench: four columns with counts; reviewer cannot reach it (403).
- Batch assign: creates assignments + reviewer in-app notification + email digest row.
- Conflict check: author/co-author/own-submission warnings.
- Manual remind: fires reminder notification + digest row.
- Notifications: type/category filter, unread count, mark-read.
"""

from __future__ import annotations

import pytest
from conftest import auth_headers
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role, Tenant, UserRole
from app.modules.notifications.models import EmailDigestRecord, Notification

_PAYLOAD = {
    "title": "Workbench Split Test",
    "type": "paper",
    "authors": ["Alice Author"],
    "year": 2026,
    "discipline": "computer science",
    "tags": ["test"],
    "abstract": "An abstract for the workbench split test.",
    "preview": "A short preview.",
    "doi": "10.1234/workbench.001",
    "keywords": ["peer review"],
    "jel_codes": ["C00"],
}


async def _create_submission(client: AsyncClient, user: dict, title: str = "Workbench Split Test") -> dict:
    body = {**_PAYLOAD, "title": title, "doi": f"10.1234/wb.{abs(hash(title)) % 100000}"}
    resp = await client.post("/api/submissions", json=body, headers=auth_headers(user))
    resp.raise_for_status()
    return resp.json()


async def _grant_role(db: AsyncSession, tenant: Tenant, user_id: int, role_name: str) -> None:
    role = (
        await db.execute(
            select(Role).where(Role.tenant_id == tenant.id, Role.name == role_name)
        )
    ).scalar_one_or_none()
    if role is None:
        role = Role(tenant_id=tenant.id, name=role_name, description=f"test {role_name}")
        db.add(role)
        await db.flush()
    existing = (
        await db.execute(
            select(UserRole).where(
                UserRole.tenant_id == tenant.id,
                UserRole.user_id == user_id,
                UserRole.role_id == role.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(UserRole(tenant_id=tenant.id, user_id=user_id, role_id=role.id))
        await db.flush()


async def _register_reviewer(client: AsyncClient, db_session: AsyncSession, tenant: Tenant, suffix: str) -> dict:
    from conftest import register_user

    user = await register_user(
        client,
        email=f"reviewer_{suffix}@example.com",
        username=f"reviewer_{suffix}",
    )
    await _grant_role(db_session, tenant, int(user["user_id"]), "reviewer")
    return user


# ---------------------------------------------------------------------------
# Reviewer workbench
# ---------------------------------------------------------------------------


async def test_reviewer_workbench_two_columns(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """审稿人工作台只有待审/已审两栏，带截止倒计时。"""
    await client.get("/api/health")
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    reviewer = await _register_reviewer(client, db_session, tenant, "wb1")

    sub = await _create_submission(client, test_user, "WB pending item")
    # admin 批量指派给 reviewer
    resp = await client.post(
        "/api/editor/workbench/batch-assign",
        json={
            "items": [{"submission_id": sub["id"], "reviewer_ids": [reviewer["user_id"]]}],
            "due_days": 7,
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()["created"]
    assert len(created) == 1

    # 审稿人工作台：待审=1，已审=0
    wb = await client.get("/api/review/workbench", headers=auth_headers(reviewer))
    assert wb.status_code == 200, wb.text
    body = wb.json()
    assert body["pending"]["count"] == 1
    assert body["completed"]["count"] == 0
    item = body["pending"]["items"][0]
    assert item["title"] == "WB pending item"
    assert item["due_label"] is not None and "剩" in item["due_label"]
    assert item["is_overdue"] is False

    # 审稿人看不到编辑四栏（403）
    forbidden = await client.get("/api/editor/workbench", headers=auth_headers(reviewer))
    assert forbidden.status_code == 403


async def test_reviewer_workbench_completed_column(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """审稿人提交报告后进入已审栏。"""
    await client.get("/api/health")
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    reviewer = await _register_reviewer(client, db_session, tenant, "wb2")

    sub = await _create_submission(client, test_user, "WB completed item")
    batch = await client.post(
        "/api/editor/workbench/batch-assign",
        json={"items": [{"submission_id": sub["id"], "reviewer_ids": [reviewer["user_id"]]}], "due_days": 7},
        headers=auth_headers(admin_user),
    )
    assignment_id = batch.json()["created"][0]["assignment_id"]

    # accept + submit report
    await client.post(f"/api/review/assignments/{assignment_id}/accept", headers=auth_headers(reviewer))
    rep = await client.post(
        f"/api/review/assignments/{assignment_id}/submit",
        json={
            "recommendation": "minor_revision",
            "scores": {"problem": 3, "argument": 3, "method": 3, "evidence": 3, "novelty": 3, "integrity": 5, "presentation": 3},
            "comments_to_author": "ok",
        },
        headers=auth_headers(reviewer),
    )
    assert rep.status_code == 201, rep.text

    wb = await client.get("/api/review/workbench", headers=auth_headers(reviewer))
    body = wb.json()
    assert body["pending"]["count"] == 0
    assert body["completed"]["count"] == 1
    assert body["completed"]["items"][0]["recommendation"] == "minor_revision"


# ---------------------------------------------------------------------------
# Editor workbench
# ---------------------------------------------------------------------------


async def test_editor_workbench_four_columns(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """主编工作台四栏计数：待指派=1（新建稿），其余随流程变化。"""
    await client.get("/api/health")
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    reviewer = await _register_reviewer(client, db_session, tenant, "wb3")

    sub = await _create_submission(client, test_user, "WB editor cols")
    # 尚未指派 → 待指派
    wb = await client.get("/api/editor/workbench", headers=auth_headers(admin_user))
    assert wb.status_code == 200, wb.text
    cols = wb.json()["columns"]
    assert cols["to_assign"]["count"] >= 1
    # 这篇在待指派里
    ids = [i["submission_id"] for i in cols["to_assign"]["items"]]
    assert sub["id"] in ids

    # 指派后 → 进入评审中
    await client.post(
        "/api/editor/workbench/batch-assign",
        json={"items": [{"submission_id": sub["id"], "reviewer_ids": [reviewer["user_id"]]}], "due_days": 7},
        headers=auth_headers(admin_user),
    )
    wb2 = await client.get("/api/editor/workbench", headers=auth_headers(admin_user))
    cols2 = wb2.json()["columns"]
    in_review_ids = [i["submission_id"] for i in cols2["in_review"]["items"]]
    assert sub["id"] in in_review_ids
    # 评审中条目展开 assignment 状态
    row = next(i for i in cols2["in_review"]["items"] if i["submission_id"] == sub["id"])
    assert row["active_count"] == 1
    assert row["assignments"][0]["reviewer_username"] == "reviewer_wb3"


async def test_batch_assign_creates_records_and_notifications(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """一次批量指派产生 assignment 记录 + 审稿人站内通知 + 邮件摘要落库。"""
    await client.get("/api/health")
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    reviewer = await _register_reviewer(client, db_session, tenant, "wb4")

    sub1 = await _create_submission(client, test_user, "WB batch A")
    sub2 = await _create_submission(client, test_user, "WB batch B")

    resp = await client.post(
        "/api/editor/workbench/batch-assign",
        json={
            "items": [
                {"submission_id": sub1["id"], "reviewer_ids": [reviewer["user_id"]]},
                {"submission_id": sub2["id"], "reviewer_ids": [reviewer["user_id"]]},
            ],
            "due_days": 10,
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["created_count"] == 2
    assert len(data["created"]) == 2

    # 审稿人站内通知：review.invited
    notes = await client.get("/api/notifications", headers=auth_headers(reviewer))
    assert notes.status_code == 200
    invited = [n for n in notes.json()["data"] if n["type"] == "review.invited"]
    assert len(invited) == 2

    # 邮件摘要落库（SMTP 未配置 → skipped_no_smtp，不假装已发）
    db_session.expire_all()
    digests = (
        await db_session.execute(
            select(EmailDigestRecord).where(EmailDigestRecord.user_id == reviewer["user_id"])
        )
    ).scalars().all()
    assert len(digests) == 2
    assert all(d.event_type == "assigned" for d in digests)
    assert all(d.status == "skipped_no_smtp" for d in digests)


async def test_conflict_check_flags_author(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """冲突检查：提交人自审被标 is_submitter 且 default_selected=False。"""
    sub = await _create_submission(client, test_user, "WB conflict")
    resp = await client.post(
        "/api/editor/workbench/conflicts",
        json={"submission_id": sub["id"], "reviewer_ids": [test_user["user_id"]]},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200, resp.text
    c = resp.json()["candidates"][0]
    assert c["is_submitter"] is True
    assert c["default_selected"] is False
    assert c["warning"] is True


async def test_manual_remind(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """手动催审：给未交报告的审稿人发 review.reminder。"""
    await client.get("/api/health")
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    reviewer = await _register_reviewer(client, db_session, tenant, "wb5")

    sub = await _create_submission(client, test_user, "WB remind")
    batch = await client.post(
        "/api/editor/workbench/batch-assign",
        json={"items": [{"submission_id": sub["id"], "reviewer_ids": [reviewer["user_id"]]}], "due_days": 3},
        headers=auth_headers(admin_user),
    )
    assignment_id = batch.json()["created"][0]["assignment_id"]

    resp = await client.post(
        "/api/editor/workbench/remind",
        json={"assignment_ids": [assignment_id]},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reminded_count"] == 1

    notes = await client.get("/api/notifications", headers=auth_headers(reviewer))
    reminders = [n for n in notes.json()["data"] if n["type"] == "review.reminder"]
    assert len(reminders) == 1


# ---------------------------------------------------------------------------
# Notifications filter / unread
# ---------------------------------------------------------------------------


async def test_notification_category_filter_and_read_state(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """通知按 category 筛选；未读计数随已读变化。"""
    await client.get("/api/health")
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    reviewer = await _register_reviewer(client, db_session, tenant, "wb6")

    sub = await _create_submission(client, test_user, "WB notif filter")
    await client.post(
        "/api/editor/workbench/batch-assign",
        json={"items": [{"submission_id": sub["id"], "reviewer_ids": [reviewer["user_id"]]}], "due_days": 5},
        headers=auth_headers(admin_user),
    )

    # 未读计数 >= 1
    uc = await client.get("/api/notifications/unread-count", headers=auth_headers(reviewer))
    assert uc.status_code == 200
    assert uc.json()["unread"] >= 1

    # category=assigned 只返回 review.invited
    cat = await client.get("/api/notifications?category=assigned", headers=auth_headers(reviewer))
    assert cat.status_code == 200
    rows = cat.json()["data"]
    assert rows, "expected at least one assigned notification"
    assert all(n["type"] == "review.invited" for n in rows)

    # 全部已读 → 未读=0
    ra = await client.patch("/api/notifications/read-all", headers=auth_headers(reviewer))
    assert ra.status_code == 200
    uc2 = await client.get("/api/notifications/unread-count", headers=auth_headers(reviewer))
    assert uc2.json()["unread"] == 0


# ---------------------------------------------------------------------------
# Email digest side-channel banner (honest "did it actually send?")
# ---------------------------------------------------------------------------


async def test_editor_workbench_email_digest_summary_honest_when_no_smtp(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """SMTP 未配置时，工作台必须如实报告：smtp_configured=False、skipped_count>0。

    不能让前端误以为邮件发出去了——站内通知照常，但邮件侧要明说。
    """
    await client.get("/api/health")
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    reviewer = await _register_reviewer(client, db_session, tenant, "wb_digest1")

    sub = await _create_submission(client, test_user, "WB digest no smtp")
    await client.post(
        "/api/editor/workbench/batch-assign",
        json={"items": [{"submission_id": sub["id"], "reviewer_ids": [reviewer["user_id"]]}], "due_days": 5},
        headers=auth_headers(admin_user),
    )

    wb = await client.get("/api/editor/workbench", headers=auth_headers(admin_user))
    assert wb.status_code == 200, wb.text
    ed = wb.json()["email_digest"]
    # 测试环境 SMTP host/user/password 全为空 → 未配置
    assert ed["smtp_configured"] is False
    assert ed["enabled"] is True
    # 刚才那次指派落了一条 skipped_no_smtp
    assert ed["skipped_count"] >= 1
    assert ed["failed_count"] == 0
    assert ed["last_status"] == "skipped_no_smtp"
    assert ed["last_attempt_at"] is not None


async def test_editor_workbench_email_digest_summary_smtp_fields_present(
    client: AsyncClient, admin_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """host/port/user/password 四项齐全时，smtp_configured=True（不看外发开关）。"""
    from app.core.config import settings

    await client.get("/api/health")
    monkeypatch.setattr(settings, "email_smtp_host", "smtp.example.com", raising=False)
    monkeypatch.setattr(settings, "email_smtp_port", 465, raising=False)
    monkeypatch.setattr(settings, "email_smtp_username", "noreply@example.com", raising=False)
    monkeypatch.setattr(settings, "email_smtp_password", "secret", raising=False)

    wb = await client.get("/api/editor/workbench", headers=auth_headers(admin_user))
    assert wb.status_code == 200, wb.text
    ed = wb.json()["email_digest"]
    assert ed["smtp_configured"] is True


async def test_editor_email_digest_records_endpoint(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """records 接口返回最近投递记录，可按 status 过滤；审稿人 403。"""
    await client.get("/api/health")
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    reviewer = await _register_reviewer(client, db_session, tenant, "wb_digest2")

    sub = await _create_submission(client, test_user, "WB digest records")
    await client.post(
        "/api/editor/workbench/batch-assign",
        json={"items": [{"submission_id": sub["id"], "reviewer_ids": [reviewer["user_id"]]}], "due_days": 5},
        headers=auth_headers(admin_user),
    )

    # editor 可读
    resp = await client.get(
        "/api/editor/workbench/email-digest/records", headers=auth_headers(admin_user)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1
    row = body["items"][0]
    assert row["event_type"] == "assigned"
    assert row["status"] == "skipped_no_smtp"
    assert row["recipient_email"]
    assert row["subject"]
    assert row["created_at"]

    # status 过滤
    only_skipped = await client.get(
        "/api/editor/workbench/email-digest/records?status=skipped_no_smtp",
        headers=auth_headers(admin_user),
    )
    assert only_skipped.status_code == 200
    assert all(r["status"] == "skipped_no_smtp" for r in only_skipped.json()["items"])

    # 非法 status → 422
    bad = await client.get(
        "/api/editor/workbench/email-digest/records?status=bogus",
        headers=auth_headers(admin_user),
    )
    assert bad.status_code == 422

    # 审稿人无权访问（403）
    forbidden = await client.get(
        "/api/editor/workbench/email-digest/records", headers=auth_headers(reviewer)
    )
    assert forbidden.status_code == 403
