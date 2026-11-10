"""Gamification tests — ladder, onboarding, XP awarding, achievements, announcements."""

from __future__ import annotations

from conftest import auth_headers, register_user
from httpx import AsyncClient


def _level(body: dict) -> int:
    return int(body["level"]["level"])


async def test_ladder_is_public_and_lists_four_identities(client: AsyncClient) -> None:
    """身份体系 3.0：四种身份（读者/作者/审稿人/编辑），不再是九级 XP 阶梯。"""
    r = await client.get("/api/gamification/ladder")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "3.0"
    identities = body["identities"]
    assert [item["slug"] for item in identities] == ["reader", "author", "reviewer", "editor"]
    by_slug = {item["slug"]: item for item in identities}
    # 审稿人身份必须能对上后端角色，否则"授予"与"门禁"会脱节
    assert "reviewer" in by_slug["reviewer"]["roles"]
    assert "editor" in by_slug["editor"]["roles"]
    # 读者与作者都不需要角色（注册/确认规范即得）
    assert by_slug["reader"]["roles"] == []
    assert by_slug["author"]["roles"] == []


async def test_new_user_starts_at_level_one(client: AsyncClient) -> None:
    user = await register_user(client, email="fresh@example.com", username="fresh")
    me = await client.get("/api/users/me", headers={"Authorization": f"Bearer {user['token']}"})
    assert me.status_code == 200
    body = me.json()
    assert body["level"] == 1
    assert body["xp"] == 10
    assert body["rules_accepted"] is False


async def test_level_one_can_submit_after_rules_ack(client: AsyncClient) -> None:
    """1.8.0 投稿零等级门槛：L1 注册即可投，唯一前置是确认当版《投稿规范》。"""
    user = await register_user(client, email="l1@example.com", username="l1user")
    headers = {"Authorization": f"Bearer {user['token']}"}
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


async def test_xp_does_not_grant_any_identity(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """身份体系 3.0 的核心承诺：积分不换权限。

    旧体系里"XP 满 400 + 录用 1 篇 → L4"。现在录用与积分都只影响荣誉
    统计，身份只由"确认规范（作者）"与"角色授予（审稿人/编辑）"决定。
    这条用例锁定：给一个作者灌到 500 XP 并录用一篇，他的身份仍然是作者。
    """
    from conftest import auth_headers as _ah

    grant = await client.post(
        f"/api/gamification/admin/users/{test_user['user_id']}/grant",
        json={"points": 340, "note": "xp should not grant identity"},
        headers=auth_headers(admin_user),
    )
    assert grant.status_code == 200, grant.text

    me = await client.get("/api/users/me", headers=_ah(test_user))
    assert me.json()["xp"] >= 400
    # 已确认规范 → 作者身份（第 2 层），积分再多也不会变成审稿人
    assert me.json()["level"] == 2

    sub = await client.post(
        "/api/submissions",
        json={
            "title": "identity paper",
            "type": "paper",
            "authors": ["A"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "用于验证身份不被积分与录用改变。",
        },
        headers=auth_headers(test_user),
    )
    assert sub.status_code == 201, sub.text
    sid = sub.json()["id"]
    from conftest import complete_one_review

    await complete_one_review(client, admin_user, sid)
    dec = await client.patch(
        f"/api/submissions/{sid}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    assert dec.status_code == 200, dec.text

    me2 = await client.get("/api/users/me", headers=_ah(test_user))
    # 录用与 XP 都不改变身份：仍是作者
    assert me2.json()["level"] == 2
    assert me2.json()["xp"] >= 400


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
    r = await register_user(client, email="l1c@example.com", username="l1comment")
    posted = await client.post(
        "/api/comments",
        json={"resource_id": rid, "body": "L1 可以发言"},
        headers={"Authorization": f"Bearer {r['token']}"},
    )
    assert posted.status_code == 201


async def test_author_onboarding_grants_author_identity(client: AsyncClient) -> None:
    """确认规范后成为作者身份（第 2 层），而不是"升到 L3"。

    身份体系不再用 XP 表达"能不能投稿"——确认规范这个动作本身就是作者
    身份的定义。
    """
    user = await register_user(client, email="onboard@example.com", username="onboard")
    headers = {"Authorization": f"Bearer {user['token']}"}

    # 未确认规范前是读者身份（1）
    me_before = await client.get("/api/users/me", headers=headers)
    assert me_before.json()["level"] == 1

    author = await client.post(
        "/api/gamification/onboarding/author", json={"accept_rules": True}, headers=headers
    )
    assert author.status_code == 200
    assert _level(author.json()) == 2
    assert author.json()["level"]["slug"] == "author"

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
    user = await register_user(client, email="noaccept@example.com", username="noaccept")
    headers = {"Authorization": f"Bearer {user['token']}"}
    resp = await client.post(
        "/api/gamification/onboarding/author", json={"accept_rules": False}, headers=headers
    )
    assert resp.status_code == 400


async def test_profile_returns_badges_and_progressive_reveal(client: AsyncClient) -> None:
    user = await register_user(client, email="profile@example.com", username="profileuser")
    headers = {"Authorization": f"Bearer {user['token']}"}
    profile = await client.get("/api/gamification/me", headers=headers)
    assert profile.status_code == 200
    body = profile.json()
    assert body["level"]["level"] == 1
    assert body["level"]["slug"] == "reader"
    # 下一步是"成为作者"，靠确认规范而不是攒积分
    assert body["level"]["next_identity"]["slug"] == "author"
    # 低等级只展示已解锁 + 最多 3 个待解锁，避免一次铺满整面墙
    assert len([b for b in body["badges"] if not b["unlocked"]]) <= 3
    assert all(not b["secret"] for b in body["badges"] if not b["unlocked"])


async def test_admin_sees_secret_badges(client: AsyncClient, admin_user: dict) -> None:
    profile = await client.get("/api/gamification/me", headers=auth_headers(admin_user))
    assert profile.status_code == 200
    body = profile.json()
    # admin 视为编辑身份（第 4 层）
    assert body["level"]["level"] == 4
    assert body["level"]["slug"] == "editor"
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
    r = await register_user(client, email="reader@example.com", username="xpreader")
    headers = {"Authorization": f"Bearer {r['token']}"}
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
    """评分口径必须公开且冻结：作者能自查，外部 AI 能复现。"""
    r = await client.get("/api/quality/rubric")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "4.0"
    assert set(body["profiles"]) == {"research", "review", "essay", "note"}
    for profile in body["profiles"].values():
        assert sum(profile["weights"].values()) == 100
    assert [g["code"] for g in body["grades"]] == [
        "A+",
        "A",
        "A-",
        "B+",
        "B",
        "B-",
        "C+",
        "C",
        "C-",
        "D+",
        "D",
        "D-",
        "E+",
        "E",
        "E-",
        "F",
    ]
    assert body["min_references"]["research"] == 8
    # 3.0 的关键承诺：学术价值维度 + 诚信一票否决 + <40 分不予发表必须打回
    keys = {d["key"] for d in body["dimensions"]}
    assert {"problem", "argument", "method", "evidence", "novelty", "integrity"} <= keys
    assert "integrity_veto" in body
    assert "rejected_action" in body


async def test_quality_form_and_prompt_are_public(client: AsyncClient) -> None:
    """审稿表单与 AI 判分规格也必须公开——口径不公开就无法自证公正。"""
    form = await client.get("/api/quality/form")
    assert form.status_code == 200
    assert len(form.json()["dimensions"]) == 7
    prompt = await client.get("/api/quality/prompt?article_type=research")
    assert prompt.status_code == 200
    assert "output_schema" in prompt.json()


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
