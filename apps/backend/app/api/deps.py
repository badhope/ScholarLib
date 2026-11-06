"""FastAPI dependencies: current user, admin, current tenant, db.

These compose into endpoint signatures:

    async def endpoint(
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_user),
    ): ...
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import bind_contextvars

from app.core.config import settings
from app.core.db import get_db
from app.core.security import decode_access_token, token_version_matches
from app.core.tenant import TENANT_CONTEXT_VAR
from app.models import Role, User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
# Variant that does not raise 401 when no token is present — used by
# endpoints that are public but personalize their response for logged-in
# users (e.g. resource view counts anonymous views).
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_current_tenant_id() -> UUID | None:
    """Return the current request's tenant id from the ContextVar.

    Always set by ``TenantContextMiddleware`` for HTTP requests. Returns
    ``None`` for non-HTTP contexts (background jobs) — callers must check.
    """
    return TENANT_CONTEXT_VAR.get()


def require_tenant_id() -> UUID:
    """Resolve tenant id or 400. Write endpoints need an explicit tenant scope."""
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context not resolved",
        )
    return tenant_id


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the access token."""
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc

    # Filter by tenant too: an access token minted in tenant A must not
    # authenticate against tenant B's deployment (User.id is global, so
    # without this filter the lookup would return the tenant-A user).
    tenant_id = TENANT_CONTEXT_VAR.get()
    stmt = select(User).where(User.id == user_id_int)
    if tenant_id is not None:
        stmt = stmt.where(User.tenant_id == tenant_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # Token-version check first: a stale token (e.g. after logout,
    # password change, or GDPR self-delete which bumps token_version)
    # is "invalid", not "user-disabled". Reporting 401 here prevents
    # leaking the account's active state to a stolen-but-revoked
    # access token.
    if not token_version_matches(payload, user.token_version):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled"
        )
    # Bind the resolved user id to the structlog context so that every
    # log line emitted during this request is automatically tagged.
    # The middleware clears the context after the request finishes.
    bind_contextvars(user_id=str(user.id), is_admin=bool(user.is_admin))
    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require the current user to have ``is_admin=True``.

    When ``settings.require_2fa_for_admin`` is True, additionally
    require the caller to have enrolled in TOTP. The reload-secret-keys
    endpoint opts out via ``require_admin_no_2fa`` below so an operator
    mid-rotation can still trigger a key reload.

    Per-tenant admin scope is enforced by RLS — a user with ``is_admin=True``
    in tenant A cannot read tenant B's data because RLS denies the rows.
    """
    # Enforce 2FA-for-admin policy before the admin check so that even
    # callers who passed the auth step still get the 2FA prompt when
    # the policy is on.
    if settings.require_2fa_for_admin and current_user.totp_enabled_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Admin access requires two-factor authentication. "
                "Enable TOTP in your account settings before calling "
                "admin endpoints."
            ),
        )
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


async def get_current_user_optional(
    token: str | None = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Resolve the current user when a valid token is present, else None.

    Used by endpoints that are publicly readable but personalize their
    response for authenticated callers. Any auth issue collapses to None
    so the endpoint can serve the anonymous response.
    """
    if token is None:
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        return None
    tenant_id = TENANT_CONTEXT_VAR.get()
    stmt = select(User).where(User.id == user_id_int)
    if tenant_id is not None:
        stmt = stmt.where(User.tenant_id == tenant_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    # Same ordering rationale as get_current_user: a revoked token
    # should look invalid (None), not look like a valid token for a
    # disabled user. Both collapse to None for the optional variant.
    if not token_version_matches(payload, user.token_version):
        return None
    bind_contextvars(user_id=str(user.id), is_admin=bool(user.is_admin))
    return user


# 预定义角色名（与 Role 表保持一致；bootstrap 创建时用此 slug）
# 编辑职权链（v1.11）：主编 > 副主编 > 编委（栏目编辑）> 执行编辑 > 审稿人。
# 主编/副主编持有终审权（四元决定）；编委与执行编辑负责初筛、送审与推荐。
ROLE_REVIEWER = "reviewer"
ROLE_SENIOR_REVIEWER = "senior_reviewer"
ROLE_EDITOR = "editor"
ROLE_SECTION_EDITOR = "section_editor"
ROLE_BOARD_EDITOR = "board_editor"
ROLE_DEPUTY_EDITOR = "deputy_editor"
ROLE_CHIEF_EDITOR = "chief_editor"
# 有终审权的角色集合（require_chief_editor 使用）
CHIEF_ROLES = (ROLE_CHIEF_EDITOR, ROLE_DEPUTY_EDITOR)
# 有编辑部职权（初筛/送审/推荐/工作台读）的角色集合（require_editor 使用）
EDITORIAL_ROLES = (
    ROLE_EDITOR,
    ROLE_SECTION_EDITOR,
    ROLE_BOARD_EDITOR,
    ROLE_DEPUTY_EDITOR,
    ROLE_CHIEF_EDITOR,
)


async def _user_has_role(db: AsyncSession, user: User, role_name: str) -> bool:
    """检查用户在当前租户内是否被分配了指定角色。

    admin 视为拥有所有角色（避免双重授予）；只要任一条件满足即通过。
    """
    if user.is_admin:
        return True
    tenant_id = user.tenant_id
    stmt = (
        select(UserRole)
        .join(Role, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user.id,
            UserRole.tenant_id == tenant_id,
            Role.tenant_id == tenant_id,
            Role.name == role_name,
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def user_has_role(db: AsyncSession, user: User, role_name: str) -> bool:
    """公开版本的角色检查，供路由内做细粒度授权判断。

    与 ``require_*`` 依赖的区别：这里返回布尔值而不是抛 403，适合
    「作者 OR 编辑 OR 被指派审稿人」这类多路授权。
    """
    return await _user_has_role(db, user, role_name)


async def user_role_names(db: AsyncSession, user: User) -> list[str]:
    """当前用户在本租户内被授予的角色名（去重排序；不含 admin 伪角色）。"""
    tenant_id = user.tenant_id
    result = await db.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user.id,
            UserRole.tenant_id == tenant_id,
            Role.tenant_id == tenant_id,
        )
    )
    return sorted({r for r in result.scalars() if r})


async def require_reviewer(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """要求当前用户拥有 reviewer / senior_reviewer 角色或 admin。

    L5 审稿人与 L6 资深审稿人共用同一套评审端点（接受/拒绝邀请、提交
    意见）；资深审稿人只是资格等级与候选池排序的差异，不是独立权限域。
    此前仅认 reviewer，导致 ladder 承诺的 L6 授予后处处 403。
    """
    if await _user_has_role(db, current_user, ROLE_REVIEWER) or await _user_has_role(
        db, current_user, ROLE_SENIOR_REVIEWER
    ):
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Reviewer role required",
    )


async def require_editor(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """要求当前用户拥有 editor / section_editor 角色或 admin。

    用于编辑工作台的读端点与送审操作（分配/撤销审稿人、匿名稿）。
    注意职权分离：**四元最终决定（录用/修回/拒稿）是 L8 执行编辑的
    职权**，见 :func:`require_chief_editor`。
    """
    for role in EDITORIAL_ROLES:
        if await _user_has_role(db, current_user, role):
            return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Editorial role required",
    )


async def require_chief_editor(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """要求当前用户拥有终审权角色：主编（chief_editor）、副主编
    （deputy_editor）或 admin。

    用于稿件四元决定端点。编委（board_editor/section_editor，L7）与
    执行编辑（editor）按职权链只做初筛、送审与推荐，没有最终裁决权；
    终审权集中在主编/主编级——决策可问责、口径统一。
    """
    for role in CHIEF_ROLES:
        if await _user_has_role(db, current_user, role):
            return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Chief editor role required",
    )
