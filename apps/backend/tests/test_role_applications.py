"""1.7.0 — 角色申请（L5/L6）+ 用户 bio 简介的集成测试。"""

from __future__ import annotations

from conftest import auth_headers
from httpx import AsyncClient

_APPLY_SAMPLE = {
    "type": "paper",
    "title": "Qual Paper",
    "authors": ["Alice"],
    "year": 2026,
    "discipline": "计算机科学",
    "abstract": "用于申请资格验证的占位摘要，长度足够校验。",
}


async def _submit_and_accept(
    client: AsyncClient, author: dict, admin: dict, title: str, rqs: float | None
) -> None:
    """作者投稿 → 上传无（跳过）→ admin 直接批准物化资源 → 打 RQS 分。"""
    r = await client.post(
        "/api/submissions",
        json={**_APPLY_SAMPLE, "title": title},
        headers=auth_headers(author),
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    # 录用要求至少一份已完成的审稿意见（no_completed_reviews）。
    from conftest import complete_one_review

    await complete_one_review(client, admin, sid)
    dec = await client.patch(
        f"/api/submissions/{sid}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin),
    )
    assert dec.status_code == 200, dec.text
    rid = dec.json()["resource_id"]
    assert rid is not None
    if rqs is not None:
        patch = await client.patch(
            f"/api/catalog/{rid}",
            json={"quality_score": rqs, "quality_grade": "B"},
            headers=auth_headers(admin),
        )
        assert patch.status_code == 200, patch.text


async def test_bio_update_and_echo(client: AsyncClient, test_user: dict) -> None:
    """PATCH /users/me 带 bio：落库、回显；空串清除。"""
    r = await client.patch(
        "/api/users/me",
        json={"bio": "  荒诞现象业余观测者。  "},
        headers=auth_headers(test_user),
    )
    assert r.status_code == 200, r.text
    assert r.json()["bio"] == "荒诞现象业余观测者。"

    cleared = await client.patch("/api/users/me", json={"bio": ""}, headers=auth_headers(test_user))
    assert cleared.status_code == 200
    assert cleared.json()["bio"] is None

    me = await client.get("/api/users/me", headers=auth_headers(test_user))
    assert me.json()["bio"] is None


async def test_reviewer_application_requires_quality(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """无录用稿件时申请 L5 → 422 eligibility_required，含画像。"""
    r = await client.post(
        "/api/gamification/applications",
        json={
            "target_role": "reviewer",
            "statement": "我长期阅读本刊文章，熟悉社区规范，希望参与审稿工作。",
        },
        headers=auth_headers(test_user),
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "eligibility_required"
    assert detail["profile"]["accepted_papers"] == 0


async def test_reviewer_application_full_flow(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """录用 1 篇 RQS=75 → 申请过闸 → admin 批准 → 用户获得 reviewer 角色 + 通知。"""
    await _submit_and_accept(client, test_user, admin_user, "申请资格稿", 75.0)

    apply = await client.post(
        "/api/gamification/applications",
        json={
            "target_role": "reviewer",
            "statement": "已有录用稿件一篇，熟悉学术规范，希望承担审稿工作。",
        },
        headers=auth_headers(test_user),
    )
    assert apply.status_code == 201, apply.text
    app_id = apply.json()["id"]

    dup = await client.post(
        "/api/gamification/applications",
        json={
            "target_role": "reviewer",
            "statement": "同一角色重复提交申请，应当被 409 状态码拒绝。",
        },
        headers=auth_headers(test_user),
    )
    assert dup.status_code == 409

    me = await client.get("/api/gamification/applications/me", headers=auth_headers(test_user))
    assert me.status_code == 200
    payload = me.json()
    assert payload["eligibility"]["reviewer"]["eligible"] is True
    assert any(a["id"] == app_id for a in payload["applications"])

    low = await client.post(
        "/api/gamification/applications",
        json={
            "target_role": "senior_reviewer",
            "statement": "审稿份数还不够，这条申请应当被系统直接拒绝。",
        },
        headers=auth_headers(test_user),
    )
    assert low.status_code == 422

    queue = await client.get(
        "/api/gamification/admin/applications?status=pending", headers=auth_headers(admin_user)
    )
    assert queue.status_code == 200
    assert any(item["id"] == app_id for item in queue.json()["data"])

    decide = await client.post(
        f"/api/gamification/admin/applications/{app_id}/decision",
        json={"decision": "approve", "note": "欢迎加入审稿团队"},
        headers=auth_headers(admin_user),
    )
    assert decide.status_code == 200, decide.text
    assert decide.json()["status"] == "approved"

    roles = await client.get("/api/users/me", headers=auth_headers(test_user))
    assert "reviewer" in roles.json()["roles"]

    again = await client.post(
        f"/api/gamification/admin/applications/{app_id}/decision",
        json={"decision": "reject"},
        headers=auth_headers(admin_user),
    )
    assert again.status_code == 400

    notif = await client.get("/api/notifications", headers=auth_headers(test_user))
    assert notif.status_code == 200
    assert any("审稿人" in n["title"] for n in notif.json()["data"])
    # 通知带上申请单指针，前端才能从通知跳回申请记录。
    assert any(
        n["related_type"] == "role_application" and n["related_id"] == str(app_id)
        for n in notif.json()["data"]
    )


async def test_application_audit_records_application_id(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """提交申请的审计行必须带真实 application_id（不是先 add 后 flush 的 None）。"""
    await _submit_and_accept(client, test_user, admin_user, "审计稿", 70.0)
    apply = await client.post(
        "/api/gamification/applications",
        json={
            "target_role": "reviewer",
            "statement": "验证审计 payload 里的申请单 id 已落库。",
        },
        headers=auth_headers(test_user),
    )
    assert apply.status_code == 201, apply.text
    app_id = apply.json()["id"]

    logs = await client.get("/api/admin/audit-logs?limit=50", headers=auth_headers(admin_user))
    assert logs.status_code == 200
    rows = [r for r in logs.json() if r["action"] == "gamification.role_application.create"]
    assert rows, "申请提交必须写审计"
    assert rows[0]["payload"]["application_id"] == app_id


async def test_senior_application_requires_reviewer_role_first(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """有 5 份审稿但还没有 reviewer 角色时，L6 申请 422（L6 是 L5 之上的阶梯）。"""
    from sqlalchemy import select

    from app.core.db import async_session_factory
    from app.models import Tenant
    from app.modules.review.models import ReviewAssignment, ReviewReport

    # 唯一约束是 (submission_id, reviewer_id)：5 份审稿必须落在 5 篇不同稿件上。
    submission_ids: list[int] = []
    for i in range(5):
        sub = await client.post(
            "/api/submissions",
            json={**_APPLY_SAMPLE, "title": f"L6 前置稿 {i + 1}"},
            headers=auth_headers(test_user),
        )
        assert sub.status_code == 201, sub.text
        submission_ids.append(sub.json()["id"])

    async with async_session_factory() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == "default"))
        ).scalar_one()
        for submission_id in submission_ids:
            assignment = ReviewAssignment(
                tenant_id=tenant.id,
                submission_id=submission_id,
                reviewer_id=test_user["user_id"],
                assigned_by=admin_user["user_id"],
                status="completed",
            )
            session.add(assignment)
            await session.flush()
            session.add(
                ReviewReport(
                    tenant_id=tenant.id,
                    assignment_id=assignment.id,
                    recommendation="accept",
                    scores={"originality": 4},
                )
            )
        await session.commit()

    profile = await client.get("/api/gamification/applications/me", headers=auth_headers(test_user))
    senior = profile.json()["eligibility"]["senior_reviewer"]
    assert senior["reviews_completed"] == 5
    assert senior["has_reviewer_role"] is False
    assert senior["eligible"] is False

    r = await client.post(
        "/api/gamification/applications",
        json={
            "target_role": "senior_reviewer",
            "statement": "份数够了但还没有 L5 角色，申请应当被拒绝。",
        },
        headers=auth_headers(test_user),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "reviewer_role_required"


async def test_reviewer_application_below_threshold_422(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """录用但 RQS=50（< 60）→ 422。"""
    await _submit_and_accept(client, test_user, admin_user, "低分稿", 50.0)
    r = await client.post(
        "/api/gamification/applications",
        json={
            "target_role": "reviewer",
            "statement": "这篇稿件质量分不够门槛，申请应当被系统拒绝。",
        },
        headers=auth_headers(test_user),
    )
    assert r.status_code == 422


async def test_applications_admin_only_queue(client: AsyncClient, test_user: dict) -> None:
    """审批队列仅 admin 可见。"""
    r = await client.get("/api/gamification/admin/applications", headers=auth_headers(test_user))
    assert r.status_code == 403


async def test_senior_reviewer_eligibility_view(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """L6 画像：0 份审稿时 eligible=False，阈值可见。"""
    me = await client.get("/api/gamification/applications/me", headers=auth_headers(test_user))
    senior = me.json()["eligibility"]["senior_reviewer"]
    assert senior["reviews_completed"] == 0
    assert senior["eligible"] is False
    assert senior["thresholds"]["reviews_completed"] == 5
