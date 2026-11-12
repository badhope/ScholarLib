"""Admin endpoints: user active-state, role validation, review-mode errors."""

from __future__ import annotations

import pytest
from conftest import auth_headers
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


@pytest.mark.asyncio
async def test_admin_cannot_change_own_active_state(client: AsyncClient, admin_user: dict) -> None:
    r = await client.patch(
        f"/api/admin/users/{admin_user['user_id']}/active",
        params={"is_active": False},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_admin_activate_unknown_user_404(client: AsyncClient, admin_user: dict) -> None:
    r = await client.patch(
        "/api/admin/users/99999/active",
        params={"is_active": False},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_disable_user_invalidates_tokens_and_audits(
    client: AsyncClient, admin_user: dict, test_user: dict, db_session: AsyncSession
) -> None:
    victim_token = {"Authorization": f"Bearer {test_user['token']}"}
    alive = await client.get("/api/users/me", headers=victim_token)
    assert alive.status_code == 200

    disabled = await client.patch(
        f"/api/admin/users/{test_user['user_id']}/active",
        params={"is_active": False},
        headers=auth_headers(admin_user),
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    dead = await client.get("/api/users/me", headers=victim_token)
    assert dead.status_code == 401

    audit = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "user.set_active",
            AuditLog.target_id == str(test_user["user_id"]),
        )
    )
    assert audit.scalars().first() is not None

    reenabled = await client.patch(
        f"/api/admin/users/{test_user['user_id']}/active",
        params={"is_active": True},
        headers=auth_headers(admin_user),
    )
    assert reenabled.status_code == 200
    assert reenabled.json()["is_active"] is True


@pytest.mark.asyncio
async def test_assign_unknown_role_rejected(client: AsyncClient, admin_user: dict) -> None:
    r = await client.post(
        f"/api/admin/users/{admin_user['user_id']}/roles",
        json={"role": "super-duper-role"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_revoke_unknown_role_rejected(client: AsyncClient, admin_user: dict) -> None:
    r = await client.delete(
        f"/api/admin/users/{admin_user['user_id']}/roles/not-a-role",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_revoke_role_not_held_404(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    r = await client.delete(
        f"/api/admin/users/{test_user['user_id']}/roles/reviewer",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_review_mode_tenant_missing_404(
    client: AsyncClient, admin_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import admin as admin_module

    async def boom(db: AsyncSession, tenant_id: object, mode: str) -> None:
        raise LookupError("tenant gone")

    monkeypatch.setattr(admin_module, "set_review_mode", boom)
    r = await client.patch(
        "/api/admin/settings/review-mode",
        json={"review_mode": "double_blind"},
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_security_reload_writes_audit(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    r = await client.post("/api/admin/security/reload", headers=auth_headers(admin_user))
    assert r.status_code == 204
    audit = await db_session.execute(select(AuditLog).where(AuditLog.action == "security.reload"))
    assert audit.scalars().first() is not None


@pytest.mark.asyncio
async def test_list_users_search_filters_before_pagination(
    client: AsyncClient, admin_user: dict, test_user: dict
) -> None:
    """搜索必须在分页之前生效。

    回归背景：前端原先只在「当前页 50 条」里做本地过滤，用户超过 50 个
    以后，搜一个确实存在的老账号会显示「暂无用户」，看起来像数据丢了。
    """
    # 造一个排在第二页的账号（新用户 id 更大，会排在前面）
    for i in range(3):
        await client.post(
            "/api/auth/register",
            json={
                "email": f"page{i}@example.com",
                "username": f"pageuser{i}",
                "password": "password123",
            },
        )

    # limit=1 时第一页只有最新那个用户
    page1 = await client.get("/api/admin/users?limit=1&offset=0", headers=auth_headers(admin_user))
    assert page1.status_code == 200
    assert len(page1.json()) == 1
    assert page1.json()[0]["username"] != "testuser"

    # 但按用户名搜索能直接命中老账号，说明过滤发生在分页之前
    found = await client.get(
        "/api/admin/users?limit=1&offset=0&q=testuser", headers=auth_headers(admin_user)
    )
    assert found.status_code == 200
    assert [u["username"] for u in found.json()] == ["testuser"]


@pytest.mark.asyncio
async def test_admin_site_settings_roundtrip_and_audit(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    """运营开关：GET 默认值 → PATCH 关 DOI → 再读 → 写审计。"""
    headers = auth_headers(admin_user)
    initial = await client.get("/api/admin/settings/site", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["doi_author_entry_enabled"] is True

    patched = await client.patch(
        "/api/admin/settings/site",
        json={"doi_author_entry_enabled": False},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["doi_author_entry_enabled"] is False

    reread = await client.get("/api/admin/settings/site", headers=headers)
    assert reread.status_code == 200
    assert reread.json()["doi_author_entry_enabled"] is False

    audit = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "admin.settings.site")
    )
    assert audit.scalars().first() is not None

    await client.patch(
        "/api/admin/settings/site",
        json={"doi_author_entry_enabled": True},
        headers=headers,
    )
