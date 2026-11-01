"""Tests for double-blind review mode.

Contract:
- Default is single-blind: reviewers see full author info (backwards
  compatible with every existing deployment — no migration needed).
- Admin can read/switch the mode via /admin/settings/review-mode
  (audited); invalid values are rejected by schema validation.
- Under double-blind, a non-admin reviewer's submission view has
  authors / corresponding email / submitted_by / venue / doi scrubbed,
  while all academic content (title/abstract/keywords) stays intact.
- Admin reviewers are exempt (platform operators can always debug).
- Author-side blinding (author never sees reviewer identity) is already
  covered by test_review.py's single-blind report tests.
"""

from __future__ import annotations

from conftest import auth_headers, register_user
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant
from app.modules.review.blinding import ANONYMIZED_AUTHOR

_PAYLOAD = {
    "title": "Double-Blind Test Paper",
    "type": "paper",
    "authors": ["Alice Identifiable", "Bob Traceable"],
    "year": 2024,
    "discipline": "computer science",
    "tags": ["blinding"],
    "abstract": "Abstract for the double-blind test.",
    "preview": "Preview text.",
    "venue": "Identifiable University Workshop",
    "doi": "10.9999/blind.test.001",
    "keywords": ["anonymity"],
    "corresponding_author_email": "alice@identifiable-university.edu",
    # 作者可控外链 —— 双盲下必须从审稿人视角抹掉（泄露向量回归测试用）
    "download_url": "https://alice-identifiable.example.org/paper-with-name",
    "external_url": "https://alice-identifiable.example.org/homepage",
}


async def _register(client: AsyncClient, tag: str) -> dict:
    return await register_user(client, email=f"{tag}@example.org", username=tag)


async def _grant_reviewer(db_session: AsyncSession, user_id: int) -> None:
    from app.models import Role, UserRole

    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    role = (
        await db_session.execute(
            select(Role).where(Role.tenant_id == tenant.id, Role.name == "reviewer")
        )
    ).scalar_one_or_none()
    if role is None:
        role = Role(tenant_id=tenant.id, name="reviewer", description="test")
        db_session.add(role)
        await db_session.flush()
    db_session.add(UserRole(tenant_id=tenant.id, user_id=user_id, role_id=role.id))
    await db_session.commit()


async def _setup(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> dict:
    """作者投稿 → 注册独立审稿人 → 授角色 → 指派。"""
    created = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(test_user))
    created.raise_for_status()
    submission = created.json()

    reviewer = await _register(client, "blindreviewer")
    await _grant_reviewer(db_session, int(reviewer["user_id"]))

    assigned = await client.post(
        f"/api/submissions/{submission['id']}/assignments",
        json={"reviewer_id": reviewer["user_id"]},
        headers=auth_headers(admin_user),
    )
    assigned.raise_for_status()
    return {
        "submission": submission,
        "assignment": assigned.json(),
        "reviewer": reviewer,
    }


async def _set_mode(client: AsyncClient, admin_user: dict, mode: str) -> None:
    resp = await client.patch(
        "/api/admin/settings/review-mode",
        json={"review_mode": mode},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["review_mode"] == mode


async def _attach_file(db_session: AsyncSession, submission_id: int) -> None:
    """给 submission 挂一份真实稿件文件（走 storage 后端相对 key）。"""
    from app.core.storage import get_storage

    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    rel_path = f"{tenant.id}/{submission_id}/manuscript.pdf"
    await get_storage().save(rel_path, b"%PDF-1.4 sealed original manuscript")

    from app.modules.submission.models import Submission

    entry = await db_session.get(Submission, submission_id)
    assert entry is not None
    entry.file_path = rel_path
    await db_session.commit()


# ---------------------------------------------------------------------------
# Settings endpoint
# ---------------------------------------------------------------------------


async def test_default_mode_is_single_blind(client: AsyncClient, admin_user: dict) -> None:
    resp = await client.get("/api/admin/settings/review-mode", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    assert resp.json()["review_mode"] == "single_blind"


async def test_switch_mode_roundtrip_and_audited(client: AsyncClient, admin_user: dict) -> None:
    await _set_mode(client, admin_user, "double_blind")
    resp = await client.get("/api/admin/settings/review-mode", headers=auth_headers(admin_user))
    assert resp.json()["review_mode"] == "double_blind"
    # 切换动作必须留审计
    logs = await client.get("/api/admin/audit-logs?limit=10", headers=auth_headers(admin_user))
    actions = [entry["action"] for entry in logs.json()]
    assert "admin.settings.review_mode" in actions
    # 切回
    await _set_mode(client, admin_user, "single_blind")


async def test_invalid_mode_rejected(client: AsyncClient, admin_user: dict) -> None:
    resp = await client.patch(
        "/api/admin/settings/review-mode",
        json={"review_mode": "triple_blind"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422


async def test_settings_require_admin(client: AsyncClient, test_user: dict) -> None:
    resp = await client.get("/api/admin/settings/review-mode", headers=auth_headers(test_user))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Reviewer-facing anonymization
# ---------------------------------------------------------------------------


async def test_single_blind_reviewer_sees_authors(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """默认（单盲）：审稿人看得到作者。守住向后兼容。"""
    setup = await _setup(client, admin_user, test_user, db_session)
    resp = await client.get(
        f"/api/review/assignments/{setup['assignment']['id']}/submission",
        headers={"Authorization": f"Bearer {setup['reviewer']['token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["authors"] == _PAYLOAD["authors"]
    assert body["corresponding_author_email"] == _PAYLOAD["corresponding_author_email"]


async def test_double_blind_scrubs_identity_keeps_content(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """双盲：身份字段被抹掉，学术内容原样保留。"""
    setup = await _setup(client, admin_user, test_user, db_session)
    await _set_mode(client, admin_user, "double_blind")

    resp = await client.get(
        f"/api/review/assignments/{setup['assignment']['id']}/submission",
        headers={"Authorization": f"Bearer {setup['reviewer']['token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # 身份字段全部被抹
    assert body["authors"] == [ANONYMIZED_AUTHOR]
    assert body["corresponding_author_email"] is None
    assert body["submitted_by"] is None
    assert body["venue"] is None
    assert body["doi"] is None
    # 作者可控外链同样被抹（双盲绕过 v2 回归）
    assert body["download_url"] is None
    assert body["external_url"] is None
    # 学术内容完好
    assert body["title"] == _PAYLOAD["title"]
    assert body["abstract"] == _PAYLOAD["abstract"]
    assert body["keywords"] == _PAYLOAD["keywords"]

    await _set_mode(client, admin_user, "single_blind")


async def test_double_blind_admin_exempt(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """admin 以审稿人身份查看时不剥离（平台运营需要能排障）。"""
    created = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(test_user))
    created.raise_for_status()
    assigned = await client.post(
        f"/api/submissions/{created.json()['id']}/assignments",
        json={"reviewer_id": admin_user["user_id"]},
        headers=auth_headers(admin_user),
    )
    assigned.raise_for_status()
    await _set_mode(client, admin_user, "double_blind")

    resp = await client.get(
        f"/api/review/assignments/{assigned.json()['id']}/submission",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["authors"] == _PAYLOAD["authors"]

    await _set_mode(client, admin_user, "single_blind")


# ---------------------------------------------------------------------------
# 双盲绕过 v2：作者可控外链不得流向审稿人
# download_url / external_url 由作者在创建/编辑端点写入，早期版本把审稿人
# 文件端点 302 到 download_url、JSON 也原样保留 —— 作者填一条带身份的链接
# 即可直穿双盲。现在审稿人视角只认编辑端点写入的 anonymized_file_url。
# ---------------------------------------------------------------------------


async def test_single_blind_reviewer_still_sees_author_links(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """单盲（默认）保持向后兼容：作者外链照常可见。"""
    setup = await _setup(client, admin_user, test_user, db_session)
    resp = await client.get(
        f"/api/review/assignments/{setup['assignment']['id']}/submission",
        headers={"Authorization": f"Bearer {setup['reviewer']['token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["download_url"] == _PAYLOAD["download_url"]
    assert body["external_url"] == _PAYLOAD["external_url"]


async def test_double_blind_file_endpoint_blocks_author_download_url(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """核心回归：双盲 + 审稿人 + 作者 download_url → 403，不得 302 到作者链接。"""
    setup = await _setup(client, admin_user, test_user, db_session)
    submission_id = setup["submission"]["id"]
    await _attach_file(db_session, submission_id)
    await _set_mode(client, admin_user, "double_blind")

    resp = await client.get(
        f"/api/submissions/{submission_id}/files",
        headers={"Authorization": f"Bearer {setup['reviewer']['token']}"},
        follow_redirects=False,
    )
    # 修复前这里会 302 到作者可控的 download_url（身份直穿双盲）。
    assert resp.status_code == 403
    assert "anonymized" in resp.json()["detail"]

    await _set_mode(client, admin_user, "single_blind")


async def test_double_blind_file_endpoint_redirects_to_editor_anonymized_url(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """编辑设置匿名稿外链后，双盲下审稿人被 302 到该编辑专属链接。"""
    setup = await _setup(client, admin_user, test_user, db_session)
    submission_id = setup["submission"]["id"]
    await _attach_file(db_session, submission_id)
    await _set_mode(client, admin_user, "double_blind")

    anon_url = "https://editor-curated.example.org/anonymized-manuscript.pdf"
    resp = await client.put(
        f"/api/submissions/{submission_id}/anonymized-file",
        json={"anonymized_file_url": anon_url},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["anonymized_file_url"] == anon_url

    resp = await client.get(
        f"/api/submissions/{submission_id}/files",
        headers={"Authorization": f"Bearer {setup['reviewer']['token']}"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == anon_url

    await _set_mode(client, admin_user, "single_blind")


async def test_editor_can_clear_anonymized_file_url(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """编辑清除匿名稿链接后，审稿人重新回到 403（与设置前一致）。"""
    setup = await _setup(client, admin_user, test_user, db_session)
    submission_id = setup["submission"]["id"]
    await _attach_file(db_session, submission_id)
    await _set_mode(client, admin_user, "double_blind")

    set_resp = await client.put(
        f"/api/submissions/{submission_id}/anonymized-file",
        json={"anonymized_file_url": "https://editor-curated.example.org/anon.pdf"},
        headers=auth_headers(admin_user),
    )
    assert set_resp.status_code == 200

    clear_resp = await client.put(
        f"/api/submissions/{submission_id}/anonymized-file",
        json={"anonymized_file_url": None},
        headers=auth_headers(admin_user),
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["anonymized_file_url"] is None

    resp = await client.get(
        f"/api/submissions/{submission_id}/files",
        headers={"Authorization": f"Bearer {setup['reviewer']['token']}"},
        follow_redirects=False,
    )
    assert resp.status_code == 403

    await _set_mode(client, admin_user, "single_blind")


async def test_anonymized_file_endpoint_requires_editor(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """作者与审稿人都不能写 anonymized_file_url（编辑专属）。"""
    setup = await _setup(client, admin_user, test_user, db_session)
    submission_id = setup["submission"]["id"]
    url = f"/api/submissions/{submission_id}/anonymized-file"
    payload = {"anonymized_file_url": "https://attacker.example.org/fake.pdf"}

    author_resp = await client.put(url, json=payload, headers=auth_headers(test_user))
    assert author_resp.status_code == 403

    reviewer_resp = await client.put(url, json=payload, headers=auth_headers(setup["reviewer"]))
    assert reviewer_resp.status_code == 403

    # 无 token 直接 401
    anon_resp = await client.put(url, json=payload)
    assert anon_resp.status_code == 401


async def test_author_edit_cannot_set_anonymized_file_url(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """作者编辑端点不认 anonymized_file_url（schema 无此字段，静默忽略）。"""
    created = await client.post("/api/submissions", json=_PAYLOAD, headers=auth_headers(test_user))
    created.raise_for_status()
    submission_id = created.json()["id"]

    resp = await client.patch(
        f"/api/submissions/{submission_id}",
        json={
            "anonymized_file_url": "https://attacker.example.org/fake.pdf",
            "title": "Edited Title",
        },
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 200
    # title 正常更新，但 anonymized_file_url 未被写入
    assert resp.json()["title"] == "Edited Title"
    assert resp.json()["anonymized_file_url"] is None


async def test_single_blind_reviewer_gets_original_file(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    """单盲下行为不变：审稿人拿到原始稿件文件（本地后端流式返回）。"""
    setup = await _setup(client, admin_user, test_user, db_session)
    submission_id = setup["submission"]["id"]
    await _attach_file(db_session, submission_id)

    resp = await client.get(
        f"/api/submissions/{submission_id}/files",
        headers={"Authorization": f"Bearer {setup['reviewer']['token']}"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
