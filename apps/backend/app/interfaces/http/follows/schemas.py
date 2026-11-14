"""Pydantic schemas for the follows module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.schemas import PaginationMeta


class FollowStatusResponse(BaseModel):
    """Whether the current user follows an author + that author's follower count."""

    following: bool
    followers_count: int


class SubscriptionStatusResponse(BaseModel):
    """Whether the current user subscribes to a discipline + its subscriber count."""

    subscribed: bool
    subscribers_count: int


class AuthorFollowEntry(BaseModel):
    """One row in GET /users/me/following/authors.

    ``followed_at`` is the API-facing name; the underlying ORM column is
    ``created_at``. The alias lets ``model_validate(orm_row)`` find the
    right attribute without renaming the column.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    author_name: str
    followed_at: datetime = Field(alias="created_at")


class AuthorFollowListResponse(BaseModel):
    data: list[AuthorFollowEntry]
    meta: PaginationMeta


class DisciplineSubscriptionListResponse(BaseModel):
    """The current user's subscribed discipline slugs."""

    data: list[str]


# Author name validation: must be 1..200 chars (matches the catalog
# author validator). Exposed here so the route layer can reuse it
# without re-importing from catalog.
AUTHOR_NAME_MIN = 1
AUTHOR_NAME_MAX = 200
DISCIPLINE_MAX = 100


__all__ = [
    "AUTHOR_NAME_MAX",
    "AUTHOR_NAME_MIN",
    "DISCIPLINE_MAX",
    "AuthorFollowEntry",
    "AuthorFollowListResponse",
    "DisciplineSubscriptionListResponse",
    "FollowStatusResponse",
    "SubscriptionStatusResponse",
]
