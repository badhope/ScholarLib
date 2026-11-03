"""SQLAlchemy models for the forum module.

Two tables, both tenant-scoped with RLS:

- ``forum_topics``   — 帖子（标题 + 正文 + 分类 + 置顶/锁定）
- ``forum_replies``  — 回帖（按时间正序展示）

为什么是"论坛"而不是"评论"：comments 模块是读者对**已发表文章**的评论，
依附于资源；论坛是**独立于文章的公共讨论区**——提建议、报 bug、聊选题、
求合作，这些内容没有对应的 resource，塞进 comments 会污染文章页。

删除策略：软删除（``deleted_at``）而不是硬删除。论坛的价值在于讨论
上下文，硬删会让被回复的楼层变成"回复不存在的内容"。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models import Base, TenantScopedMixin


class ForumTopic(Base, TenantScopedMixin):
    """一个讨论帖。"""

    __tablename__ = "forum_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # 分类：讨论 / 建议 / 求助 / 公告（编辑部可发）
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="discussion")
    # 置顶与锁定：版主/管理员操作
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 反冗余计数：列表页直接读，避免每次 COUNT(replies)
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    # 软删除：保留讨论上下文
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # 列表页默认排序：置顶优先 + 最近活跃
        Index(
            "ix_forum_topics_tenant_pinned_last",
            "tenant_id",
            "is_pinned",
            last_reply_at.desc(),
            "created_at",
        ),
    )


class ForumReply(Base, TenantScopedMixin):
    """一条回帖。"""

    __tablename__ = "forum_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("forum_topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_forum_replies_tenant_topic_created", "tenant_id", "topic_id", "created_at"),
    )
