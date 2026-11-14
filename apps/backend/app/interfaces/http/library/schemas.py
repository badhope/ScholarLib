"""Pydantic schemas for the library module.

Two response shapes:

- ``ReadingListResponse`` — list view, includes ``item_count`` (computed
  from ``items``, which is excluded from the JSON output).
- ``ReadingListDetailResponse`` — detail view, includes full ``items``
  with each item's ``resource`` reference (ResourceRef).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.schemas import MessageResponse, PaginationMeta


class ReadingListBase(BaseModel):
    """Shared fields for create / update."""

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)


class ReadingListCreate(ReadingListBase):
    """Body for POST /reading-lists."""


class ReadingListUpdate(BaseModel):
    """Body for PATCH /reading-lists/{id}. All fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)


class ReadingListItemCreate(BaseModel):
    """Body for POST /reading-lists/{id}/items."""

    resource_id: int


class ResourceRef(BaseModel):
    """Minimal resource reference for item responses.

    Full resource fields belong to the catalog module; here we only
    expose what a list view needs to render a row.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    type: str
    authors: list[str]
    year: int


class ReadingListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_id: int
    added_at: datetime
    resource: ResourceRef


class ReadingListResponse(BaseModel):
    """List view — without items, with item_count."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    # Loaded to compute item_count but excluded from the JSON output.
    items: list[ReadingListItemResponse] = Field(exclude=True, default_factory=list)
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def item_count(self) -> int:
        return len(self.items)


class ReadingListDetailResponse(BaseModel):
    """Detail view — with items."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    items: list[ReadingListItemResponse]
    created_at: datetime
    updated_at: datetime


class ReadingListListResponse(BaseModel):
    data: list[ReadingListResponse]
    meta: PaginationMeta


__all__ = [
    "MessageResponse",
    "ReadingListBase",
    "ReadingListCreate",
    "ReadingListDetailResponse",
    "ReadingListItemCreate",
    "ReadingListItemResponse",
    "ReadingListListResponse",
    "ReadingListResponse",
    "ReadingListUpdate",
    "ResourceRef",
]
