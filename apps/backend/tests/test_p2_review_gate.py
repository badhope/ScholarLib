"""P2：版本号、双人审稿闸门、essay CLC null、admin 鉴权。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.models import Tenant
from app.modules.catalog.models import Resource
from app.modules.review.models import ReviewAssignment
from app.modules.submission.models import Submission


async def _default_tenant(db: AsyncSession) -> Tenant:
    return (await db.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()


@pytest.mark.asyncio
async def test_version_is_current(client: AsyncClient) -> None:
    """版本号与 app 包一致，/api/health 返回。"""
    assert __version__ == "1.15.0"
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == "1.15.0"


@pytest.mark.asyncio
async def test_essay_clc_null(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict
) -> None:
    """content_track=essay 的文章不下发 clc_code/clc_label。"""
    tenant = await _default_tenant(db_session)
    r = Resource(
        tenant_id=tenant.id,
        title="娱乐稿",
        type="paper",
        authors=["A"],
        year=2026,
        discipline="physics",
        abstract="x",
        preview="x",
        tags=[],
        publication_status="published",
        content_category="fun",
        clc_code="TP3",
        clc_label="计算机",
    )
    db_session.add(r)
    await db_session.commit()
    resp = await client.get(f"/api/catalog/{r.id}")
    body = resp.json()
    assert body["content_track"] == "essay"
    assert body["clc_code"] is None
    assert body["clc_label"] is None


@pytest.mark.asyncio
async def test_paper_clc_preserved(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict
) -> None:
    """论文稿 clc_code/clc_label 照常下发。"""
    tenant = await _default_tenant(db_session)
    r = Resource(
        tenant_id=tenant.id,
        title="学术稿",
        type="paper",
        authors=["A"],
        year=2026,
        discipline="physics",
        abstract="x",
        preview="x",
        tags=[],
        publication_status="published",
        content_category="academic",
        clc_code="TP3",
        clc_label="计算机",
    )
    db_session.add(r)
    await db_session.commit()
    resp = await client.get(f"/api/catalog/{r.id}")
    body = resp.json()
    assert body["content_track"] == "paper"
    assert body["clc_code"] == "TP3"


@pytest.mark.asyncio
async def test_decision_409_when_lt_two_reports(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict
) -> None:
    """双人审稿闸门：<2 份 completed 报告时 decision 返回 409。"""
    tenant = await _default_tenant(db_session)
    sub = Submission(
        tenant_id=tenant.id,
        title="稿件",
        type="paper",
        year=2026,
        authors=["A"],
        discipline="physics",
        abstract="x",
        preview="x",
        tags=[],
        file_path="x.pdf",
        markdown_path="x.md",
        submitted_by=admin_user["user_id"],
        status="under_review",
    )
    db_session.add(sub)
    await db_session.commit()
    # 只有 1 份 completed 报告
    a = ReviewAssignment(
        tenant_id=tenant.id,
        submission_id=sub.id,
        reviewer_id=admin_user["user_id"],
        assigned_by=admin_user["user_id"],
        status="completed",
    )
    db_session.add(a)
    await db_session.commit()
    resp = await client.post(
        f"/api/review/submissions/{sub.id}/decision",
        json={"decision": "accept", "reason": "ok"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert resp.status_code == 409, resp.text
    assert "还差" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_matrix_returns_reports_completed(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict
) -> None:
    """matrix 端点返回 reports_completed / can_decide / conflict。"""
    tenant = await _default_tenant(db_session)
    sub = Submission(
        tenant_id=tenant.id,
        title="稿件",
        type="paper",
        year=2026,
        authors=["A"],
        discipline="physics",
        abstract="x",
        preview="x",
        tags=[],
        file_path="x.pdf",
        markdown_path="x.md",
        submitted_by=admin_user["user_id"],
        status="under_review",
    )
    db_session.add(sub)
    await db_session.commit()
    # 0 份报告
    resp = await client.get(
        f"/api/review/submissions/{sub.id}/matrix",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reports_completed"] == 0
    assert body["can_decide"] is False
    assert body["conflict"] is False


@pytest.mark.asyncio
async def test_admin_claims_unauthenticated_401(client: AsyncClient) -> None:
    """未登录访问 /api/admin/claims → 401。"""
    resp = await client.get("/api/admin/claims?state=pending")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_claims_non_admin_403(client: AsyncClient, test_user: dict) -> None:
    """非管理员访问 /api/admin/claims → 403。"""
    resp = await client.get(
        "/api/admin/claims?state=pending",
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert resp.status_code == 403
