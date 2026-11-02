"""User self-management endpoints.

Admin user management (list/create/delete) lives in ``app.api.admin``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, user_role_names
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.security import hash_password, verify_password
from app.models import User
from app.schemas import (
    UserResponse,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["users"])

logger = get_logger("rubbish.users")


class ChangePasswordRequest(BaseModel):
    # Body, not query string: passwords must never appear in URLs
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    resp = UserResponse.model_validate(current_user)
    resp.roles = await user_role_names(db, current_user)
    from app.api.levels import CURRENT_RULES_VERSION, level_of

    resp.level = await level_of(db, current_user)
    resp.rules_accepted = current_user.rules_ack_version == CURRENT_RULES_VERSION
    return resp


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Allow a user to update their own email / username / active flag.

    Email change resets ``is_email_verified`` to False and triggers a new
    verification email (best effort) so the user can re-verify.

    Disabling your own account is permitted — it's the closest thing to
    "delete me" we offer without data-loss risk; an admin can re-enable.
    """
    email_changed = payload.email is not None and payload.email != current_user.email
    if payload.email is not None:
        current_user.email = payload.email
    if email_changed:
        current_user.is_email_verified = False
    if payload.username is not None:
        current_user.username = payload.username
    if payload.is_active is not None:
        current_user.is_active = payload.is_active
    # bio：字段出现即写入（schema 已把空串归一为 None = 清除简介）；
    # 未提供（缺键）时不触碰，与 orcid 的 None-保持不变约定一致。
    if "bio" in payload.model_fields_set:
        current_user.bio = payload.bio
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already taken in this tenant",
        ) from exc
    await db.refresh(current_user)

    if email_changed:
        try:
            from app.api.auth import _send_verification_email

            await _send_verification_email(current_user)
        except Exception:
            logger.warning(
                "post_email_change_verification_send_failed",
                user_id=current_user.id,
                exc_info=True,
            )

    resp = UserResponse.model_validate(current_user)
    resp.roles = await user_role_names(db, current_user)
    return resp


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Change the current user's password; bumps token_version + rtv.

    Both counters are bumped so outstanding access AND refresh tokens
    are invalidated — the user must re-authenticate on every device.
    """
    if not verify_password(payload.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect"
        )
    current_user.hashed_password = hash_password(payload.new_password)
    current_user.token_version += 1
    current_user.refresh_token_version += 1
    await db.commit()


# Two-factor auth (TOTP) self-management lives at /api/auth/2fa/* (see
# app/api/two_factor.py) on the single, encrypted ``totp_*`` column group.
# The legacy /api/users/me/2fa/* plaintext path was removed; see migration
# 021_merge_two_factor.
