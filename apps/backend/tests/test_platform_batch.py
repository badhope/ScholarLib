"""第一批施工的回归：板块树、敏感词、相似度、通知与健康卡。"""

from __future__ import annotations

import pytest
from conftest import auth_headers
from httpx import AsyncClient
from sqlalchemy import update

from app.modules.catalog.models import Resource
from tests.test_catalog import _SAMPLE
from tests.test_submission import _PAYLOAD


@pytest.mark.asyncio
async def test_forum_board_tree_and_board_topic(client: AsyncClient, admin_user: dict, test_user: dict) -> None:
    parent = await client.post(
        "/api/forum/admin/boards",
        json={"slug": "academic", "name": "学术交流", "sort_order": 1},
        headers=auth_headers(admin_user),
    )
    assert parent.status_code == 201, parent.text
    parent_id = parent.json()["id"]
    child = await client.post(
        "/api/forum/admin/boards",
        json={"parent_id": parent_id, "slug": "paper", "name": "论文沙龙", "sort_order": 0},
        headers=auth_headers(admin_user),
    )
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]

    topic = await client.post(
        "/api/forum/topics",
        json={"title": "板块内的帖子", "body": "正文", "board_id": child_id},
        headers=auth_headers(test_user),
    )
    assert topic.status_code == 201, topic.text
    body = topic.json()
    assert body["board_id"] == child_id
    assert body["board_name"] == "论文沙龙"
    assert "学术交流" in body["board_path"]

    boards = await client.get("/api/forum/boards")
    assert boards.status_code == 200
    tree = boards.json()["tree"]
    assert any(b["slug"] == "academic" and b["children"] for b in tree)

    # 父板块聚合子板块帖子
    listing = await client.get("/api/forum/topics?board=academic")
    assert listing.status_code == 200
    assert listing.json()["meta"]["total"] == 1


@pytest.mark.asyncio
async def test_moderation_blocks_ad_text(client: AsyncClient, test_user: dict) -> None:
    r = await client.post(
        "/api/forum/topics",
        json={"title": "兼职日赚500", "body": "加微信 xxx 拉你进群，刷单返利"},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "content_blocked"


@pytest.mark.asyncio
async def test_site_similarity_flags_copy_of_resource(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    resource = await client.post(
        "/api/catalog",
        json={**_SAMPLE, "title": "站内相似度基准标题", "abstract": "这是一段用于站内相似度比对的稳定摘要文本，包含足够多的中文字符来形成 shingle。"},
        headers=auth_headers(admin_user),
    )
    assert resource.status_code == 201
    payload = {
        **_PAYLOAD,
        "title": "站内相似度基准标题",
        "abstract": "这是一段用于站内相似度比对的稳定摘要文本，包含足够多的中文字符来形成 shingle。",
        "doi": "10.1234/similarity.001",
    }
    submission = await client.post(
        "/api/submissions", json=payload, headers=auth_headers(test_user)
    )
    assert submission.status_code == 201, submission.text
    body = submission.json()
    assert body["similarity_score"] is not None
    assert body["similarity_score"] >= 35
    assert body["similarity_matches"]
    assert body["similarity_matches"][0]["kind"] in {"resource", "submission"}


@pytest.mark.asyncio
async def test_comment_notifies_owner_and_preferences_roundtrip(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session
) -> None:
    rid = (
        await client.post(
            "/api/catalog",
            json={**_SAMPLE, "title": "评论通知目标"},
            headers=auth_headers(admin_user),
        )
    ).json()["id"]
    # 目录创建接口不接收 owner_id；这里直接把资源归属给 admin，
    # 专门验证“评论 -> 作者通知”这条链路。
    await db_session.execute(
        update(Resource).where(Resource.id == rid).values(owner_id=admin_user["user_id"])
    )
    await db_session.commit()
    r = await client.post(
        "/api/comments",
        json={"resource_id": rid, "body": "这条评论应该通知资源作者"},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 201

    notes = await client.get(
        "/api/notifications?category=community", headers=auth_headers(admin_user)
    )
    assert notes.status_code == 200
    assert any(n["type"] == "comment.new" for n in notes.json()["data"])

    prefs = await client.get(
        "/api/users/me/notification-preferences", headers=auth_headers(admin_user)
    )
    assert prefs.status_code == 200
    assert prefs.json()["in_app_comment"] is True

    off = await client.patch(
        "/api/users/me/notification-preferences",
        json={"in_app_comment": False},
        headers=auth_headers(admin_user),
    )
    assert off.status_code == 200
    assert off.json()["in_app_comment"] is False


@pytest.mark.asyncio
async def test_system_health_requires_admin(client: AsyncClient, admin_user: dict, test_user: dict) -> None:
    forbidden = await client.get("/api/admin/system/health", headers=auth_headers(test_user))
    assert forbidden.status_code in (401, 403)
    ok = await client.get("/api/admin/system/health", headers=auth_headers(admin_user))
    assert ok.status_code == 200
    body = ok.json()
    assert body["status"] in {"ok", "warn", "fail"}
    assert any(c["key"] == "database" for c in body["checks"])
    # 迁移图里有元组 down_revision 与重复 revision id，健康页必须用
    # Alembic 自己的图取 head，不能靠正则差集。
    assert body["code_revision"] == "040_user_notification_prefs"


@pytest.mark.asyncio
async def test_submission_edit_recomputes_similarity(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    original = "原创摘要：讨论可复现实验的登记、版本锁定与失败样本归档，不涉及任何已有站内文本。"
    copied = "站内相似度编辑重算：这段摘要会故意与站内资源保持一致，用来验证修改后的重算链路是否生效。"
    resource = await client.post(
        "/api/catalog",
        json={**_SAMPLE, "title": "编辑重算基准", "abstract": copied},
        headers=auth_headers(admin_user),
    )
    assert resource.status_code == 201
    created = await client.post(
        "/api/submissions",
        json={**_PAYLOAD, "title": "编辑重算前的原创标题", "abstract": original, "doi": "10.1234/edit.001"},
        headers=auth_headers(test_user),
    )
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    patched = await client.patch(
        f"/api/submissions/{sid}",
        json={"title": "编辑重算基准", "abstract": copied},
        headers=auth_headers(test_user),
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["similarity_score"] >= 35
    assert body["similarity_matches"]
