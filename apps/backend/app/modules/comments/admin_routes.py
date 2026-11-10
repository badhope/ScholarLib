"""评论审核后台接口（editor 及以上）。

挂载在 ``/api/admin/comments``：

- GET  /api/admin/comments?status=pending|published|rejected
        分页、按 created_at 倒序；返回评论正文、作者、所属资源标题、
        审核状态与审核元数据。
- POST /api/admin/comments/{id}/moderate
        body: ``{action: "approve"|"reject", note?: str}``
        approve → status=published；reject → status=rejected（前台立即下架）。

审计：每次裁决写一条 ``AuditLog``（action = ``comment.approve`` /
``comment.reject``），与现有 ``comment.delete`` 留痕口径一致。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role, require_tenant_id
from app.core.db import get_db, paginate
from app.models import AuditLog, User
from app.modules.catalog.models import Resource
from app.modules.comments.models import Comment
from app.modules.comments.schemas import (
    AdminCommentListResponse,
    AdminCommentRow,
    AdminCommentStatusCounts,
    CommentModerateRequest,
)

router = APIRouter(prefix="/admin/comments", tags=["admin-comments"])

StatusFilter = Literal["pending", "published", "rejected"]


async def _usernames(db: AsyncSession, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    return {uid: uname for uid, uname in rows.all()}


async def _serialize_admin(db: AsyncSession, rows: list[Comment]) -> list[AdminCommentRow]:
    """联表作者、被评论资源标题、审核人。"""
    user_ids: set[int] = set()
    resource_ids: list[int] = []
    for r in rows:
        user_ids.add(r.user_id)
        if r.moderated_by is not None:
            user_ids.add(r.moderated_by)
        resource_ids.append(r.resource_id)

    names = await _usernames(db, list(user_ids))
    titles: dict[int, str] = {}
    if resource_ids:
        t_rows = await db.execute(
            select(Resource.id, Resource.title).where(Resource.id.in_(resource_ids))
        )
        titles = {rid: t for rid, t in t_rows.all()}

    return [
        AdminCommentRow(
            id=r.id,
            resource_id=r.resource_id,
            resource_title=titles.get(r.resource_id),
            user_id=r.user_id,
            author_name=names.get(r.user_id, "已注销用户"),
            body=r.body,
            status=r.status,
            moderation_note=r.moderation_note,
            moderated_by=r.moderated_by,
            moderated_by_name=(names.get(r.moderated_by) if r.moderated_by is not None else None),
            moderated_at=r.moderated_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("", response_model=AdminCommentListResponse)
async def list_admin_comments(
    status_filter: StatusFilter | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _editor: User = Depends(require_role("editor")),
) -> AdminCommentListResponse:
    """后台评论列表：按状态过滤，时间倒序。"""
    tenant_id = require_tenant_id()
    stmt = select(Comment).where(Comment.tenant_id == tenant_id)
    if status_filter is not None:
        stmt = stmt.where(Comment.status == status_filter)
    rows, meta = await paginate(
        db,
        stmt,
        page=page,
        page_size=page_size,
        order_by=(Comment.created_at.desc(), Comment.id.desc()),
    )
    return AdminCommentListResponse(data=await _serialize_admin(db, list(rows)), meta=meta)


@router.get("/counts", response_model=AdminCommentStatusCounts)
async def comment_status_counts(
    db: AsyncSession = Depends(get_db),
    _editor: User = Depends(require_role("editor")),
) -> AdminCommentStatusCounts:
    """顶部状态筛选徽标：各状态当前租户下的评论数。"""
    tenant_id = require_tenant_id()
    rows = await db.execute(
        select(Comment.status, func.count())
        .where(Comment.tenant_id == tenant_id)
        .group_by(Comment.status)
    )
    out: dict[str, int] = {"pending": 0, "published": 0, "rejected": 0}
    for s, c in rows.all():
        if s in out:
            out[s] = int(c)
    return AdminCommentStatusCounts(**out)


@router.post("/{comment_id}/moderate", response_model=AdminCommentRow)
async def moderate_comment(
    comment_id: int,
    payload: CommentModerateRequest,
    db: AsyncSession = Depends(get_db),
    editor: User = Depends(require_role("editor")),
) -> AdminCommentRow:
    """通过或拒绝一条评论。拒绝后前台立即不可见。"""
    tenant_id = require_tenant_id()
    result = await db.execute(
        select(Comment).where(Comment.id == comment_id, Comment.tenant_id == tenant_id)
    )
    comment = result.scalar_one_or_none()
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评论不存在")

    new_status: Literal["published", "rejected"] = (
        "published" if payload.action == "approve" else "rejected"
    )
    comment.status = new_status
    comment.moderated_by = editor.id
    from app.core.time import utcnow

    comment.moderated_at = utcnow()
    comment.moderation_note = payload.note.strip() if payload.note else None

    audit_entry = AuditLog(
        tenant_id=editor.tenant_id,
        actor_user_id=editor.id,
        action=f"comment.{payload.action}",
        target_type="comment",
        target_id=str(comment.id),
        payload={
            "resource_id": comment.resource_id,
            "owner_user_id": comment.user_id,
            "from_status": "pending",
            "to_status": new_status,
            "note": comment.moderation_note,
        },
    )
    db.add(audit_entry)
    await db.commit()
    await db.refresh(comment)
    return (await _serialize_admin(db, [comment]))[0]
