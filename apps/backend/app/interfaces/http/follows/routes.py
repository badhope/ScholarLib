"""Follows API routes — author follow + discipline subscription.

Spans three URL prefixes (``/authors``, ``/disciplines``, ``/users``)
because the resource being followed determines the URL shape. The router
is registered without a prefix and each route declares its full path.

Follow/subscribe writes are idempotent: re-following an already-followed
author returns 200 with the current status (not 409), and unfollowing
when not following also returns 200. Idempotent writes keep existing
API clients working across retries.

Auth model:
- Write endpoints (follow/unfollow/subscribe/unsubscribe) require auth.
- Status-check endpoints accept optional auth: ``following`` is false
  for anonymous callers, but the count is still returned.
- Listing endpoints (/users/me/...) require auth and are user-scoped.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_user_optional, require_tenant_id
from app.core.db import get_db, paginate
from app.domain.follows.models import AuthorFollow, DisciplineSubscription
from app.interfaces.http.follows.schemas import (
    AUTHOR_NAME_MAX,
    AUTHOR_NAME_MIN,
    DISCIPLINE_MAX,
    AuthorFollowEntry,
    AuthorFollowListResponse,
    DisciplineSubscriptionListResponse,
    FollowStatusResponse,
    SubscriptionStatusResponse,
)
from app.models import User

router = APIRouter(tags=["follows"])

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# Author follows
# ---------------------------------------------------------------------------


async def _author_follow_status(
    db: AsyncSession, author_name: str, user_id: int | None
) -> FollowStatusResponse:
    """Compute (following, followers_count) for a (tenant, author) pair.

    Filters by tenant_id too so counts never leak across tenants even
    if two tenants happen to track authors with the same name.
    """
    tenant_id = require_tenant_id()
    count_result = await db.execute(
        select(func.count())
        .select_from(AuthorFollow)
        .where(
            AuthorFollow.author_name == author_name,
            AuthorFollow.tenant_id == tenant_id,
        )
    )
    followers_count = count_result.scalar_one()

    following = False
    if user_id is not None:
        existing = await db.execute(
            select(AuthorFollow).where(
                AuthorFollow.user_id == user_id,
                AuthorFollow.author_name == author_name,
                AuthorFollow.tenant_id == tenant_id,
            )
        )
        following = existing.scalar_one_or_none() is not None

    return FollowStatusResponse(following=following, followers_count=followers_count)


@router.post(
    "/authors/{author_name}/follow",
    response_model=FollowStatusResponse,
)
async def follow_author(
    author_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FollowStatusResponse:
    """Follow an author by name. Idempotent: re-following is a no-op."""
    if not (AUTHOR_NAME_MIN <= len(author_name) <= AUTHOR_NAME_MAX):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Author not found",
        )

    existing = await db.execute(
        select(AuthorFollow).where(
            AuthorFollow.user_id == current_user.id,
            AuthorFollow.author_name == author_name,
            AuthorFollow.tenant_id == current_user.tenant_id,
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(
            AuthorFollow(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                author_name=author_name,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            # Race: another concurrent request created the same row.
            await db.rollback()

    return await _author_follow_status(db, author_name, current_user.id)


@router.delete(
    "/authors/{author_name}/follow",
    response_model=FollowStatusResponse,
)
async def unfollow_author(
    author_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FollowStatusResponse:
    """Unfollow an author by name. Idempotent: unfollowing when not following is a no-op."""
    result = await db.execute(
        select(AuthorFollow).where(
            AuthorFollow.user_id == current_user.id,
            AuthorFollow.author_name == author_name,
            AuthorFollow.tenant_id == current_user.tenant_id,
        )
    )
    follow = result.scalar_one_or_none()
    if follow is not None:
        await db.delete(follow)
        await db.commit()

    return await _author_follow_status(db, author_name, current_user.id)


@router.get(
    "/authors/{author_name}/follow",
    response_model=FollowStatusResponse,
)
async def get_author_follow_status(
    author_name: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> FollowStatusResponse:
    """Check follow status + follower count. Public; ``following`` is false
    for anonymous callers."""
    user_id = current_user.id if current_user is not None else None
    return await _author_follow_status(db, author_name, user_id)


@router.get(
    "/users/me/following/authors",
    response_model=AuthorFollowListResponse,
)
async def list_my_followed_authors(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuthorFollowListResponse:
    """List the authors the current user follows, newest first."""
    base = select(AuthorFollow).where(
        AuthorFollow.user_id == current_user.id,
        AuthorFollow.tenant_id == current_user.tenant_id,
    )
    rows, meta = await paginate(
        db,
        base,
        page=page,
        page_size=page_size,
        order_by=(desc(AuthorFollow.created_at), AuthorFollow.id.desc()),
    )
    return AuthorFollowListResponse(
        data=[AuthorFollowEntry.model_validate(r) for r in rows],
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Discipline subscriptions
# ---------------------------------------------------------------------------


async def _discipline_subscription_status(
    db: AsyncSession, discipline: str, user_id: int | None
) -> SubscriptionStatusResponse:
    """Compute (subscribed, subscribers_count) for a (tenant, discipline) pair."""
    tenant_id = require_tenant_id()
    count_result = await db.execute(
        select(func.count())
        .select_from(DisciplineSubscription)
        .where(
            DisciplineSubscription.discipline == discipline,
            DisciplineSubscription.tenant_id == tenant_id,
        )
    )
    subscribers_count = count_result.scalar_one()

    subscribed = False
    if user_id is not None:
        existing = await db.execute(
            select(DisciplineSubscription).where(
                DisciplineSubscription.user_id == user_id,
                DisciplineSubscription.discipline == discipline,
                DisciplineSubscription.tenant_id == tenant_id,
            )
        )
        subscribed = existing.scalar_one_or_none() is not None

    return SubscriptionStatusResponse(subscribed=subscribed, subscribers_count=subscribers_count)


@router.post(
    "/disciplines/{discipline}/subscribe",
    response_model=SubscriptionStatusResponse,
)
async def subscribe_discipline(
    discipline: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionStatusResponse:
    """Subscribe to a discipline by slug. Idempotent: re-subscribing is a no-op."""
    # 超长/空串是输入问题（422），不是"资源不存在"（404）。
    if not discipline or len(discipline) > DISCIPLINE_MAX:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Discipline must be 1-{DISCIPLINE_MAX} characters",
        )

    existing = await db.execute(
        select(DisciplineSubscription).where(
            DisciplineSubscription.user_id == current_user.id,
            DisciplineSubscription.discipline == discipline,
            DisciplineSubscription.tenant_id == current_user.tenant_id,
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(
            DisciplineSubscription(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                discipline=discipline,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()

    return await _discipline_subscription_status(db, discipline, current_user.id)


@router.delete(
    "/disciplines/{discipline}/subscribe",
    response_model=SubscriptionStatusResponse,
)
async def unsubscribe_discipline(
    discipline: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionStatusResponse:
    """Unsubscribe from a discipline. Idempotent."""
    result = await db.execute(
        select(DisciplineSubscription).where(
            DisciplineSubscription.user_id == current_user.id,
            DisciplineSubscription.discipline == discipline,
            DisciplineSubscription.tenant_id == current_user.tenant_id,
        )
    )
    sub = result.scalar_one_or_none()
    if sub is not None:
        await db.delete(sub)
        await db.commit()

    return await _discipline_subscription_status(db, discipline, current_user.id)


@router.get(
    "/disciplines/{discipline}/subscribe",
    response_model=SubscriptionStatusResponse,
)
async def get_discipline_subscription_status(
    discipline: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionStatusResponse:
    """Check subscription status + subscriber count. Public."""
    user_id = current_user.id if current_user is not None else None
    return await _discipline_subscription_status(db, discipline, user_id)


@router.get(
    "/users/me/subscriptions/disciplines",
    response_model=DisciplineSubscriptionListResponse,
)
async def list_my_subscribed_disciplines(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DisciplineSubscriptionListResponse:
    """List the discipline slugs the current user is subscribed to, newest first."""
    result = await db.execute(
        select(DisciplineSubscription.discipline)
        .where(
            DisciplineSubscription.user_id == current_user.id,
            DisciplineSubscription.tenant_id == current_user.tenant_id,
        )
        .order_by(
            # id 决胜（desc）：「最新订阅在前」= 后插入的在前；同批插入
            # created_at 相同，asc 会让顺序抖动。
            desc(DisciplineSubscription.created_at),
            DisciplineSubscription.id.desc(),
        )
    )
    slugs = [row[0] for row in result.all()]
    return DisciplineSubscriptionListResponse(data=slugs)
