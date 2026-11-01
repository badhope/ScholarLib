"""Comments module tests — public read, authed write, owner/admin delete."""

from __future__ import annotations

from conftest import auth_headers
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
    registered = await client.post(
        "/api/auth/register",
        json={
            "email": "comment-l1@example.com",
            "username": "comment_l1",
            "password": "password123",
        },
    )
    assert registered.status_code == 201
    token = registered.json()["access_token"]
    posted = await client.post(
        "/api/comments",
        json={"resource_id": rid, "body": "L1读者评论"},
        headers={"Authorization": f"Bearer {token}"},
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
