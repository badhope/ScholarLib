"""Pydantic schemas for the comments module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import PaginationMeta


class CommentCreate(BaseModel):
    """Body for POST /comments."""

    resource_id: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=1000)


class CommentResponse(BaseModel):
    """One comment row as shown in the public thread.

    前台不暴露 status / moderated_by / moderation_note——评论者本人和普通
    读者不需要看到审核状态（被拒评论直接从列表过滤掉，pending 评论按
    正常评论展示，事后审核）。
    """

    id: int
    resource_id: int
    user_id: int
    author_name: str
    body: str
    created_at: datetime


class CommentListResponse(BaseModel):
    data: list[CommentResponse]
    meta: PaginationMeta


# ---------------------------------------------------------------------------
# 后台审核
# ---------------------------------------------------------------------------

ModerationAction = Literal["approve", "reject"]


class CommentModerateRequest(BaseModel):
    """Body for POST /api/admin/comments/{id}/moderate."""

    action: ModerationAction
    note: str | None = Field(default=None, max_length=500)


class AdminCommentRow(BaseModel):
    """后台列表一行：比前台多了审核状态、所属资源标题、审核人/时间/理由。"""

    id: int
    resource_id: int
    resource_title: str | None = None
    user_id: int
    author_name: str
    body: str
    status: Literal["pending", "published", "rejected"]
    moderation_note: str | None = None
    moderated_by: int | None = None
    moderated_by_name: str | None = None
    moderated_at: datetime | None = None
    created_at: datetime


class AdminCommentListResponse(BaseModel):
    data: list[AdminCommentRow]
    meta: PaginationMeta


class AdminCommentStatusCounts(BaseModel):
    """顶部状态筛选的计数徽标。"""

    pending: int = 0
    published: int = 0
    rejected: int = 0
