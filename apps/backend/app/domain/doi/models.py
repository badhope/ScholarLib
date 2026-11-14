"""SQLAlchemy model for DOI registration tracking.

``doi_registrations`` keeps a record of every DOI minted or updated
through the DataCite API. The table is append-only: each row captures
one registration event so the history is auditable.

The actual DOI metadata is stored on the ``resources`` table (the
``doi`` column) and in the DataCite index. This table is purely a
local audit trail + status tracker.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models import Base, TenantScopedMixin


class DOIRegistration(Base, TenantScopedMixin):
    """Audit record for a DOI mint/update event."""

    __tablename__ = "doi_registrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The resource this DOI was registered for.
    resource_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The DOI that was registered (e.g. "10.12345/abc-def-ghi").
    # DOI 天然是全局唯一标识。此前只有 index 而非 unique，多租户/同租户内
    # 都能铸出重复 DOI 且无任何拦截（见 P0-3）。
    doi: Mapped[str] = mapped_column(String(200), nullable=False, index=True, unique=True)
    # Registration state: "pending" | "completed" | "failed"
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # DataCite API response / error message.
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who triggered this registration. Nullable because the FK is ON DELETE
    # SET NULL: the audit trail is append-only, so removing a user must not
    # erase the registration events they triggered.
    registered_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )


__all__ = ["DOIRegistration"]
