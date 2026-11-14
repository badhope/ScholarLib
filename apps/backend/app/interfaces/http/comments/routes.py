"""Comments API — public read, authenticated write, owner/admin delete.

- GET  /api/comments?resource_id={id}  公开（游客可读）
- POST /api/comments                   登录用户；仅限已刊出资源
- DELETE /api/comments/{id}            本人或管理员；审计 comment.delete
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_tenant_id
from app.api.levels import require_reader
from app.core.db import get_db, paginate
from app.core.moderation import rejection_detail
from app.domain.catalog.visibility import is_public
from app.domain.comments.models import Comment
from app.domain.notifications import services as notifications
from app.interfaces.http.comments.schemas import CommentCreate, CommentListResponse, CommentResponse
from app.models import AuditLog, User

router = APIRouter(prefix="/comments", tags=["comments"])

MAX_BODY_LENGTH = 1000


async def _serialize(db: AsyncSession, rows: list[Comment]) -> list[CommentResponse]:
    """Attach author display names (username; no emails leave the DB)."""
    from app.models import User as UserModel

    user_ids = list({r.user_id for r in rows})
    profiles: dict[int, tuple[str, str | None]] = {}
    if user_ids:
        result = await db.execute(
            select(
                UserModel.id,
                UserModel.username,
                UserModel.display_name,
                UserModel.avatar_url,
            ).where(UserModel.id.in_(user_ids))
        )
        profiles = {
            uid: (display_name or uname, avatar_url)
            for uid, uname, display_name, avatar_url in result.all()
        }
    return [
        CommentResponse(
            id=r.id,
            resource_id=r.resource_id,
            user_id=r.user_id,
            author_name=profiles.get(r.user_id, ("已注销用户", None))[0],
            author_avatar_url=profiles.get(r.user_id, ("已注销用户", None))[1],
            body=r.body,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def _require_published_resource(db: AsyncSession, resource_id: int, tenant_id: Any) -> Any:
    """Comments are only allowed on published records (404 mirrors catalog)."""
    from app.domain.catalog.models import Resource

    result = await db.execute(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.tenant_id == tenant_id,
        )
    )
    resource = result.scalar_one_or_none()
    # 排期中的期号同样不可评论：公开面判定统一走 is_public。
    if not is_public(resource):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return resource


@router.get("", response_model=CommentListResponse)
async def list_comments(
    resource_id: int = Query(ge=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> CommentListResponse:
    """Public thread for a resource, newest first.

    公开面口径与目录一致：资源被撤回或转入排期后，其评论线程同样不再
    对匿名/普通用户可见（否则评论端点会变成「这篇排期稿存在」的探针，
    且已撤回稿件的历史讨论继续外泄）。
    """
    tenant_id = require_tenant_id()
    await _require_published_resource(db, resource_id, tenant_id)
    # 前台口径：过滤掉被拒绝的评论。新评论写入 pending，但仍按正常评论
    # 展示（事后审核，避免用户发完看不到自己的发言）；只有 editor 及以上
    # 在后台判 reject 后，前台才下架。
    stmt = select(Comment).where(
        Comment.tenant_id == tenant_id,
        Comment.resource_id == resource_id,
        Comment.status != "rejected",
    )
    rows, meta = await paginate(
        db,
        stmt,
        page=page,
        page_size=page_size,
        order_by=(Comment.created_at.desc(), Comment.id.desc()),
    )
    return CommentListResponse(data=await _serialize(db, list(rows)), meta=meta)


@router.post("", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def create_comment(
    payload: CommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_reader),
) -> CommentResponse:
    """Post a comment (L1+; published resources only)."""
    tenant_id = require_tenant_id()
    body = payload.body.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="评论内容不能为空"
        )
    blocked = rejection_detail(body)
    if blocked is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=blocked)
    resource = await _require_published_resource(db, payload.resource_id, tenant_id)

    comment = Comment(
        tenant_id=tenant_id,
        resource_id=payload.resource_id,
        user_id=current_user.id,
        body=body[:MAX_BODY_LENGTH],
        # 新评论默认 pending（事后审核）；前台仍展示，被拒后才下架。
        status="pending",
    )
    db.add(comment)
    try:
        await db.flush()
        from app.domain.gamification import service as gamification

        await gamification.award(
            db,
            current_user,
            "comment.create",
            ref_type="comment",
            ref_id=str(comment.id),
        )
        # 评论通知：只通知资源作者（不通知其他读者），自己评论自己不通知。
        owner_id = getattr(resource, "owner_id", None)
        if owner_id and owner_id != current_user.id:
            owner = (await db.execute(select(User).where(User.id == owner_id))).scalar_one_or_none()
            if owner is not None:
                prefs = notifications.merged_prefs(owner)
                if prefs.get("in_app_comment"):
                    await notifications.create(
                        db,
                        tenant_id=tenant_id,
                        user_id=owner.id,
                        type_="comment.new",
                        title=f"《{resource.title[:80]}》有新评论",
                        body=f"{current_user.display_name or current_user.username}：{body[:120]}",
                        related_type="resource",
                        related_id=str(resource.id),
                    )
                if prefs.get("email_comment") and owner.email:
                    await notifications.record_email_digest(
                        db,
                        tenant_id=tenant_id,
                        user_id=owner.id,
                        event_type="comment.new",
                        recipient_email=owner.email,
                        subject=f"Rubbish：{resource.title[:80]} 有新评论",
                        text=f"{current_user.display_name or current_user.username} 评论了你的文章：\n\n{body[:500]}",
                        related_type="resource",
                        related_id=str(resource.id),
                    )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="评论提交冲突，请重试"
        ) from exc
    await db.refresh(comment)
    return (await _serialize(db, [comment]))[0]


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete own comment; admin may delete any. Audit: comment.delete."""
    tenant_id = require_tenant_id()
    result = await db.execute(
        select(Comment).where(
            Comment.id == comment_id,
            Comment.tenant_id == tenant_id,
        )
    )
    comment = result.scalar_one_or_none()
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")
    if comment.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能删除自己的评论")

    await db.delete(comment)
    db.add(
        AuditLog(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            action="comment.delete",
            target_type="comment",
            target_id=str(comment_id),
            payload={"resource_id": comment.resource_id, "owner_user_id": comment.user_id},
        )
    )
    await db.commit()
