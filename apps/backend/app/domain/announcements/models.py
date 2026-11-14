"""Announcement models — site notices shown on the first visit.

A single table with an explicit publish window. The homepage asks for the
active announcement; dismissing it is a client-side cookie so no per-user
state is stored (guests must see it too).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models import Base, TenantScopedMixin


class Announcement(Base, TenantScopedMixin):
    __tablename__ = "announcements"
    # 与迁移 010 的命名约束一致：alembic check 不应报漂移。
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_announcements_tenant_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 显式起止时间：到点自动下线，不需要再动一次数据库。
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


__all__ = ["Announcement"]
