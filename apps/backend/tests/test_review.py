"""Integration tests for the peer-review workflow.

Covers:
- Reviewer role enforcement (403 for non-reviewers; admin bypass).
- Editor→reviewer assignment lifecycle + 4-元 decision state machine.
- Reviewer side: accept / decline / submit report (terminal).
- Single-blind report visibility: author sees only comments_to_author,
  editor sees comments_to_editor.
- Author resubmit after major_revision / minor_revision.
- File upload: MIME whitelist, owner-only, status gate.
"""

from __future__ import annotations

from io import BytesIO

from conftest import auth_headers, register_reviewer, review_scores
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role, Tenant, UserRole

_PAYLOAD = {
    "title": "Peer-Review Workflow Test",
    "type": "paper",
    "authors": ["Alice Author"],
    "year": 2024,
    "discipline": "computer science",
    "tags": ["test"],
    "abstract": "An abstract for the peer-review workflow test.",
    "preview": "A short preview for the test.",
    "doi": "10.1234/test.review.001",
    "keywords": ["peer review", "workflow"],
    "jel_codes": ["C00"],
}


async def _create_submission(client: AsyncClient, user: dict, payload: dict | None = None) -> dict:
    body = payload if payload is not None else _PAYLOAD
    response = await client.post("/api/submissions", json=body, headers=auth_headers(user))
    response.raise_for_status()
    return response.json()


async def _grant_reviewer_role(db_session: AsyncSession, tenant: Tenant, user_id: int) -> None:
    """把 reviewer 角色授给一个普通用户（绕开 bootstrap；测试环境跳过 bootstrap）。"""
    role = (
        await db_session.execute(
            select(Role).where(
                Role.tenant_id == tenant.id,
                Role.name == "reviewer",
            )
        )
    ).scalar_one_or_none()
    if role is None:
        role = Role(
            tenant_id=tenant.id,
            name="reviewer",
            description="Test reviewer role",
        )
        db_session.add(role)
        await db_session.flush()
    existing = (
        await db_session.execute(
            select(UserRole).where(
                UserRole.tenant_id == tenant.id,
                UserRole.user_id == user_id,
                UserRole.role_id == role.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db_session.add(
            UserRole(
                tenant_id=tenant.id,
                user_id=user_id,
                role_id=role.id,
            )
        )
        await db_session.commit()


# ---------------------------------------------------------------------------
# Reviewer role enforcement
# ---------------------------------------------------------------------------


async def test_reviewer_endpoints_require_role(client: AsyncClient, test_user: dict) -> None:
    """普通用户（无 reviewer 角色、非 admin）不能访问审稿人端点。"""
    resp = await client.get("/api/review/assignments/me", headers=auth_headers(test_user))
    assert resp.status_code == 403
    assert "Reviewer role required" in resp.json()["detail"]


async def test_admin_bypasses_reviewer_role(client: AsyncClient, admin_user: dict) -> None:
    """admin 通过 is_admin=True 绕过 role 检查，能直接访问审稿人端点。"""
    resp = await client.get("/api/review/assignments/me", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []


async def test_reviewer_role_grants_access(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: dict,
) -> None:
    """显式授予 reviewer 角色后，普通用户也能访问。"""
    # Warm tenant + fetch it
    await client.get("/api/health")
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    await _grant_reviewer_role(db_session, tenant, int(test_user["user_id"]))

    resp = await client.get("/api/review/assignments/me", headers=auth_headers(test_user))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Editor assigns reviewer → submission transitions to under_review
# ---------------------------------------------------------------------------


async def test_assign_reviewer_transitions_pending_to_under_review(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    submission = await _create_submission(client, test_user)
    assert submission["status"] == "pending"

    resp = await client.post(
        f"/api/submissions/{submission['id']}/assignments",
        json={"reviewer_id": admin_user["user_id"]},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201
    assignment = resp.json()
    assert assignment["status"] == "pending"
    assert assignment["reviewer_id"] == admin_user["user_id"]
    assert assignment["reviewer_username"] == "adminuser"
    assert assignment["submission_title"] == submission["title"]

    # Submission should now be under_review
    after = await client.get(
        f"/api/submissions/{submission['id']}", headers=auth_headers(test_user)
    )
    assert after.json()["status"] == "under_review"


async def test_assign_reviewer_unique_constraint(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """同一审稿人对同一稿件只能被分配一次。"""
    submission = await _create_submission(client, test_user)
    body = {"reviewer_id": admin_user["user_id"]}
    first = await client.post(
        f"/api/submissions/{submission['id']}/assignments",
        json=body,
        headers=auth_headers(admin_user),
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/submissions/{submission['id']}/assignments",
        json=body,
        headers=auth_headers(admin_user),
    )
    assert second.status_code == 409


async def test_second_reviewer_gets_next_slot_after_completed_review(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """补派审稿人不能复用已完成审稿人的 slot。"""
    submission = await _create_submission(client, test_user)
    first = await client.post(
        f"/api/submissions/{submission['id']}/assignments",
        json={"reviewer_id": admin_user["user_id"]},
        headers=auth_headers(admin_user),
    )
    assert first.status_code == 201
    assert first.json()["slot"] == 1
    assignment_id = first.json()["id"]
    await client.post(
        f"/api/review/assignments/{assignment_id}/accept", headers=auth_headers(admin_user)
    )
    report = await client.post(
        f"/api/review/assignments/{assignment_id}/submit",
        json={
            "recommendation": "minor_revision",
            "scores": review_scores(72),
            "comments_to_author": "Please clarify.",
        },
        headers=auth_headers(admin_user),
    )
    assert report.status_code == 201

    second_user = await register_reviewer(client, admin_user, "slot_two", "slot_two@example.com")
    second = await client.post(
        f"/api/submissions/{submission['id']}/assignments",
        json={"reviewer_id": second_user["user_id"]},
        headers=auth_headers(admin_user),
    )
    assert second.status_code == 201
    assert second.json()["slot"] == 2


async def test_assign_reviewer_to_nonexistent_user_400(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    submission = await _create_submission(client, test_user)
    resp = await client.post(
        f"/api/submissions/{submission['id']}/assignments",
        json={"reviewer_id": 99999},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()


async def test_list_assignments_for_submission(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    submission = await _create_submission(client, test_user)
    await client.post(
        f"/api/submissions/{submission['id']}/assignments",
        json={"reviewer_id": admin_user["user_id"]},
        headers=auth_headers(admin_user),
    )
    resp = await client.get(
        f"/api/submissions/{submission['id']}/assignments",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["reviewer_username"] == "adminuser"


async def test_cancel_assignment(client: AsyncClient, admin_user: dict, test_user: dict) -> None:
    submission = await _create_submission(client, test_user)
    assignment = (
        await client.post(
            f"/api/submissions/{submission['id']}/assignments",
            json={"reviewer_id": admin_user["user_id"]},
            headers=auth_headers(admin_user),
        )
    ).json()
    resp = await client.delete(
        f"/api/submissions/{submission['id']}/assignments/{assignment['id']}",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    # Verify cancelled
    listing = await client.get(
        f"/api/submissions/{submission['id']}/assignments",
        headers=auth_headers(admin_user),
    )
    assert listing.json()["data"][0]["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Reviewer side: accept / decline / submit report
# ---------------------------------------------------------------------------


async def _setup_assignment(client: AsyncClient, admin_user: dict, test_user: dict) -> dict:
    """Helper: 创建 submission + 分配 admin 作为审稿人。"""
    submission = await _create_submission(client, test_user)
    resp = await client.post(
        f"/api/submissions/{submission['id']}/assignments",
        json={"reviewer_id": admin_user["user_id"]},
        headers=auth_headers(admin_user),
    )
    resp.raise_for_status()
    return {"submission": submission, "assignment": resp.json()}


async def test_reviewer_accept_assignment(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]

    resp = await client.post(
        f"/api/review/assignments/{assignment_id}/accept",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


async def test_reviewer_cannot_accept_twice(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]
    first = await client.post(
        f"/api/review/assignments/{assignment_id}/accept",
        headers=auth_headers(admin_user),
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/review/assignments/{assignment_id}/accept",
        headers=auth_headers(admin_user),
    )
    assert second.status_code == 400


async def test_reviewer_decline_assignment(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]
    resp = await client.post(
        f"/api/review/assignments/{assignment_id}/decline",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "declined"


async def test_reviewer_submit_report_without_accept_400(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """必须先 accept 才能 submit。"""
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]
    resp = await client.post(
        f"/api/review/assignments/{assignment_id}/submit",
        json={
            "recommendation": "accept",
            "scores": review_scores(),
            "comments_to_author": "Good work",
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 400


async def test_reviewer_submit_report_full(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """完整审稿报告提交：accept → submit。"""
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]
    await client.post(
        f"/api/review/assignments/{assignment_id}/accept",
        headers=auth_headers(admin_user),
    )
    resp = await client.post(
        f"/api/review/assignments/{assignment_id}/submit",
        json={
            "recommendation": "minor_revision",
            "scores": review_scores(72),
            "comments_to_editor": "Need minor revisions to methodology.",
            "comments_to_author": "Please clarify section 3.2.",
        },
        headers=auth_headers(admin_user),
    )
    # 201: the report is a newly created resource (was 200, fixed per T2 L-1).
    assert resp.status_code == 201
    body = resp.json()
    assert body["recommendation"] == "minor_revision"
    assert body["comments_to_editor"] == "Need minor revisions to methodology."
    assert body["comments_to_author"] == "Please clarify section 3.2."

    # Assignment should now be completed
    listing = await client.get(
        f"/api/submissions/{setup['submission']['id']}/assignments",
        headers=auth_headers(admin_user),
    )
    assert listing.json()["data"][0]["status"] == "completed"


async def test_reviewer_cannot_submit_twice(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]
    await client.post(
        f"/api/review/assignments/{assignment_id}/accept",
        headers=auth_headers(admin_user),
    )
    body = {
        "recommendation": "accept",
        "scores": review_scores(),
        "comments_to_author": "OK",
    }
    first = await client.post(
        f"/api/review/assignments/{assignment_id}/submit",
        json=body,
        headers=auth_headers(admin_user),
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/review/assignments/{assignment_id}/submit",
        json=body,
        headers=auth_headers(admin_user),
    )
    assert second.status_code == 400


async def test_reviewer_can_only_see_own_assignment(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """审稿人不能查看分配给其他人的 assignment。"""
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]
    # test_user 不是这个 assignment 的审稿人，应 403
    resp = await client.get(
        f"/api/review/assignments/{assignment_id}",
        headers=auth_headers(test_user),
    )
    # test_user 没有 reviewer 角色 → 403
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Editor 4-元 decision
# ---------------------------------------------------------------------------


async def test_decision_accept_materializes_resource(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    submission = await _create_submission(client, test_user)
    from conftest import complete_two_reviews

    await complete_two_reviews(client, admin_user, submission["id"])
    resp = await client.patch(
        f"/api/submissions/{submission['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["resource_id"] is not None
    # Resource 可在 catalog 中查到
    resource = await client.get(f"/api/catalog/{body['resource_id']}")
    assert resource.status_code == 200
    assert resource.json()["title"] == _PAYLOAD["title"]


async def test_decision_accept_notification_deep_links_to_resource(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """录用通知的 related 必须指向物化出的公开 Resource（作者点通知直达发表页）。"""
    submission = await _create_submission(client, test_user)
    from conftest import complete_two_reviews

    await complete_two_reviews(client, admin_user, submission["id"])
    resp = await client.patch(
        f"/api/submissions/{submission['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    resource_id = resp.json()["resource_id"]
    assert resource_id is not None

    inbox = await client.get("/api/notifications", headers=auth_headers(test_user))
    assert inbox.status_code == 200
    decisions = [n for n in inbox.json()["data"] if n["type"] == "submission.decision"]
    assert decisions, "作者应收到稿件决定通知"
    latest = decisions[0]
    assert latest["related_type"] == "resource"
    assert latest["related_id"] == str(resource_id)
    assert "录用" in latest["body"]


async def test_decision_major_revision_then_resubmit(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    submission = await _create_submission(client, test_user)
    decision = await client.patch(
        f"/api/submissions/{submission['id']}/decision",
        json={
            "decision": "major_revision",
            "editor_note": "Please revise the methodology.",
        },
        headers=auth_headers(admin_user),
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "major_revision"
    assert decision.json()["editor_note"] == "Please revise the methodology."

    # 作者重投
    resubmit = await client.post(
        f"/api/submissions/{submission['id']}/resubmit",
        headers=auth_headers(test_user),
    )
    assert resubmit.status_code == 200
    assert resubmit.json()["status"] == "under_review"


async def test_decision_reject_is_terminal(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    submission = await _create_submission(client, test_user)
    first = await client.patch(
        f"/api/submissions/{submission['id']}/decision",
        json={"decision": "reject"},
        headers=auth_headers(admin_user),
    )
    assert first.status_code == 200
    assert first.json()["status"] == "rejected"
    # 第二次决策应 400
    second = await client.patch(
        f"/api/submissions/{submission['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    assert second.status_code == 400


async def test_decision_invalid_state_400(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """已 accept 的稿件不能再决断。"""
    submission = await _create_submission(client, test_user)
    from conftest import complete_two_reviews

    await complete_two_reviews(client, admin_user, submission["id"])
    await client.patch(
        f"/api/submissions/{submission['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    resp = await client.patch(
        f"/api/submissions/{submission['id']}/decision",
        json={"decision": "reject"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 400


async def test_decision_requires_editor_role(client: AsyncClient, test_user: dict) -> None:
    submission = await _create_submission(client, test_user)
    resp = await client.patch(
        f"/api/submissions/{submission['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 403
    # 四元决定是 L8 职权（require_chief_editor），普通作者/读者不可越权
    assert "Chief editor role required" in resp.json()["detail"]


async def test_resubmit_only_author(client: AsyncClient, admin_user: dict, test_user: dict) -> None:
    """非作者不能重投。"""
    submission = await _create_submission(client, test_user)
    await client.patch(
        f"/api/submissions/{submission['id']}/decision",
        json={"decision": "major_revision"},
        headers=auth_headers(admin_user),
    )
    # admin 不是作者，但 admin 也不能 resubmit
    resp = await client.post(
        f"/api/submissions/{submission['id']}/resubmit",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 403


async def test_resubmit_invalid_state_400(client: AsyncClient, test_user: dict) -> None:
    """pending 状态的稿件不能 resubmit。"""
    submission = await _create_submission(client, test_user)
    resp = await client.post(
        f"/api/submissions/{submission['id']}/resubmit",
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Single-blind report visibility
# ---------------------------------------------------------------------------


async def test_author_sees_only_comments_to_author(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """作者查看报告：剥离 comments_to_editor（单盲）。"""
    setup = await _setup_assignment(client, admin_user, test_user)
    submission_id = setup["submission"]["id"]
    assignment_id = setup["assignment"]["id"]

    await client.post(
        f"/api/review/assignments/{assignment_id}/accept",
        headers=auth_headers(admin_user),
    )
    await client.post(
        f"/api/review/assignments/{assignment_id}/submit",
        json={
            "recommendation": "major_revision",
            "scores": review_scores(68),
            "comments_to_editor": "Confidential note to editor.",
            "comments_to_author": "Visible to author.",
        },
        headers=auth_headers(admin_user),
    )

    # 作者视角：comments_to_editor 必须为 None
    resp = await client.get(
        f"/api/submissions/{submission_id}/reports",
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 200
    reports = resp.json()
    assert len(reports) == 1
    assert reports[0]["comments_to_author"] == "Visible to author."
    assert reports[0]["comments_to_editor"] is None


async def test_editor_sees_full_report(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """编辑视角：完整报告，包含 comments_to_editor。"""
    setup = await _setup_assignment(client, admin_user, test_user)
    submission_id = setup["submission"]["id"]
    assignment_id = setup["assignment"]["id"]

    await client.post(
        f"/api/review/assignments/{assignment_id}/accept",
        headers=auth_headers(admin_user),
    )
    await client.post(
        f"/api/review/assignments/{assignment_id}/submit",
        json={
            "recommendation": "accept",
            "scores": review_scores(95),
            "comments_to_editor": "Editor-only confidential note.",
            "comments_to_author": "Great paper.",
        },
        headers=auth_headers(admin_user),
    )

    resp = await client.get(
        f"/api/submissions/{submission_id}/reports",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    reports = resp.json()
    assert len(reports) == 1
    assert reports[0]["comments_to_editor"] == "Editor-only confidential note."
    assert reports[0]["comments_to_author"] == "Great paper."


async def test_reports_list_empty_when_no_completed(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """无 completed 报告时返回空列表。"""
    setup = await _setup_assignment(client, admin_user, test_user)
    resp = await client.get(
        f"/api/submissions/{setup['submission']['id']}/reports",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------


async def test_upload_file_pdf(client: AsyncClient, test_user: dict, tmp_path) -> None:
    """作者上传合法 PDF → file_path 入库。"""
    submission = await _create_submission(client, test_user)
    pdf_bytes = b"%PDF-1.4\n%test content\n%%EOF"
    resp = await client.post(
        f"/api/submissions/{submission['id']}/files",
        files={
            "file": (
                "paper.pdf",
                BytesIO(pdf_bytes),
                "application/pdf",
            )
        },
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["file_path"] is not None
    assert str(body["id"]) in body["file_path"]
    assert body["file_path"].endswith(".pdf")


async def test_upload_file_invalid_mime(client: AsyncClient, test_user: dict) -> None:
    """非法类型应 400。

    注意：图片（.png/.svg 等）自 0.9.1 起是**允许**的——期刊常要求单独提交
    300 dpi 图件。这里用可执行文件作为非法样例，并断言错误信息给出可接受清单。
    """
    submission = await _create_submission(client, test_user)
    resp = await client.post(
        f"/api/submissions/{submission['id']}/files",
        files={
            "file": (
                "installer.exe",
                BytesIO(b"MZ\x90\x00" + b"0" * 100),
                "application/x-msdownload",
            )
        },
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]
    assert ".pdf" in resp.json()["detail"]


async def test_upload_file_non_owner_403(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """非作者上传应 403。"""
    submission = await _create_submission(client, test_user)
    resp = await client.post(
        f"/api/submissions/{submission['id']}/files",
        files={
            "file": (
                "paper.pdf",
                BytesIO(b"%PDF-1.4"),
                "application/pdf",
            )
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 403


async def test_upload_file_under_review_allowed(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """under_review 状态下允许作者替换稿件文件（编辑可能要求更新版本）。

    之前禁止 under_review 上传是过度限制：编辑在审稿过程中要求作者换一份
    PDF 是常见场景，强制让作者删了重投反而割裂 workflow。
    accepted/rejected 终态仍拒绝上传（保留历史不可篡改）。
    """
    submission = await _create_submission(client, test_user)
    # 分配审稿人 → under_review
    await client.post(
        f"/api/submissions/{submission['id']}/assignments",
        json={"reviewer_id": admin_user["user_id"]},
        headers=auth_headers(admin_user),
    )
    resp = await client.post(
        f"/api/submissions/{submission['id']}/files",
        files={
            "file": (
                "paper.pdf",
                BytesIO(b"%PDF-1.4"),
                "application/pdf",
            )
        },
        headers=auth_headers(test_user),
    )
    # under_review 现在允许上传（替换式覆盖 file_path）
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Reviewer assignment list endpoint (reviewer's own view)
# ---------------------------------------------------------------------------


async def test_reviewer_list_my_assignments_filter(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """分配后审稿人能在 /review/assignments/me 看到任务，且可按 status 过滤。"""
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]

    # 默认列表
    resp = await client.get("/api/review/assignments/me", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 1
    ids = [a["id"] for a in body["data"]]
    assert assignment_id in ids

    # 过滤 pending
    pending = await client.get(
        "/api/review/assignments/me?status=pending",
        headers=auth_headers(admin_user),
    )
    assert pending.status_code == 200
    for a in pending.json()["data"]:
        assert a["status"] == "pending"

    # accept 后过滤 accepted
    await client.post(
        f"/api/review/assignments/{assignment_id}/accept",
        headers=auth_headers(admin_user),
    )
    accepted = await client.get(
        "/api/review/assignments/me?status=accepted",
        headers=auth_headers(admin_user),
    )
    assert accepted.status_code == 200
    found = [a for a in accepted.json()["data"] if a["id"] == assignment_id]
    assert len(found) == 1
    assert found[0]["submission_title"] == setup["submission"]["title"]


# ---------------------------------------------------------------------------
# Reviewer views submission detail (abstract / file_path / etc.)
# ---------------------------------------------------------------------------


async def test_reviewer_can_view_submission_detail(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """审稿人通过 assignment 端点获取稿件完整内容（abstract / preview / authors）。"""
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]

    resp = await client.get(
        f"/api/review/assignments/{assignment_id}/submission",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    # 必须返回完整字段，而非仅 title
    assert body["abstract"] == setup["submission"]["abstract"]
    assert body["preview"] == setup["submission"]["preview"]
    assert body["authors"] == setup["submission"]["authors"]
    assert body["title"] == setup["submission"]["title"]
    # keywords 与 jel_codes 必须保留（编辑需要的元数据）
    assert body["keywords"] == setup["submission"]["keywords"]
    assert body["jel_codes"] == setup["submission"]["jel_codes"]


async def test_reviewer_view_submission_other_reviewer_403(
    client: AsyncClient,
    admin_user: dict,
    test_user: dict,
    db_session: AsyncSession,
) -> None:
    """审稿人不能查看分配给别人的稿件的详情。"""
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]

    # 给 test_user 授 reviewer 角色（但 assignment 不是给他的）
    await client.get("/api/health")
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    await _grant_reviewer_role(db_session, tenant, int(test_user["user_id"]))

    resp = await client.get(
        f"/api/review/assignments/{assignment_id}/submission",
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 403


async def test_reviewer_view_submission_declined_400(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """declined 状态的 assignment 不能再查看稿件。"""
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]
    await client.post(
        f"/api/review/assignments/{assignment_id}/decline",
        headers=auth_headers(admin_user),
    )
    resp = await client.get(
        f"/api/review/assignments/{assignment_id}/submission",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 400


async def test_reviewer_view_submission_after_complete(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """completed 状态后审稿人仍可查看稿件（便于复核）。"""
    setup = await _setup_assignment(client, admin_user, test_user)
    assignment_id = setup["assignment"]["id"]
    await client.post(
        f"/api/review/assignments/{assignment_id}/accept",
        headers=auth_headers(admin_user),
    )
    await client.post(
        f"/api/review/assignments/{assignment_id}/submit",
        json={
            "recommendation": "accept",
            "scores": review_scores(),
            "comments_to_author": "Good",
        },
        headers=auth_headers(admin_user),
    )
    resp = await client.get(
        f"/api/review/assignments/{assignment_id}/submission",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["abstract"] == setup["submission"]["abstract"]
