"""论坛模块集成测试：发帖 / 回帖 / 权限 / 版主操作。"""

from __future__ import annotations

import pytest
from conftest import auth_headers, register_user
from httpx import AsyncClient


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
        json={
            "title": "如何选择投稿赛道？",
            "body": "正经和荒诞该怎么选？",
            "category": "question",
        },
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
async def test_editor_can_post_notice(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
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
    r = await client.delete(f"/api/forum/topics/{topic['id']}", headers=auth_headers(other))
    assert r.status_code == 403
    ok = await client.delete(f"/api/forum/topics/{topic['id']}", headers=auth_headers(test_user))
    assert ok.status_code == 204
    # 软删除后列表不再出现
    listing = await client.get("/api/forum/topics")
    assert listing.json()["data"] == []


@pytest.mark.asyncio
async def test_pinned_topic_sorts_first(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    editor = await _as_editor(client, admin_user, "forum_pin_ed")
    t1 = (
        await client.post(
            "/api/forum/topics",
            json={"title": "普通帖", "body": "正文内容"},
            headers=auth_headers(test_user),
        )
    ).json()
    t2 = (
        await client.post(
            "/api/forum/topics",
            json={"title": "要置顶的帖", "body": "正文内容"},
            headers=auth_headers(test_user),
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


@pytest.mark.asyncio
async def test_reaction_toggle_counts_and_viewer_state(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """赞同/有帮助/收藏：再点一次取消，详情页带当前用户状态。"""
    topic = (
        await client.post(
            "/api/forum/topics",
            json={"title": "多维反馈测试", "body": "正文"},
            headers=auth_headers(test_user),
        )
    ).json()

    first = await client.post(
        "/api/forum/reactions/toggle",
        json={"target_type": "topic", "target_id": topic["id"], "kind": "agree"},
        headers=auth_headers(admin_user),
    )
    assert first.status_code == 200, first.text
    assert first.json()["active"] is True
    assert first.json()["counts"]["agree"] == 1

    detail = await client.get(f"/api/forum/topics/{topic['id']}", headers=auth_headers(admin_user))
    assert detail.json()["reactions"]["agree"] == 1
    assert "agree" in detail.json()["viewer_reactions"]

    # 再点一次：取消，而不是累加
    second = await client.post(
        "/api/forum/reactions/toggle",
        json={"target_type": "topic", "target_id": topic["id"], "kind": "agree"},
        headers=auth_headers(admin_user),
    )
    assert second.json()["active"] is False
    assert second.json()["counts"]["agree"] == 0


@pytest.mark.asyncio
async def test_reaction_requires_login(client: AsyncClient, test_user: dict) -> None:
    topic = (
        await client.post(
            "/api/forum/topics",
            json={"title": "未登录反馈", "body": "正文"},
            headers=auth_headers(test_user),
        )
    ).json()
    r = await client.post(
        "/api/forum/reactions/toggle",
        json={"target_type": "topic", "target_id": topic["id"], "kind": "helpful"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_nested_reply_flattens_to_two_levels(client: AsyncClient, test_user: dict) -> None:
    """回复子楼时归到根楼，只保留两级，避免无限缩进。"""
    topic = (
        await client.post(
            "/api/forum/topics",
            json={"title": "楼中楼测试", "body": "正文"},
            headers=auth_headers(test_user),
        )
    ).json()
    root = (
        await client.post(
            f"/api/forum/topics/{topic['id']}/replies",
            json={"body": "根回复"},
            headers=auth_headers(test_user),
        )
    ).json()
    assert root["parent_id"] is None

    child = (
        await client.post(
            f"/api/forum/topics/{topic['id']}/replies",
            json={"body": "子回复", "parent_id": root["id"]},
            headers=auth_headers(test_user),
        )
    ).json()
    assert child["parent_id"] == root["id"]

    grandchild = (
        await client.post(
            f"/api/forum/topics/{topic['id']}/replies",
            json={"body": "回复子楼", "parent_id": child["id"]},
            headers=auth_headers(test_user),
        )
    ).json()
    assert grandchild["parent_id"] == root["id"], "第三层必须归到根楼"


@pytest.mark.asyncio
async def test_hot_sort_puts_replied_topic_first(client: AsyncClient, test_user: dict) -> None:
    quiet = (
        await client.post(
            "/api/forum/topics",
            json={"title": "没人回的帖", "body": "正文"},
            headers=auth_headers(test_user),
        )
    ).json()
    hot = (
        await client.post(
            "/api/forum/topics",
            json={"title": "有回复的帖", "body": "正文"},
            headers=auth_headers(test_user),
        )
    ).json()
    await client.post(
        f"/api/forum/topics/{hot['id']}/replies",
        json={"body": "顶一下"},
        headers=auth_headers(test_user),
    )
    listing = (await client.get("/api/forum/topics?sort=hot")).json()["data"]
    assert listing[0]["id"] == hot["id"]
    assert listing[1]["id"] == quiet["id"]


@pytest.mark.asyncio
async def test_admin_report_list_includes_reporter(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """举报队列必须带举报人，不能因为字段名映射丢掉。"""
    topic = (
        await client.post(
            "/api/forum/topics",
            json={"title": "举报人字段", "body": "正文"},
            headers=auth_headers(test_user),
        )
    ).json()
    await client.post(
        "/api/forum/reports",
        json={"topic_id": topic["id"], "reason": "垃圾广告"},
        headers=auth_headers(test_user),
    )
    admin_list = (await client.get("/api/forum/reports", headers=auth_headers(admin_user))).json()
    row = next(item for item in admin_list if item["topic_id"] == topic["id"])
    assert row["reporter"] is not None
    assert row["reporter"]["username"] == test_user["username"]


@pytest.mark.asyncio
async def test_forum_image_upload_and_public_read(client: AsyncClient, test_user: dict) -> None:
    """论坛图片：登录可上传，公开可读，未登录不能传。"""
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8"
        b"\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND"
        b"\xaeB`\x82"
    )
    assert (
        await client.post(
            "/api/forum/images",
            files={"file": ("a.png", png, "image/png")},
        )
    ).status_code == 401
    uploaded = await client.post(
        "/api/forum/images",
        files={"file": ("a.png", png, "image/png")},
        headers=auth_headers(test_user),
    )
    assert uploaded.status_code == 201
    url = uploaded.json()["url"]
    fetched = await client.get(url)
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/png"
    assert fetched.content == png


@pytest.mark.asyncio
async def test_parent_board_slug_filters_descendant_topics(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """多级版块：父板块 slug 必须能筛出后代版块的帖子（不能 422）。"""
    parent = await client.post(
        "/api/forum/admin/boards",
        json={"slug": "test-parent", "name": "测试父板块"},
        headers=auth_headers(admin_user),
    )
    assert parent.status_code == 201, parent.text
    child = await client.post(
        "/api/forum/admin/boards",
        json={"slug": "test-child", "name": "测试子板块", "parent_id": parent.json()["id"]},
        headers=auth_headers(admin_user),
    )
    assert child.status_code == 201, child.text

    created = await client.post(
        "/api/forum/topics",
        json={
            "title": "子板块里的帖子",
            "body": "验证父板块聚合。",
            "board_id": child.json()["id"],
        },
        headers=auth_headers(test_user),
    )
    assert created.status_code == 201, created.text

    for param in (f"category={parent.json()['slug']}", f"board={parent.json()['slug']}"):
        listing = await client.get(f"/api/forum/topics?{param}")
        assert listing.status_code == 200, listing.text
        assert listing.json()["meta"]["total"] == 1
