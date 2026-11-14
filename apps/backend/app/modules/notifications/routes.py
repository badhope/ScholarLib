"""Notification API routes — per-user in-app notification stream.

All endpoints require authentication; every user sees only their own
notifications. Read state is per-user and per-notification — there is no
shared stream.

Endpoints:
  GET   /notifications                — list (paginated, newest first; ?type= / ?category=)
  GET   /notifications/unread-count    — unread count
  PATCH /notifications/read-all        — mark all unread as read
  PATCH /notifications/{id}/read       — mark one as read
  DELETE /notifications/{id}           — delete one

Category mapping (``?category=``):
  assigned   -> review.invited
  reminder   -> review.reminder
  decision   -> submission.decision
  claim      -> claim.decision
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_tenant_id
from app.core.db import get_db, paginate
from app.models import User
from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import (
    MessageResponse,
    NotificationListResponse,
    NotificationResponse,
    ReadAllResponse,
    UnreadCountResponse,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 工作台四类事件的聚合筛选（前端 tab：指派/催审/裁决/认领结果）。
_CATEGORY_TYPES: dict[str, tuple[str, ...]] = {
    # 旧键保留，避免老客户端/测试失效
    "assigned": ("review.invited", "review.reminder", "review.accepted", "review.submitted"),
    "reminder": ("review.reminder",),
    "decision": ("submission.decision", "submission.resubmitted", "submission.rework_requested"),
    "claim": ("claim.created", "claim.decision"),
    # 新分组：通知页按工作流分开，不再全部倒进「全部」
    "review": ("review.invited", "review.reminder", "review.accepted", "review.submitted"),
    "submission": ("submission.decision", "submission.resubmitted", "submission.rework_requested"),
    "feedback": ("site.feedback",),
    "community": ("comment.new", "forum.reply"),
    "system": ("system", "gamification.role_application"),
}


def _tenant_filter(user: User) -> tuple[UUID, int]:
    """Resolve (tenant_id, user_id) for scoping queries.

    tenant_id 是 RLS 作用域的必需条件；缺上下文即请求非法（400），
    语义与 require_tenant_id() 一致，直接复用而不是各写一遍。
    """
    return require_tenant_id(), user.id


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    type: str | None = Query(default=None, description="精确 type 过滤"),
    category: str | None = Query(
        default=None,
        pattern=r"^(assigned|reminder|decision|claim|review|submission|feedback|community|system)$",
        description="聚合分类：审稿/投稿/认领/反馈/系统",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    """List the current user's notifications, newest first."""
    tenant_id, user_id = _tenant_filter(current_user)
    base = select(Notification).where(
        Notification.tenant_id == tenant_id,
        Notification.user_id == user_id,
    )
    if type is not None:
        base = base.where(Notification.type == type)
    if category is not None:
        base = base.where(Notification.type.in_(_CATEGORY_TYPES[category]))
    rows, meta = await paginate(
        db,
        base,
        page=page,
        page_size=page_size,
        # id 决胜（desc）：同 tick 插入的行 created_at 相同，asc 会把先插入的
        # 排到「最新在前」列表的最前 —— 与语义相反（test_notifications 抓到过）。
        order_by=(desc(Notification.created_at), Notification.id.desc()),
    )
    return NotificationListResponse(
        data=[NotificationResponse.model_validate(r) for r in rows],
        meta=meta,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UnreadCountResponse:
    """Count the current user's unread notifications."""
    tenant_id, user_id = _tenant_filter(current_user)
    result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
    )
    return UnreadCountResponse(unread=result.scalar_one())


@router.patch("/read-all", response_model=ReadAllResponse)
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReadAllResponse:
    """Mark every unread notification of the current user as read."""
    tenant_id, user_id = _tenant_filter(current_user)
    result: Any = await db.execute(
        update(Notification)
        .where(
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()
    return ReadAllResponse(updated=result.rowcount or 0)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    """Mark one notification as read (must belong to the current user)."""
    tenant_id, user_id = _tenant_filter(current_user)
    entry = (
        await db.execute(
            select(Notification).where(
                Notification.tenant_id == tenant_id,
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    entry.is_read = True
    await db.commit()
    await db.refresh(entry)
    return NotificationResponse.model_validate(entry)


@router.delete(
    "/{notification_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Delete one notification (must belong to the current user)."""
    tenant_id, user_id = _tenant_filter(current_user)
    entry = (
        await db.execute(
            select(Notification).where(
                Notification.tenant_id == tenant_id,
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    await db.delete(entry)
    await db.commit()
    return MessageResponse(message="Notification deleted")
