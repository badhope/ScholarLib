"""补 submission 模块主干路径的单测：审稿分配、编辑决断、作者重投、单盲、稿件文件。

背景：``app/modules/submission/routes.py`` 单测覆盖仅 33%，未覆盖区间集中在
``assign_reviewer`` / ``list_assignments`` / ``cancel_assignment`` /
``list_review_reports`` / ``editor_decision`` / ``author_resubmit`` /
``upload_submission_file`` / ``download_submission_file``。E2E 覆盖了
submission→review→accept 的 happy path，但**越权、非法状态流转、单盲剥离**
这类边界条件 E2E 走不到，只能靠单测守住。
"""

from __future__ import annotations

from datetime import UTC, datetime

from conftest import auth_headers, complete_one_review, register_user
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.review.models import ReviewAssignment, ReviewReport

_PAYLOAD = {
    "title": "Workflow Coverage Specimen",
    "type": "paper",
    "authors": ["Alice Author"],
    "year": 2024,
    "venue": "Journal of Testing",
    "discipline": "physics",
    "subdiscipline": "quantum",
    "tags": ["workflow"],
    "abstract": "A submission used to exercise the review workflow endpoints.",
    "preview": "Short preview.",
}


async def _create_submission(client: AsyncClient, user: dict) -> dict:
    response = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(user))
    response.raise_for_status()
    return response.json()


async def _register(client: AsyncClient, username: str, email: str) -> dict:
    """注册一个额外的普通用户（审稿人 / 无关第三方）。"""
    user = await register_user(client, email=email, username=username)
    return {"token": user["token"], "user_id": user["user_id"], "username": username}


async def _register_reviewer(
    client: AsyncClient, admin_user: dict, username: str, email: str
) -> dict:
    """注册用户并授予 reviewer 角色。

    分配审稿人时会校验被指派者持有 reviewer 角色（否则该用户在 /review
    端点全部 403，分配即死路），所以测试里的审稿人必须先拿角色。
    """
    user = await _register(client, username, email)
    response = await client.post(
        f"/api/admin/users/{user['user_id']}/roles",
        json={"role": "reviewer"},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 201, response.text
    return user


async def _get(client: AsyncClient, submission_id: int, user: dict) -> dict:
    response = await client.get(f"/api/submissions/{submission_id}", headers=auth_headers(user))
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# A. 审稿人分配
# ---------------------------------------------------------------------------


async def test_admin_assigns_reviewer_flips_status_to_under_review(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sub = await _create_submission(client, test_user)
    reviewer = await _register_reviewer(client, admin_user, "rev_one", "rev1@example.com")

    response = await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["reviewer_id"] == reviewer["user_id"]
    assert body["status"] == "pending"
    assert body["reviewer_username"] == "rev_one"

    # pending → under_review（仅 pending 时自动翻转）
    assert (await _get(client, sub["id"], admin_user))["status"] == "under_review"


async def test_author_cannot_be_assigned_or_decide_own_submission(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    await _assign_role(client, admin_user, int(test_user["user_id"]), "reviewer")
    await _assign_role(client, admin_user, int(test_user["user_id"]), "editor")
    sub = await _create_submission(client, test_user)
    assigned = await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": test_user["user_id"]},
        headers=auth_headers(admin_user),
    )
    assert assigned.status_code == 403
    decision = await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "reject"},
        headers=auth_headers(test_user),
    )
    assert decision.status_code == 403
    assert (await _get(client, sub["id"], test_user))["status"] == "pending"


async def test_admin_cannot_review_own_submission(client: AsyncClient, admin_user: dict) -> None:
    await client.post(
        "/api/gamification/onboarding/author",
        json={"accept_rules": True},
        headers=auth_headers(admin_user),
    )
    sub = await _create_submission(client, admin_user)
    response = await client.patch(
        f"/api/submissions/{sub['id']}/review",
        json={"status": "rejected"},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 403


async def test_legacy_self_assignment_cannot_accept_or_submit(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: object
) -> None:
    await _assign_role(client, admin_user, int(test_user["user_id"]), "reviewer")
    sub = await _create_submission(client, test_user)
    from app.modules.submission.models import Submission

    entry = (
        await db_session.execute(select(Submission).where(Submission.id == sub["id"]))
    ).scalar_one()
    assignment = ReviewAssignment(
        tenant_id=entry.tenant_id,
        submission_id=entry.id,
        reviewer_id=test_user["user_id"],
        assigned_by=admin_user["user_id"],
        status="pending",
    )
    db_session.add(assignment)
    await db_session.commit()
    accepted = await client.post(
        f"/api/review/assignments/{assignment.id}/accept", headers=auth_headers(test_user)
    )
    assert accepted.status_code == 403
    assignment.status = "accepted"
    await db_session.commit()
    submitted = await client.post(
        f"/api/review/assignments/{assignment.id}/submit",
        json={"recommendation": "accept", "scores": {}, "comments_to_author": "ok"},
        headers=auth_headers(test_user),
    )
    assert submitted.status_code == 403


async def test_non_editor_cannot_assign_reviewer(client: AsyncClient, test_user: dict) -> None:
    sub = await _create_submission(client, test_user)
    reviewer = await _register(client, "rev_two", "rev2@example.com")

    response = await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 403


async def test_assign_reviewer_rejects_unknown_reviewer(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sub = await _create_submission(client, test_user)

    response = await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": 999_999},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 400


async def test_assign_reviewer_rejected_on_terminal_status(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """accepted / rejected 是终态，不能再分配审稿人。"""
    sub = await _create_submission(client, test_user)
    reviewer = await _register_reviewer(client, admin_user, "rev_three", "rev3@example.com")

    decision = await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "reject", "editor_note": "not a fit"},
        headers=auth_headers(admin_user),
    )
    assert decision.status_code == 200

    response = await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 400


async def test_admin_lists_and_cancels_assignment(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sub = await _create_submission(client, test_user)
    reviewer = await _register_reviewer(client, admin_user, "rev_four", "rev4@example.com")

    created = await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(admin_user),
    )
    assignment_id = created.json()["id"]

    listed = await client.get(
        f"/api/submissions/{sub['id']}/assignments", headers=auth_headers(admin_user)
    )
    assert listed.status_code == 200
    assert [a["id"] for a in listed.json()["data"]] == [assignment_id]

    cancelled = await client.delete(
        f"/api/submissions/{sub['id']}/assignments/{assignment_id}",
        headers=auth_headers(admin_user),
    )
    assert cancelled.status_code in (200, 204)


# ---------------------------------------------------------------------------
# B. 单盲：审稿报告按角色剥离
# ---------------------------------------------------------------------------


async def _completed_report(db_session: object, submission_id: int, tenant_id: object) -> int:
    """把该 submission 的分配标为 completed 并插入一份报告，返回 assignment_id。"""
    result = await db_session.execute(  # type: ignore[attr-defined]
        select(ReviewAssignment).where(ReviewAssignment.submission_id == submission_id)
    )
    assignment = result.scalars().first()
    assert assignment is not None
    assignment.status = "completed"
    db_session.add(  # type: ignore[attr-defined]
        ReviewReport(
            tenant_id=assignment.tenant_id,
            assignment_id=assignment.id,
            recommendation="minor_revision",
            scores={"originality": 4, "clarity": 3},
            comments_to_author="Please clarify section 3.",
            comments_to_editor="Reviewer suspects the data is thin.",  # editor-only
            submitted_at=datetime.now(UTC),
        )
    )
    await db_session.commit()  # type: ignore[attr-defined]
    return assignment.id


async def test_author_sees_report_without_editor_comments(
    client: AsyncClient, test_user: dict, admin_user: dict, db_session: object
) -> None:
    """单盲核心断言：作者可见 comments_to_author，但 comments_to_editor 必须为 None。"""
    sub = await _create_submission(client, test_user)
    reviewer = await _register_reviewer(client, admin_user, "rev_five", "rev5@example.com")
    await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(admin_user),
    )
    await _completed_report(db_session, sub["id"], None)

    response = await client.get(
        f"/api/submissions/{sub['id']}/reports", headers=auth_headers(test_user)
    )
    assert response.status_code == 200
    reports = response.json()
    assert len(reports) == 1
    assert reports[0]["comments_to_author"] == "Please clarify section 3."
    assert reports[0]["comments_to_editor"] is None


async def test_submitter_editor_cannot_access_or_change_review_management(
    client: AsyncClient, test_user: dict, admin_user: dict, db_session: object
) -> None:
    await _assign_role(client, admin_user, int(test_user["user_id"]), "editor")
    sub = await _create_submission(client, test_user)
    reviewer = await _register_reviewer(client, admin_user, "rev_conflict", "conflict@example.com")
    created = await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(admin_user),
    )
    assert created.status_code == 201
    assignment_id = created.json()["id"]
    headers = auth_headers(test_user)
    listed = await client.get(f"/api/submissions/{sub['id']}/assignments", headers=headers)
    assert listed.status_code == 403
    cancelled = await client.delete(
        f"/api/submissions/{sub['id']}/assignments/{assignment_id}", headers=headers
    )
    assert cancelled.status_code == 403
    anonymous = await client.put(
        f"/api/submissions/{sub['id']}/anonymized-file",
        json={"anonymized_file_url": "https://example.com/anonymous.pdf"},
        headers=headers,
    )
    assert anonymous.status_code == 403
    await _completed_report(db_session, sub["id"], None)
    reports = await client.get(f"/api/submissions/{sub['id']}/reports", headers=headers)
    assert reports.status_code == 200
    assert reports.json()[0]["comments_to_editor"] is None


async def test_editor_sees_full_report_including_editor_comments(
    client: AsyncClient, test_user: dict, admin_user: dict, db_session: object
) -> None:
    sub = await _create_submission(client, test_user)
    reviewer = await _register_reviewer(client, admin_user, "rev_six", "rev6@example.com")
    await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(admin_user),
    )
    await _completed_report(db_session, sub["id"], None)

    response = await client.get(
        f"/api/submissions/{sub['id']}/reports", headers=auth_headers(admin_user)
    )
    assert response.status_code == 200
    assert response.json()[0]["comments_to_editor"] == "Reviewer suspects the data is thin."


async def test_unrelated_user_cannot_read_reports(
    client: AsyncClient, test_user: dict, admin_user: dict, db_session: object
) -> None:
    sub = await _create_submission(client, test_user)
    reviewer = await _register_reviewer(client, admin_user, "rev_seven", "rev7@example.com")
    await client.post(
        f"/api/submissions/{sub['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(admin_user),
    )
    await _completed_report(db_session, sub["id"], None)

    outsider = await _register(client, "outsider", "outsider@example.com")
    response = await client.get(
        f"/api/submissions/{sub['id']}/reports", headers=auth_headers(outsider)
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# C. 编辑决断
# ---------------------------------------------------------------------------


async def test_editor_decision_major_revision(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sub = await _create_submission(client, test_user)

    response = await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "major_revision", "editor_note": "needs more experiments"},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "major_revision"
    assert body["editor_note"] == "needs more experiments"
    assert body["reviewed_by"] == admin_user["user_id"]


async def test_editor_decision_accept_materializes_resource(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sub = await _create_submission(client, test_user)
    # 录用要求至少一份已完成的审稿意见（见 no_completed_reviews）。
    await complete_one_review(client, admin_user, sub["id"])

    response = await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["resource_id"] is not None


async def test_accept_without_any_review_is_blocked(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """零审稿直接录用必须被拒：同行评审不能被前端按钮的显隐当成唯一防线。"""
    sub = await _create_submission(client, test_user)

    response = await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "no_completed_reviews"
    # 状态未被改动：拒绝要彻底，不能留下"半录用"
    assert (await _get(client, sub["id"], test_user))["status"] == "pending"


async def test_waive_review_unblocks_desk_accept_and_is_audited(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """免评审录用要留理由：豁免是显式例外，不是沉默的默认路径。"""
    sub = await _create_submission(client, test_user)

    # 理由太短直接拒（10 字下限由 schema 层拦下 → 422）
    too_short = await client.post(
        f"/api/submissions/{sub['id']}/waive-review",
        json={"reason": "约稿"},
        headers=auth_headers(admin_user),
    )
    assert too_short.status_code == 422

    waive = await client.post(
        f"/api/submissions/{sub['id']}/waive-review",
        json={"reason": "编委特稿：编辑部约稿，已在内部完成双人审读"},
        headers=auth_headers(admin_user),
    )
    assert waive.status_code == 200

    decision = await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "accepted"

    logs = await client.get("/api/admin/audit-logs", headers=auth_headers(admin_user))
    assert logs.status_code == 200
    # 审计列表端点直接返回数组（无分页包装）。
    actions = [row["action"] for row in logs.json()]
    assert "submission.review_waived" in actions


async def test_editor_decision_requires_editor(client: AsyncClient, test_user: dict) -> None:
    sub = await _create_submission(client, test_user)

    response = await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 403


async def test_section_editor_cannot_decide(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """职权分离：L7 栏目编辑可送审（分配审稿人），但四元决定是 L8 职权。

    此前 require_editor 让 section_editor 也能直接录用/拒稿，与 ladder
    「推荐录用名单（无最终裁决权）」的分工承诺不符。
    """
    await _assign_role(client, admin_user, int(test_user["user_id"]), "section_editor")
    sub = await _create_submission(client, test_user)

    # 送审权在（分配审稿人先拿一个真审稿人占位不必——直接验证决定被拒）
    response = await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 403
    # 状态未被改动
    body = await _get(client, sub["id"], test_user)
    assert body["status"] == "pending"


async def _assign_role(client: AsyncClient, admin: dict, user_id: int, role: str) -> None:
    response = await client.post(
        f"/api/admin/users/{user_id}/roles", json={"role": role}, headers=auth_headers(admin)
    )
    assert response.status_code == 201, response.text


async def test_editor_decision_rejects_unknown_decision(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sub = await _create_submission(client, test_user)

    response = await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "maybe"},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 422  # pydantic enum 校验在业务分支之前拦下


async def test_editor_decision_rejected_on_terminal_status(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sub = await _create_submission(client, test_user)
    await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "reject"},
        headers=auth_headers(admin_user),
    )

    response = await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# D. 作者重投 + 版本历史
# ---------------------------------------------------------------------------


async def test_author_resubmit_creates_new_version(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sub = await _create_submission(client, test_user)
    await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "minor_revision"},
        headers=auth_headers(admin_user),
    )

    response = await client.post(
        f"/api/submissions/{sub['id']}/resubmit",
        json={"note": "按意见补充了实验"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "under_review"

    versions = await client.get(
        f"/api/submissions/{sub['id']}/versions", headers=auth_headers(test_user)
    )
    assert versions.status_code == 200
    # 版本历史按版本号倒序返回：v1 初稿 + v2 本次重投快照
    rows = versions.json()["data"]
    assert sorted(v["version"] for v in rows) == [1, 2]
    latest = next(v for v in rows if v["version"] == 2)
    assert latest["note"] == "按意见补充了实验"


async def test_resubmit_by_non_author_forbidden(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sub = await _create_submission(client, test_user)
    await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "minor_revision"},
        headers=auth_headers(admin_user),
    )
    other = await _register(client, "other_author", "other@example.com")

    response = await client.post(
        f"/api/submissions/{sub['id']}/resubmit", json={}, headers=auth_headers(other)
    )
    assert response.status_code == 403


async def test_resubmit_rejected_in_pending_status(client: AsyncClient, test_user: dict) -> None:
    """pending 尚未进入返修，不能直接重投。"""
    sub = await _create_submission(client, test_user)

    response = await client.post(
        f"/api/submissions/{sub['id']}/resubmit", json={}, headers=auth_headers(test_user)
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# E. 稿件文件上传 / 下载
# ---------------------------------------------------------------------------

_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"


async def test_author_uploads_and_downloads_manuscript(
    client: AsyncClient, test_user: dict
) -> None:
    sub = await _create_submission(client, test_user)

    uploaded = await client.post(
        f"/api/submissions/{sub['id']}/files",
        files={"file": ("manuscript.pdf", _PDF, "application/pdf")},
        headers=auth_headers(test_user),
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["file_path"]

    downloaded = await client.get(
        f"/api/submissions/{sub['id']}/files", headers=auth_headers(test_user)
    )
    assert downloaded.status_code == 200
    assert downloaded.content == _PDF


async def test_upload_by_non_author_forbidden(client: AsyncClient, test_user: dict) -> None:
    sub = await _create_submission(client, test_user)
    other = await _register(client, "uploader", "uploader@example.com")

    response = await client.post(
        f"/api/submissions/{sub['id']}/files",
        files={"file": ("m.pdf", _PDF, "application/pdf")},
        headers=auth_headers(other),
    )
    assert response.status_code == 403


async def test_upload_rejects_disallowed_mime(client: AsyncClient, test_user: dict) -> None:
    sub = await _create_submission(client, test_user)

    response = await client.post(
        f"/api/submissions/{sub['id']}/files",
        files={"file": ("evil.sh", b"#!/bin/sh", "application/x-sh")},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 400


async def test_upload_rejected_on_terminal_status(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    sub = await _create_submission(client, test_user)
    await client.patch(
        f"/api/submissions/{sub['id']}/decision",
        json={"decision": "reject"},
        headers=auth_headers(admin_user),
    )

    response = await client.post(
        f"/api/submissions/{sub['id']}/files",
        files={"file": ("m.pdf", _PDF, "application/pdf")},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 400
