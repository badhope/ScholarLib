"""SQLAlchemy models for the comments module.

``comments`` — reader comments on published resources. Tenant-scoped
with RLS (migration 007). The user FK points at the core ``users``
table; the resource FK at the catalog ``resources`` table — both
inherit from the shared core ``Base`` so cross-module FKs resolve
without metadata gymnastics.

审核状态机（2026-11-07）：
    * ``status`` ∈ {pending, published, rejected}，新评论写入 pending；
    * 历史行默认 published（迁移 DDL 兜底）；
    * 前台 list 过滤 rejected（事后审核：pending 仍可见，被拒才下架）；
    * editor 及以上可在 ``/api/admin/comments`` 改判，留 moderated_by /
      moderated_at / moderation_note 审计痕迹。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models import Base, TenantScopedMixin

CommentStatus = Literal["pending", "published", "rejected"]


class Comment(Base, TenantScopedMixin):
    """A reader comment on a published resource.

    Deletion policy: hard delete (owner or admin), never edited —
    the timeline stays honest; audit log keeps the moderation trail.
    """

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    # --- 审核状态机（migration 20261107_comment_moderation） ---------------
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="published", server_default="published"
    )
    moderated_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    moderation_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_comments_tenant_resource_created", "tenant_id", "resource_id", created_at.desc()),
        # 后台待审列表主查询：WHERE tenant_id=? AND status=? ORDER BY created_at DESC
        Index("ix_comments_tenant_status_created", "tenant_id", "status", created_at.desc()),
    )
