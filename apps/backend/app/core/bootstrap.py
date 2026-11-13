"""Startup bootstrap: ensure the bootstrap tenant + initial admin user exist.

Why a dedicated module (not inline in ``main.py`` lifespan):
- tenant creation currently happens lazily in ``TenantContextMiddleware``
  on the first request. That works for tenant, but admin user creation
  has the same first-startup need and would otherwise require a manual
  one-off script (which is what ``_dev_create_admin.py`` was).
- Keeping the two concerns separate (tenant vs admin) lets us test
  each in isolation and avoids coupling admin creation to the HTTP
  middleware layer.

Idempotency:
- Tenant: SELECT by ``slug == settings.bootstrap_tenant_slug``; create
  only if missing.
- Admin: SELECT by ``tenant_id + username == settings.admin_username``;
  create only if missing. Updating the password of an existing admin
  is intentionally NOT done here — operators change passwords via the
  admin UI or password-reset flow, not by editing ``.env`` and
  restarting.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import async_session_factory
from app.core.logging import get_logger
from app.core.security import hash_password
from app.core.tenant import TENANT_CONTEXT_VAR
from app.models import Role, Tenant, User, UserRole

logger = get_logger("rubbish.bootstrap")

# Predefined role slugs (kept in sync with deps.py).
ROLE_EDITOR = "editor"
ROLE_REVIEWER = "reviewer"
ROLE_BOARD_EDITOR = "board_editor"
ROLE_DEPUTY_EDITOR = "deputy_editor"
ROLE_CHIEF_EDITOR = "chief_editor"
ROLE_SHOP_MANAGER = "shop_manager"


async def _ensure_bootstrap_tenant(session: AsyncSession) -> Tenant:
    """Return the bootstrap tenant, creating it if absent (single mode)."""
    slug = settings.bootstrap_tenant_slug
    result = await session.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if tenant is not None:
        return tenant
    tenant = Tenant(
        slug=slug,
        name=f"Bootstrap ({slug})",
        tenant_type="journal",
        is_active=True,
    )
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)
    logger.info("bootstrap_tenant_created", slug=slug, tenant_id=str(tenant.id))
    return tenant


async def _ensure_admin_user(session: AsyncSession, tenant: Tenant) -> None:
    """Create the initial admin user under ``tenant`` if absent.

    Idempotent: if an admin with ``settings.admin_username`` already
    exists under this tenant, do nothing. Password rotations are NOT
    applied here — see module docstring.
    """
    username = settings.admin_username
    result = await session.execute(
        select(User).where(
            User.tenant_id == tenant.id,
            User.username == username,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return
    user = User(
        tenant_id=tenant.id,
        email=settings.admin_email,
        username=username,
        hashed_password=hash_password(settings.admin_password),
        is_active=True,
        is_admin=True,
        # Bootstrap admin is trusted — skip the email-verification gate.
        is_email_verified=True,
    )
    session.add(user)
    await session.commit()
    logger.info(
        "bootstrap_admin_created",
        user_id=user.id,
        username=username,
        tenant_id=str(tenant.id),
    )


async def run_bootstrap() -> None:
    """Ensure the bootstrap tenant and initial admin user exist.

    Called from the FastAPI lifespan on startup (skipped in test env,
    where fixtures build their own users).
    """
    if settings.is_test:
        return

    # 关键：RLS 落地（迁移 003，FORCE ROW LEVEL SECURITY）之后，连表属主也受
    # 策略约束，而会话 GUC 是在**事务 BEGIN 之后**注入的（见
    # app/core/db.py::_reissue_tenant_guc）。所以在同一个事务里改
    # TENANT_CONTEXT_VAR 是无效的——租户已存在时 _ensure_bootstrap_tenant 会
    # 提前 return、不提交，事务不结束，GUC 就一直是 NULL，后续写 users/roles
    # 会被 RLS 全部拒绝（实测：启动直接 500 "new row violates row-level
    # security policy for table users"）。
    #
    # 因此分两段会话：第一段只查/建租户（tenants 表没有 tenant_id，不受 RLS
    # 约束），关闭后再带着租户 id 开第二段，让新事务 BEGIN 时设置正确的 GUC。
    async with async_session_factory() as session:
        tenant = await _ensure_bootstrap_tenant(session)

    TENANT_CONTEXT_VAR.set(tenant.id)
    async with async_session_factory() as session:
        await _ensure_admin_user(session, tenant)
        # Create the reviewer + editor roles the review workflow needs; the
        # admin is then granted both so operators can self-test the
        # reviewer/editor flows directly.
        await _ensure_review_roles(session, tenant)
        await _ensure_admin_roles(session, tenant)


async def _ensure_review_roles(session: AsyncSession, tenant: Tenant) -> None:
    """Idempotently create the editorial role chain + reviewer rows.

    v1.11 编辑职权链：主编 > 副主编 > 编委 > 执行编辑 > 审稿人。
    终审权（四元决定）只属主编/副主编；编委与执行编辑负责初筛、送审
    与推荐。幂等：已存在的角色行不动。
    """
    for name, desc in (
        (ROLE_CHIEF_EDITOR, "Editor-in-chief (final accept/revise/reject decisions)"),
        (ROLE_DEPUTY_EDITOR, "Deputy editor-in-chief (final decisions, deputizes for EIC)"),
        (ROLE_BOARD_EDITOR, "Editorial board (screening, assigning reviewers, recommendation)"),
        (ROLE_EDITOR, "Editor (assign reviewers + desk screening)"),
        (ROLE_REVIEWER, "Peer reviewer (accept/decline invitations + submit reports)"),
        (ROLE_SHOP_MANAGER, "Shop manager (R-coin shop catalog, pricing and issuance rules)"),
    ):
        existing = (
            await session.execute(
                select(Role).where(
                    Role.tenant_id == tenant.id,
                    Role.name == name,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        session.add(
            Role(
                tenant_id=tenant.id,
                name=name,
                description=desc,
            )
        )
    await session.commit()


async def _ensure_admin_roles(session: AsyncSession, tenant: Tenant) -> None:
    """Assign the editor + reviewer roles to the admin user (dev convenience only).

    In production, roles are granted on demand via the user-management API.
    The admin already passes every require_editor / require_reviewer check
    via is_admin=True, so this assignment is purely an explicit marker
    for visibility in the admin UI.
    """
    admin = (
        await session.execute(
            select(User).where(
                User.tenant_id == tenant.id,
                User.username == settings.admin_username,
            )
        )
    ).scalar_one_or_none()
    if admin is None:
        return
    roles = (
        (
            await session.execute(
                select(Role).where(
                    Role.tenant_id == tenant.id,
                    Role.name.in_((ROLE_EDITOR, ROLE_REVIEWER)),
                )
            )
        )
        .scalars()
        .all()
    )
    for role in roles:
        existing = (
            await session.execute(
                select(UserRole).where(
                    UserRole.tenant_id == tenant.id,
                    UserRole.user_id == admin.id,
                    UserRole.role_id == role.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        session.add(
            UserRole(
                tenant_id=tenant.id,
                user_id=admin.id,
                role_id=role.id,
            )
        )
    await session.commit()
