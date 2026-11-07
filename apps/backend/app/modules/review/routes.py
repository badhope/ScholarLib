"""Peer-review API routes.

Reviewer side (auth + reviewer role, see deps.require_reviewer):
  GET    /review/assignments/me           — list my assignments
  GET    /review/assignments/{id}         — view one assignment + submission details
  POST   /review/assignments/{id}/accept  — accept invitation
  POST   /review/assignments/{id}/decline — decline invitation
  POST   /review/assignments/{id}/submit  — submit review report

Editor-facing assignment management lives under ``/submissions`` for
cohesion (both modules share the Submission row). See ``submission.routes``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_editor, require_reviewer, require_tenant_id
from app.core.db import get_db, paginate
from app.core.time import utcnow
from app.models import User
from app.modules.notifications import services as notifications
from app.modules.review.blinding import get_review_mode, reviewer_facing_payload
from app.modules.review.models import ReviewAssignment, ReviewReport
from app.modules.review.schemas import (
    AssignmentListResponse,
    AssignmentResponse,
    ReviewReportResponse,
    ReviewSubmit,
)
from app.modules.submission.models import Submission
from app.modules.submission.schemas import SubmissionResponse

router = APIRouter(prefix="/review", tags=["review"])

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _to_assignment_response(
    a: ReviewAssignment, *, include_submission_title: bool = False
) -> AssignmentResponse:
    return AssignmentResponse(
        id=a.id,
        submission_id=a.submission_id,
        reviewer_id=a.reviewer_id,
        assigned_by=a.assigned_by,
        status=a.status,
        due_date=a.due_date,
        invited_at=a.invited_at,
        responded_at=a.responded_at,
        completed_at=a.completed_at,
        reviewer_username=a.reviewer.username if a.reviewer else None,
        submission_title=(
            a.submission.title if include_submission_title and a.submission else None
        ),
        last_reminded_at=a.last_reminded_at,
        reminder_count=a.reminder_count,
    )


async def _get_assignment_or_404(db: AsyncSession, assignment_id: int) -> ReviewAssignment:
    tenant_id = require_tenant_id()
    a = (
        await db.execute(
            select(ReviewAssignment)
            .where(
                ReviewAssignment.id == assignment_id,
                ReviewAssignment.tenant_id == tenant_id,
            )
            .options(
                selectinload(ReviewAssignment.reviewer),
                selectinload(ReviewAssignment.submission),
            )
        )
    ).scalar_one_or_none()
    if a is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found",
        )
    return a


async def _get_assignment_for_reviewer(
    db: AsyncSession, assignment_id: int, reviewer_id: int
) -> ReviewAssignment:
    """Fetch assignment + ensure current reviewer is the assignee."""
    a = await _get_assignment_or_404(db, assignment_id)
    if a.reviewer_id != reviewer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This assignment belongs to another reviewer",
        )
    return a


@router.get("/assignments/me", response_model=AssignmentListResponse)
async def list_my_assignments(
    status_filter: str = Query(
        default=None,
        alias="status",
        pattern=r"^(pending|accepted|declined|completed|cancelled)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
) -> AssignmentListResponse:
    """List the current reviewer's assignments (filter by status)."""
    query = (
        select(ReviewAssignment)
        .where(
            ReviewAssignment.reviewer_id == current_user.id,
            ReviewAssignment.tenant_id == current_user.tenant_id,
        )
        .options(selectinload(ReviewAssignment.submission))
    )
    if status_filter is not None:
        query = query.where(ReviewAssignment.status == status_filter)
    rows, meta = await paginate(
        db,
        query,
        page=page,
        page_size=page_size,
        order_by=(desc(ReviewAssignment.invited_at), ReviewAssignment.id.asc()),
    )
    return AssignmentListResponse(
        data=[_to_assignment_response(r, include_submission_title=True) for r in rows],
        meta=meta,
    )


@router.get("/assignments/{assignment_id}", response_model=AssignmentResponse)
async def get_my_assignment(
    assignment_id: int,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
) -> AssignmentResponse:
    """View one assignment (reviewer only sees their own)."""
    a = await _get_assignment_for_reviewer(db, assignment_id, current_user.id)
    return _to_assignment_response(a, include_submission_title=True)


@router.get(
    "/assignments/{assignment_id}/submission",
    response_model=SubmissionResponse,
)
async def get_assignment_submission(
    assignment_id: int,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """审稿人查看分配稿件的完整内容（abstract / preview / file_path 等）。

    单盲（默认）：审稿人看到完整稿件，含作者姓名。
    双盲：作者姓名/通讯邮箱/venue/DOI/提交人 id 被抹掉（见 blinding 模块），
    审稿人仍能拿到正文与所有学术内容。

    作者侧的剥离（作者看不到审稿人身份）两种模式下都生效，在
    ``submission.routes.list_review_reports`` 里处理。

    仅 pending/accepted/completed 状态可查看；declined/cancelled 不可查看。
    """
    a = await _get_assignment_for_reviewer(db, assignment_id, current_user.id)
    if a.status not in ("pending", "accepted", "completed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot view submission in status '{a.status}'",
        )
    s = a.submission
    if s is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )
    payload = {
        "id": s.id,
        "title": s.title,
        "type": s.type,
        # 赛道：审稿人必须知道自己在按哪条赛道的标准评审——同一篇文字
        # 按"正经研究"评可能结构不完整，按"荒诞研究"评则完全成立。
        "track": s.track,
        "authors": s.authors,
        "year": s.year,
        "venue": s.venue,
        "discipline": s.discipline,
        "subdiscipline": s.subdiscipline,
        "keywords": s.keywords,
        "jel_codes": s.jel_codes,
        "tags": s.tags,
        "abstract": s.abstract,
        "preview": s.preview,
        "download_url": s.download_url,
        "external_url": s.external_url,
        # 双盲下作者可控外链会被 anonymize 抹掉；本字段是编辑提供的
        # 匿名稿链接，审稿人需要看到，原样透传。
        "anonymized_file_url": s.anonymized_file_url,
        "doi": s.doi,
        "corresponding_author_email": s.corresponding_author_email,
        "status": s.status,
        "admin_note": s.admin_note,
        "editor_note": s.editor_note,
        "resource_id": s.resource_id,
        "file_path": s.file_path,
        "submitted_by": s.submitted_by,
        "submitted_at": s.submitted_at,
        "reviewed_by": s.reviewed_by,
        "reviewed_at": s.reviewed_at,
    }
    # admin 例外：平台管理员需要能复现问题，且其身份天然不受盲审约束。
    if not current_user.is_admin:
        mode = await get_review_mode(db, s.tenant_id)
        # 单盲与双盲都走字段裁剪：编辑的内部备注在两种模式下都不属于
        # 审稿人可见信息（单盲只解除"作者是谁"，不解除编辑的私密评语）。
        payload = reviewer_facing_payload(payload, double_blind=(mode == "double_blind"))
    return SubmissionResponse(**payload)


@router.post(
    "/assignments/{assignment_id}/accept",
    response_model=AssignmentResponse,
)
async def accept_assignment(
    assignment_id: int,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
) -> AssignmentResponse:
    """Reviewer accepts the invitation."""
    a = await _get_assignment_for_reviewer(db, assignment_id, current_user.id)
    if a.submission is None or a.submission.submitted_by == current_user.id:
        raise HTTPException(status_code=403, detail="Cannot review own submission")
    if a.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Assignment is in status '{a.status}', cannot accept",
        )
    a.status = "accepted"
    a.responded_at = utcnow()
    # 通知指派编辑：邀请被接受（否则编辑只能反复刷新工作台才知道有人应邀）
    if a.assigned_by is not None and a.assigned_by != current_user.id:
        await notifications.create(
            db,
            tenant_id=current_user.tenant_id,
            user_id=a.assigned_by,
            type_="review.accepted",
            title=f"审稿邀请已被接受：{a.submission.title if a.submission else '稿件 #' + str(a.submission_id)}",
            body=f"{current_user.username} 已接受《#{a.submission_id}》的审稿邀请。",
        )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not update assignment (concurrent change)",
        ) from exc
    await db.refresh(a)
    return _to_assignment_response(a)


@router.post(
    "/assignments/{assignment_id}/decline",
    response_model=AssignmentResponse,
)
async def decline_assignment(
    assignment_id: int,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
) -> AssignmentResponse:
    """Reviewer declines the invitation."""
    a = await _get_assignment_for_reviewer(db, assignment_id, current_user.id)
    if a.status not in ("pending", "accepted"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Assignment is in status '{a.status}', cannot decline",
        )
    a.status = "declined"
    a.responded_at = utcnow()
    # 通知指派编辑：邀请被拒——编辑需要尽快改派他人，静默会让稿件干等
    if a.assigned_by is not None and a.assigned_by != current_user.id:
        await notifications.create(
            db,
            tenant_id=current_user.tenant_id,
            user_id=a.assigned_by,
            type_="review.declined",
            title=f"审稿邀请被拒：{a.submission.title if a.submission else '稿件 #' + str(a.submission_id)}",
            body=f"{current_user.username} 拒绝了《#{a.submission_id}》的审稿邀请，请考虑改派其他审稿人。",
        )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not update assignment (concurrent change)",
        ) from exc
    await db.refresh(a)
    return _to_assignment_response(a)


@router.post(
    "/assignments/{assignment_id}/submit",
    response_model=ReviewReportResponse,
    # 201: the report is a newly created resource (T2 finding L-1 — was 200).
    status_code=status.HTTP_201_CREATED,
)
async def submit_review_report(
    assignment_id: int,
    body: ReviewSubmit,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
) -> ReviewReportResponse:
    """Reviewer submits the review report (terminal)."""
    a = await _get_assignment_for_reviewer(db, assignment_id, current_user.id)
    if a.submission is None or a.submission.submitted_by == current_user.id:
        raise HTTPException(status_code=403, detail="Cannot review own submission")
    if a.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Assignment must be 'accepted' to submit (currently '{a.status}')",
        )
    existing = (
        await db.execute(select(ReviewReport).where(ReviewReport.assignment_id == a.id))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A report has already been submitted for this assignment",
        )
    report = ReviewReport(
        tenant_id=current_user.tenant_id,
        assignment_id=a.id,
        recommendation=body.recommendation,
        scores=body.scores,
        comments_to_editor=body.comments_to_editor,
        comments_to_author=body.comments_to_author,
    )
    db.add(report)
    a.status = "completed"
    a.completed_at = utcnow()
    try:
        await db.flush()
        from app.modules.gamification import service as gamification

        await gamification.award(
            db, current_user, "review.completed", ref_type="assignment", ref_id=str(a.id)
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not submit report (concurrent change)",
        ) from exc
    await db.refresh(report)

    # 通知编辑分配者：审稿人提交了报告
    if a.assigned_by is not None:
        await notifications.create(
            db,
            tenant_id=current_user.tenant_id,
            user_id=a.assigned_by,
            type_="review.submitted",
            title=(
                f"审稿人提交了报告：{a.submission.title if a.submission else f'#{a.submission_id}'}"
            ),
            body=f"推荐：{body.recommendation}",
            related_type="review_assignment",
            related_id=str(a.id),
        )
        await db.commit()

    return ReviewReportResponse(
        id=report.id,
        assignment_id=report.assignment_id,
        recommendation=report.recommendation,
        scores=report.scores,
        comments_to_editor=report.comments_to_editor,
        comments_to_author=report.comments_to_author,
        submitted_at=report.submitted_at,
    )


# ============================================================================
# Editor-facing endpoints (P1：双人审稿闸门)
# ============================================================================

from pydantic import BaseModel, Field  # noqa: E402


class AssignReviewersBody(BaseModel):
    reviewer_ids: list[int] = Field(min_length=1, max_length=3)
    due_days: int = Field(default=14, ge=1, le=90)


class EditorDecisionBody(BaseModel):
    decision: str = Field(pattern="^(accept|reject|revise)$")
    reason: str = Field(default="", max_length=2000)


def _completed_reports_count(assignments: list[ReviewAssignment]) -> int:
    return sum(1 for a in assignments if a.status == "completed")


def _distinct_reviewers_completed(assignments: list[ReviewAssignment]) -> int:
    return len({a.reviewer_id for a in assignments if a.status == "completed"})


@router.post("/submissions/{submission_id}/assign", status_code=status.HTTP_201_CREATED)
async def assign_reviewers(
    submission_id: int,
    body: AssignReviewersBody,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """批量指派审稿人（slot 1/2/3）。禁止指派给稿件作者/共同作者。"""
    tenant_id = require_tenant_id()
    sub = (
        await db.execute(
            select(Submission).where(
                Submission.id == submission_id, Submission.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    # 校验：reviewer 不能是 submitted_by 或 authors 里的人
    author_ids = {sub.submitted_by}
    # authors 是 list[str]（姓名），无法直接映射到 user_id；这里只拦 submitted_by。
    # （共同作者绑定 user_id 是 P1 认领后的事，此处先拦第一作者。）
    for rid in body.reviewer_ids:
        if rid in author_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="禁止指派给稿件作者（自审）",
            )

    # 已有 assignments 中，pending/accepted 的占 slot
    existing = (
        await db.execute(
            select(ReviewAssignment).where(
                ReviewAssignment.submission_id == submission_id,
                ReviewAssignment.tenant_id == tenant_id,
                ReviewAssignment.status.in_(["pending", "accepted"]),
            )
        )
    ).scalars().all()
    used_slots = {a.slot for a in existing}
    next_slot = 1
    created = []
    for rid in body.reviewer_ids:
        # 跳过已存在的 assignment（同一 reviewer 重复邀请）
        dup = await db.execute(
            select(ReviewAssignment).where(
                ReviewAssignment.submission_id == submission_id,
                ReviewAssignment.reviewer_id == rid,
            )
        )
        if dup.scalar_one_or_none() is not None:
            continue
        while next_slot in used_slots:
            next_slot += 1
        used_slots.add(next_slot)
        due = utcnow() + __import__("datetime").timedelta(days=body.due_days)
        a = ReviewAssignment(
            tenant_id=tenant_id,
            submission_id=submission_id,
            reviewer_id=rid,
            assigned_by=current_user.id,
            status="pending",
            due_date=due,
            round=1,
            slot=next_slot,
        )
        db.add(a)
        created.append(a)

    await db.commit()
    return {"assigned": len(created), "submission_id": submission_id}


@router.get("/submissions/{submission_id}/matrix")
async def review_matrix(
    submission_id: int,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """审稿矩阵：每位审稿人状态/推荐/截止/超期/冲突。"""
    tenant_id = require_tenant_id()
    assignments = (
        await db.execute(
            select(ReviewAssignment)
            .where(
                ReviewAssignment.submission_id == submission_id,
                ReviewAssignment.tenant_id == tenant_id,
            )
            .options(selectinload(ReviewAssignment.report))
            .order_by(ReviewAssignment.slot)
        )
    ).scalars().all()

    now = utcnow()
    rows = []
    recommendations = []
    for a in assignments:
        status = a.status
        if a.due_date and a.status in ("pending", "accepted") and a.due_date < now:
            status = "overdue"
        rec = None
        if a.report:
            rec = a.report[0].recommendation if a.report else None
            recommendations.append(rec)
        # reviewer username
        u = await db.get(User, a.reviewer_id)
        rows.append({
            "reviewer_id": a.reviewer_id,
            "username": u.username if u else None,
            "slot": a.slot,
            "status": status,
            "recommendation": rec,
            "due_date": a.due_date.isoformat() if a.due_date else None,
            "is_overdue": status == "overdue",
            "is_adjudicator": a.is_adjudicator,
        })

    completed = _completed_reports_count(assignments)
    distinct = _distinct_reviewers_completed(assignments)
    # 冲突：有 accept 和 reject/major_revision 同时存在
    conflict = False
    if "accept" in recommendations and ("reject" in recommendations or "major_revision" in recommendations):
        conflict = True

    return {
        "submission_id": submission_id,
        "assignments": rows,
        "reports_completed": completed,
        "distinct_reviewers": distinct,
        "can_decide": distinct >= 2,
        "conflict": conflict,
    }


@router.post("/submissions/{submission_id}/decision")
async def editor_decision(
    submission_id: int,
    body: EditorDecisionBody,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """编辑决定：≥2 份 completed 报告（不同 reviewer）才允许，否则 409。"""
    tenant_id = require_tenant_id()
    sub = (
        await db.execute(
            select(Submission).where(
                Submission.id == submission_id, Submission.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    assignments = (
        await db.execute(
            select(ReviewAssignment).where(
                ReviewAssignment.submission_id == submission_id,
                ReviewAssignment.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    completed = _completed_reports_count(assignments)
    distinct = _distinct_reviewers_completed(assignments)
    if distinct < 2:
        missing = 2 - distinct
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"还差 {missing} 份审稿报告（已收 {completed}/2）",
        )

    # 写审计
    from app.models import AuditLog
    db.add(AuditLog(
        tenant_id=tenant_id,
        actor_user_id=current_user.id,
        action="review.editor_decision",
        target_type="submission",
        target_id=str(submission_id),
        payload={"decision": body.decision, "reason": body.reason},
    ))
    await db.commit()
    return {"submission_id": submission_id, "decision": body.decision, "reports_completed": completed}
