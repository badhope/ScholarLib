"""Integration tests for the submission module.

Three groups:

- Author side (auth, user sees their own only):
  POST /submissions, GET /submissions/me, GET /submissions/{id}
- Editor side (admin only):
  GET /submissions (list + filter), GET /submissions/pending,
  PATCH /submissions/{id}/review (approve / reject)
- Lifecycle / cross-module:
  Approval materializes a catalog Resource; the linked resource_id is
  returned. Reviewer re-review rejected/approved → 400. Submitter can
  delete own pending only.
"""

from __future__ import annotations

from conftest import auth_headers, complete_one_review, register_user
from httpx import AsyncClient

_PAYLOAD = {
    "title": "Quantum Foobar Revisited",
    "type": "paper",
    "authors": ["Alice Author", "Bob Coauthor"],
    "year": 2024,
    "venue": "Journal of Testing",
    "discipline": "physics",
    "subdiscipline": "quantum",
    "tags": ["quantum", "test"],
    "abstract": "A test submission abstract for the submission module.",
    "preview": "A short preview of the test submission.",
    "doi": "10.1234/test.001",
}


async def _create_submission(client: AsyncClient, user: dict, payload: dict | None = None) -> dict:
    body = payload if payload is not None else _PAYLOAD
    response = await client.post("/api/submissions", json=body, headers=auth_headers(user))
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Author side
# ---------------------------------------------------------------------------


async def test_create_requiresauth_headers(client: AsyncClient) -> None:
    response = await client.post("/api/submissions", json=_PAYLOAD)
    assert response.status_code == 401


async def test_create_submission(client: AsyncClient, test_user: dict) -> None:
    response = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(test_user))
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["status"] == "pending"
    assert body["title"] == _PAYLOAD["title"]
    assert body["submitted_by"] == test_user["user_id"]
    assert body["reviewed_by"] is None
    assert body["reviewed_at"] is None
    assert body["resource_id"] is None


async def test_create_without_preview_autofills_from_abstract(
    client: AsyncClient, test_user: dict
) -> None:
    """preview 留空时自动从 abstract 截取（避免首次投稿 422 摩擦点）。"""
    payload = dict(_PAYLOAD)
    payload.pop("preview")
    response = await client.post("/api/submissions", json=payload, headers=auth_headers(test_user))
    assert response.status_code == 201
    body = response.json()
    # preview 应被自动填充为 abstract 的截断
    assert body["preview"]
    assert body["preview"] == payload["abstract"][:500]


async def test_create_with_long_abstract_truncates_preview(
    client: AsyncClient, test_user: dict
) -> None:
    """超长 abstract 截取到 500 字（preview 上限 5000 字，自动填充只取 500）。"""
    payload = dict(_PAYLOAD)
    payload.pop("preview")
    long_abstract = "X" * 1000  # 1000 字 abstract
    payload["abstract"] = long_abstract
    response = await client.post("/api/submissions", json=payload, headers=auth_headers(test_user))
    assert response.status_code == 201
    body = response.json()
    # 截取到 500 字，不超 preview 字段上限
    assert len(body["preview"]) == 500
    assert body["preview"] == "X" * 500


async def test_list_my_submissions_empty(client: AsyncClient, test_user: dict) -> None:
    response = await client.get("/api/submissions/me", headers=auth_headers(test_user))
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


async def test_list_my_submissions_filter_by_status(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    # test_user submits two; admin approves one.
    s1 = await _create_submission(client, test_user, {**_PAYLOAD, "title": "S1"})
    s2 = await _create_submission(client, test_user, {**_PAYLOAD, "title": "S2"})
    review = await client.patch(
        f"/api/submissions/{s1['id']}/review",
        json={"status": "approved"},
        headers=auth_headers(admin_user),
    )
    assert review.status_code == 200

    # Filter pending only — should return s2 only.
    pending = await client.get(
        "/api/submissions/me?status=pending", headers=auth_headers(test_user)
    )
    body = pending.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == s2["id"]

    # Filter approved only — should return s1 only.
    approved = await client.get(
        "/api/submissions/me?status=approved", headers=auth_headers(test_user)
    )
    body = approved.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == s1["id"]


async def test_get_submission_owner_can_see_own(client: AsyncClient, test_user: dict) -> None:
    created = await _create_submission(client, test_user)
    response = await client.get(
        f"/api/submissions/{created['id']}", headers=auth_headers(test_user)
    )
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_get_submission_other_user_forbidden(client: AsyncClient, test_user: dict) -> None:
    """A different user cannot see someone else's submission."""
    created = await _create_submission(client, test_user)
    # Register a second user and try to read test_user's submission.
    second = await register_user(client, email="other@example.com", username="otheruser")
    response = await client.get(
        f"/api/submissions/{created['id']}",
        headers={"Authorization": f"Bearer {second['token']}"},
    )
    assert response.status_code == 403


async def test_get_submission_404(client: AsyncClient, test_user: dict) -> None:
    response = await client.get("/api/submissions/99999", headers=auth_headers(test_user))
    assert response.status_code == 404


async def test_create_rejects_invalid_type(client: AsyncClient, test_user: dict) -> None:
    response = await client.post(
        "/api/submissions",
        json={**_PAYLOAD, "type": "not-a-real-type"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Editor side
# ---------------------------------------------------------------------------


async def test_admin_list_requires_admin(client: AsyncClient, test_user: dict) -> None:
    response = await client.get("/api/submissions", headers=auth_headers(test_user))
    assert response.status_code == 403


async def test_admin_list_shows_all(client: AsyncClient, admin_user: dict, test_user: dict) -> None:
    await _create_submission(client, test_user, {**_PAYLOAD, "title": "First"})
    await _create_submission(client, test_user, {**_PAYLOAD, "title": "Second"})
    response = await client.get("/api/submissions", headers=auth_headers(admin_user))
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 2


async def test_admin_pending_list(client: AsyncClient, admin_user: dict, test_user: dict) -> None:
    s1 = await _create_submission(client, test_user, {**_PAYLOAD, "title": "P1"})
    await _create_submission(client, test_user, {**_PAYLOAD, "title": "P2"})

    # Approve s1 — pending list should now contain only P2.
    review = await client.patch(
        f"/api/submissions/{s1['id']}/review",
        json={"status": "approved"},
        headers=auth_headers(admin_user),
    )
    assert review.status_code == 200

    pending = await client.get("/api/submissions/pending", headers=auth_headers(admin_user))
    body = pending.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["title"] == "P2"


async def test_review_requires_admin(client: AsyncClient, test_user: dict) -> None:
    created = await _create_submission(client, test_user)
    response = await client.patch(
        f"/api/submissions/{created['id']}/review",
        json={"status": "approved"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 403


async def test_review_404(client: AsyncClient, admin_user: dict) -> None:
    response = await client.patch(
        "/api/submissions/99999/review",
        json={"status": "approved"},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 404


async def test_approve_materializes_resource(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """Approving without resource_id creates a catalog Resource and links it."""
    created = await _create_submission(client, test_user)
    review = await client.patch(
        f"/api/submissions/{created['id']}/review",
        json={"status": "approved"},
        headers=auth_headers(admin_user),
    )
    assert review.status_code == 200
    body = review.json()
    assert body["status"] == "approved"
    assert body["resource_id"] is not None
    assert body["reviewed_by"] == admin_user["user_id"]
    assert body["reviewed_at"] is not None

    # The linked catalog Resource exists and matches the submission.
    resource = await client.get(f"/api/catalog/{body['resource_id']}")
    assert resource.status_code == 200
    rbody = resource.json()
    assert rbody["title"] == _PAYLOAD["title"]
    assert rbody["doi"] == _PAYLOAD["doi"]


async def test_approve_links_to_existing_resource(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """Approving with resource_id links the submission to that Resource."""
    # First create a catalog Resource as admin.
    resource_payload = {
        "type": "paper",
        "title": "Existing Catalog Resource",
        "authors": ["Existing Author"],
        "year": 2023,
        "discipline": "physics",
        "tags": ["existing"],
        "abstract": "An existing catalog resource abstract.",
        "preview": "An existing catalog resource preview.",
    }
    create_resource = await client.post(
        "/api/catalog", json=resource_payload, headers=auth_headers(admin_user)
    )
    create_resource.raise_for_status()
    existing_rid = create_resource.json()["id"]

    # Submit a record and approve it with the existing resource_id.
    created = await _create_submission(client, test_user)
    review = await client.patch(
        f"/api/submissions/{created['id']}/review",
        json={"status": "approved", "resource_id": existing_rid},
        headers=auth_headers(admin_user),
    )
    assert review.status_code == 200
    body = review.json()
    assert body["resource_id"] == existing_rid


async def test_accept_hold_draft_gates_public_visibility(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """录用暂存（publication_status='draft'）：物化条目对外 404，编辑与
    作者本人可刊前预览；admin 刊出后对公众开放——补齐录用→刊出之间的
    刊前整理环节。"""
    created = await _create_submission(client, test_user)
    # 录用要求至少一份已完成的审稿意见：先走完一轮评审。
    await complete_one_review(client, admin_user, created["id"])
    decision = await client.patch(
        f"/api/submissions/{created['id']}/decision",
        json={"decision": "accept", "publication_status": "draft"},
        headers=auth_headers(admin_user),
    )
    assert decision.status_code == 200
    body = decision.json()
    assert body["status"] == "accepted"
    rid = body["resource_id"]
    assert rid is not None

    # 匿名：不确认存在；作者本人：可预览草稿详情。
    # （文件端点此处 404 属预期——该 helper 的投稿未上传稿件文件，
    #   "no downloadable file"；带文件的刊前预览由 test_catalog 的
    #   editor 用例覆盖。）
    assert (await client.get(f"/api/catalog/{rid}")).status_code == 404
    author_detail = await client.get(f"/api/catalog/{rid}", headers=auth_headers(test_user))
    assert author_detail.status_code == 200
    assert author_detail.json()["publication_status"] == "draft"

    # admin 刊出：PATCH catalog 后对公众开放。
    publish = await client.patch(
        f"/api/catalog/{rid}",
        json={"publication_status": "published"},
        headers=auth_headers(admin_user),
    )
    assert publish.status_code == 200
    assert (await client.get(f"/api/catalog/{rid}")).status_code == 200


async def test_accept_default_publishes_immediately(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """默认录用即刊（兼容旧行为）：不带 publication_status 时物化条目
    立即对公众可见。"""
    created = await _create_submission(client, test_user)
    await complete_one_review(client, admin_user, created["id"])
    decision = await client.patch(
        f"/api/submissions/{created['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    assert decision.status_code == 200
    rid = decision.json()["resource_id"]
    assert rid is not None
    assert (await client.get(f"/api/catalog/{rid}")).status_code == 200


async def test_approve_with_nonexistent_resource_id_400(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    created = await _create_submission(client, test_user)
    review = await client.patch(
        f"/api/submissions/{created['id']}/review",
        json={"status": "approved", "resource_id": 99999},
        headers=auth_headers(admin_user),
    )
    assert review.status_code == 400
    assert "does not exist" in review.json()["detail"]


async def test_reject_does_not_create_resource(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    created = await _create_submission(client, test_user)
    review = await client.patch(
        f"/api/submissions/{created['id']}/review",
        json={"status": "rejected", "admin_note": "Out of scope"},
        headers=auth_headers(admin_user),
    )
    assert review.status_code == 200
    body = review.json()
    assert body["status"] == "rejected"
    assert body["resource_id"] is None
    assert body["admin_note"] == "Out of scope"


async def test_reject_re_review_400(client: AsyncClient, admin_user: dict, test_user: dict) -> None:
    """A reviewed submission cannot be re-reviewed."""
    created = await _create_submission(client, test_user)
    first = await client.patch(
        f"/api/submissions/{created['id']}/review",
        json={"status": "rejected"},
        headers=auth_headers(admin_user),
    )
    assert first.status_code == 200
    second = await client.patch(
        f"/api/submissions/{created['id']}/review",
        json={"status": "approved"},
        headers=auth_headers(admin_user),
    )
    assert second.status_code == 400
    assert "already been reviewed" in second.json()["detail"]


async def test_review_rejects_invalid_status(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    created = await _create_submission(client, test_user)
    response = await client.patch(
        f"/api/submissions/{created['id']}/review",
        json={"status": "pending"},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Deletion lifecycle
# ---------------------------------------------------------------------------


async def test_submitter_can_delete_own_pending(client: AsyncClient, test_user: dict) -> None:
    created = await _create_submission(client, test_user)
    response = await client.delete(
        f"/api/submissions/{created['id']}", headers=auth_headers(test_user)
    )
    assert response.status_code == 200
    # Subsequent GET → 404.
    assert (
        await client.get(f"/api/submissions/{created['id']}", headers=auth_headers(test_user))
    ).status_code == 404


async def test_submitter_cannot_delete_reviewed(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    created = await _create_submission(client, test_user)
    await client.patch(
        f"/api/submissions/{created['id']}/review",
        json={"status": "approved"},
        headers=auth_headers(admin_user),
    )
    response = await client.delete(
        f"/api/submissions/{created['id']}", headers=auth_headers(test_user)
    )
    assert response.status_code == 400
    assert "Cannot delete a reviewed submission" in response.json()["detail"]


async def test_other_user_cannot_delete(client: AsyncClient, test_user: dict) -> None:
    created = await _create_submission(client, test_user)
    second = await register_user(client, email="other2@example.com", username="otheruser2")
    response = await client.delete(
        f"/api/submissions/{created['id']}",
        headers={"Authorization": f"Bearer {second['token']}"},
    )
    assert response.status_code == 403
