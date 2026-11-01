"""Integration tests for submission versioning (Phase 2.4).

Covers the gap this phase closes: before it, an author who received
"major revision" could only flip the status back — they could not
actually change the manuscript. Now:

- v1 is snapshotted at creation;
- the author can PATCH the submission in pending/major/minor revision;
- resubmit snapshots a new version with an optional author note;
- version history is visible to author + editor, not to strangers.
"""

from __future__ import annotations

from conftest import auth_headers, register_user
from httpx import AsyncClient

_PAYLOAD = {
    "title": "Versioning Test Manuscript",
    "type": "paper",
    "authors": ["Alice Author"],
    "year": 2024,
    "discipline": "economics",
    "tags": ["versioning"],
    "abstract": "The original abstract before any revision.",
    "preview": "Original preview.",
    "keywords": ["versions"],
    "jel_codes": ["C00"],
}


async def _create(client: AsyncClient, user: dict) -> dict:
    resp = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(user))
    resp.raise_for_status()
    return resp.json()


async def _to_major_revision(client: AsyncClient, admin_user: dict, submission_id: int) -> None:
    resp = await client.patch(
        f"/api/submissions/{submission_id}/decision",
        json={"decision": "major_revision", "editor_note": "Revise section 3."},
        headers=auth_headers(admin_user),
    )
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# v1 snapshot on creation
# ---------------------------------------------------------------------------


async def test_creation_snapshots_version_one(client: AsyncClient, test_user: dict) -> None:
    """创建投稿时立刻产生 v1 快照，内容与提交的 payload 一致。"""
    submission = await _create(client, test_user)

    resp = await client.get(
        f"/api/submissions/{submission['id']}/versions",
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 200
    versions = resp.json()["data"]
    assert len(versions) == 1
    v1 = versions[0]
    assert v1["version"] == 1
    assert v1["note"] is None
    assert v1["created_by"] == test_user["user_id"]
    assert v1["payload"]["title"] == _PAYLOAD["title"]
    assert v1["payload"]["abstract"] == _PAYLOAD["abstract"]
    # 工作流字段不进快照：版本 diff 只应包含作者写的内容
    assert "status" not in v1["payload"]
    assert "editor_note" not in v1["payload"]


# ---------------------------------------------------------------------------
# Author edit
# ---------------------------------------------------------------------------


async def test_author_can_edit_pending_submission(client: AsyncClient, test_user: dict) -> None:
    submission = await _create(client, test_user)

    resp = await client.patch(
        f"/api/submissions/{submission['id']}",
        json={"title": "Corrected Title", "abstract": "A corrected abstract."},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Corrected Title"
    assert body["abstract"] == "A corrected abstract."
    # 未提供的字段不变
    assert body["discipline"] == _PAYLOAD["discipline"]

    # 编辑本身不产生新版本（避免每敲一个字就一个版本）；历史仍是 v1
    versions = (
        await client.get(
            f"/api/submissions/{submission['id']}/versions",
            headers=auth_headers(test_user),
        )
    ).json()["data"]
    assert len(versions) == 1


async def test_author_can_edit_after_major_revision(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """这是本阶段补上的核心断链：修回后作者必须能真正改稿。"""
    submission = await _create(client, test_user)
    await _to_major_revision(client, admin_user, submission["id"])

    resp = await client.patch(
        f"/api/submissions/{submission['id']}",
        json={"abstract": "Rewritten methodology as requested by the editor."},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 200
    assert "Rewritten methodology" in resp.json()["abstract"]
    # 状态不因编辑而改变，仍待作者主动重投
    assert resp.json()["status"] == "major_revision"


async def test_author_cannot_edit_while_under_review(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """审稿人正在看的稿子不能被作者悄悄换掉。"""
    submission = await _create(client, test_user)
    await _to_major_revision(client, admin_user, submission["id"])
    resubmit = await client.post(
        f"/api/submissions/{submission['id']}/resubmit",
        headers=auth_headers(test_user),
    )
    assert resubmit.json()["status"] == "under_review"

    resp = await client.patch(
        f"/api/submissions/{submission['id']}",
        json={"title": "Sneaky Swap"},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 400
    assert "under_review" in resp.json()["detail"]


async def test_author_cannot_edit_after_rejection(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    submission = await _create(client, test_user)
    await client.patch(
        f"/api/submissions/{submission['id']}/decision",
        json={"decision": "reject"},
        headers=auth_headers(admin_user),
    )

    resp = await client.patch(
        f"/api/submissions/{submission['id']}",
        json={"title": "Too Late"},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 400


async def test_stranger_cannot_edit_submission(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """连 admin 都不能替作者改稿 —— 编辑要改内容得走决定流程。"""
    submission = await _create(client, test_user)

    resp = await client.patch(
        f"/api/submissions/{submission['id']}",
        json={"title": "Editor Rewrite"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 403


async def test_edit_validates_field_constraints(client: AsyncClient, test_user: dict) -> None:
    submission = await _create(client, test_user)

    resp = await client.patch(
        f"/api/submissions/{submission['id']}",
        json={"title": ""},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Resubmit → new version
# ---------------------------------------------------------------------------


async def test_resubmit_snapshots_edited_content_as_new_version(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    submission = await _create(client, test_user)
    await _to_major_revision(client, admin_user, submission["id"])
    await client.patch(
        f"/api/submissions/{submission['id']}",
        json={"abstract": "Second-round abstract with the requested changes."},
        headers=auth_headers(test_user),
    )

    resubmit = await client.post(
        f"/api/submissions/{submission['id']}/resubmit",
        json={"note": "扩写了方法论一节，补充了稳健性检验。"},
        headers=auth_headers(test_user),
    )
    assert resubmit.status_code == 200
    assert resubmit.json()["status"] == "under_review"

    versions = (
        await client.get(
            f"/api/submissions/{submission['id']}/versions",
            headers=auth_headers(test_user),
        )
    ).json()["data"]
    assert len(versions) == 2
    # 倒序：最新在前
    latest, first = versions
    assert latest["version"] == 2
    assert latest["note"] == "扩写了方法论一节，补充了稳健性检验。"
    assert "Second-round abstract" in latest["payload"]["abstract"]
    # v1 是不可变快照：原始摘要必须保持原样
    assert first["version"] == 1
    assert first["payload"]["abstract"] == _PAYLOAD["abstract"]


async def test_resubmit_without_body_still_works(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """向后兼容：旧客户端不带 body 调 resubmit 仍应成功。"""
    submission = await _create(client, test_user)
    await _to_major_revision(client, admin_user, submission["id"])

    resp = await client.post(
        f"/api/submissions/{submission['id']}/resubmit",
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 200

    versions = (
        await client.get(
            f"/api/submissions/{submission['id']}/versions",
            headers=auth_headers(test_user),
        )
    ).json()["data"]
    assert len(versions) == 2
    assert versions[0]["note"] is None


async def test_resubmit_note_reaches_editor_notification(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """作者修改说明要送达编辑，否则编辑得逐字段猜改了什么。"""
    submission = await _create(client, test_user)
    await _to_major_revision(client, admin_user, submission["id"])
    await client.post(
        f"/api/submissions/{submission['id']}/resubmit",
        json={"note": "已补充稳健性检验"},
        headers=auth_headers(test_user),
    )

    inbox = await client.get("/api/notifications", headers=auth_headers(admin_user))
    resubmitted = [n for n in inbox.json()["data"] if n["type"] == "submission.resubmitted"]
    assert resubmitted, "编辑应收到重投通知"
    assert "已补充稳健性检验" in resubmitted[0]["body"]
    assert "v2" in resubmitted[0]["body"]


# ---------------------------------------------------------------------------
# Version history visibility
# ---------------------------------------------------------------------------


async def test_editor_can_read_version_history(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    submission = await _create(client, test_user)

    resp = await client.get(
        f"/api/submissions/{submission['id']}/versions",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


async def test_stranger_cannot_read_version_history(client: AsyncClient, test_user: dict) -> None:
    submission = await _create(client, test_user)

    # 另一个普通用户
    outsider = await register_user(
        client, email="outsider_v@example.com", username="outsider_v", password="OutsiderPass123!"
    )

    resp = await client.get(
        f"/api/submissions/{submission['id']}/versions",
        headers={"Authorization": f"Bearer {outsider['token']}"},
    )
    assert resp.status_code == 403


async def test_version_history_requires_auth(client: AsyncClient, test_user: dict) -> None:
    submission = await _create(client, test_user)
    resp = await client.get(f"/api/submissions/{submission['id']}/versions")
    assert resp.status_code == 401
