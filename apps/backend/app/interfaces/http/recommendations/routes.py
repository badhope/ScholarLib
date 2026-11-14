"""Recommendations API routes — personalized resource recommendations.

Single endpoint: ``GET /api/recommendations/me`` returns the current
user's top-N content-based recommendations, computed on demand from
their reading history. No write endpoints.

The response is not a direct paginated DB query (the results come from
the scoring engine), so ``paginate()`` is not used here; the
``PaginationMeta`` is filled with total = items returned, page = 1,
single page — enough for clients that expect the standard envelope.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.core.schemas import PaginationMeta
from app.domain.recommendations.engine import recommend
from app.interfaces.http.recommendations.schemas import (
    RecommendationItem,
    RecommendationListResponse,
)
from app.models import User

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

DEFAULT_LIMIT = 10
MAX_LIMIT = 50


@router.get("/me", response_model=RecommendationListResponse)
async def list_my_recommendations(
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecommendationListResponse:
    """Return the current user's top-N recommended resources."""
    scored = await recommend(db, current_user.id, current_user.tenant_id, limit)
    items = [
        RecommendationItem(
            id=s.resource.id,
            title=s.resource.title,
            authors=s.resource.authors,
            year=s.resource.year,
            doi=s.resource.doi,
            discipline=s.resource.discipline,
            subdiscipline=s.resource.subdiscipline,
            tags=s.resource.tags,
            score=s.score,
            reason=s.reason,
        )
        for s in scored
    ]
    return RecommendationListResponse(
        data=items,
        meta=PaginationMeta(
            total=len(items),
            page=1,
            page_size=limit,
            total_pages=1,
        ),
    )
