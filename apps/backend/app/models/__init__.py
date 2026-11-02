"""ORM models for the base spine.

All models inherit from ``Base`` (defined here). Domain-specific tables
(submissions, publications, etc.) live in module packages under
``app.modules.<name>.models`` and contribute their own ``Base.metadata``
via the module registry.

Every multi-tenant table MUST carry ``tenant_id`` (UUID, non-null, indexed)
and rely on PostgreSQL RLS for isolation. See ARCHITECTURE.md §Tenancy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.time import utcnow

# JSONB falls back to JSON on SQLite so in-memory tests can run.
JSONBVariant = JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    """Declarative base for the core models. Modules declare their own
    ``Base`` subclasses; the registry merges their metadata into the
    Alembic target_metadata (see alembic/env.py).
    """

    pass


class TenantScopedMixin:
    """Q-4 统一 tenant_id 列声明。

    所有多租户表共享的 ``tenant_id`` 列定义：UUID + FK→tenants.id +
    non-null + indexed。各模块模型通过混入此 Mixin 获得该列，避免
    22 处重复声明（旧代码里每个模型都手写一遍 5 行 mapped_column）。

    Mixin 不声明 ``__tablename__``，不声明主键——只做"列注入"。
    使用方::

        class MyModel(Base, TenantScopedMixin):
            __tablename__ = "my_table"
            id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
            ...
    """

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class Tenant(Base):
    """A tenant = one journal/press/server/etc. on the platform.

    In single mode, exactly one row exists (created lazily on first
    startup). In multi mode, one row per tenant. All domain tables carry
    ``tenant_id`` referencing this table.
    """

    __tablename__ = "tenants"
    # Named constraint (not `unique=True` on the column) so the metadata
    # matches what the migration created and `alembic check` stays clean.
    __table_args__ = (UniqueConstraint("slug", name="uq_tenants_slug"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    # Type enables future expansion: 'journal' | 'press' | 'server' | 'institution'.
    tenant_type: Mapped[str] = mapped_column(String(32), default="journal")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Arbitrary key/value settings — replaces OJS-style ``*_settings`` tables.
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSONBVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    users: Mapped[list[User]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    hosts: Mapped[list[TenantHost]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class TenantHost(Base, TenantScopedMixin):
    """Maps a host-header domain name to a tenant.

    Used in multi-tenant mode to resolve which tenant a request belongs to
    based on the ``Host`` header. One tenant can have multiple hostnames
    (e.g. ``journal-a.example.com`` and ``www.journal-a.org``).
    """

    __tablename__ = "tenant_hosts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    tenant: Mapped[Tenant] = relationship(back_populates="hosts")


class User(Base, TenantScopedMixin):
    """A platform user. Belongs to one tenant; role assignments are M:N.

    ``token_version`` is bumped on logout/password change to
    invalidate all outstanding access tokens.

    ``refresh_token_version`` is a separate counter bumped on each
    ``/auth/refresh`` call. It invalidates only the consumed refresh
    token (and any other refresh tokens issued before this refresh) —
    access tokens and the user's other devices are not affected.
    This is OAuth2-standard refresh token rotation: a stolen refresh
    token becomes useless the moment the legitimate holder refreshes.
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
        # Composite lookup used by ORCID attribution search; created by
        # migration 014 but previously missing here, which made
        # `alembic check` report a spurious drift.
        Index("ix_users_tenant_orcid", "tenant_id", "orcid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Independent from token_version so refresh rotation does not log out
    # every device the way logout / password change do.
    refresh_token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # --- TOTP two-factor auth (opt-in per user) ---
    # TOTP 2FA secret encrypted at rest with Fernet; used by app/api/two_factor.py
    # via core/totp.py. 2FA takes effect once ``totp_enabled_at`` is stamped
    # (i.e. after the user has proven they can produce a valid code).
    # The legacy plaintext ``two_factor_*`` column group was dropped by
    # migration 021_unify_two_factor.
    totp_secret_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # JSON array of SHA-256 hashes of the one-time backup codes.
    totp_backup_codes_hashed: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Timestamp when 2FA was enabled (used for the privacy audit log).
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Highest TOTP counter (30s window index) ever accepted for this user.
    # Replay protection: verify_totp rejects any counter <= this value, so a
    # captured code cannot be reused within its window. See migration 022.
    totp_last_used_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # --- WebAuthn / Passkeys ---
    # JSON array of registered credential dicts:
    #   [{"id": "...", "public_key": "...", "sign_count": 0, "name": "...", "created_at": "..."}]
    webauthn_credentials: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONBVariant, nullable=True
    )
    # OpenID Connect ORCID iD linked to this user (optional).
    orcid: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 用户自定义一句话简介（个人中心展示；迁移 012）。
    bio: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Soft-delete timestamp. Set when the user requests account deletion
    # (GDPR right-to-erasure). The row is anonymised in place, and a
    # background job hard-deletes it after the grace window.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # --- 等级体系（gamification 模块） ---
    # 运行中的 XP 总分：ledger（user_xp_events）是事实源，这里是热路径快照。
    xp: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 投稿规范确认：作者必须读过当前版本的《投稿规范》才能提交。
    # 版本号与 docs/editorial-standards.md 的 front-matter 对齐。
    rules_ack_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rules_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")
    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(Base, TenantScopedMixin):
    """Pre-defined role labels per tenant. Roles are NOT user-defined yet —
    a fixed enum is enough for the base spine.

    The base ships with: editor / section_editor / author / reviewer /
    reader. Modules may add their own roles by inserting rows here.
    """

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    assignments: Mapped[list[UserRole]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class UserRole(Base, TenantScopedMixin):
    """M:N between User and Role, scoped per tenant.

    Both User and Role already carry tenant_id; this junction table
    repeats it for RLS coverage and easier per-tenant queries.
    """

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "role_id", name="uq_user_roles_tenant_user_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship(back_populates="assignments")


class AuditLog(Base):
    """Immutable record of destructive operations (user delete, role change,
    module enable/disable, schema migration).

    Append-only: never UPDATE or DELETE rows. The admin UI exposes this
    read-only; the cleanup policy is a separate operational concern.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(128))
    # Arbitrary structured payload (before/after/diff).
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONBVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
        index=True,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # S-3 租户隔离收口：audit 表 tenant_id 允许 None（ondelete=SET NULL），
        # 但所有 15+ 写点都应绑定租户。001 的 RLS policy
        # `WITH CHECK (tenant_id IS NULL OR ...)` 还放行 NULL 写入，这是
        # 多租户下"审计行漂移到无主租户"的潜在泄漏面。这里在模型层兜底：
        # 任何无租户上下文（如系统级 cleanup）的写点必须显式传入
        # `audit_tenant_exempt=True` kwarg 才能写 None，否则直接抛错，
        # 把"分散 15 处都要查 tenant 非空"的风险收敛到这一处模型级断言。
        tenant_id = kwargs.get("tenant_id", getattr(self, "tenant_id", None))
        if tenant_id is None and not kwargs.pop("audit_tenant_exempt", False):
            raise ValueError(
                "AuditLog.tenant_id must be non-null in tenant context; "
                "pass audit_tenant_exempt=True for system-level (no-tenant) writes"
            )


class EmailLoginCode(Base, TenantScopedMixin):
    """一次性邮箱登录验证码（哈希存储，10 分钟有效）。

    为什么做：读者记不住密码，「输邮箱收个码就进」是内容站的标准期待。
    码只存 SHA-256 哈希；同邮箱重新请求即作废旧码；每码最多 5 次校验
    尝试，防 6 位数字空间被在线爆破。
    """

    __tablename__ = "email_login_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # SHA-256(email:code:server_secret) 的 hex——库里泄露也不可回用
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 每码最多 5 次尝试；超过即作废（校验时删除）
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)




__all__ = [
    "AuditLog",
    "EmailLoginCode",
    "Base",
    "Role",
    "Tenant",
    "TenantHost",
    "TenantScopedMixin",
    "User",
    "UserRole",
]
