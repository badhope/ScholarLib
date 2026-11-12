"""Pydantic schemas for the base spine API.

Auth + user + module + admin endpoints. Domain schemas (catalog,
submission, etc.) live in module packages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


# --- Auth ---
class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    # Optional CAPTCHA token. Required when the deployment has
    # captcha_required_for_registration=True; ignored otherwise.
    captcha_token: str | None = None
    captcha_answer: str | None = None

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        """邮箱统一小写存储。

        注册原样落库、登录忽略大小写、找回密码按原样等值匹配 —— 三者
        口径不一致时，用 ``Foo@x.com`` 注册的人在找回密码时输入
        ``foo@x.com`` 永远收不到信，而 ``Foo@x.com`` 与 ``foo@x.com``
        又能被当成两个账号注册。入口归一化是唯一能同时修掉两者的位置。
        """
        return value.strip().lower()


class UserLogin(BaseModel):
    username: str
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    user_id: int
    username: str
    is_admin: bool
    # 当前用户的角色名列表（reviewer/editor/section_editor/author/reader）。
    # 登录响应即携带，前端据此渲染「审稿工作台 / 编辑工作台」等入口，
    # 不必再调 /admin/users（那个接口要求 admin 权限）。
    roles: list[str] = Field(default_factory=list)
    # M2 2FA: when 2FA is required but not yet completed, access/refresh
    # are empty strings and ``requires_2fa`` is True with a short-lived
    # ``two_factor_token`` to redeem via POST /auth/2fa/authenticate.
    # Fields are optional with defaults so non-2FA callers keep working.
    requires_2fa: bool = False
    two_factor_token: str | None = None


class TwoFactorSetupResponse(BaseModel):
    """Returned by GET/POST /auth/2fa/setup - the secret + 10 backup codes.

    ``secret`` is the raw base32 secret. The client renders it as a QR
    code via the otpauth URI. It is the LAST time the secret is exposed:
    once the user verifies and enables, it lives only in the encrypted
    column on the server. ``backup_codes`` is similarly one-shot: the
    cleartext list is returned exactly once, never persisted.
    """

    secret: str
    otpauth_uri: str
    backup_codes: list[str] = Field(default_factory=list)


class TwoFactorVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class TwoFactorAuthenticateRequest(BaseModel):
    """Body for POST /auth/2fa/authenticate.

    Exactly one of ``code`` (TOTP) or ``backup_code`` is required.
    """

    two_factor_token: str = Field(min_length=1)
    code: str | None = Field(default=None, min_length=6, max_length=10)
    backup_code: str | None = Field(default=None, min_length=4, max_length=20)


class TwoFactorStatusResponse(BaseModel):
    """Returned by GET /auth/2fa/status - tells the SPA whether 2FA is on."""

    enabled: bool
    # Count of remaining un-used backup codes. 0 means the user should
    # regenerate; the SPA can prompt accordingly.
    backup_codes_remaining: int


class TwoFactorDisableRequest(BaseModel):
    """Body for POST /auth/2fa/disable.

    Require both the user's current password AND a fresh TOTP code OR
    a backup code - so a stolen device / hijacked session alone cannot
    turn off 2FA. A bare password is not enough.
    """

    password: str = Field(min_length=1)
    code: str | None = Field(default=None, min_length=6, max_length=10)
    backup_code: str | None = Field(default=None, min_length=4, max_length=20)


# --- Two-factor auth (TOTP) ---
class TwoFactorRequiredResponse(BaseModel):
    """Returned by /auth/login when the account has 2FA enabled.

    No access/refresh tokens yet — the client exchanges
    ``pending_token`` + a TOTP (or recovery) code at /auth/login/2fa.
    """

    two_factor_required: Literal[True] = True
    pending_token: str


class TwoFactorLoginRequest(BaseModel):
    pending_token: str = Field(min_length=1)
    # 6-digit TOTP or a xxxx-xxxx-xxxx recovery code
    code: str = Field(min_length=6, max_length=32)


class TwoFactorEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class TwoFactorEnableResponse(BaseModel):
    enabled: Literal[True] = True
    # Shown exactly once at enable time; only hashes are stored.
    recovery_codes: list[str]


# --- Email verification + password reset ---
class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1)


class ResendVerificationRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class EmailCodeRequest(BaseModel):
    """请求邮箱登录验证码。"""

    email: EmailStr


class EmailCodeVerify(BaseModel):
    """邮箱 + 验证码登录。code 刻意用 str：前导 0（如 012345）是合法码。"""

    email: EmailStr
    code: str = Field(min_length=6, max_length=8, pattern=r"^\d{6}$")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


# --- User ---
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # 输出 schema 不再用 EmailStr：数据库里已存过的 email 视为合法。
    # 之前用 EmailStr 会导致 admin@rubbish.local 这类保留 TLD 邮箱无法
    # 序列化（admin/users 直接 500），输出端做二次校验是反模式。
    email: str
    username: str
    is_active: bool
    is_admin: bool
    is_email_verified: bool
    created_at: datetime
    # ORCID iD in canonical hyphenated form, or null when not set.
    orcid: str | None = None
    # 用户自定义一句话简介（个人中心/评论区展示；迁移 012）。
    bio: str | None = None
    # 可扩展资料（迁移 026）；全部可空，旧客户端不受影响。
    display_name: str | None = None
    real_name: str | None = None
    affiliation: str | None = None
    department: str | None = None
    academic_title: str | None = None
    research_interests: str | None = None
    website: str | None = None
    google_scholar: str | None = None
    location: str | None = None
    # 当前用户在本租户内被授予的角色名列表（如 ["reviewer", "editor"]）
    # 默认空列表：未填充时视为"无角色"，向后兼容旧调用点
    roles: list[str] = Field(default_factory=list)
    # 等级体系：XP 总分与生效等级（1–9）。/auth/me、/users/me 现算填充；
    # ORM 直出路径取默认值（0 / 1），admin 列表另有显式填充。
    xp: int = 0
    level: int = 1
    rules_accepted: bool = False

    @model_validator(mode="before")
    @classmethod
    def _do_not_lazy_load_roles(cls, data: Any) -> Any:
        """防止 from_attributes 触发 User.roles SQLAlchemy relationship lazy load。

        SQLAlchemy relationship 异步访问会抛 MissingGreenlet；这里拦截 ORM 实例
        并只取标量字段，让 roles 走默认空列表（admin 端点用 _user_with_roles 显式填充）。
        """
        # 用 duck typing 避免循环 import：检查是否为 SQLAlchemy ORM 实例
        if hasattr(data, "_sa_instance_state"):
            # ORM 实例：只取标量列，避免触发 relationship lazy load
            return {
                "id": data.id,
                "email": data.email,
                "username": data.username,
                "is_active": data.is_active,
                "is_admin": data.is_admin,
                "is_email_verified": data.is_email_verified,
                "created_at": data.created_at,
                "orcid": data.orcid,
                "bio": data.bio,
                "display_name": data.display_name,
                "real_name": data.real_name,
                "affiliation": data.affiliation,
                "department": data.department,
                "academic_title": data.academic_title,
                "research_interests": data.research_interests,
                "website": data.website,
                "google_scholar": data.google_scholar,
                "location": data.location,
                "xp": int(getattr(data, "xp", 0) or 0),
                # roles 不在此填：让默认空列表生效；admin 路径用 _user_with_roles 显式覆盖
            }
        return data


class RoleAssign(BaseModel):
    """Body for POST /admin/users/{id}/roles — assign a role to a user."""

    # 仅允许分配编辑部/社区角色；admin 角色由 is_admin 字段控制，不在此处
    # 编辑职权链（v1.11）：主编/副主编/编委与执行编辑同级可分配；
    # author/reader 是身份不是角色（见 admin.ASSIGNABLE_ROLES 注释）。
    role: Literal[
        "chief_editor",
        "deputy_editor",
        "board_editor",
        "reviewer",
        "senior_reviewer",
        "editor",
        "section_editor",
        "author",
        "reader",
    ]


class ReviewModeUpdate(BaseModel):
    """Body for PATCH /admin/settings/review-mode."""

    review_mode: Literal["single_blind", "double_blind"]


class ReviewModeResponse(BaseModel):
    review_mode: Literal["single_blind", "double_blind"]


class SiteSettingsResponse(BaseModel):
    """Tenant-editable runtime switches (persist across restarts)."""

    captcha_required_for_registration: bool
    doi_author_entry_enabled: bool


class SiteSettingsUpdate(BaseModel):
    """Partial update; omitted keys keep their stored values."""

    captcha_required_for_registration: bool | None = None
    doi_author_entry_enabled: bool | None = None


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=3, max_length=100)
    is_active: bool | None = None
    # ORCID iD. Set to empty string to clear; pass None to leave
    # unchanged. We validate and canonicalise here so the DB layer
    # never sees a malformed value.
    orcid: str | None = None
    # 一句话简介：≤200 字；空串按清除处理，None 保持不变。
    bio: str | None = Field(default=None, max_length=200)
    # 可扩展资料（迁移 026）。空串统一按清除处理；缺键不触碰。
    display_name: str | None = Field(default=None, max_length=100)
    real_name: str | None = Field(default=None, max_length=100)
    affiliation: str | None = Field(default=None, max_length=300)
    department: str | None = Field(default=None, max_length=200)
    academic_title: str | None = Field(default=None, max_length=100)
    research_interests: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=300)
    google_scholar: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=100)

    @field_validator(
        "display_name",
        "real_name",
        "affiliation",
        "department",
        "academic_title",
        "research_interests",
        "location",
    )
    @classmethod
    def _clean_profile_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("website", "google_scholar")
    @classmethod
    def _clean_profile_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("个人主页必须是 http(s) 链接")
        return cleaned

    @field_validator("bio")
    @classmethod
    def _clean_bio(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str | None) -> str | None:
        return value.strip().lower() if value is not None else None

    @field_validator("orcid")
    @classmethod
    def _canonicalise_orcid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value == "":
            return None  # explicit clear
        from app.core.orcid import is_valid_orcid, normalize_orcid

        if not is_valid_orcid(value):
            raise ValueError(f"Invalid ORCID iD: {value!r}")
        return normalize_orcid(value)


class ORCIDUpdateRequest(BaseModel):
    """Body for PATCH /me/orcid. Empty string clears; missing field is no-op.

    Separate from ``UserUpdate`` so the /me/orcid endpoint has an
    explicit, narrow contract: ``{"orcid": "..."}`` (set),
    ``{"orcid": ""}`` (clear), or ``{}`` (no-op). This keeps the
    self-service ORCID editing flow decoupled from the admin's
    ``UserUpdate`` body.

    ``max_length`` is generous because we accept URL forms up to
    ``https://orcid.org/0000-0002-1825-0097`` (38 chars). The
    canonical validator truncates the URL to its 19-char iD.
    """

    orcid: str | None = Field(default=None, max_length=64)

    @field_validator("orcid")
    @classmethod
    def _canonicalise_orcid(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        from app.core.orcid import is_valid_orcid, normalize_orcid

        if not is_valid_orcid(value):
            raise ValueError(f"Invalid ORCID iD: {value!r}")
        return normalize_orcid(value)


# --- Module ---
class ModuleInfo(BaseModel):
    name: str
    version: str
    description: str = ""


# --- Health ---
class HealthResponse(BaseModel):
    status: Literal["ok"]
    # 前端/部署脚本用 version 做“这次到底部署成功没有”的指纹；
    # 之前只有 status，测试和发布核对都拿不到版本。
    version: str = ""


class HealthReadyResponse(BaseModel):
    status: Literal["ok", "error"]
    database: Literal["connected", "unavailable"]


# --- Tenant ---
class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    tenant_type: str
    is_active: bool


# --- Tenant Host ---
class TenantHostCreate(BaseModel):
    """Body for POST /api/admin/tenant-hosts — add a host mapping."""

    host: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*$",
    )


class TenantHostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: UUID
    host: str
    is_active: bool
    created_at: datetime
