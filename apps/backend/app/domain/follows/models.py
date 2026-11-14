"""SQLAlchemy models for the follows module.

Two tables, both tenant-scoped with RLS:

- ``author_follows`` — (tenant, user, author_name). Keyed on the author
  NAME (string), not a structured Author entity, because the catalog
  module defers the structured Author table to a future phase (its
  primary author storage is the JSON ``authors`` list[str] column on
  ``resources``). Following a string matches that model and lets the
  follow relationship exist independently of any catalog record
  existing for that author.

- ``discipline_subscriptions`` — (tenant, user, discipline slug). The
  discipline slug is a free-form string (e.g. ``physics``,
  ``computer-science``); the catalog module owns the canonical list,
  but follows does not enforce it cross-module to avoid coupling
  module enablement. The route layer validates against the catalog's
  observed disciplines at request time.

Both tables carry a UniqueConstraint on (tenant_id, user_id, <target>)
so the relationship is idempotent at the DB level — re-following the
same author is a no-op rather than a 409.

The user FK points at ``users.id`` in the core schema; the model
inherits from the core ``Base`` so cross-module FKs resolve without
metadata gymnastics (ARCHITECTURE.md "All modules share the tenant's
PostgreSQL database").
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models import Base, TenantScopedMixin

if TYPE_CHECKING:
    pass


class AuthorFollow(Base, TenantScopedMixin):
    """A user's follow relationship with one author (by name).

    The author is identified by name string (not a structured entity),
    matching how catalog stores authors (JSON list[str] on resources).
    """

    __tablename__ = "author_follows"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "author_name", name="uq_author_follows_tenant_user_author"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Author name (the string used in catalog Resource.authors). No FK —
    # an author may be followed before any catalog record exists for
    # them; and deleting a catalog Resource must not invalidate the
    # follow relationship (the user still wants to be notified when the
    # author publishes again).
    author_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class DisciplineSubscription(Base, TenantScopedMixin):
    """A user's subscription to a discipline slug.

    The slug is a free-form string (e.g. ``physics``); the catalog
    module owns the canonical list, but follows does not enforce it at
    the model layer to avoid coupling module enablement.
    """

    __tablename__ = "discipline_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "discipline",
            name="uq_discipline_subscriptions_tenant_user_discipline",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    discipline: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


__all__ = ["AuthorFollow", "DisciplineSubscription"]
