"""P1 认领绑定 + 作者归属行为锁定。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.catalog.models import AuthorClaim, Resource
from app.models import Tenant


async def _default_tenant(db: AsyncSession) -> Tenant:
    return (await db.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()


@pytest.mark.asyncio
async def test_claim_403_when_owner_bound(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict, test_user: dict
) -> None:
    """已绑定 owner_id 的文章，POST claim 必须 403。"""
    tenant = await _default_tenant(db_session)
    resource = Resource(
        tenant_id=tenant.id,
        title="已归属",
        type="paper",
        authors=["A"],
        year=2026,
        discipline="physics",
        abstract="x",
        preview="x",
        tags=[],
        publication_status="published",
        owner_id=admin_user["user_id"],
    )
    db_session.add(resource)
    await db_session.commit()
    resp = await client.post(
        f"/api/catalog/{resource.id}/claim",
        json={
            "note": "x",
            "author_position": 1,
            "evidence_type": "email",
            "evidence_value": "a@b.c",
        },
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_claim_open_creates_pending_with_evidence(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict, test_user: dict
) -> None:
    """未绑定文章可提交认领，带 author_position/evidence 写入 pending。"""
    tenant = await _default_tenant(db_session)
    resource = Resource(
        tenant_id=tenant.id,
        title="待认领",
        type="paper",
        authors=["A"],
        year=2026,
        discipline="physics",
        abstract="x",
        preview="x",
        tags=[],
        publication_status="published",
        owner_id=None,
    )
    db_session.add(resource)
    await db_session.commit()
    resp = await client.post(
        f"/api/catalog/{resource.id}/claim",
        json={
            "note": "我是作者",
            "author_position": 1,
            "evidence_type": "orcid",
            "evidence_value": "0000-0001",
        },
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert resp.status_code == 200, resp.text
    claim = (
        await db_session.execute(select(AuthorClaim).where(AuthorClaim.resource_id == resource.id))
    ).scalar_one()
    assert claim.status == "pending"
    assert claim.author_position == 1
    assert claim.evidence_type == "orcid"


@pytest.mark.asyncio
async def test_approve_binds_owner_and_marks_author(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict, test_user: dict
) -> None:
    """审核通过后：owner_id 绑定、authors_detail 对应位 claimed=true。"""
    tenant = await _default_tenant(db_session)
    resource = Resource(
        tenant_id=tenant.id,
        title="待批",
        type="paper",
        authors=["Alice", "Bob"],
        year=2026,
        discipline="physics",
        abstract="x",
        preview="x",
        tags=[],
        publication_status="published",
        owner_id=None,
    )
    db_session.add(resource)
    await db_session.commit()
    # 用户发起认领
    await client.post(
        f"/api/catalog/{resource.id}/claim",
        json={"author_position": 1, "evidence_type": "email", "evidence_value": "alice@x.com"},
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    claim = (
        await db_session.execute(select(AuthorClaim).where(AuthorClaim.resource_id == resource.id))
    ).scalar_one()
    # admin 批准
    resp = await client.post(
        f"/api/admin/claims/{claim.id}/decision",
        json={"action": "approve", "note": "ok"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert resp.status_code == 200, resp.text
    await db_session.refresh(resource)
    assert resource.owner_id == test_user["user_id"]
    # authors_detail 第 1 位 claimed
    detail = await client.get(f"/api/catalog/{resource.id}")
    body = detail.json()
    authors = body["authors_detail"]
    assert authors[0]["claimed"] is True
    assert authors[0]["user_id"] == test_user["user_id"]
    assert authors[1]["claimed"] is False


@pytest.mark.asyncio
async def test_unclaimed_author_email_null_in_public(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict
) -> None:
    """未认领作者位：公开响应 email 一律 null，不下发解析邮箱。"""
    tenant = await _default_tenant(db_session)
    resource = Resource(
        tenant_id=tenant.id,
        title="稿",
        type="paper",
        authors=["Alice", "Bob"],
        year=2026,
        discipline="physics",
        abstract="x",
        preview="x",
        tags=[],
        publication_status="published",
        owner_id=None,
        authors_meta=[
            {"name": "Alice", "email": "alice@private"},
            {"name": "Bob", "email": "bob@private"},
        ],
    )
    db_session.add(resource)
    await db_session.commit()
    resp = await client.get(f"/api/catalog/{resource.id}")
    body = resp.json()
    for a in body["authors_detail"]:
        assert a["claimed"] is False
        assert a["email"] is None
        assert a["user_id"] is None


@pytest.mark.asyncio
async def test_edit_authors_validation(
    client: AsyncClient, db_session: AsyncSession, admin_user: dict
) -> None:
    """作者编辑校验：第一作者唯一、通讯作者唯一、order 连续。"""
    tenant = await _default_tenant(db_session)
    resource = Resource(
        tenant_id=tenant.id,
        title="稿",
        type="paper",
        authors=["Alice", "Bob"],
        year=2026,
        discipline="physics",
        abstract="x",
        preview="x",
        tags=[],
        publication_status="published",
    )
    db_session.add(resource)
    await db_session.commit()
    # 两个第一作者 → 400
    bad = {
        "authors": [
            {"name": "A", "order": 1, "roles": ["first"]},
            {"name": "B", "order": 2, "roles": ["first"]},
        ]
    }
    resp = await client.put(
        f"/api/admin/resources/{resource.id}/authors",
        json=bad,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert resp.status_code == 400, resp.text
    # 两个通讯作者 → 400
    bad2 = {
        "authors": [
            {"name": "A", "order": 1, "roles": ["first", "corresponding"]},
            {"name": "B", "order": 2, "roles": ["corresponding"]},
        ]
    }
    resp2 = await client.put(
        f"/api/admin/resources/{resource.id}/authors",
        json=bad2,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert resp2.status_code == 400, resp2.text
    # 合法
    ok = {
        "authors": [
            {"name": "Alice", "order": 1, "roles": ["first", "corresponding"], "email": "a@x.com"},
            {"name": "Bob", "order": 2, "roles": []},
        ]
    }
    resp3 = await client.put(
        f"/api/admin/resources/{resource.id}/authors",
        json=ok,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert resp3.status_code == 200, resp3.text
