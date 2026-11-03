"""Admin endpoints: list users, enable/disable users, list audit logs,
manage role assignments.

All endpoints require ``is_admin=True``. Per-tenant scoping is enforced
both at the application layer (explicit ``tenant_id`` filter on every
query) and by RLS in production. An admin in tenant A cannot read
tenant B's data.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_tenant_id
from app.core.config import settings
from app.core.db import get_db
from app.core.key_rotation import _active_secret_keys, _signing_key, reload_settings
from app.core.logging import get_logger
from app.models import AuditLog, Role, User, UserRole
from app.modules.review.blinding import get_review_mode, set_review_mode
from app.schemas import (
    ReviewModeResponse,
    ReviewModeUpdate,
    RoleAssign,
    UserResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])

logger = get_logger("rubbish.admin")

# Allowlist of assignable role names; mirrors Role.name values. Admin
# privilege is governed by User.is_admin, not by role membership.
# senior_reviewer（L6 资深审稿人）与 reviewer 共用评审端点，仅资格差异。
ASSIGNABLE_ROLES = {
    "reviewer",
    "senior_reviewer",
    "editor",
    "section_editor",
    "author",
    "reader",
}


@router.get("/security/status")
async def security_status(
    _admin: User = Depends(require_admin),
) -> dict[str, object]:
    """Report the JWT signing key state for the running process.

    Operators call this to confirm a rotation landed: the
    ``active_keys`` count goes up by 1 immediately after a successful
    ``POST /admin/security/reload`` if ``RUBBISH_PREVIOUS_SECRET_KEYS``
    was populated. The actual key material is NEVER returned — only
    the SHA-256 prefix (kid) so a dashboard can show which key signed
    a given token.
    """
    import hashlib

    keys = _active_secret_keys()
    current = _signing_key()
    return {
        "signing_key_count": len(keys),
        "previous_key_count": max(0, len(keys) - 1),
        # Public prefix only — never the key itself.
        "signing_key_kid": hashlib.sha256(current.encode("utf-8")).hexdigest()[:16]
        if current
        else None,
        # Operator-facing signal: did the most recent decode actually
        # consult a fallback key? Useful when verifying a rotation
        # worked in production.
        "rotation_window_open": len(keys) > 1,
    }


@router.post("/security/reload", status_code=status.HTTP_204_NO_CONTENT)
async def reload_security_settings(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> None:
    """Re-read ``RUBBISH_*`` env vars without restarting the process.

    Use this after rotating ``RUBBISH_SECRET_KEY`` /
    ``RUBBISH_PREVIOUS_SECRET_KEYS`` / ``RUBBISH_FERNET_KEYS``.
    New tokens use the new key immediately; tokens already in
    flight verify against the previous-key list until they expire.

    Audit-logged so a compromised admin cannot quietly rotate the
    signing key without a record.
    """
    reload_settings()
    db.add(
        AuditLog(
            tenant_id=current_admin.tenant_id,
            actor_user_id=current_admin.id,
            action="security.reload",
            target_type="security",
            target_id=None,
            payload={"keys_after_reload": len(_active_secret_keys())},
        )
    )
    await db.commit()
    logger.info("security_settings_reloaded", actor=current_admin.id)


async def _user_with_roles(db: AsyncSession, user: User) -> UserResponse:
    """Build a UserResponse and populate its role-name list for the current tenant."""
    result = await db.execute(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user.id,
            UserRole.tenant_id == user.tenant_id,
            Role.tenant_id == user.tenant_id,
        )
    )
    role_names = sorted({r for r in result.scalars() if r})
    resp = UserResponse.model_validate(user)
    resp.roles = role_names
    from app.api.levels import level_of

    resp.level = await level_of(db, user)
    return resp


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default="", max_length=200, description="按用户名或邮箱模糊匹配"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[UserResponse]:
    """List users in the current tenant, newest first.

    ``q`` 是服务端过滤：前端原先只在「当前这一页 50 条」里做本地过滤，
    用户超过 50 个以后，搜一个确实存在的账号会显示「暂无用户」——
    看起来像数据丢了。过滤必须在分页之前发生。
    """
    tenant_id = require_tenant_id()
    stmt = select(User).where(User.tenant_id == tenant_id)
    term = q.strip()
    if term:
        like = f"%{term.lower()}%"
        stmt = stmt.where(
            or_(func.lower(User.username).like(like), func.lower(User.email).like(like))
        )
    result = await db.execute(stmt.order_by(User.id.desc()).limit(limit).offset(offset))
    users = result.scalars().all()
    return [await _user_with_roles(db, u) for u in users]


@router.patch("/users/{user_id}/active", response_model=UserResponse)
async def set_user_active(
    user_id: int,
    is_active: bool,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> UserResponse:
    """Enable or disable a user. Disabling yourself is refused.

    When disabling, bump both token_version AND refresh_token_version
    so the disabled user's outstanding tokens (access + refresh) become
    invalid immediately, not just on next login.
    """
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own active state from this endpoint",
        )
    tenant_id = require_tenant_id()
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    previous = user.is_active
    user.is_active = is_active
    if not is_active:
        # Disable invalidates every token we've ever handed out so the
        # user can't keep using a still-valid access/refresh token.
        user.token_version += 1
        user.refresh_token_version += 1
    # Audit trail: record who flipped whose active flag, in the same
    # transaction so the log row never exists without the change.
    db.add(
        AuditLog(
            tenant_id=current_admin.tenant_id,
            actor_user_id=current_admin.id,
            action="user.set_active",
            target_type="user",
            target_id=str(user.id),
            payload={"field": "is_active", "old": previous, "new": is_active},
        )
    )
    await db.commit()
    await db.refresh(user)
    return await _user_with_roles(db, user)


@router.patch("/users/{user_id}/admin", response_model=UserResponse)
async def set_user_admin(
    user_id: int,
    is_admin: bool,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> UserResponse:
    """设置/取消平台管理员（提权为 admin）。

    ``is_admin`` 是平台级特权（可管理所有用户、改评分、看审计），不是租户
    角色。此前只能靠直接改数据库，前端「用户管理」页只读展示，导致
    "把某人提成管理员"在界面上无路可走。

    安全约束（三条都必要）：
    1. 不能改自己的 admin 状态——防止误操作把自己锁在门外；
    2. 不能把最后一个管理员降级——否则无人可管理系统；
    3. 提权/降权都写审计（谁在什么时候给了谁特权）。
    """
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能修改自己的管理员状态（避免把自己锁在门外）",
        )
    tenant_id = require_tenant_id()
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # 降级检查：至少保留一个管理员
    if not is_admin and user.is_admin:
        remaining = (
            await db.execute(
                select(func.count(User.id)).where(
                    User.tenant_id == tenant_id,
                    User.is_admin.is_(True),
                    User.id != user.id,
                )
            )
        ).scalar_one()
        if remaining < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能取消最后一个管理员——否则无人可管理系统",
            )

    previous = user.is_admin
    user.is_admin = is_admin
    if not is_admin:
        # 降权即吊销全部令牌：旧 access token 里的 is_admin 判断会随
        # 下次请求回查数据库失效，但 refresh token 仍能换新 access，
        # 所以必须同时 bump 两个版本号，确保彻底退出特权。
        user.token_version += 1
        user.refresh_token_version += 1
    db.add(
        AuditLog(
            tenant_id=current_admin.tenant_id,
            actor_user_id=current_admin.id,
            action="user.set_admin",
            target_type="user",
            target_id=str(user.id),
            payload={"field": "is_admin", "old": previous, "new": is_admin},
        )
    )
    await db.commit()
    await db.refresh(user)
    return await _user_with_roles(db, user)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> None:
    """Permanently delete a user (admin housekeeping for test/spam accounts).

    防护：管理员账号（含自己）不可删除，避免锁死管理入口；目标不存在
    或不属于本租户 → 404。关联内容按外键级联清理（users 的全部外键均
    为 CASCADE 或 SET NULL，无 RESTRICT），删除动作写入审计日志且与
    变更同事务。
    """
    tenant_id = require_tenant_id()
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.is_admin or user.id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrator accounts cannot be deleted",
        )
    username = user.username
    await db.delete(user)
    # Audit trail: record who deleted whom, same transaction as the delete.
    db.add(
        AuditLog(
            tenant_id=current_admin.tenant_id,
            actor_user_id=current_admin.id,
            action="user.deleted",
            target_type="user",
            target_id=str(user_id),
            payload={"username": username},
        )
    )
    await db.commit()


async def _get_or_create_role(db: AsyncSession, tenant_id: UUID, role_name: str) -> Role:
    """Get or create a role row (name is unique per tenant)."""
    role = (
        await db.execute(
            select(Role).where(
                Role.tenant_id == tenant_id,
                Role.name == role_name,
            )
        )
    ).scalar_one_or_none()
    if role is not None:
        return role
    role = Role(tenant_id=tenant_id, name=role_name)
    db.add(role)
    await db.flush()
    return role


@router.post(
    "/users/{user_id}/roles",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_role(
    user_id: int,
    body: RoleAssign,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> UserResponse:
    """Assign a role to a user (idempotent per tenant: returns the current state if already assigned)."""
    if body.role not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role '{body.role}' is not assignable",
        )
    tenant_id = require_tenant_id()
    user = (
        await db.execute(
            select(User).where(
                User.id == user_id,
                User.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    role = await _get_or_create_role(db, tenant_id, body.role)
    # Idempotent: if already assigned, return without re-inserting.
    existing = (
        await db.execute(
            select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_id == role.id,
                UserRole.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            UserRole(
                tenant_id=tenant_id,
                user_id=user.id,
                role_id=role.id,
            )
        )
        db.add(
            AuditLog(
                tenant_id=current_admin.tenant_id,
                actor_user_id=current_admin.id,
                action="user.assign_role",
                target_type="user",
                target_id=str(user.id),
                payload={"role": body.role},
            )
        )
        await db.commit()
    await db.refresh(user)
    return await _user_with_roles(db, user)


@router.delete(
    "/users/{user_id}/roles/{role_name}",
    response_model=UserResponse,
)
async def revoke_role(
    user_id: int,
    role_name: str,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> UserResponse:
    """Revoke a role from a user (returns 404 when absent, so silent success never misleads the frontend)."""
    tenant_id = require_tenant_id()
    if role_name not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role '{role_name}' is not revocable via this endpoint",
        )
    user = (
        await db.execute(
            select(User).where(
                User.id == user_id,
                User.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    role = (
        await db.execute(
            select(Role).where(
                Role.tenant_id == tenant_id,
                Role.name == role_name,
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Role '{role_name}' not found in this tenant",
        )
    link = (
        await db.execute(
            select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_id == role.id,
                UserRole.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User does not have this role",
        )
    await db.delete(link)
    db.add(
        AuditLog(
            tenant_id=current_admin.tenant_id,
            actor_user_id=current_admin.id,
            action="user.revoke_role",
            target_type="user",
            target_id=str(user.id),
            payload={"role": role_name},
        )
    )
    await db.commit()
    await db.refresh(user)
    return await _user_with_roles(db, user)


@router.get("/audit-logs", response_model=list[dict[str, Any]])
async def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List recent audit log entries for the current tenant (newest first)."""
    tenant_id = require_tenant_id()
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.tenant_id == tenant_id)
        # id 决胜：同秒写入的日志行排序稳定，审计页不抖动。
        .order_by(desc(AuditLog.created_at), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        {
            "id": log.id,
            "tenant_id": str(log.tenant_id) if log.tenant_id else None,
            "actor_user_id": log.actor_user_id,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "payload": log.payload,
            "created_at": log.created_at.isoformat(),
        }
        for log in result.scalars()
    ]


# ---------------------------------------------------------------------------
# Journal settings（租户级配置；目前只有评审模式）
# ---------------------------------------------------------------------------


@router.get("/settings/review-mode", response_model=ReviewModeResponse)
async def get_review_mode_setting(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> ReviewModeResponse:
    """读取本租户的评审模式（single_blind / double_blind）。"""
    tenant_id = require_tenant_id()
    return ReviewModeResponse(review_mode=await get_review_mode(db, tenant_id))


@router.patch("/settings/review-mode", response_model=ReviewModeResponse)
async def update_review_mode_setting(
    payload: ReviewModeUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> ReviewModeResponse:
    """切换本租户的评审模式。

    切换即时生效，但只影响此后的「审稿人读取稿件」请求 —— 已经看过
    作者姓名的审稿人无法被"取消知晓"，这一点在 UI 上要向管理员说明。
    """
    tenant_id = require_tenant_id()
    try:
        await set_review_mode(db, tenant_id, payload.review_mode)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        ) from exc
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_admin.id,
            action="admin.settings.review_mode",
            target_type="tenant",
            target_id=str(tenant_id),
            payload={"review_mode": payload.review_mode},
        )
    )
    await db.commit()
    return ReviewModeResponse(review_mode=payload.review_mode)


@router.post("/maintenance/review-reminders")
async def trigger_review_reminders(
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """手动触发一轮审稿催办（运维/排障用）。

    定时任务每 6 小时自动跑一次；此端点让管理员在需要时立即执行，
    返回本轮检查/催办/发信的计数。催办本身幂等（3 天窗口内不重置）。
    """
    from app.modules.submission.review_reminders import run_overdue_reminders

    tenant_id = require_tenant_id()
    stats = await run_overdue_reminders(db, tenant_id=tenant_id)
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_admin.id,
            action="admin.maintenance.review_reminders",
            target_type="tenant",
            target_id=str(tenant_id),
            payload=dict(stats),
        )
    )
    await db.commit()
    return stats


@router.get("/maintenance/email-status")
async def email_status(
    current_admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """邮件通道自检：是否配置、SMTP 是否可达（不发送真实邮件）。"""
    from app.core.email import configured_accounts, smtp_configured, verify_smtp_connection
    from app.core.mail_guard import guard_stats

    ok, detail = await verify_smtp_connection()
    accounts = configured_accounts()
    return {
        "configured": smtp_configured(),
        "reachable": ok,
        "detail": detail,
        "backend": settings.email_backend,
        # 发件身份列表：只回地址与主机，绝不回授权码。
        "accounts": [
            {"from_address": a.from_address, "host": a.host, "port": a.port} for a in accounts
        ],
        "from_address": accounts[0].from_address if accounts else "",
        "guard": guard_stats(),
    }
