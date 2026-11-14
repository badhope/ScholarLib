"""HTTP response serialization for submissions.

Serialization is an inbound-adapter concern: business code returns ORM
objects, only this module knows the public JSON shape.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import paginate
from app.core.tenant import require_tenant_id
from app.core.tracks import normalize_track
from app.domain.submission.models import Submission
from app.interfaces.http.submission.schemas import SubmissionListResponse, SubmissionResponse


async def _get_or_404(db: AsyncSession, submission_id: int) -> Submission:
    """Fetch a submission by id (scoped to current tenant) or raise 404."""
    tenant_id = require_tenant_id()
    entry = (
        await db.execute(
            select(Submission).where(
                Submission.id == submission_id,
                Submission.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )
    return entry


def _to_response(
    entry: Submission, review_stats: dict[Any, Any] | None = None
) -> SubmissionResponse:
    stats = review_stats or {}
    return SubmissionResponse(
        id=entry.id,
        title=entry.title,
        type=entry.type,
        track=normalize_track(getattr(entry, "track", None)),
        authors=entry.authors,
        year=entry.year,
        venue=entry.venue,
        discipline=entry.discipline,
        subdiscipline=entry.subdiscipline,
        article_section=getattr(entry, "article_section", None),
        issue_part=getattr(entry, "issue_part", None),
        keywords=entry.keywords or [],
        jel_codes=entry.jel_codes or [],
        tags=entry.tags,
        abstract=entry.abstract,
        preview=entry.preview,
        download_url=entry.download_url,
        external_url=entry.external_url,
        anonymized_file_url=entry.anonymized_file_url,
        doi=entry.doi,
        corresponding_author_email=entry.corresponding_author_email,
        status=entry.status,
        admin_note=entry.admin_note,
        editor_note=entry.editor_note,
        resource_id=entry.resource_id,
        similarity_score=getattr(entry, "similarity_score", None),
        similarity_matches=getattr(entry, "similarity_matches", None) or [],
        cover_image=entry.cover_image,
        file_path=entry.file_path,
        markdown_path=entry.markdown_path,
        submitted_by=entry.submitted_by,
        submitted_at=entry.submitted_at,
        reviewed_by=entry.reviewed_by,
        reviewed_at=entry.reviewed_at,
        triage_status=getattr(entry, "triage_status", None),
        triage_note=getattr(entry, "triage_note", None),
        triaged_at=getattr(entry, "triaged_at", None),
        triaged_by=getattr(entry, "triaged_by", None),
        reports_completed=stats.get("reports_completed", 0),
        distinct_reviewers=stats.get("distinct_reviewers", 0),
        accept_recommendations=stats.get("accept_recommendations", 0),
        reject_recommendations=stats.get("reject_recommendations", 0),
        can_decide=stats.get("can_decide", False),
        conflict=stats.get("conflict", False),
        adjudicator_assigned=stats.get("adjudicator_assigned", False),
        adjudicator_accepted=stats.get("adjudicator_accepted", False),
    )


async def _review_stats_for_submissions(
    db: AsyncSession, ids: list[int], tenant_id: str
) -> dict[int, dict[str, Any]]:
    """批量算当前轮审稿进度，避免列表把“已有 1 份意见”显示成 0。"""
    if not ids:
        return {}
    from app.domain.review.models import ReviewAssignment, ReviewReport

    rows = (
        await db.execute(
            select(
                ReviewAssignment.submission_id,
                ReviewAssignment.reviewer_id,
                ReviewAssignment.round,
                ReviewAssignment.is_adjudicator,
                ReviewReport.recommendation,
            )
            .join(ReviewReport, ReviewReport.assignment_id == ReviewAssignment.id, isouter=True)
            .where(
                ReviewAssignment.submission_id.in_(ids),
                ReviewAssignment.tenant_id == tenant_id,
            )
        )
    ).all()
    by_sub: dict[int, list[Any]] = {}
    for r in rows:
        by_sub.setdefault(r[0], []).append(r)
    out: dict[int, dict[str, Any]] = {}
    for sid, rs in by_sub.items():
        current_round = max((x[2] or 1) for x in rs)
        cur = [x for x in rs if (x[2] or 1) == current_round and x[4] is not None]
        accept_ids = {x[1] for x in cur if x[4] == "accept"}
        reject = sum(1 for x in cur if x[4] == "reject")
        major = sum(1 for x in cur if x[4] == "major_revision")
        adj_rows = [x for x in rs if (x[2] or 1) == current_round and x[3]]
        adj_accept = any(x[4] == "accept" for x in adj_rows)
        conflict = bool(accept_ids) and (reject > 0 or major > 0)
        out[sid] = {
            "reports_completed": len(cur),
            "distinct_reviewers": len({x[1] for x in cur}),
            "accept_recommendations": len(accept_ids),
            "reject_recommendations": reject,
            "conflict": conflict,
            "adjudicator_assigned": bool(adj_rows),
            "adjudicator_accepted": adj_accept,
            "can_decide": len(accept_ids) >= 2 and (not conflict or adj_accept),
        }
    return out


async def _list_submissions(
    db: AsyncSession,
    base_query: Any,
    page: int,
    page_size: int,
) -> SubmissionListResponse:
    """Paginate + serialize a submission query."""
    rows, meta = await paginate(
        db,
        base_query,
        page=page,
        page_size=page_size,
        order_by=(desc(Submission.submitted_at), Submission.id.asc()),
    )
    tenant_id = rows[0].tenant_id if rows else None
    stats = (
        await _review_stats_for_submissions(db, [r.id for r in rows], tenant_id)
        if tenant_id
        else {}
    )
    return SubmissionListResponse(
        data=[_to_response(r, stats.get(r.id)) for r in rows],
        meta=meta,
    )
