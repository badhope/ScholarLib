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

    过渡实现：内部映射到五层权限轴的 ``editor_in_chief``。新代码应直接用
    ``Depends(require_role("editor_in_chief"))``。
    """
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

# ---------------------------------------------------------------------------
# 权限轴：五层收敛（v1.14）
# 访客（不入库） < user（读者=作者已合并） < reviewer（审稿人）
#   < editor（栏目编辑） < editor_in_chief（主编）
# 大身份包含小身份全部权限；主编不叠加小身份。所有权限校验统一走
# require_role(min_role)；旧 require_admin/require_reviewer/require_editor/
# require_chief_editor 保留为薄包装，内部映射到本轴。
# ---------------------------------------------------------------------------
PERMISSION_ROLES = ("user", "reviewer", "editor", "editor_in_chief")
PERMISSION_RANK: dict[str, int] = {
    "user": 1,
    "reviewer": 2,
    "editor": 3,
    "editor_in_chief": 4,
}
# 历史 user_roles 名 → 五层权限档位（过渡映射；迁移后以 users.role 为准）。
_LEGACY_ROLE_TO_PERMISSION: dict[str, str] = {
    "reviewer": "reviewer",
    "senior_reviewer": "reviewer",
    "section_editor": "editor",
    "board_editor": "editor",
    "editor": "editor",
    "deputy_editor": "editor_in_chief",
    "chief_editor": "editor_in_chief",
}


async def effective_permission_role(db: AsyncSession, user: User) -> str:
    """解析用户当前最高权限档位（五层之一）。

    以 ``users.role`` 为权威；若仍停留在迁移前的默认值 ``user``，则回退到
    ``is_admin`` 与历史 ``user_roles`` 推导，保证迁移窗口内与单测里不丢权限。
    """
    # is_admin 历史上等价主编；优先于普通 user 档位。
    if user.is_admin:
        return "editor_in_chief"
    role = (user.role or "user").strip()
    if role in PERMISSION_RANK and role != "user":
        return role
    # 迁移前兜底：从 user_roles 推导最高档位。
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
    best = "user"
    best_rank = PERMISSION_RANK["user"]
    for name in result.scalars():
        mapped = _LEGACY_ROLE_TO_PERMISSION.get(name)
        if mapped and PERMISSION_RANK[mapped] > best_rank:
            best = mapped
            best_rank = PERMISSION_RANK[mapped]
    return best


def require_role(min_role: str):
    """权限校验统一依赖：要求当前用户权限档位 >= min_role。

    用法::

        async def endpoint(user: User = Depends(require_role("editor"))): ...

    档位层级：user < reviewer < editor < editor_in_chief。低权限账号打
    高权限接口一律 403。
    """
    if min_role not in PERMISSION_RANK:
        raise ValueError(f"unknown permission role: {min_role}")
    min_rank = PERMISSION_RANK[min_role]

    async def _guard(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        # 2FA-for-admin 只对主编级生效（沿用 require_admin 的既有策略）。
        if (
            min_role == "editor_in_chief"
            and settings.require_2fa_for_admin
            and current_user.totp_enabled_at is None
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Admin access requires two-factor authentication. "
                    "Enable TOTP in your account settings before calling "
                    "admin endpoints."
                ),
            )
        actual = await effective_permission_role(db, current_user)
        if PERMISSION_RANK[actual] < min_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "insufficient_permission",
                    "required_role": min_role,
                    "actual_role": actual,
                    "message": f"需要 {min_role} 权限，当前为 {actual}。",
                },
            )
        return current_user

    return _guard


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
    """要求当前用户权限档位 >= reviewer（五层轴）。

    历史上认 reviewer / senior_reviewer 两个角色；现在统一由 users.role
    （迁移自 user_roles）判定，两者等价。
    """
    actual = await effective_permission_role(db, current_user)
    if PERMISSION_RANK[actual] < PERMISSION_RANK["reviewer"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer role required",
        )
    return current_user


async def require_editor(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """要求当前用户权限档位 >= editor（五层轴）。

    用于编辑工作台的读端点与送审操作（分配/撤销审稿人、匿名稿）。
    """
    actual = await effective_permission_role(db, current_user)
    if PERMISSION_RANK[actual] < PERMISSION_RANK["editor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Editorial role required",
        )
    return current_user


async def require_chief_editor(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """要求当前用户权限档位 == editor_in_chief（五层轴，终审权）。"""
    actual = await effective_permission_role(db, current_user)
    if PERMISSION_RANK[actual] < PERMISSION_RANK["editor_in_chief"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chief editor role required",
        )
    return current_user
