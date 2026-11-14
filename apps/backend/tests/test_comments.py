"""Comments module tests — public read, authed write, owner/admin delete."""

from __future__ import annotations

from conftest import auth_headers, register_user
from httpx import AsyncClient

from tests.test_catalog import _SAMPLE


async def _create_resource(client: AsyncClient, admin_user: dict, title: str) -> int:
    r = await client.post(
        "/api/catalog", json={**_SAMPLE, "title": title}, headers=auth_headers(admin_user)
    )
    assert r.status_code == 201
    return r.json()["id"]


async def _draft_resource(client: AsyncClient, admin_user: dict, title: str) -> int:
    r = await client.post(
        "/api/catalog",
        json={**_SAMPLE, "title": title, "publication_status": "draft"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 201
    return r.json()["id"]


async def test_list_comments_public_empty(client: AsyncClient, admin_user: dict) -> None:
    rid = await _create_resource(client, admin_user, "Comment Target")
    r = await client.get(f"/api/comments?resource_id={rid}")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


async def test_post_comment_requires_auth(client: AsyncClient, admin_user: dict) -> None:
    rid = await _create_resource(client, admin_user, "Comment Auth Gate")
    r = await client.post("/api/comments", json={"resource_id": rid, "body": "匿名试图发言"})
    assert r.status_code == 401


async def test_l1_user_can_post_comment(client: AsyncClient, admin_user: dict) -> None:
    rid = await _create_resource(client, admin_user, "Comment L1 Gate")
    l1_user = await register_user(client, email="comment-l1@example.com", username="comment_l1")
    posted = await client.post(
        "/api/comments",
        json={"resource_id": rid, "body": "L1读者评论"},
        headers={"Authorization": f"Bearer {l1_user['token']}"},
    )
    assert posted.status_code == 201


async def test_post_and_list_comment_roundtrip(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:

    rid = await _create_resource(client, admin_user, "Comment Thread")
    r = await client.post(
        "/api/comments",
        json={"resource_id": rid, "body": "  荒诞研究也需要同行质疑。 "},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["body"] == "荒诞研究也需要同行质疑。"
    assert body["author_name"]

    listing = (await client.get(f"/api/comments?resource_id={rid}")).json()
    assert listing["meta"]["total"] == 1
    assert listing["data"][0]["id"] == body["id"]


async def test_comment_body_length_validated(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    rid = await _create_resource(client, admin_user, "Comment Length")
    too_long = await client.post(
        "/api/comments",
        json={"resource_id": rid, "body": "x" * 1001},
        headers=auth_headers(test_user),
    )
    assert too_long.status_code == 422
    blank = await client.post(
        "/api/comments",
        json={"resource_id": rid, "body": "   "},
        headers=auth_headers(test_user),
    )
    assert blank.status_code == 422


async def test_comment_on_unpublished_resource_404(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """未刊稿一律 404：不向公众确认存在，编辑也不在评论区走后门。"""
    rid = await _draft_resource(client, admin_user, "Comment Draft Only")
    r = await client.post(
        "/api/comments",
        json={"resource_id": rid, "body": "draft 试图评论"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 404
    # 列表端点与创建端点同口径：草稿/排期稿的评论线程也 404，
    # 不返回空线程（那等于换一种方式确认资源存在）。
    listing = await client.get(f"/api/comments?resource_id={rid}")
    assert listing.status_code == 404


async def test_delete_own_comment(client: AsyncClient, admin_user: dict, test_user: dict) -> None:
    rid = await _create_resource(client, admin_user, "Comment Own Delete")
    posted = (
        await client.post(
            "/api/comments",
            json={"resource_id": rid, "body": "自我删除测试"},
            headers=auth_headers(test_user),
        )
    ).json()
    other = await client.post(
        "/api/comments",
        json={"resource_id": rid, "body": "别人试图删"},
        headers=auth_headers(admin_user),
    )
    assert other.status_code == 201
    other_id = other.json()["id"]

    # 非本人非管理员（用 test_user 删 admin 的评论）→ 403
    forbidden = await client.delete(f"/api/comments/{other_id}", headers=auth_headers(test_user))
    assert forbidden.status_code == 403

    # 本人删除 → 204，列表清空
    r = await client.delete(f"/api/comments/{posted['id']}", headers=auth_headers(test_user))
    assert r.status_code == 204
    assert (await client.get(f"/api/comments?resource_id={rid}")).json()["meta"]["total"] == 1


async def test_admin_can_delete_any_comment(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    rid = await _create_resource(client, admin_user, "Comment Admin Delete")
    posted = (
        await client.post(
            "/api/comments",
            json={"resource_id": rid, "body": "管理员仲裁测试"},
            headers=auth_headers(test_user),
        )
    ).json()
    r = await client.delete(f"/api/comments/{posted['id']}", headers=auth_headers(admin_user))
    assert r.status_code == 204

    # 审计留痕
    audit = await client.get("/api/admin/audit-logs?limit=50", headers=auth_headers(admin_user))
    actions = [e["action"] for e in audit.json() if isinstance(e, dict) and "action" in e]
    assert "comment.delete" in actions


async def test_delete_missing_comment_404(client: AsyncClient, test_user: dict) -> None:
    r = await client.delete("/api/comments/999999", headers=auth_headers(test_user))
    assert r.status_code == 404


async def test_comment_xp_is_capped_per_day(client: AsyncClient, admin_user: dict) -> None:
    """L1 也能评论后，评论 XP 必须受每日上限约束，否则新号可刷级。"""
    from app.domain.gamification.xp import DAILY_COMMENT_XP_CAP, XP_RULES

    rid = await _create_resource(client, admin_user, "Comment XP Cap Target")
    user = await register_user(client, email="comment-xp-cap@example.com", username="commentxpcap")

    per_comment = XP_RULES["comment.create"]
    max_comments = DAILY_COMMENT_XP_CAP // per_comment
    assert max_comments >= 1

    for i in range(max_comments + 2):
        r = await client.post(
            "/api/comments",
            json={"resource_id": rid, "body": f"每日上限测试评论 {i}"},
            headers=auth_headers(user),
        )
        assert r.status_code == 201

    me = await client.get("/api/auth/me", headers=auth_headers(user))
    assert me.status_code == 200
    body = me.json()

    from app.domain.gamification.xp import XP_RULES as RULES

    baseline = RULES["register"]
    earned = body["xp"] - baseline
    assert earned == DAILY_COMMENT_XP_CAP, f"expected cap {DAILY_COMMENT_XP_CAP}, got {earned}"


# ---------------------------------------------------------------------------
# 评论审核（2026-11-07）：新评论落 pending，editor 可在后台通过/拒绝。
# ---------------------------------------------------------------------------


async def test_new_comment_lands_pending_but_still_publicly_visible(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """事后审核口径：写入 status=pending；前台仍展示（避免用户发完看不到自己的）。"""
    rid = await _create_resource(client, admin_user, "Pending Visible")
    posted = (
        await client.post(
            "/api/comments",
            json={"resource_id": rid, "body": "新评论待审"},
            headers=auth_headers(test_user),
        )
    ).json()

    # 前台：pending 评论仍展示（事后审核）
    listing = (await client.get(f"/api/comments?resource_id={rid}")).json()
    assert listing["meta"]["total"] == 1
    assert listing["data"][0]["id"] == posted["id"]
    # 前台 schema 不暴露 status 字段
    assert "status" not in listing["data"][0]

    # 后台：pending 列表能看到这条
    pending = (
        await client.get("/api/admin/comments?status=pending", headers=auth_headers(admin_user))
    ).json()
    assert pending["meta"]["total"] >= 1
    row = next(r for r in pending["data"] if r["id"] == posted["id"])
    assert row["status"] == "pending"
    assert row["resource_id"] == rid
    assert row["resource_title"] == "Pending Visible"
    assert row["author_name"] == test_user["username"]


async def test_admin_can_approve_then_reject_comment(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """approve → published；reject → rejected 且前台立即下架。"""
    rid = await _create_resource(client, admin_user, "Moderate Me")
    posted = (
        await client.post(
            "/api/comments",
            json={"resource_id": rid, "body": "待我裁决"},
            headers=auth_headers(test_user),
        )
    ).json()
    cid = posted["id"]

    # 先通过
    approved = await client.post(
        f"/api/admin/comments/{cid}/moderate",
        json={"action": "approve"},
        headers=auth_headers(admin_user),
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "published"
    assert approved.json()["moderated_by"] == admin_user["user_id"]
    assert approved.json()["moderated_at"] is not None

    # 前台仍在
    listing = (await client.get(f"/api/comments?resource_id={rid}")).json()
    assert listing["meta"]["total"] == 1

    # 再拒绝（带理由）
    rejected = await client.post(
        f"/api/admin/comments/{cid}/moderate",
        json={"action": "reject", "note": "含广告链接"},
        headers=auth_headers(admin_user),
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["moderation_note"] == "含广告链接"

    # 前台立即下架
    listing = (await client.get(f"/api/comments?resource_id={rid}")).json()
    assert listing["meta"]["total"] == 0
    assert listing["data"] == []

    # 后台 rejected 列表能查到
    rej = (
        await client.get("/api/admin/comments?status=rejected", headers=auth_headers(admin_user))
    ).json()
    assert any(r["id"] == cid for r in rej["data"])


async def test_admin_comment_list_status_filter_and_counts(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """顶部计数 + 状态筛选。"""
    rid = await _create_resource(client, admin_user, "Filter Me")
    c1 = (
        await client.post(
            "/api/comments",
            json={"resource_id": rid, "body": "待审 1"},
            headers=auth_headers(test_user),
        )
    ).json()["id"]
    c2 = (
        await client.post(
            "/api/comments",
            json={"resource_id": rid, "body": "待审 2"},
            headers=auth_headers(test_user),
        )
    ).json()["id"]

    counts = (
        await client.get("/api/admin/comments/counts", headers=auth_headers(admin_user))
    ).json()
    assert counts["pending"] >= 2
    assert counts["rejected"] >= 0

    # 通过 c1
    r = await client.post(
        f"/api/admin/comments/{c1}/moderate",
        json={"action": "approve"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200

    pending = (
        await client.get("/api/admin/comments?status=pending", headers=auth_headers(admin_user))
    ).json()
    pending_ids = [row["id"] for row in pending["data"]]
    assert c1 not in pending_ids
    assert c2 in pending_ids

    published = (
        await client.get("/api/admin/comments?status=published", headers=auth_headers(admin_user))
    ).json()
    assert c1 in [row["id"] for row in published["data"]]


async def test_non_editor_cannot_moderate_comments(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """普通读者（user 档位）打 admin 评论接口一律 403。"""
    rid = await _create_resource(client, admin_user, "No Permission")
    posted = (
        await client.post(
            "/api/comments",
            json={"resource_id": rid, "body": "普通用户想越权审"},
            headers=auth_headers(test_user),
        )
    ).json()

    r = await client.get("/api/admin/comments", headers=auth_headers(test_user))
    assert r.status_code == 403

    r = await client.get("/api/admin/comments/counts", headers=auth_headers(test_user))
    assert r.status_code == 403

    r = await client.post(
        f"/api/admin/comments/{posted['id']}/moderate",
        json={"action": "approve"},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 403

    # 未登录更不行
    r = await client.get("/api/admin/comments")
    assert r.status_code == 401


async def test_moderate_missing_comment_404(client: AsyncClient, admin_user: dict) -> None:
    r = await client.post(
        "/api/admin/comments/999999/moderate",
        json={"action": "approve"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 404
