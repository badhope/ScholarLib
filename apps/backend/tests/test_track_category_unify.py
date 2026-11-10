"""单一权威口径：content_track（paper/essay）为唯一权威轨道字段。

锁定行为：
- 写入：paper 强制 academic；essay 只允许 fun/rant（缺省 fun）；
  essay 带 rant 透传；track 缺失时 category 回推赛道。
- 读：列表/详情对历史脏数据（paper+fun、essay+academic）按 track 校正。
- 物化：投稿 content_track=essay → 资源 content_category=fun。
"""

from __future__ import annotations

import pytest
from conftest import auth_headers
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant
from app.modules.catalog.models import Resource


async def _default_tenant(db: AsyncSession) -> Tenant:
    return (await db.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()


def _payload(title: str, **extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "type": "paper",
        "title": title,
        "authors": ["Alice Author"],
        "year": 2026,
        "discipline": "computer-science",
        "tags": [],
        "abstract": "Abstract body for track/category unification tests.",
        "preview": "Preview.",
        "publication_status": "published",
    }
    base.update(extra)
    return base


@pytest.mark.asyncio
async def test_create_paper_with_fun_category_forced_to_academic(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    """paper 写入带 fun → 落库 academic（track 权威，fun 被覆盖）。"""
    r = await client.post(
        "/api/catalog",
        json=_payload("paper+fun", content_track="paper", content_category="fun"),
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["content_track"] == "paper"
    assert body["content_category"] == "academic"

    row = (await db_session.execute(select(Resource).where(Resource.id == body["id"]))).scalar_one()
    assert row.content_track == "paper"
    assert row.content_category == "academic"


@pytest.mark.asyncio
async def test_create_essay_without_category_defaults_fun(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    """essay 无 category → fun。"""
    r = await client.post(
        "/api/catalog",
        json=_payload("essay-default", content_track="essay"),
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["content_track"] == "essay"
    assert body["content_category"] == "fun"

    row = (await db_session.execute(select(Resource).where(Resource.id == body["id"]))).scalar_one()
    assert row.content_track == "essay"
    assert row.content_category == "fun"


@pytest.mark.asyncio
async def test_create_essay_with_rant_preserved(client: AsyncClient, admin_user: dict) -> None:
    """essay 带 rant → rant。"""
    r = await client.post(
        "/api/catalog",
        json=_payload("essay-rant", content_track="essay", content_category="rant"),
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["content_track"] == "essay"
    assert body["content_category"] == "rant"


@pytest.mark.asyncio
async def test_create_without_track_category_backfills_track(
    client: AsyncClient, admin_user: dict
) -> None:
    """只传 category=fun（老客户端）→ track 回推为 essay。"""
    r = await client.post(
        "/api/catalog",
        json=_payload("category-only", content_category="fun"),
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["content_track"] == "essay"
    assert body["content_category"] == "fun"


@pytest.mark.asyncio
async def test_patch_track_flips_category(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    """PATCH 把 paper 翻成 essay → category 自动变 fun；再 PATCH rant。"""
    created = (
        await client.post(
            "/api/catalog",
            json=_payload("patch-me"),
            headers=auth_headers(admin_user),
        )
    ).json()
    rid = created["id"]

    r = await client.patch(
        f"/api/catalog/{rid}",
        json={"content_track": "essay"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    assert r.json()["content_track"] == "essay"
    assert r.json()["content_category"] == "fun"

    r = await client.patch(
        f"/api/catalog/{rid}",
        json={"content_category": "rant"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    assert r.json()["content_track"] == "essay"
    assert r.json()["content_category"] == "rant"

    row = (await db_session.execute(select(Resource).where(Resource.id == rid))).scalar_one()
    assert row.content_track == "essay"
    assert row.content_category == "rant"


@pytest.mark.asyncio
async def test_list_and_detail_correct_dirty_rows(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    """历史脏数据（paper+fun / essay+academic）在列表与详情按 track 校正。"""
    tenant = await _default_tenant(db_session)
    dirty_paper = Resource(
        tenant_id=tenant.id,
        title="漂移 paper+fun",
        type="paper",
        authors=["A"],
        year=2026,
        discipline="computer-science",
        tags=[],
        abstract="x",
        preview="x",
        publication_status="published",
        content_track="paper",
        content_category="fun",  # 历史漂移：用户改了 track 忘改 category
    )
    dirty_essay = Resource(
        tenant_id=tenant.id,
        title="漂移 essay+academic",
        type="paper",
        authors=["A"],
        year=2026,
        discipline="computer-science",
        tags=[],
        abstract="x",
        preview="x",
        publication_status="published",
        content_track="essay",
        content_category="academic",  # 历史漂移
    )
    db_session.add_all([dirty_paper, dirty_essay])
    await db_session.commit()
    await db_session.refresh(dirty_paper)
    await db_session.refresh(dirty_essay)

    # 详情：paper+fun → academic；essay+academic → fun
    d1 = await client.get(f"/api/catalog/{dirty_paper.id}")
    assert d1.status_code == 200
    assert d1.json()["content_track"] == "paper"
    assert d1.json()["content_category"] == "academic"

    d2 = await client.get(f"/api/catalog/{dirty_essay.id}")
    assert d2.status_code == 200
    assert d2.json()["content_track"] == "essay"
    assert d2.json()["content_category"] == "fun"

    # 列表同样自洽
    lst = await client.get("/api/catalog")
    assert lst.status_code == 200
    by_id = {row["id"]: row for row in lst.json()["data"]}
    assert by_id[dirty_paper.id]["content_category"] == "academic"
    assert by_id[dirty_essay.id]["content_category"] == "fun"


@pytest.mark.asyncio
async def test_materialize_submission_essay_track(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    """投稿 content_track=essay → 物化出的资源 category=fun。"""
    from app.modules.submission._helpers import _materialize_resource_from_submission
    from app.modules.submission.models import Submission

    tenant = await _default_tenant(db_session)
    submission = Submission(
        tenant_id=tenant.id,
        submitted_by=admin_user["user_id"],
        status="accepted",
        title="物化 essay 稿",
        type="paper",
        authors=["Alice"],
        year=2026,
        discipline="computer-science",
        tags=[],
        abstract="x",
        preview="x",
        content_track="essay",
    )
    db_session.add(submission)
    await db_session.commit()

    resource = await _materialize_resource_from_submission(db_session, submission)
    assert resource.content_track == "essay"
    assert resource.content_category == "fun"

    # 缺省（track=None）按 paper/academic 物化
    submission2 = Submission(
        tenant_id=tenant.id,
        submitted_by=admin_user["user_id"],
        status="accepted",
        title="物化默认稿",
        type="paper",
        authors=["Bob"],
        year=2026,
        discipline="computer-science",
        tags=[],
        abstract="x",
        preview="x",
    )
    db_session.add(submission2)
    await db_session.commit()
    resource2 = await _materialize_resource_from_submission(db_session, submission2)
    assert resource2.content_track == "paper"
    assert resource2.content_category == "academic"
