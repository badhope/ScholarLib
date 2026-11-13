"""User self-management endpoints.

Admin user management (list/create/delete) lives in ``app.api.admin``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_current_user_optional,
    require_tenant_id,
    user_role_names,
)
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
    # 自定义主题色是 R 币消费项：未解锁前只允许保持默认色。
    if (
        "accent_color" in payload.model_fields_set
        and payload.accent_color is not None
        and payload.accent_color.lower() != (current_user.accent_color or "").lower()
        and not current_user.accent_unlocked
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="自定义主题色需要先在 R 币钱包解锁",
        )

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
    # 扩展资料：字段出现即写入，缺键保持不变。空串在 schema 层已归一为 None。
    for field in (
        "display_name",
        "real_name",
        "affiliation",
        "department",
        "academic_title",
        "research_interests",
        "website",
        "google_scholar",
        "location",
        "avatar_url",
        "banner_url",
        "accent_color",
        "contact_email",
        "profile_visibility",
    ):
        if field in payload.model_fields_set:
            setattr(current_user, field, getattr(payload, field))
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


# ---------------------------------------------------------------------------
# 公开个人主页
# ---------------------------------------------------------------------------

PUBLIC_PROFILE_WORKS_LIMIT = 12
PUBLIC_PROFILE_TOPICS_LIMIT = 6


def _public_user(user: User) -> dict[str, object]:
    """只输出可公开的资料；账号 email 永不进入公开响应。"""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "banner_url": user.banner_url,
        "accent_color": user.accent_color or "#2f5d46",
        "bio": user.bio,
        "affiliation": user.affiliation,
        "department": user.department,
        "academic_title": user.academic_title,
        "research_interests": user.research_interests,
        "location": user.location,
        "website": user.website,
        "google_scholar": user.google_scholar,
        "orcid": user.orcid,
        "contact_email": user.contact_email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.get("/{username}/public")
async def get_public_profile(
    username: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """公开主页：资料 + 作品 + 论坛动态 + 关注/徽章统计。

    默认公开；``profile_visibility=private`` 时只有本人（或管理员）能看。
    访客版本不返回账号 email、密码、内部 id 列表等敏感字段。
    """
    from app.core.time import utcnow
    from app.modules.catalog.models import Resource
    from app.modules.follows.models import AuthorFollow
    from app.modules.forum.models import ForumReply, ForumTopic
    from app.modules.gamification.badges import BADGE_BY_KEY
    from app.modules.gamification.models import UserAchievement
    from app.modules.submission.models import Submission

    tenant_id = require_tenant_id()
    user = (
        await db.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.username == username,
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    is_owner = bool(current_user and current_user.id == user.id)
    is_admin_viewer = bool(current_user and current_user.is_admin)
    if (user.profile_visibility or "public") != "public" and not (is_owner or is_admin_viewer):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该主页未公开")

    # 已发表作品：走 Submission -> Resource，避免把未录用的投稿暴露出去。
    rows = (
        await db.execute(
            select(Submission, Resource)
            .join(Resource, Submission.resource_id == Resource.id)
            .where(
                Submission.tenant_id == tenant_id,
                Submission.submitted_by == user.id,
                Submission.status.in_(("accepted", "approved")),
                Resource.tenant_id == tenant_id,
                Resource.publication_status == "published",
                or_(Resource.publish_at.is_(None), Resource.publish_at <= utcnow()),
            )
            .order_by(Resource.publish_at.desc(), Resource.id.desc())
            .limit(PUBLIC_PROFILE_WORKS_LIMIT)
        )
    ).all()
    works = [
        {
            "id": resource.id,
            "title": resource.title,
            "type": resource.type,
            "cover_image": resource.cover_image,
            "published_at": (resource.publish_at.isoformat() if resource.publish_at else None),
            "authors": resource.authors or [],
            "discipline": resource.discipline,
        }
        for _sub, resource in rows
    ]
    works_count = (
        await db.execute(
            select(func.count(Submission.id))
            .join(Resource, Submission.resource_id == Resource.id)
            .where(
                Submission.tenant_id == tenant_id,
                Submission.submitted_by == user.id,
                Submission.status.in_(("accepted", "approved")),
                Resource.tenant_id == tenant_id,
                Resource.publication_status == "published",
            )
        )
    ).scalar_one()

    topics = (
        (
            await db.execute(
                select(ForumTopic)
                .where(
                    ForumTopic.tenant_id == tenant_id,
                    ForumTopic.author_id == user.id,
                    ForumTopic.deleted_at.is_(None),
                )
                .order_by(ForumTopic.created_at.desc())
                .limit(PUBLIC_PROFILE_TOPICS_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    topics_count = (
        await db.execute(
            select(func.count(ForumTopic.id)).where(
                ForumTopic.tenant_id == tenant_id,
                ForumTopic.author_id == user.id,
                ForumTopic.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    replies_count = (
        await db.execute(
            select(func.count(ForumReply.id)).where(
                ForumReply.tenant_id == tenant_id,
                ForumReply.author_id == user.id,
                ForumReply.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    # 关注按作者名匹配：现有 follows 表以字符串作者名为键，兼容历史目录。
    author_names = [name for name in (user.display_name, user.real_name, user.username) if name]
    followers_count = (
        (
            await db.execute(
                select(func.count(AuthorFollow.id)).where(
                    AuthorFollow.tenant_id == tenant_id,
                    AuthorFollow.author_name.in_(author_names),
                )
            )
        ).scalar_one()
        if author_names
        else 0
    )
    following_count = (
        await db.execute(
            select(func.count(AuthorFollow.id)).where(
                AuthorFollow.tenant_id == tenant_id,
                AuthorFollow.user_id == user.id,
            )
        )
    ).scalar_one()
    following = False
    if current_user and not is_owner and author_names:
        following = (
            await db.execute(
                select(AuthorFollow.id).where(
                    AuthorFollow.tenant_id == tenant_id,
                    AuthorFollow.user_id == current_user.id,
                    AuthorFollow.author_name.in_(author_names),
                )
            )
        ).scalar_one_or_none() is not None

    owned_badges = (
        (
            await db.execute(
                select(UserAchievement.badge_key).where(
                    UserAchievement.tenant_id == tenant_id,
                    UserAchievement.user_id == user.id,
                )
            )
        )
        .scalars()
        .all()
    )
    badges = [
        {
            "key": key,
            "name": BADGE_BY_KEY[key].name,
            "tier": BADGE_BY_KEY[key].tier,
            "category": BADGE_BY_KEY[key].category,
            "description": BADGE_BY_KEY[key].description,
        }
        for key in owned_badges
        if key in BADGE_BY_KEY and not BADGE_BY_KEY[key].secret
    ]

    return {
        "user": _public_user(user),
        "is_owner": is_owner,
        "following": following,
        "stats": {
            "works": int(works_count or 0),
            "forum_topics": int(topics_count or 0),
            "forum_replies": int(replies_count or 0),
            "followers": int(followers_count or 0),
            "following": int(following_count or 0),
            "badges": len(badges),
        },
        "works": works,
        "topics": [
            {
                "id": topic.id,
                "title": topic.title,
                "category": topic.category,
                "reply_count": topic.reply_count,
                "created_at": topic.created_at.isoformat(),
            }
            for topic in topics
        ],
        "badges": badges,
    }
