"""SQLAlchemy models for the library module.

Two tables:

- ``reading_lists`` — (tenant, user, name). Tenant-scoped with RLS.
  The (tenant, user, name) tuple is unique so a user can't create two
  lists with the same name.

- ``reading_list_items`` — (list, resource, tenant). The (list_id,
  resource_id) tuple is unique so adding the same resource twice is a
  no-op. Items are ordered by ``added_at`` (insertion order); manual
  reordering is a future concern. ``tenant_id`` is denormalized from
  ``reading_lists`` so RLS can protect this table directly (a cross-
  table policy would be slower and fragile) and so direct queries
  without RLS still scope correctly.

The ``resource_id`` is an ``Integer`` FK → ``resources.id`` (instead
of business-id strings) for sort stability and FK performance,
matching the catalog module's PK type.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models import Base, TenantScopedMixin

if TYPE_CHECKING:
    from app.domain.catalog.models import Resource


class ReadingList(Base, TenantScopedMixin):
    """A user's named collection of catalog resources."""

    __tablename__ = "reading_lists"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "name", name="uq_reading_lists_tenant_user_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    items: Mapped[list[ReadingListItem]] = relationship(
        back_populates="reading_list",
        cascade="all, delete-orphan",
        order_by="ReadingListItem.added_at",
        lazy="selectin",
    )


class ReadingListItem(Base, TenantScopedMixin):
    """An item in a reading list — a reference to a catalog Resource."""

    __tablename__ = "reading_list_items"
    __table_args__ = (
        UniqueConstraint("reading_list_id", "resource_id", name="uq_reading_list_item_resource"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Denormalized from reading_lists so RLS can protect this table directly
    # and direct queries without RLS still scope to a single tenant.
    reading_list_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reading_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    reading_list: Mapped[ReadingList] = relationship(back_populates="items")
    resource: Mapped[Resource] = relationship(lazy="selectin")


__all__ = ["ReadingList", "ReadingListItem"]
