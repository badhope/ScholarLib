"""论坛模块集成测试：发帖 / 回帖 / 权限 / 版主操作。"""

from __future__ import annotations

from conftest import auth_headers, register_user
from httpx import AsyncClient

import pytest


async def _as_editor(client: AsyncClient, admin: dict, name: str) -> dict:
    user = await register_user(client, email=f"{name}@example.com", username=name)
    grant = await client.post(
        f"/api/admin/users/{user['user_id']}/roles",
        json={"role": "editor"},
        headers=auth_headers(admin),
    )
    grant.raise_for_status()
    return user


@pytest.mark.asyncio
async def test_forum_topics_publicly_readable(client: AsyncClient) -> None:
    """论坛公开可读：未登录也能浏览（社区是橱窗）。"""
    r = await client.get("/api/forum/topics")
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_create_topic_requires_login(client: AsyncClient) -> None:
    r = await client.post("/api/forum/topics", json={"title": "测试帖", "body": "内容"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_topic_and_list(client: AsyncClient, test_user: dict) -> None:
    created = await client.post(
        "/api/forum/topics",
        json={"title": "如何选择投稿赛道？", "body": "正经和荒诞该怎么选？", "category": "question"},
        headers=auth_headers(test_user),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "如何选择投稿赛道？"
    assert body["category"] == "question"
    assert body["author"]["username"] == test_user["username"]
    assert body["reply_count"] == 0

    listing = await client.get("/api/forum/topics")
    assert len(listing.json()["data"]) == 1


@pytest.mark.asyncio
async def test_reply_increments_count_and_updates_last_active(
    client: AsyncClient, test_user: dict
) -> None:
    topic = (
        await client.post(
            "/api/forum/topics",
            json={"title": "讨论帖", "body": "正文内容"},
            headers=auth_headers(test_user),
        )
    ).json()
    r = await client.post(
        f"/api/forum/topics/{topic['id']}/replies",
        json={"body": "我也有同样的问题"},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 201, r.text

    detail = await client.get(f"/api/forum/topics/{topic['id']}")
    assert detail.json()["reply_count"] == 1
    assert detail.json()["last_reply_at"] is not None


@pytest.mark.asyncio
async def test_notice_category_requires_editor(client: AsyncClient, test_user: dict) -> None:
    """「公告」分类只有编辑能发——否则任何人都能伪装官方公告。"""
    r = await client.post(
        "/api/forum/topics",
        json={"title": "官方公告", "body": "假公告", "category": "notice"},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_editor_can_post_notice(client: AsyncClient, test_user: dict, admin_user: dict) -> None:
    editor = await _as_editor(client, admin_user, "forum_editor")
    r = await client.post(
        "/api/forum/topics",
        json={"title": "第 5 期已刊出", "body": "本期共 27 篇", "category": "notice"},
        headers=auth_headers(editor),
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_locked_topic_rejects_replies(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """锁定后不能再回复（防止已结束的讨论被顶上来）。"""
    editor = await _as_editor(client, admin_user, "forum_lock_ed")
    topic = (
        await client.post(
            "/api/forum/topics",
            json={"title": "将锁定的帖子", "body": "正文"},
            headers=auth_headers(test_user),
        )
    ).json()
    lock = await client.patch(
        f"/api/forum/topics/{topic['id']}",
        json={"is_locked": True},
        headers=auth_headers(editor),
    )
    assert lock.status_code == 200
    r = await client.post(
        f"/api/forum/topics/{topic['id']}/replies",
        json={"body": "还能回复吗"},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_only_author_or_moderator_can_delete(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    topic = (
        await client.post(
            "/api/forum/topics",
            json={"title": "待删帖", "body": "正文"},
            headers=auth_headers(test_user),
        )
    ).json()
    other = await register_user(client, email="other_forum@example.com", username="other_forum")
    r = await client.delete(
        f"/api/forum/topics/{topic['id']}", headers=auth_headers(other)
    )
    assert r.status_code == 403
    ok = await client.delete(
        f"/api/forum/topics/{topic['id']}", headers=auth_headers(test_user)
    )
    assert ok.status_code == 204
    # 软删除后列表不再出现
    listing = await client.get("/api/forum/topics")
    assert listing.json()["data"] == []


@pytest.mark.asyncio
async def test_pinned_topic_sorts_first(client: AsyncClient, test_user: dict, admin_user: dict) -> None:
    editor = await _as_editor(client, admin_user, "forum_pin_ed")
    t1 = (
        await client.post(
            "/api/forum/topics", json={"title": "普通帖", "body": "正文内容"}, headers=auth_headers(test_user)
        )
    ).json()
    t2 = (
        await client.post(
            "/api/forum/topics", json={"title": "要置顶的帖", "body": "正文内容"}, headers=auth_headers(test_user)
        )
    ).json()
    await client.patch(
        f"/api/forum/topics/{t2['id']}", json={"is_pinned": True}, headers=auth_headers(editor)
    )
    listing = (await client.get("/api/forum/topics")).json()["data"]
    assert listing[0]["id"] == t2["id"], "置顶帖必须排第一"
    assert listing[1]["id"] == t1["id"]


@pytest.mark.asyncio
async def test_report_requires_login(client: AsyncClient, test_user: dict) -> None:
    """举报必须登录：未登录返回 401。"""
    topic = (
        await client.post(
            "/api/forum/topics",
            json={"title": "待举报帖", "body": "正文"},
            headers=auth_headers(test_user),
        )
    ).json()
    r = await client.post("/api/forum/reports", json={"topic_id": topic["id"], "reason": "垃圾"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_report_topic_idempotent(client: AsyncClient, test_user: dict) -> None:
    """同一用户对同一帖子重复举报：第二次返回已存在记录，不重复入库。"""
    topic = (
        await client.post(
            "/api/forum/topics",
            json={"title": "待举报帖2", "body": "正文"},
            headers=auth_headers(test_user),
        )
    ).json()
    r1 = await client.post(
        "/api/forum/reports",
        json={"topic_id": topic["id"], "reason": "垃圾广告"},
        headers=auth_headers(test_user),
    )
    assert r1.status_code == 201, r1.text
    rid = r1.json()["id"]

    r2 = await client.post(
        "/api/forum/reports",
        json={"topic_id": topic["id"], "reason": "重复举报"},
        headers=auth_headers(test_user),
    )
    # 幂等：返回已有记录，不报错
    assert r2.status_code in (200, 201)
    assert r2.json()["id"] == rid, "重复举报必须复用同一条记录"


@pytest.mark.asyncio
async def test_report_reply_and_admin_list(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """举报回复 + 管理员能在 /reports 队列里看到。"""
    topic = (
        await client.post(
            "/api/forum/topics",
            json={"title": "举报回复测试", "body": "正文"},
            headers=auth_headers(test_user),
        )
    ).json()
    reply = (
        await client.post(
            f"/api/forum/topics/{topic['id']}/replies",
            json={"body": "回复内容"},
            headers=auth_headers(test_user),
        )
    ).json()
    r = await client.post(
        "/api/forum/reports",
        json={"reply_id": reply["id"], "reason": "不友善内容"},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 201, r.text

    # 普通用户不能看举报队列
    forbidden = await client.get("/api/forum/reports", headers=auth_headers(test_user))
    assert forbidden.status_code == 403

    # 管理员能看到
    admin_list = await client.get("/api/forum/reports", headers=auth_headers(admin_user))
    assert admin_list.status_code == 200, admin_list.text
    assert any(item["reply_id"] == reply["id"] for item in admin_list.json())
