"""Authentication endpoints: register, login, refresh, logout, me,
email verification, password reset.

JWT-based: access token (short-lived) + refresh token (long-lived in
httpOnly cookie). ``token_version`` on the User row invalidates all
outstanding access tokens on logout/password change.

Refresh tokens use a JTI-based denylist for fine-grained per-token
revocation: each ``/auth/refresh`` adds the consumed token's ``jti``
to the denylist, so the same refresh token cannot be replayed without
affecting other devices. ``refresh_token_version`` is reserved for
bulk revocation (revoke-all, password change).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_tenant_id,
    get_current_user,
    require_tenant_id,
    user_role_names,
)
from app.core.captcha import issue_captcha, verify_captcha_token
from app.core.config import settings
from app.core.db import get_db
from app.core.email import get_email_sender
from app.core.email_code import (
    CODE_TTL_MINUTES,
    DAILY_SEND_LIMIT,
    MAX_VERIFY_ATTEMPTS,
    SEND_INTERVAL_SECONDS,
    codes_match,
    generate_code,
    hash_code,
)
from app.core.email_templates import (
    duplicate_registration,
)
from app.core.email_templates import email_login_code as _email_login_code_template
from app.core.email_templates import (
    reset_password as reset_password_tpl,
)
from app.core.email_templates import (
    verify_email as verify_email_tpl,
)
from app.core.logging import get_logger
from app.core.mail_guard import allow_email_to
from app.core.schemas import MessageResponse
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    refresh_token_version_matches,
    token_version_matches,
    verify_password,
)
from app.core.time import utcnow
from app.core.token_denylist import get_denylist
from app.core.tokens import (
    RESET_PASSWORD_TOKEN_TYPE,
    VERIFY_EMAIL_TOKEN_TYPE,
    create_email_verification_token,
    create_password_reset_token,
    decode_token,
    random_jti,
)
from app.core.totp import (
    create_two_factor_pending_token,
    decode_two_factor_pending_token,
    decrypt_secret,
    hash_backup_code,
    normalize_backup_code,
    verify_totp,
)
from app.models import EmailLoginCode, User
from app.schemas import (
    EmailCodeRequest,
    EmailCodeVerify,
    ForgotPasswordRequest,
    ORCIDUpdateRequest,
    RefreshTokenRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    TwoFactorLoginRequest,
    TwoFactorRequiredResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    VerifyEmailRequest,
)

# Anti-enumeration: the same body is returned whether registration succeeded
# or hit a duplicate-email/username collision, and neither path issues tokens.
_REGISTER_MESSAGE = "If the email is not yet registered, a verification email has been sent."

router = APIRouter(prefix="/auth", tags=["auth"])

logger = get_logger("rubbish.auth")

_REFRESH_COOKIE_KEY = settings.refresh_token_cookie_name


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Set the refresh token as an HttpOnly cookie scoped to /api/auth."""
    response.set_cookie(
        key=_REFRESH_COOKIE_KEY,
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.refresh_token_expire_days * 86400,
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE_KEY,
        path="/api/auth",
        samesite=settings.cookie_samesite,
    )


def _extract_refresh_token(request: Request, body_token: str | None) -> str | None:
    """Read refresh token from cookie first (HttpOnly, XSS-safe), then body."""
    return request.cookies.get(_REFRESH_COOKIE_KEY) or body_token


@router.get("/captcha")
async def captcha_challenge() -> dict[str, str]:
    """签发一道自建算术验证码；注册时回传 token + answer。"""
    return issue_captcha()


@router.post(
    "/register",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    request: Request,
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Register a new user under the current tenant.

    Anti-enumeration: success and a duplicate email/username return the SAME
    201 ``MessageResponse`` and neither path sets a session cookie, so the
    caller cannot tell whether the account already existed. Tokens are only
    issued by ``POST /auth/login`` after the user submits the credentials
    they just chose. The owner of an existing matching email is notified of
    the duplicate attempt (best effort when SMTP is configured).
    """
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context not resolved",
        )
    # CAPTCHA policy is tenant-editable (admin settings), with the process
    # default as the fallback. Read it before validating the token.
    from app.core.site_settings import get_site_flag

    captcha_required = await get_site_flag(db, tenant_id, "captcha_required_for_registration")
    await verify_captcha_token(
        request,
        payload.captcha_token,
        payload.captcha_answer,
        required=captcha_required,
    )
    user = User(
        tenant_id=tenant_id,
        email=payload.email,
        username=payload.username,
        hashed_password=hash_password(payload.password),
        is_admin=False,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Duplicate email or username — identical 201 body to the success
        # path. No token is issued (anti-takeover) and no second user is
        # created.
        await db.rollback()
        await _notify_duplicate_registration(db, payload.email, payload.username)
        return MessageResponse(message=_REGISTER_MESSAGE)
    await db.refresh(user)

    # 注册即得 10 XP：L1 起步，确认社区规范后到 L2。
    from app.modules.gamification import service as gamification

    await gamification.award(db, user, "register", ref_type="user", ref_id=str(user.id))
    await db.commit()

    # Fire-and-forget verification email. Failure is logged but does not
    # fail registration — the user can request a resend via /resend-verification.
    try:
        await _send_verification_email(user)
    except Exception:
        logger.warning("verification_email_send_failed", user_id=user.id, exc_info=True)

    # Same body as the duplicate branch; the client signs in via /auth/login.
    return MessageResponse(message=_REGISTER_MESSAGE)


@router.post(
    "/login",
    response_model=TokenResponse | TwoFactorRequiredResponse,
    responses={
        200: {
            "description": (
                "Tokens on success; or `{two_factor_required: true, "
                "pending_token}` when the account has 2FA enabled."
            )
        }
    },
)
async def login(
    request: Request,
    response: Response,
    payload: UserLogin,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse | TwoFactorRequiredResponse:
    """Authenticate and issue tokens.

    When the account has TOTP 2FA enabled, no tokens are issued here —
    the response carries a short-lived ``pending_token`` that must be
    exchanged with a valid code at ``/auth/login/2fa``.
    """
    # User.username uniqueness is (tenant_id, username) — a query without
    # the tenant filter could match a user from another tenant.
    # 登录标识同时接受用户名或邮箱（大小写不敏感）：期刊读者记住的往往
    # 是注册邮箱；用户名精确匹配优先级不变，邮箱走 lower 等值比较。
    tenant_id = require_tenant_id()
    identifier = payload.username.strip()
    # 账号级爆破节流：IP 限流可被换 IP 绕过，最后一道闸按账号计数
    # （app/core/login_throttle.py）。冷却期内与密码错误同文案 401，
    # 不向攻击者区分「密码错」与「已节流」。
    from app.core.login_throttle import is_locked, record_failure, record_success

    if is_locked(tenant_id, identifier):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            (User.username == identifier) | (func.lower(User.email) == identifier.lower()),
        )
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        record_failure(tenant_id, identifier)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    record_success(tenant_id, identifier)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled"
        )

    if user.totp_enabled_at is not None:
        # Password OK, but the second factor is outstanding. Issue a
        # 5-minute pending token instead of real credentials.
        return TwoFactorRequiredResponse(
            pending_token=create_two_factor_pending_token(user.id, user.token_version)
        )

    return await _issue_tokens(user, response, db)


@router.post("/login/2fa", response_model=TokenResponse)
async def login_two_factor(
    response: Response,
    payload: TwoFactorLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Second step of 2FA login: pending token + TOTP/recovery code → tokens.

    Accepts either a 6-digit TOTP code or an unused XXXXX-XXXXX recovery
    code (which is consumed on success). The source of truth is the
    encrypted ``totp_*`` column group.
    """
    claims = decode_two_factor_pending_token(payload.pending_token)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired two-factor session; log in again",
        )

    tenant_id = require_tenant_id()
    result = await db.execute(
        select(User).where(
            User.id == int(claims["sub"]),
            User.tenant_id == tenant_id,
        )
    )
    user = result.scalar_one_or_none()
    # token_version check: a password change / logout-everywhere after
    # the pending token was issued must invalidate it too.
    if (
        user is None
        or not user.is_active
        or user.totp_enabled_at is None
        or user.totp_secret_encrypted is None
        or claims.get("token_version") != user.token_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired two-factor session; log in again",
        )

    ok = False
    if payload.code:
        try:
            secret = decrypt_secret(user.totp_secret_encrypted)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="2FA secret cannot be decrypted - encryption key may have rotated",
            ) from exc
        # A TOTP code is exactly 6 digits; recovery codes are XXXXX-XXXXX.
        if payload.code.isdigit() and len(payload.code) == 6:
            # Replay protection (T2 finding H-1): reject counters already
            # consumed, and persist the accepted one so the same window's
            # code cannot be reused on either 2FA completion path.
            counter = verify_totp(
                secret, payload.code, last_counter=user.totp_last_used_counter or -1
            )
            if counter is not None:
                user.totp_last_used_counter = counter
                await db.commit()
                ok = True
        if not ok:
            # Try the provided value as a single-use recovery code.
            candidate_hash = hash_backup_code(normalize_backup_code(payload.code))
            try:
                hashes = (
                    set(json.loads(user.totp_backup_codes_hashed))
                    if user.totp_backup_codes_hashed
                    else set()
                )
            except (json.JSONDecodeError, TypeError):
                hashes = set()
            if candidate_hash in hashes:
                hashes.discard(candidate_hash)
                user.totp_backup_codes_hashed = json.dumps(sorted(hashes))
                await db.commit()
                logger.info(
                    "two_factor_recovery_code_used",
                    user_id=user.id,
                    remaining=len(hashes),
                )
                ok = True

    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid two-factor code",
        )

    return await _issue_tokens(user, response, db)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    payload: RefreshTokenRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a refresh token for a fresh access + refresh token pair.

    Per-token revocation via JTI denylist: the consumed refresh token's
    ``jti`` is added to the denylist so it cannot be replayed. The
    ``rtv`` (refresh_token_version) is NOT bumped here — other devices'
    refresh tokens remain valid (fine-grained). Bulk revocation
    (password change, revoke-all) still bumps ``rtv``.
    """
    body_token = payload.refresh_token if payload else None
    raw_token = _extract_refresh_token(request, body_token)
    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    decoded = decode_refresh_token(raw_token)
    if decoded is None or "sub" not in decoded:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    # Per-token denylist check — a previously-consumed refresh token
    # (e.g. rotated or logged out) must be rejected.
    denylist = await get_denylist()
    token_jti = decoded.get("jti")
    if token_jti and await denylist.is_denied(str(token_jti)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    try:
        user_id = int(decoded["sub"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from exc

    result = await db.execute(
        select(User)
        .where(
            User.id == user_id,
            # Reject refresh tokens whose owner lives in another tenant —
            # without this, a token minted in tenant A would still refresh
            # against tenant B's deployment.
            User.tenant_id == require_tenant_id(),
        )
        # Row lock serializes concurrent refresh attempts: the first caller
        # adds the JTI to the denylist and commits, the second caller sees
        # the denylist entry and fails.
        .with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    # token_version check catches logout / password change.
    if not token_version_matches(decoded, user.token_version):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    # rtv check enforces bulk revocation (revoke-all, password change).
    if not refresh_token_version_matches(decoded, user.refresh_token_version):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been rotated"
        )

    # Per-token revocation: add the consumed token's JTI to the denylist
    # so it cannot be replayed. The new token pair gets a fresh JTI.
    if token_jti and "exp" in decoded:
        await denylist.add(str(token_jti), float(decoded["exp"]))

    # Commit releases the row lock. We do NOT bump refresh_token_version
    # here — the denylist handles per-token rotation so other devices'
    # refresh tokens are unaffected.
    await db.commit()
    await db.refresh(user)

    return await _issue_tokens(user, response, db)


@router.post("/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Bump token_version + refresh_token_version to invalidate all
    outstanding access AND refresh tokens."""
    current_user.token_version += 1
    current_user.refresh_token_version += 1
    await db.commit()
    _clear_refresh_cookie(response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Log out the current session only (fine-grained).

    Adds the current refresh token's ``jti`` to the denylist so it
    cannot be replayed, and bumps ``token_version`` to invalidate the
    current access token. Other sessions' refresh tokens are unaffected
    — this is a per-session logout, not a logout-everywhere.

    For bulk revocation (all sessions), use ``/auth/revoke-all``.
    """
    # Denylist the current refresh token (per-session revocation).
    raw_token = _extract_refresh_token(request, None)
    if raw_token:
        decoded = decode_refresh_token(raw_token)
        if decoded and "jti" in decoded and "exp" in decoded:
            denylist = await get_denylist()
            await denylist.add(str(decoded["jti"]), float(decoded["exp"]))

    # Bump token_version to invalidate the current access token.
    # We do NOT bump refresh_token_version — the JTI denylist above
    # handles per-token refresh revocation, so other sessions survive.
    current_user.token_version += 1
    await db.commit()
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """当前用户资料：包含角色名列表（前端按角色渲染导航）。"""
    resp = UserResponse.model_validate(current_user)
    resp.roles = await user_role_names(db, current_user)
    from app.api.levels import CURRENT_RULES_VERSION, level_of

    resp.level = await level_of(db, current_user)

    resp.rules_accepted = current_user.rules_ack_version == CURRENT_RULES_VERSION
    return resp


@router.patch("/me/orcid", response_model=UserResponse)
async def patch_orcid(
    payload: ORCIDUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update the current user's ORCID iD.

    Accepts ``{"orcid": "0000-0002-1825-0097"}`` (set),
    ``{"orcid": ""}`` (clear), or ``{}`` (no-op). The canonical
    ORCID iD (19-char hyphenated form) is stored on the User row.
    """
    # Check if the orcid field was explicitly provided in the request body.
    # payload.orcid is None both when the field is omitted (no-op) and when
    # empty string is sent (validator converts "" to None). Use
    # exclude_unset to distinguish the two cases.
    if "orcid" in payload.model_dump(exclude_unset=True):
        current_user.orcid = payload.orcid
        await db.commit()
        await db.refresh(current_user)
    resp = UserResponse.model_validate(current_user)
    resp.roles = await user_role_names(db, current_user)
    return resp


async def _issue_tokens(user: User, response: Response, db: AsyncSession) -> TokenResponse:
    """Helper: build access+refresh tokens and set the refresh cookie.

    Access token carries ``token_version`` (invalidated on logout /
    password change). Refresh token additionally carries ``rtv``
    (refresh_token_version) — a separate counter bumped on revoke-all
    so bulk revocation does not depend on the JTI denylist — and a
    unique ``jti`` (JWT ID) for per-token revocation via the denylist.

    Also returns the caller's role names: the SPA renders role-gated
    navigation (审稿工作台 / 编辑工作台) from them, and /admin/users —
    the only other source of roles — is admin-only.
    """
    base_claims = {"sub": str(user.id), "token_version": user.token_version}
    access_token = create_access_token(base_claims)
    # Refresh token gets its own version claim so it can be rotated
    # independently of the access token, and a unique jti for the denylist.
    refresh_claims = {
        **base_claims,
        "rtv": user.refresh_token_version,
        "jti": random_jti(),
    }
    refresh_token = create_refresh_token(refresh_claims)
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        roles=await user_role_names(db, user),
    )


# --- Email verification + password reset ---


def _verify_link(token: str) -> str:
    """Build the verify-email deep link for the SPA to consume."""
    base = settings.frontend_base_url.rstrip("/") if settings.frontend_base_url else ""
    return f"{base}/verify-email?token={token}"


def _reset_link(token: str) -> str:
    """Build the password-reset deep link for the SPA to consume."""
    base = settings.frontend_base_url.rstrip("/") if settings.frontend_base_url else ""
    return f"{base}/reset-password?token={token}"


async def _send_verification_email(user: User) -> None:
    """Send the verify-email message via the configured sender.

    收件地址护栏：同地址 60 秒内不重复发、30 分钟内最多 8 封。
    超限直接返回（调用方仍回 200），避免把「这个地址被限流」暴露出去。
    """
    if not allow_email_to(user.email):
        return
    token = create_email_verification_token(user.id, user.token_version)
    link = _verify_link(token)
    subject, text, html = verify_email_tpl(
        user.username, link, settings.email_verification_expire_hours
    )
    await get_email_sender().send(to=user.email, subject=subject, body=text, html=html)


async def _send_password_reset_email(user: User) -> None:
    """Send the password-reset message via the configured sender."""
    if not allow_email_to(user.email):
        return
    token = create_password_reset_token(user.id, user.token_version)
    link = _reset_link(token)
    subject, text, html = reset_password_tpl(
        user.username, link, settings.password_reset_expire_minutes
    )
    await get_email_sender().send(to=user.email, subject=subject, body=text, html=html)


async def _notify_duplicate_registration(
    db: AsyncSession, attempted_email: str, attempted_username: str
) -> None:
    """Best-effort: warn the owner of an existing matching account that
    someone tried to register with their email/username.

    Failures are logged but never surface to the caller — the caller always
    sees the same 201 to preserve the anti-enumeration contract.
    """
    # Scope to the current tenant so a duplicate attempt in tenant A does
    # not surface the email of a user in tenant B.
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        return
    result = await db.execute(
        select(User).where(
            (func.lower(User.email) == attempted_email.strip().lower())
            | (User.username == attempted_username),
            User.tenant_id == tenant_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is None:
        return
    # 重复注册通知也是「用户可反复触发」的信件：不设护栏时，攻击者只要
    # 拿受害者邮箱反复注册，就能给受害者灌邮件。走同一套收件护栏。
    if not allow_email_to(existing.email):
        return
    subject, text, html = duplicate_registration(existing.username)
    try:
        await get_email_sender().send(to=existing.email, subject=subject, body=text, html=html)
    except Exception:
        logger.warning("duplicate_registration_email_send_failed", exc_info=True)


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_email(
    payload: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Exchange a verification token for ``is_email_verified=True``."""
    decoded = decode_token(payload.token, expected_type=VERIFY_EMAIL_TOKEN_TYPE)
    if decoded is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )
    try:
        user_id = int(decoded["sub"])
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token",
        ) from exc

    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == require_tenant_id(),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token",
        )
    # token_version check ties the token to the account state at issue
    # time — bumping it (logout, password change, admin disable) invalidates
    # outstanding verification tokens too.
    if not token_version_matches(decoded, user.token_version):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification token is no longer valid",
        )
    if user.is_email_verified:
        return MessageResponse(message="Email already verified")
    user.is_email_verified = True
    await db.commit()
    return MessageResponse(message="Email verified")


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def resend_verification(
    payload: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Re-send the verification email. Always returns 200 (don't leak
    whether an account exists for the address)."""
    tenant_id = get_current_tenant_id()
    stmt = select(User).where(func.lower(User.email) == payload.email.strip().lower())
    if tenant_id is not None:
        stmt = stmt.where(User.tenant_id == tenant_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None or user.is_email_verified:
        # Pretend success to avoid account enumeration.
        return MessageResponse(message="If the account exists, a verification email was sent")
    try:
        await _send_verification_email(user)
    except Exception:
        logger.warning("resend_verification_failed", user_id=user.id, exc_info=True)
    return MessageResponse(message="If the account exists, a verification email was sent")


def _as_aware(dt: datetime) -> datetime:
    """SQLite 读回 naive datetime（无时区），PG 读回 aware——统一到 aware 再比。

    测试跑在 SQLite 上；生产 PostgreSQL 不受影响。request/verify 两个
    验证码端点都要处理同一问题，所以放在端点定义之前。
    """
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Trigger a password-reset email. Always returns 200 (don't leak
    whether an account exists for the address)."""
    tenant_id = get_current_tenant_id()
    stmt = select(User).where(func.lower(User.email) == payload.email.strip().lower())
    if tenant_id is not None:
        stmt = stmt.where(User.tenant_id == tenant_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return MessageResponse(message="If the account exists, a reset email was sent")
    try:
        await _send_password_reset_email(user)
    except Exception:
        logger.warning("password_reset_email_failed", user_id=user.id, exc_info=True)
    return MessageResponse(message="If the account exists, a reset email was sent")


@router.post(
    "/email-code/request",
    response_model=MessageResponse,
)
async def request_email_login_code(
    payload: EmailCodeRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """请求邮箱登录验证码。无论邮箱是否注册都返回 200（反枚举）。

    节流（应用层，IP 层由 RateLimitMiddleware 兜底）：
    - 同邮箱 60 秒内 1 条——防止输错一次就连发；
    - 同邮箱 24 小时最多 10 条——防邮件轰炸/骚扰；
    console 邮件后端（本地开发）把码写进日志而非返回体，不破坏反枚举。
    """
    tenant_id = require_tenant_id()
    email = payload.email.strip().lower()
    now = utcnow()

    if settings.email_backend != "smtp":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="邮箱验证码登录未启用：站点尚未配置 SMTP 发信。",
        )

    # 60 秒窗口
    recent = (
        await db.execute(
            select(func.count(EmailLoginCode.id)).where(
                EmailLoginCode.tenant_id == tenant_id,
                EmailLoginCode.email == email,
                EmailLoginCode.created_at >= now - timedelta(seconds=SEND_INTERVAL_SECONDS),
            )
        )
    ).scalar_one()
    if recent >= 1:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="验证码发送过于频繁，请 1 分钟后再试。",
        )
    # 24h 窗口
    today = (
        await db.execute(
            select(func.count(EmailLoginCode.id)).where(
                EmailLoginCode.tenant_id == tenant_id,
                EmailLoginCode.email == email,
                EmailLoginCode.created_at >= now - timedelta(hours=24),
            )
        )
    ).scalar_one()
    if today >= DAILY_SEND_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="今日验证码请求次数已达上限，请明天再试或使用密码登录。",
        )

    # 重新请求即作废旧码（同邮箱未消费的行直接删，配合唯一约束不冲突）
    await db.execute(
        delete(EmailLoginCode).where(
            EmailLoginCode.tenant_id == tenant_id,
            EmailLoginCode.email == email,
            EmailLoginCode.consumed_at.is_(None),
        )
    )
    code = generate_code()
    row = EmailLoginCode(
        tenant_id=tenant_id,
        email=email,
        code_hash=hash_code(email, code),
        expires_at=now + timedelta(minutes=CODE_TTL_MINUTES),
    )
    db.add(row)
    await db.commit()

    # 发信：查用户拿称呼（查不到 = 未注册邮箱，仍走同一响应）
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            func.lower(User.email) == email,
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        # 反枚举：不确认存在性，也不发信（未注册邮箱发了也没意义）
        return MessageResponse(message="如果该邮箱已注册，验证码已发送，请查收（含垃圾邮件箱）")

    subject, body, html = _email_login_code_template(code, CODE_TTL_MINUTES)
    try:
        sender = get_email_sender()
        await sender.send(to=email, subject=subject, body=body, html=html)
        allow_email_to(email)
    except Exception as exc:
        logger.warning(
            "email_login_code_send_failed", email_domain=email.split("@")[-1], exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="验证码邮件发送失败，请稍后再试或使用密码登录。",
        ) from exc
    return MessageResponse(message="验证码已发送，请查收（10 分钟内有效，含垃圾邮件箱）")


@router.post(
    "/email-code/verify",
    response_model=TokenResponse | TwoFactorRequiredResponse,
)
async def verify_email_login_code(
    payload: EmailCodeVerify,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse | TwoFactorRequiredResponse:
    """用邮箱 + 6 位验证码换取登录凭据。

    校验顺序刻意为：找码 → 比对 → 尝试计数 → 找用户。找码失败与码错误
    都返回 401 "Invalid or expired code"，不区分（未注册邮箱不发码，
    攻击者本来就无码可试，不需要额外混淆）。
    """
    tenant_id = require_tenant_id()
    email = payload.email.strip().lower()
    now = utcnow()

    row = (
        await db.execute(
            select(EmailLoginCode)
            .where(
                EmailLoginCode.tenant_id == tenant_id,
                EmailLoginCode.email == email,
                EmailLoginCode.consumed_at.is_(None),
            )
            # 取最新一条：request 端点已保证生产路径同邮箱只有一条未消费码，
            # 这里再兜一层（历史遗留行/手工插行），避免 scalar_one 直接炸。
            .order_by(EmailLoginCode.created_at.desc(), EmailLoginCode.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or _as_aware(row.expires_at) < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="验证码无效或已过期，请重新获取。",
        )
    if not codes_match(email, payload.code, row.code_hash):
        row.attempts += 1
        if row.attempts >= MAX_VERIFY_ATTEMPTS:
            await db.delete(row)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="验证码无效或已过期，请重新获取。",
        )
    row.consumed_at = now
    await db.commit()

    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            func.lower(User.email) == email,
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="验证码无效或已过期，请重新获取。",
        )

    # 收到并输对了发往该邮箱的 6 位码，就等于证明了邮箱所有权——此刻不置
    # is_email_verified，用户会永远停在「未验证」：注册时那封验证邮件被忽略
    # 或被丢进垃圾箱之后，他再也不会去点链接，后台却一直显示未验证。
    # 两条证明路径（点邮件链接 / 用邮箱验证码登录）必须收敛到同一个状态。
    if not user.is_email_verified:
        user.is_email_verified = True
        await db.commit()

    # 2FA 账户照常走 pending token：邮箱验证码只是第一因子替代，
    # 不能绕过第二因子。
    if user.totp_enabled_at is not None:
        return TwoFactorRequiredResponse(
            pending_token=create_two_factor_pending_token(user.id, user.token_version)
        )
    return await _issue_tokens(user, response, db)


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Exchange a reset token for a new password. Bumps ``token_version``
    so all previously-issued access + refresh tokens are invalidated."""
    decoded = decode_token(payload.token, expected_type=RESET_PASSWORD_TOKEN_TYPE)
    if decoded is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    try:
        user_id = int(decoded["sub"])
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token",
        ) from exc

    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.tenant_id == require_tenant_id(),
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token",
        )
    if not token_version_matches(decoded, user.token_version):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token is no longer valid",
        )
    user.hashed_password = hash_password(payload.new_password)
    # Bumping token_version invalidates outstanding access tokens AND any
    # other outstanding reset tokens for this user; bumping refresh_token_version
    # also invalidates outstanding refresh tokens so the user must log in again.
    user.token_version += 1
    user.refresh_token_version += 1
    await db.commit()
    return MessageResponse(message="Password reset successful")
