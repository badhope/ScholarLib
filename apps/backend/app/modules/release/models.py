from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models import Base, JSONBVariant, TenantScopedMixin


class ReleaseManifest(Base, TenantScopedMixin):
    """Immutable snapshot of one issue's release gate.

    A manifest is created by ``POST /admin/releases/check`` and can only be
    used by ``POST /admin/releases/publish`` while its content hash still
    matches the live issue.  Keeping the gate result and the published
    resource snapshot together makes the release reproducible: the exact
    issue, checks, file hashes and actor are available after deploy.
    """

    __tablename__ = "release_manifests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    volume: Mapped[str] = mapped_column(String(50), nullable=False)
    issue: Mapped[str] = mapped_column(String(50), nullable=False)
    # blocked | ready | scheduled | published | superseded
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="blocked")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONBVariant, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_release_manifests_tenant_issue", "tenant_id", "volume", "issue"),
        Index("ix_release_manifests_tenant_status", "tenant_id", "status"),
    )
