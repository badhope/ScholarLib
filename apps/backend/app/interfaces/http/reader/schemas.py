"""Pydantic schemas for the reader module.

History endpoints (read + write) are authenticated — every user sees
their own history only. FileAsset endpoints are admin-only (creating
file metadata requires admin privileges; the byte upload pipeline is a
separate concern handled by the storage layer).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.schemas import MessageResponse, PaginationMeta

StorageBackend = Literal["local", "s3", "minio"]


class FileAssetCreate(BaseModel):
    """Body for POST /reader/file-assets — record stored-file metadata.

    The caller is responsible for having already written the bytes to the
    storage backend; this endpoint only records what was stored.
    """

    filename: str = Field(min_length=1, max_length=255)
    original_filename: str = Field(min_length=1, max_length=500)
    mime_type: str = Field(min_length=1, max_length=100)
    file_size: int = Field(ge=0)
    storage_path: str = Field(min_length=1, max_length=500)
    storage_backend: StorageBackend = "local"
    sha256: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("storage_path")
    @classmethod
    def _storage_path_no_traversal(cls, v: str) -> str:
        # Reject absolute paths and parent traversal (..) so future file-read
        # endpoints cannot escape the storage root.
        p = PurePosixPath(v)
        if p.is_absolute():
            raise ValueError("storage_path must be relative, not absolute")
        if ".." in p.parts:
            raise ValueError("storage_path must not contain parent traversal (..)")
        return v


class FileAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    original_filename: str
    mime_type: str
    file_size: int
    storage_path: str
    storage_backend: str
    sha256: str | None = None
    uploaded_by: int | None = None
    created_at: datetime


class ReadingProgressUpdate(BaseModel):
    """Body for PUT /reader/history/{resource_id}/progress.

    All fields optional. ``duration_sec`` is ADDED to the existing value
    (not overwritten) so concurrent updates from multiple devices never
    lose reading time.
    """

    page: int | None = Field(default=None, ge=0)
    progress_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    duration_sec: int | None = Field(default=None, ge=0)
    completed: bool | None = None


class ReadingProgressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    resource_id: int
    page: int | None = None
    progress_percent: float | None = None
    duration_sec: int
    visit_count: int
    last_read_at: datetime | None = None
    viewed_at: datetime
    completed: bool


class ReadingHistoryEntryResponse(BaseModel):
    """One row in GET /reader/history — progress for a single resource.

    ``title`` / ``authors`` / ``discipline`` / ``year`` / ``resource_type``
    are joined from the catalog row so the frontend can render a
    「继续阅读」卡片 without a second round-trip. They are ``None`` only in
    the degenerate case where the joined row vanished mid-request.
    """

    model_config = ConfigDict(from_attributes=True)

    resource_id: int
    viewed_at: datetime
    last_read_at: datetime | None = None
    visit_count: int
    page: int | None = None
    progress_percent: float | None = None
    duration_sec: int
    completed: bool
    # JOIN 附加的资源元信息（继续阅读卡直接渲染用）
    title: str | None = None
    authors: list[str] = []
    discipline: str | None = None
    year: int | None = None
    resource_type: str | None = None


class ReadingHistoryListResponse(BaseModel):
    data: list[ReadingHistoryEntryResponse]
    meta: PaginationMeta


__all__ = [
    "FileAssetCreate",
    "FileAssetResponse",
    "MessageResponse",
    "PaginationMeta",
    "ReadingHistoryEntryResponse",
    "ReadingHistoryListResponse",
    "ReadingProgressResponse",
    "ReadingProgressUpdate",
]
