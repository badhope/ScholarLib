"""Editor 分配审稿人：候选端点 + 权限边界。

以前前端编辑工作台的「分配审稿人」下拉调用 /admin/users——只有 admin
能访问，非 admin 的 editor 拿到 403 后看到「没有可指派的审稿人」。
新端点 /submissions/reviewer-candidates 只返回持有 reviewer 角色且启用
的账号，并要求 editor 权限。
"""

from __future__ import annotations

from conftest import auth_headers
from httpx import AsyncClient


async def _assign(client: AsyncClient, admin: dict, user_id: int, role: str) -> None:
    r = await client.post(
        f"/api/admin/users/{user_id}/roles", json={"role": role}, headers=auth_headers(admin)
    )
    assert r.status_code == 201, r.text


async def test_candidates_empty_when_nobody_is_reviewer(
    client: AsyncClient, admin_user: dict
) -> None:
    r = await client.get("/api/submissions/reviewer-candidates", headers=auth_headers(admin_user))
    assert r.status_code == 200
    assert r.json()["data"] == []


async def test_candidates_include_reviewer_role_holders(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    await _assign(client, admin_user, int(test_user["user_id"]), "reviewer")
    r = await client.get("/api/submissions/reviewer-candidates", headers=auth_headers(admin_user))
    assert r.status_code == 200
    data = r.json()["data"]
    assert [c["username"] for c in data] == ["testuser"]
    # 只暴露分配所需字段，不带 is_admin / 密码类信息
    assert set(data[0]) == {
        "id",
        "username",
        "email",
        "score",
        "active_assignments",
        "completed_reviews",
        "matched_keywords",
        "match_reasons",
        "coi_declared",
        "coi_year",
        "conflict",
        "conflict_reasons",
    }


async def test_non_editor_gets_403(client: AsyncClient, test_user: dict) -> None:
    r = await client.get("/api/submissions/reviewer-candidates", headers=auth_headers(test_user))
    assert r.status_code == 403


async def test_editor_without_admin_can_list_pending_submissions(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """非 admin 的 editor 也能进编辑工作台（此前前端路由只放行 isAdmin）。"""
    await _assign(client, admin_user, int(test_user["user_id"]), "editor")
    login = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "password123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    for path in ("/api/submissions/pending", "/api/submissions/reviewer-candidates"):
        r = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"{path}: {r.text[:200]}"


async def test_section_editor_has_editor_access(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """section_editor（栏目编辑）此前可分配但无任何权限：应等同 editor 入口。"""
    await _assign(client, admin_user, int(test_user["user_id"]), "section_editor")
    login = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "password123"},
    )
    token = login.json()["access_token"]
    assert login.json()["roles"] == ["section_editor"]
    for path in ("/api/submissions/pending", "/api/submissions/reviewer-candidates"):
        r = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"{path}: {r.text[:200]}"


async def test_senior_reviewer_can_review_and_enter_pool(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """L6 资深审稿人断链修复：角色可授予、能进候选池、能走评审端点。

    此前 ASSIGNABLE_ROLES 不含 senior_reviewer、require_reviewer 不认它、
    候选池只查 reviewer —— ladder 承诺的 L6 是个空头等级。
    """
    await _assign(client, admin_user, int(test_user["user_id"]), "senior_reviewer")
    login = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "password123"},
    )
    assert login.status_code == 200
    assert login.json()["roles"] == ["senior_reviewer"]
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 候选池应包含资深审稿人（与 reviewer 同池）
    r = await client.get("/api/submissions/reviewer-candidates", headers=auth_headers(admin_user))
    assert r.status_code == 200
    assert "testuser" in [c["username"] for c in r.json()["data"]]

    # 评审侧端点：/review/assignments/me 此前对 senior_reviewer 是 403
    r = await client.get("/api/review/assignments/me", headers=headers)
    assert r.status_code == 200, r.text[:200]


def test_candidate_score_is_explainable_and_load_penalized() -> None:
    """匹配分不应该是黑盒：同学科/关键词要加分，当前负载要减分。"""
    from types import SimpleNamespace

    from app.interfaces.http.submission.routes_editor import _candidate_score

    current = SimpleNamespace(
        discipline="计算机科学",
        subdiscipline="人工智能",
        keywords=["machine learning", "ethics"],
        tags=["AI"],
    )
    matching = SimpleNamespace(
        discipline="计算机科学",
        subdiscipline="人工智能",
        keywords=["Machine Learning", "fairness"],
        tags=["ai"],
    )
    unrelated = SimpleNamespace(
        discipline="历史学",
        subdiscipline=None,
        keywords=["archives"],
        tags=[],
    )

    high, reasons, matched = _candidate_score(
        current=current, history=[matching, matching], active_count=1
    )
    low, _, _ = _candidate_score(current=current, history=[unrelated], active_count=0)
    assert high > low
    assert "machine learning" in matched
    assert any("同子领域" in reason for reason in reasons)
    assert any("当前在审 1 篇" in reason for reason in reasons)
