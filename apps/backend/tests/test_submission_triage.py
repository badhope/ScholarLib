"""P1-9：两段式初筛（triage）。"""

from __future__ import annotations

from conftest import auth_headers
from httpx import AsyncClient

_PAYLOAD = {
    "title": "Triage Workflow Test",
    "type": "paper",
    "authors": ["Triage Author"],
    "year": 2024,
    "discipline": "computer science",
    "tags": ["test"],
    "abstract": "An abstract for the triage workflow test.",
    "preview": "A short preview for the triage workflow test.",
    "doi": "10.1234/test.triage.001",
}


async def _submission(
    client: AsyncClient, user: dict, doi: str = "10.1234/test.triage.001"
) -> dict:
    payload = dict(_PAYLOAD)
    payload["doi"] = doi
    r = await client.post("/api/submissions", json=payload, headers=auth_headers(user))
    assert r.status_code == 201, r.text
    return r.json()


async def test_triage_queue_starts_with_new_submission(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    sub = await _submission(client, test_user, "10.1234/test.triage.queue")
    r = await client.get("/api/submissions/triage", headers=auth_headers(admin_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["total"] >= 1
    assert any(item["id"] == sub["id"] for item in body["data"])
    item = next(x for x in body["data"] if x["id"] == sub["id"])
    assert item["triage_status"] == "pending"
    assert item["status"] == "pending"


async def test_send_to_review_marks_passed_and_keeps_pending(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    sub = await _submission(client, test_user, "10.1234/test.triage.pass")
    r = await client.post(
        f"/api/submissions/{sub['id']}/triage",
        json={"decision": "send_to_review", "note": "选题与格式符合当版要求"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["triage_status"] == "passed"
    assert body["status"] == "pending"
    assert body["triaged_by"] == admin_user["user_id"]

    # 已初筛的稿件不应再出现在初筛队列
    r = await client.get("/api/submissions/triage", headers=auth_headers(admin_user))
    assert all(item["id"] != sub["id"] for item in r.json()["data"])

    # 再初筛一次应 409，不能无限改判
    r = await client.post(
        f"/api/submissions/{sub['id']}/triage",
        json={"decision": "desk_reject", "note": "改判理由足够长但不应允许"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 409


async def test_return_for_revision_requires_reason_and_sets_major_revision(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    sub = await _submission(client, test_user, "10.1234/test.triage.rework")
    r = await client.post(
        f"/api/submissions/{sub['id']}/triage",
        json={"decision": "return_for_revision", "note": "太短"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 422

    r = await client.post(
        f"/api/submissions/{sub['id']}/triage",
        json={
            "decision": "return_for_revision",
            "note": "图表编号与正文不一致，请按模板重排后再投。",
        },
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["triage_status"] == "rework"
    assert body["status"] == "major_revision"
    assert body["editor_note"] == "图表编号与正文不一致，请按模板重排后再投。"


async def test_desk_reject_is_terminal_and_audited(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    sub = await _submission(client, test_user, "10.1234/test.triage.reject")
    r = await client.post(
        f"/api/submissions/{sub['id']}/triage",
        json={
            "decision": "desk_reject",
            "note": "与刊物范围不符，建议改投专门期刊。",
        },
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["triage_status"] == "rejected"
    assert body["status"] == "rejected"
    assert body["triaged_at"] is not None


async def test_assignment_implicitly_passes_triage(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """存量流程仍然可一直接分派；分派即视为初筛通过，不让旧调用断掉。"""
    from conftest import register_reviewer

    reviewer = await register_reviewer(
        client, admin_user, "triage-reviewer", "triage-reviewer@example.com"
    )
    sub = await _submission(client, test_user, "10.1234/test.triage.assign")
    r = await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 201, r.text
    r = await client.get(f"/api/submissions/{sub['id']}", headers=auth_headers(admin_user))
    assert r.status_code == 200
    assert r.json()["triage_status"] == "passed"
    assert r.json()["status"] == "under_review"
