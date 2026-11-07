"""身份（权限轴）+ 等级（激励轴）双轴的集成测试（v1.14）。"""

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
    """先经 client 触发 lifespan/建表暖场，再给 db_session。

    直接在测试函数里并列请求 db_session 会让 pytest-asyncio 在
    autouse fresh_database 之前开 session，导致「no such table: tenants」。
    """
    yield db_session


async def test_me_profile_user_identity_and_cross_identity_forbidden(
    client: AsyncClient, test_user: dict
) -> None:
    r = await client.get("/api/me/profile", headers=auth_headers(test_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["permission_role"] == "user"
    assert "author" in body["identities"]
    assert "reviewer" not in body["identities"]
    assert "editor" not in body["identities"]
    assert "author" in body["levels"]
    assert "editor" not in body["levels"]

    forbidden = await client.get(
        "/api/me/points", params={"identity": "editor"}, headers=auth_headers(test_user)
    )
    assert forbidden.status_code == 403, forbidden.text

    ok = await client.get(
        "/api/me/points", params={"identity": "author"}, headers=auth_headers(test_user)
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["identity"] == "author"


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


async def test_reviewer_sees_reviewer_track_and_403_on_editor_api(
    client: AsyncClient, admin_user: dict
) -> None:
    reviewer = await register_reviewer(client, admin_user, "rev1", "rev1@example.com")
    r = await client.get("/api/me/profile", headers=auth_headers(reviewer))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["permission_role"] == "reviewer"
    assert "author" in body["identities"]
    assert "reviewer" in body["identities"]
    assert "editor" not in body["identities"]

    resp = await client.get("/api/submissions/pending", headers=auth_headers(reviewer))
    assert resp.status_code == 403, resp.text
