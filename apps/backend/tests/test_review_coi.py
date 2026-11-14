"""P1-8：审稿人年度利益冲突声明与分派拦截。"""

from __future__ import annotations

from conftest import auth_headers, register_reviewer
from httpx import AsyncClient

_PAYLOAD = {
    "title": "COI Workflow Test",
    "type": "paper",
    "authors": ["Alice Author"],
    "year": 2024,
    "discipline": "computer science",
    "tags": ["test"],
    "abstract": "An abstract for the COI workflow test.",
    "preview": "A short preview for the COI workflow test.",
    "doi": "10.1234/test.coi.001",
}


async def _submission(client: AsyncClient, user: dict) -> dict:
    r = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(user))
    assert r.status_code == 201, r.text
    return r.json()


async def test_declaration_roundtrip_and_deduplication(
    client: AsyncClient, admin_user: dict
) -> None:
    reviewer = await register_reviewer(
        client, admin_user, "coi-reviewer", "coi-reviewer@example.com"
    )
    headers = auth_headers(reviewer)
    r = await client.get("/api/review/conflicts/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["declared"] is False

    r = await client.put(
        "/api/review/conflicts/me",
        json={
            "conflicts": ["  Alice Author  ", "alice author", "Example University"],
            "notes": "测试声明",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["declared"] is True
    assert body["conflicts"] == ["Alice Author", "Example University"]
    assert body["notes"] == "测试声明"

    r = await client.get("/api/review/conflicts/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["conflicts"] == ["Alice Author", "Example University"]


async def test_declared_conflict_blocks_single_assignment(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    reviewer = await register_reviewer(client, admin_user, "coi-blocker", "coi-blocker@example.com")
    await client.put(
        "/api/review/conflicts/me",
        json={"conflicts": ["Alice Author"]},
        headers=auth_headers(reviewer),
    )
    sub = await _submission(client, test_user)
    r = await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "reviewer_declared_conflict"
    assert "Alice Author" in detail["matched_terms"]


async def test_declaration_after_invitation_blocks_accept(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    reviewer = await register_reviewer(client, admin_user, "coi-late", "coi-late@example.com")
    sub = await _submission(client, test_user)
    r = await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 201, r.text
    assignment_id = r.json()["id"]

    # 收到邀请后才补报冲突：接受时必须再拦一次，而不是让冲突静默通过。
    r = await client.put(
        "/api/review/conflicts/me",
        json={"conflicts": ["Alice Author"]},
        headers=auth_headers(reviewer),
    )
    assert r.status_code == 200

    r = await client.post(
        f"/api/review/assignments/{assignment_id}/accept",
        headers=auth_headers(reviewer),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "reviewer_declared_conflict"


async def test_declared_conflict_blocks_bulk_assignment(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    reviewer = await register_reviewer(client, admin_user, "coi-bulk", "coi-bulk@example.com")
    await client.put(
        "/api/review/conflicts/me",
        json={"conflicts": ["ALICE AUTHOR"]},
        headers=auth_headers(reviewer),
    )
    sub = await _submission(client, test_user)
    r = await client.post(
        f"/api/review/submissions/{sub['id']}/assign",
        json={"reviewer_ids": [reviewer["user_id"]], "due_days": 14},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 409, r.text


async def test_candidate_payload_exposes_conflict_and_undeclared_state(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    reviewer = await register_reviewer(
        client, admin_user, "coi-candidate", "coi-candidate@example.com"
    )
    sub = await _submission(client, test_user)
    r = await client.get(
        f"/api/submissions/reviewer-candidates?submission_id={sub['id']}",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
    candidate = next(c for c in r.json()["data"] if c["username"] == "coi-candidate")
    assert candidate["coi_declared"] is False
    assert candidate["conflict"] is False

    await client.put(
        "/api/review/conflicts/me",
        json={"conflicts": ["Alice Author"]},
        headers=auth_headers(reviewer),
    )
    r = await client.get(
        f"/api/submissions/reviewer-candidates?submission_id={sub['id']}",
        headers=auth_headers(admin_user),
    )
    candidate = next(c for c in r.json()["data"] if c["username"] == "coi-candidate")
    assert candidate["coi_declared"] is True
    assert candidate["conflict"] is True
    assert candidate["conflict_reasons"] == ["Alice Author"]


async def test_author_without_reviewer_role_cannot_declare(
    client: AsyncClient, test_user: dict
) -> None:
    r = await client.get("/api/review/conflicts/me", headers=auth_headers(test_user))
    assert r.status_code == 403
