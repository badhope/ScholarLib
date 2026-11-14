"""Reviewer quarterly calibration (P1-10).

同一篇稿件通常有多位审稿人。季度校准不评价“谁对谁错”，只把每位审稿人
相对同稿共识的平均偏移、绝对偏移和推荐分布摆出来，供主编在下一季度
定向沟通。只有编辑可见；不自动降级/封禁任何人。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_editor, require_tenant_id
from app.core.db import get_db
from app.core.time import utcnow
from app.domain.review.models import ReviewAssignment, ReviewReport
from app.models import User

router = APIRouter(prefix="/calibration", tags=["review-calibration"])


class CalibrationReviewerRow(BaseModel):
    reviewer_id: int
    username: str
    completed_reviews: int
    avg_score: float | None = None
    avg_deviation: float | None = None
    avg_abs_deviation: float | None = None
    accept_rate: float | None = None
    flags: list[str] = Field(default_factory=list)


class CalibrationResponse(BaseModel):
    year: int
    quarter: int
    period_start: datetime
    period_end: datetime
    submission_count: int
    reviewers: list[CalibrationReviewerRow]
    generated_at: datetime


def _quarter_bounds(year: int, quarter: int) -> tuple[datetime, datetime]:
    if quarter < 1 or quarter > 4:
        raise ValueError("quarter must be 1–4")
    start_month = (quarter - 1) * 3 + 1
    start = datetime(year, start_month, 1, tzinfo=UTC)
    if quarter == 4:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, start_month + 3, 1, tzinfo=UTC)
    return start, end


def _overall_score(scores: Any) -> float | None:
    if not isinstance(scores, dict):
        return None
    raw = scores.get("score")
    if isinstance(raw, (int, float)):
        return float(raw)
    dimensions = scores.get("dimensions")
    if not isinstance(dimensions, dict):
        return None
    values: list[float] = []
    for item in dimensions.values():
        if isinstance(item, dict) and isinstance(item.get("score"), (int, float)):
            values.append(float(item["score"]))
    return mean(values) if values else None


def _recommendation_value(recommendation: str) -> float:
    return {
        "accept": 1.0,
        "minor_revision": 0.75,
        "major_revision": 0.25,
        "reject": 0.0,
    }.get(recommendation, 0.5)


@router.get("", response_model=CalibrationResponse)
async def reviewer_calibration(
    year: int | None = Query(default=None, ge=2000, le=2100),
    quarter: int | None = Query(default=None, ge=1, le=4),
    _: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> CalibrationResponse:
    tenant_id = require_tenant_id()
    now = utcnow()
    target_year = year or now.year
    target_quarter = quarter or ((now.month - 1) // 3 + 1)
    start, end = _quarter_bounds(target_year, target_quarter)

    rows = (
        await db.execute(
            select(
                ReviewAssignment.reviewer_id,
                User.username,
                ReviewAssignment.submission_id,
                ReviewReport.scores,
                ReviewReport.recommendation,
            )
            .join(ReviewReport, ReviewReport.assignment_id == ReviewAssignment.id)
            .join(User, User.id == ReviewAssignment.reviewer_id)
            .where(
                ReviewAssignment.tenant_id == tenant_id,
                ReviewAssignment.status == "completed",
                ReviewAssignment.completed_at.is_not(None),
                ReviewAssignment.completed_at >= start,
                ReviewAssignment.completed_at < end,
                ReviewReport.tenant_id == tenant_id,
            )
        )
    ).all()

    # submission -> list of (reviewer_id, score)
    by_submission: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for row in rows:
        score = _overall_score(row.scores)
        if score is not None:
            by_submission[row.submission_id].append((row.reviewer_id, score))

    deviations: dict[int, list[float]] = defaultdict(list)
    abs_deviations: dict[int, list[float]] = defaultdict(list)
    for reports in by_submission.values():
        if len(reports) < 2:
            continue
        consensus = mean(score for _, score in reports)
        for reviewer_id, score in reports:
            deviations[reviewer_id].append(score - consensus)
            abs_deviations[reviewer_id].append(abs(score - consensus))

    scores_by_reviewer: dict[int, list[float]] = defaultdict(list)
    recommendations_by_reviewer: dict[int, list[float]] = defaultdict(list)
    names: dict[int, str] = {}
    for row in rows:
        names[row.reviewer_id] = row.username
        score = _overall_score(row.scores)
        if score is not None:
            scores_by_reviewer[row.reviewer_id].append(score)
        recommendations_by_reviewer[row.reviewer_id].append(
            _recommendation_value(row.recommendation)
        )

    result: list[CalibrationReviewerRow] = []
    for reviewer_id, name in sorted(names.items(), key=lambda item: item[1]):
        count = len(recommendations_by_reviewer[reviewer_id])
        avg_score = (
            mean(scores_by_reviewer[reviewer_id]) if scores_by_reviewer[reviewer_id] else None
        )
        avg_dev = mean(deviations[reviewer_id]) if deviations[reviewer_id] else None
        avg_abs = mean(abs_deviations[reviewer_id]) if abs_deviations[reviewer_id] else None
        accept_rate = sum(recommendations_by_reviewer[reviewer_id]) / count * 100 if count else None
        flags: list[str] = []
        if count < 2:
            flags.append("insufficient_volume")
        if avg_dev is not None and avg_dev <= -8:
            flags.append("harsh")
        if avg_dev is not None and avg_dev >= 8:
            flags.append("lenient")
        if avg_abs is not None and avg_abs >= 15:
            flags.append("high_variance")
        result.append(
            CalibrationReviewerRow(
                reviewer_id=reviewer_id,
                username=name,
                completed_reviews=count,
                avg_score=round(avg_score, 1) if avg_score is not None else None,
                avg_deviation=round(avg_dev, 1) if avg_dev is not None else None,
                avg_abs_deviation=round(avg_abs, 1) if avg_abs is not None else None,
                accept_rate=round(accept_rate, 1) if accept_rate is not None else None,
                flags=flags,
            )
        )

    return CalibrationResponse(
        year=target_year,
        quarter=target_quarter,
        period_start=start,
        period_end=end,
        submission_count=len(by_submission),
        reviewers=result,
        generated_at=now,
    )
