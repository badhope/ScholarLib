"""身份（权限轴）+ 等级（激励轴）双轴的集成测试（v1.14 定稿口径）。

口径：
- chief 只显示「主编」，identities=[]（不挂任何 L/R/E 轨）；
- editor 只显示 editor 轨；
- reviewer 只显示 reviewer 轨（有作者产出才加 author 轨）；
- user 有作者产出才显示 author 轨，否则不展示。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.modules.gamification import levels_axis
from conftest import auth_headers, register_reviewer, register_user


@pytest_asyncio.fixture
async def warmed_db(
    client: AsyncClient, db_session: AsyncSession
) -> AsyncGenerator[AsyncSession, None]:
    yield db_session


async def test_plain_reader_has_no_level_tracks(client: AsyncClient, test_user: dict) -> None:
    """普通读者（无投稿/无认领）不展示任何等级轨。"""
    r = await client.get("/api/me/profile", headers=auth_headers(test_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["permission_role"] == "user"
    assert body["identities"] == []
    assert body["levels"] == {}

    # 无作者轨时取 author 流水 → 403。
    forbidden = await client.get(
        "/api/me/points", params={"identity": "author"}, headers=auth_headers(test_user)
    )
    assert forbidden.status_code == 403, forbidden.text


async def test_award_points_idempotent_and_essay_zero(
    client: AsyncClient, test_user: dict, warmed_db: AsyncSession
) -> None:
    user = (
        await warmed_db.execute(select(User).where(User.id == test_user["user_id"]))
    ).scalar_one()

    first = await levels_axis.award_points(
        warmed_db, user, "claim.approve", ref_type="author_claim", ref_id="9001"
    )
    await warmed_db.commit()
    second = await levels_axis.award_points(
        warmed_db, user, "claim.approve", ref_type="author_claim", ref_id="9001"
    )
    await warmed_db.commit()
    assert first is True
    assert second is False

    snap = await levels_axis.level_snapshot(warmed_db, user, "author")
    assert snap["points"] == 20

    # 有了 author 积分后，author 轨应出现在 identities 里。
    prof = await client.get("/api/me/profile", headers=auth_headers(test_user))
    assert prof.status_code == 200, prof.text
    assert "author" in prof.json()["identities"]

    essay = await levels_axis.award_points(
        warmed_db,
        user,
        "submission.accepted.essay",
        ref_type="submission",
        ref_id="8001",
    )
    await warmed_db.commit()
    assert essay is True
    snap2 = await levels_axis.level_snapshot(warmed_db, user, "author")
    assert snap2["points"] == 20


async def test_reviewer_only_reviewer_track_and_403_on_editor_api(
    client: AsyncClient, admin_user: dict
) -> None:
    reviewer = await register_reviewer(client, admin_user, "rev1", "rev1@example.com")
    r = await client.get("/api/me/profile", headers=auth_headers(reviewer))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["permission_role"] == "reviewer"
    # reviewer 没有作者产出，只有 reviewer 轨，不并列 author 轨。
    assert body["identities"] == ["reviewer"]
    assert "editor" not in body["identities"]
    assert "author" not in body["identities"]

    resp = await client.get("/api/submissions/pending", headers=auth_headers(reviewer))
    assert resp.status_code == 403, resp.text


async def test_chief_has_no_level_tracks(client: AsyncClient, admin_user: dict) -> None:
    """主编：identities 为空，不出现 L/R/E 任何等级轨。"""
    r = await client.get("/api/me/profile", headers=auth_headers(admin_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["permission_role"] == "editor_in_chief"
    assert body["identities"] == []
    assert body["levels"] == {}
