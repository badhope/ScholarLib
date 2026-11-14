"""SQLAlchemy models for the reader module.

Two tables, both tenant-scoped with RLS:

- ``file_assets`` — PDF host metadata (filename / mime / size / storage path /
  sha256 / uploader). The actual byte storage is delegated to a storage
  backend (local FS / S3-compatible / etc.); this table records what was
  stored so the reader UI can resolve a download URL. No FK back to
  ``resources`` here — that link is owned by the catalog module (a future
  catalog migration may add ``resources.pdf_file_id``).
- ``reading_history`` — one row per (tenant, user, resource). Combines the
  access log (``viewed_at`` + ``visit_count``) with cross-device progress
  (``page`` / ``progress_percent`` / ``duration_sec`` / ``last_read_at`` /
  ``completed``). The unique constraint on (tenant_id, user_id, resource_id)
  makes the upsert path a single-row lookup.

Both inherit from the core ``Base`` so cross-module FKs
(``reading_history.resource_id → resources.id``) resolve without metadata
gymnastics (ARCHITECTURE.md "All modules share the tenant's PostgreSQL
database").
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models import Base, TenantScopedMixin, User


class FileAsset(Base, TenantScopedMixin):
    """Metadata for a stored PDF (or other readable asset).

    The actual file bytes live in a storage backend (local FS, S3, etc.).
    This row records what was stored, who uploaded it, and a content hash
    for dedup / integrity checks. Tenant-scoped so one tenant cannot
    enumerate another tenant's files.

    No FK back to ``resources``: that link is a catalog-side concern. A
    future catalog migration may add ``resources.pdf_file_id`` referencing
    this table; until then, ``FileAsset`` is referenced by id from the
    reader UI / download endpoints.
    """

    __tablename__ = "file_assets"
    __table_args__ = (
        # Per-tenant dedup space: same sha256 in two tenants is allowed,
        # but within a tenant sha256 must be unique (so re-uploads of the
        # same file surface as a 409 instead of silently duplicating).
        UniqueConstraint("tenant_id", "sha256", name="uq_file_assets_tenant_sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Storage-side filename (e.g. "abc123.pdf"), unique per tenant via
    # (tenant_id, filename) to keep listings predictable.
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # User-facing original name (e.g. "Manuscript v3.pdf"); informational only.
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    # Optional content hash for dedup / integrity verification. Unique per
    # tenant (not globally) so two tenants can have separate dedup spaces.
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    uploaded_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    uploader: Mapped[User | None] = relationship("User", foreign_keys="FileAsset.uploaded_by")


class ReadingHistory(Base, TenantScopedMixin):
    """One row per (tenant, user, resource) — the user's reading record.

    Combines two earlier concepts into one table because they share the
    same lifecycle:

    - Access log: ``viewed_at`` (last view timestamp), ``visit_count``
      (how many times the user opened the resource).
    - Cross-device progress: ``page`` (current PDF page),
      ``progress_percent`` (0.0..100.0), ``duration_sec`` (accumulated
      reading time in seconds, never overwritten), ``last_read_at`` (when
      the user last advanced progress), ``completed`` (finished flag).

    The unique constraint makes the upsert path a single-row lookup, and
    the IntegrityError retry (see ``PUT /progress`` in routes.py) handles
    the race between two concurrent inserts for the same pair.
    """

    __tablename__ = "reading_history"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "resource_id", name="uq_reading_history_tenant_user_resource"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Access log fields.
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    visit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Cross-device progress fields.
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Accumulated reading time in seconds. Upsert ADDS to this field,
    # never overwrites — see routes.py PUT /progress.
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


__all__ = ["FileAsset", "ReadingHistory"]
