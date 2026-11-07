"""P0 重构后端行为锁定：文件头识别 / 质量闸门 / 认领 403 / clc 筛选 / 指标分域。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.models import Tenant
from app.modules.catalog.models import Resource
from app.modules.submission.models import Submission
from app.modules.submission.manuscript import needs_docx_storage_key


async def _default_tenant(db: AsyncSession) -> Tenant:
    return (
        await db.execute(select(Tenant).where(Tenant.slug == "default"))
    ).scalar_one()


@pytest.mark.asyncio
async def test_claim_403_when_owner_bound(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict, test_user: dict
) -> None:
    """owner_id 已绑定的文章，POST claim 必须 403（后端硬拦，不靠前端隐藏）。"""
    tenant = await _default_tenant(db_session)
    resource = Resource(
        tenant_id=tenant.id,
        title="已归属文章",
        type="paper",
        authors=["Author A"],
        year=2026,
        discipline="computer-science", tags=[],
        abstract="abstract body",
        preview="preview",
        publication_status="published",
        owner_id=admin_user["user_id"],  # 已绑定
    )
    db_session.add(resource)
    await db_session.commit()
    await db_session.refresh(resource)

    resp = await client.post(
        f"/api/catalog/{resource.id}/claim",
        json={"note": "我是作者"},
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert resp.status_code == 403, resp.text

    st = await client.get(
        f"/api/catalog/{resource.id}/claim-status",
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert st.status_code == 200
    body = st.json()
    assert body["claimable"] is False and body["state"] == "claimed"


@pytest.mark.asyncio
async def test_claim_open_when_no_owner(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict, test_user: dict
) -> None:
    """owner_id 为 NULL 的存量稿可发起认领（走审批流，不直接绑定）。"""
    tenant = await _default_tenant(db_session)
    resource = Resource(
        tenant_id=tenant.id,
        title="待认领存量稿",
        type="paper",
        authors=["Old Editor"],
        year=2024,
        discipline="physics", tags=[],
        abstract="old",
        preview="old",
        publication_status="published",
        owner_id=None,
    )
    db_session.add(resource)
    await db_session.commit()
    await db_session.refresh(resource)

    st = await client.get(
        f"/api/catalog/{resource.id}/claim-status",
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert st.json()["claimable"] is True

    resp = await client.post(
        f"/api/catalog/{resource.id}/claim",
        json={"note": "我是作者"},
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending"
    await db_session.refresh(resource)
    assert resource.owner_id is None  # 审批流，不直接绑定


@pytest.mark.asyncio
async def test_clc_prefix_filter(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict
) -> None:
    """?clc=TP 前缀筛选：命中 TP 开头，不命中 F 开头。"""
    tenant = await _default_tenant(db_session)
    db_session.add_all([
        Resource(
            tenant_id=tenant.id, title="CLC TP 稿", type="paper", authors=["A"],
            year=2026, discipline="computer-science", abstract="x", preview="x", tags=[],
            publication_status="published", clc_code="TP311.13", clc_label="计算机",
            content_category="academic",
        ),
        Resource(
            tenant_id=tenant.id, title="CLC F 稿", type="paper", authors=["A"],
            year=2026, discipline="economics", abstract="x", preview="x", tags=[],
            publication_status="published", clc_code="F83", content_category="academic",
        ),
    ])
    await db_session.commit()

    resp = await client.get("/api/catalog?clc=TP")
    assert resp.status_code == 200
    titles = [r["title"] for r in resp.json()["data"]]
    assert "CLC TP 稿" in titles
    assert "CLC F 稿" not in titles


@pytest.mark.asyncio
async def test_manuscript_409_needs_docx(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict
) -> None:
    """无 Markdown 且有 needs_docx 侧car → 409 + 原因 + 可下载原件。"""
    tenant = await _default_tenant(db_session)
    resource = Resource(
        tenant_id=tenant.id, title="扫描件稿", type="paper", authors=["A"],
        year=2026, discipline="physics", abstract="x", preview="x", tags=[],
        publication_status="published",
    )
    db_session.add(resource)
    await db_session.commit()
    await db_session.refresh(resource)

    rel_path = f"{tenant.id}/{resource.id}/scan.pdf"
    await get_storage().save(rel_path, b"%PDF-1.4 scanned")
    await get_storage().save(needs_docx_storage_key(rel_path), "无文本层".encode())

    db_session.add(
        Submission(
            tenant_id=tenant.id,
            resource_id=resource.id,
            submitted_by=admin_user["user_id"],
            title="扫描件稿", type="paper", authors=["A"], year=2026,
            discipline="physics", abstract="x", preview="x", tags=[],
            status="accepted", file_path=rel_path, markdown_path=None,
        )
    )
    await db_session.commit()

    resp = await client.get(f"/api/catalog/{resource.id}/manuscript")
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["readable"] is False
    assert "无文本层" in body["reason"]
    assert body["downloadable"] is True
