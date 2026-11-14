"""Pydantic schemas for the recommendations module.

The recommendation endpoint wraps catalog ``Resource`` rows with a
content-based match score and a short human-readable reason. There are
no write endpoints — recommendations are computed on demand from the
user's reading history, so the only response shapes are the item and
the list wrapper.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.schemas import Authors, PaginationMeta


class RecommendationItem(BaseModel):
    """One recommended resource with its match score and reason."""

    id: int
    title: str
    authors: Authors
    year: int | None
    doi: str | None
    discipline: str | None
    subdiscipline: str | None
    tags: list[str]
    score: float
    reason: str


class RecommendationListResponse(BaseModel):
    data: list[RecommendationItem]
    meta: PaginationMeta


__all__ = ["RecommendationItem", "RecommendationListResponse"]
