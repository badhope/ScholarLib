"""Gamification tests — ladder, onboarding, XP awarding, achievements, announcements."""

from __future__ import annotations

from conftest import auth_headers
from httpx import AsyncClient


def _level(body: dict) -> int:
    return int(body["level"]["level"])


async def test_ladder_is_public_and_has_nine_levels(client: AsyncClient) -> None:
    r = await client.get("/api/gamification/ladder")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "2.0"
    assert [item["level"] for item in body["levels"]] == list(range(1, 10))
    levels = {item["level"]: item for item in body["levels"]}
    assert levels[1]["track"] == "merit"
    assert levels[9]["track"] == "staff"
    assert "reviewer" in levels[5]["roles"]
    assert "editor" in levels[8]["roles"]


async def test_new_user_starts_at_level_one(client: AsyncClient) -> None:
    r = await client.post(
        "/api/auth/register",
        json={"email": "fresh@example.com", "username": "fresh", "password": "password123"},
    )
    assert r.status_code == 201
    token = r.json()["access_token"]
    me = await client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["level"] == 1
    assert body["xp"] == 10
    assert body["rules_accepted"] is False


async def test_level_one_can_submit_after_rules_ack(client: AsyncClient) -> None:
    """1.8.0 投稿零等级门槛：L1 注册即可投，唯一前置是确认当版《投稿规范》。"""
    r = await client.post(
        "/api/auth/register",
        json={"email": "l1@example.com", "username": "l1user", "password": "password123"},
    )
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "title": "L1 direct submission",
        "type": "paper",
        "authors": ["A"],
        "year": 2026,
        "discipline": "计算机科学",
        "abstract": "L1 用户确认规范后即可投稿。",
    }

    blocked = await client.post("/api/submissions", json=body, headers=headers)
    assert blocked.status_code == 403
    detail = blocked.json()["detail"]
    assert detail["code"] == "rules_ack_required"

    # 确认社区规范 + 作者引导（写入 rules_ack_version）→ 直接投稿成功
    await client.post(
        "/api/gamification/onboarding/author", json={"accept_rules": True}, headers=headers
    )
    submitted = await client.post("/api/submissions", json=body, headers=headers)
    assert submitted.status_code == 201, submitted.text


async def test_l4_requires_accepted_paper_not_just_xp(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """1.8.0 升级口径：XP 满 400 只是必要条件，录用 >= 1 才升 L4。"""
    from conftest import auth_headers as _ah

    # onboarding 已把 test_user 送到 L3（160 XP）；再 grant 到 500 XP
    grant = await client.post(
        f"/api/gamification/admin/users/{test_user['user_id']}/grant",
        json={"points": 340, "note": "xp floor for L4"},
        headers=auth_headers(admin_user),
    )
    assert grant.status_code == 200, grant.text

    me = await client.get("/api/users/me", headers=_ah(test_user))
    assert me.json()["xp"] >= 400
    assert me.json()["level"] == 3, "XP 满但无录用 → 不得升 L4"

    # 投稿 → admin 录用（物化资源）→ L4 指标达成
    sub = await client.post(
        "/api/submissions",
        json={
            "title": "L4 metric paper",
            "type": "paper",
            "authors": ["A"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "用于验证 L4 录用指标的占位摘要，长度足够校验。",
        },
        headers=auth_headers(test_user),
    )
    assert sub.status_code == 201, sub.text
    sid = sub.json()["id"]
    dec = await client.patch(
        f"/api/submissions/{sid}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    assert dec.status_code == 200, dec.text

    me2 = await client.get("/api/users/me", headers=_ah(test_user))
    assert me2.json()["level"] == 4, "录用达成 → 升 L4"


async def test_level_one_can_comment(client: AsyncClient, admin_user: dict) -> None:
    sample = {
        "type": "paper",
        "title": "Comment Gate Target",
        "authors": ["A"],
        "year": 2026,
        "discipline": "计算机科学",
        "abstract": "用于验证 L1 评论门禁的占位摘要。",
    }
    rid = (await client.post("/api/catalog", json=sample, headers=auth_headers(admin_user))).json()[
        "id"
    ]
    r = await client.post(
        "/api/auth/register",
        json={"email": "l1c@example.com", "username": "l1comment", "password": "password123"},
    )
    token = r.json()["access_token"]
    posted = await client.post(
        "/api/comments",
        json={"resource_id": rid, "body": "L1 可以发言"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert posted.status_code == 201


async def test_author_onboarding_unlocks_level_three(client: AsyncClient) -> None:
    r = await client.post(
        "/api/auth/register",
        json={"email": "onboard@example.com", "username": "onboard", "password": "password123"},
    )
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    community = await client.post("/api/gamification/onboarding/community", headers=headers)
    assert community.status_code == 200
    assert _level(community.json()) == 2

    author = await client.post(
        "/api/gamification/onboarding/author", json={"accept_rules": True}, headers=headers
    )
    assert author.status_code == 200
    assert _level(author.json()) == 3

    me = await client.get("/api/users/me", headers=headers)
    assert me.json()["rules_accepted"] is True

    submitted = await client.post(
        "/api/submissions",
        json={
            "title": "Onboarded submission",
            "type": "paper",
            "authors": ["A"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "完成引导后应可投稿。",
        },
        headers=headers,
    )
    assert submitted.status_code == 201


async def test_author_onboarding_requires_accept_flag(client: AsyncClient) -> None:
    r = await client.post(
        "/api/auth/register",
        json={"email": "noaccept@example.com", "username": "noaccept", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    resp = await client.post(
        "/api/gamification/onboarding/author", json={"accept_rules": False}, headers=headers
    )
    assert resp.status_code == 400


async def test_profile_returns_badges_and_progressive_reveal(client: AsyncClient) -> None:
    r = await client.post(
        "/api/auth/register",
        json={"email": "profile@example.com", "username": "profileuser", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    profile = await client.get("/api/gamification/me", headers=headers)
    assert profile.status_code == 200
    body = profile.json()
    assert body["level"]["level"] == 1
    assert body["level"]["next_level_xp"] == 30
    assert body["level"]["progress"] < 1
    # 低等级只展示已解锁 + 最多 3 个待解锁，避免一次铺满整面墙
    assert len([b for b in body["badges"] if not b["unlocked"]]) <= 3
    assert all(not b["secret"] for b in body["badges"] if not b["unlocked"])


async def test_admin_sees_secret_badges(client: AsyncClient, admin_user: dict) -> None:
    profile = await client.get("/api/gamification/me", headers=auth_headers(admin_user))
    assert profile.status_code == 200
    body = profile.json()
    assert body["level"]["level"] == 9
    assert any(b["secret"] for b in body["badges"])


async def test_reading_awards_xp_once(client: AsyncClient, admin_user: dict) -> None:
    sample = {
        "type": "paper",
        "title": "XP Reading Target",
        "authors": ["A"],
        "year": 2026,
        "discipline": "计算机科学",
        "abstract": "用于验证阅读积分幂等。",
    }
    rid = (await client.post("/api/catalog", json=sample, headers=auth_headers(admin_user))).json()[
        "id"
    ]
    r = await client.post(
        "/api/auth/register",
        json={"email": "reader@example.com", "username": "xpreader", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    first = await client.post(f"/api/reader/history/{rid}", headers=headers)
    assert first.status_code == 201
    second = await client.post(f"/api/reader/history/{rid}", headers=headers)
    assert second.status_code == 201
    me = await client.get("/api/users/me", headers=headers)
    assert me.json()["xp"] == 12  # 10 注册 + 2 阅读（第二次不重复计分）


async def test_announcement_lifecycle(client: AsyncClient, admin_user: dict) -> None:
    active = await client.get("/api/announcements/active")
    assert active.status_code == 200
    payload = {
        "slug": "launch-2026",
        "title": "站点迁移公告",
        "body": "Rubbish 已迁移至新域名。",
        "level": "info",
        "is_active": True,
    }
    created = await client.post(
        "/api/announcements", json=payload, headers=auth_headers(admin_user)
    )
    assert created.status_code == 201
    published = await client.get("/api/announcements/active")
    assert published.json()["slug"] == "launch-2026"
    hidden = await client.post(
        "/api/announcements",
        json={**payload, "slug": "hidden", "is_active": False},
        headers=auth_headers(admin_user),
    )
    assert hidden.status_code == 201
    still = await client.get("/api/announcements/active")
    assert still.json()["slug"] == "launch-2026"


async def test_announcement_requires_admin(client: AsyncClient, test_user: dict) -> None:
    r = await client.post(
        "/api/announcements",
        json={"slug": "x", "title": "x", "body": "x"},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 403


async def test_quality_rubric_is_public_and_frozen(client: AsyncClient) -> None:
    r = await client.get("/api/quality/rubric")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "1.0"
    assert set(body["profiles"]) == {"research", "review", "essay", "note"}
    for profile in body["profiles"].values():
        assert sum(profile["weights"].values()) == 100
    assert [g["code"] for g in body["grades"]] == ["A+", "A", "B", "C", "D"]
    assert body["min_references"]["research"] == 8


async def test_daily_checkin_idempotent_and_streak(client: AsyncClient, test_user: dict) -> None:
    """每日签到：首次 +2 XP，重复签到幂等，状态口径一致。"""
    headers = auth_headers(test_user)
    before = (await client.get("/api/gamification/checkin", headers=headers)).json()
    assert before["checked_in_today"] is False
    assert before["streak"] == 0

    first = await client.post("/api/gamification/checkin", headers=headers)
    assert first.status_code == 200
    body = first.json()
    assert body["awarded"] is True
    assert body["checked_in_today"] is True
    assert body["streak"] == 1
    assert body["total"] == 1

    # 重复签到：幂等，不重复加分
    me1 = (await client.get("/api/gamification/me", headers=headers)).json()
    again = await client.post("/api/gamification/checkin", headers=headers)
    assert again.status_code == 200
    assert again.json()["awarded"] is False
    me2 = (await client.get("/api/gamification/me", headers=headers)).json()
    assert me2["xp"] == me1["xp"]

    # 状态端点与签到端点口径一致
    status = (await client.get("/api/gamification/checkin", headers=headers)).json()
    assert status["checked_in_today"] is True
    assert status["streak"] == 1
    assert status["total"] == 1


async def test_checkin_requires_auth(client: AsyncClient) -> None:
    r = await client.post("/api/gamification/checkin")
    assert r.status_code in (401, 403)
