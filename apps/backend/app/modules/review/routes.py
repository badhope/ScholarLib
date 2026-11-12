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

import mimetypes
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    ROLE_REVIEWER,
    ROLE_SENIOR_REVIEWER,
    get_current_user,
    require_editor,
    require_reviewer,
    require_tenant_id,
    user_has_role,
)
from app.core.db import get_db, paginate
from app.core.storage import get_storage
from app.core.time import utcnow
from app.models import User
from app.modules.catalog.models import Resource
from app.modules.notifications import services as notifications
from app.modules.review.blinding import get_review_mode, reviewer_facing_payload
from app.modules.review.models import ReviewAssignment, ReviewReport
from app.modules.review.schemas import (
    AssignmentListResponse,
    AssignmentResponse,
    ReviewReportResponse,
    ReviewSubmit,
)
from app.modules.quality.rubric import RUBRIC_VERSION, DimensionScore, evaluate, dimensions_for
from app.modules.submission.models import Submission
from app.modules.submission.schemas import SubmissionResponse

router = APIRouter(prefix="/review", tags=["review"])

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _normalize_review_scores(scores: dict[str, Any]) -> dict[str, Any]:
    """校验并计算审稿评分：五维、逐维分数/理由/证据缺一不可。

    旧版报告里的自由结构（originality: 4）不再受理新提交：没有正文证据的
    分数无法复核，也会让“随手给高分”绕过口径。读取旧报告不受影响。
    """
    track = str(scores.get("track") or "academic")
    if track not in ("academic", "absurd"):
        raise HTTPException(status_code=422, detail="track must be 'academic' or 'absurd'")
    raw = scores.get("dimensions")
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=422,
            detail="评分必须按五维提交：scores.dimensions = {key: {score, reason, evidence}}",
        )
    required = [k for k, _, _ in dimensions_for(track)]
    missing = [k for k in required if k not in raw]
    if missing:
        raise HTTPException(status_code=422, detail=f"缺少维度评分：{', '.join(missing)}")
    parsed: list[DimensionScore] = []
    for key in required:
        item = raw.get(key)
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail=f"{key}: 维度评分必须是对象")
        try:
            score = int(item.get("score"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"{key}: score 必须是 0–100 整数") from exc
        if not 0 <= score <= 100:
            raise HTTPException(status_code=422, detail=f"{key}: score 必须在 0–100")
        reason = str(item.get("reason") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        # 分越高，证据门槛越高：90+ 是“顶刊范本”，不能用一句“写得不错”
        # 换一个高分。80+ 也要求能定位到正文位置，而不是泛泛而谈。
        if score >= 90:
            reason_min, evidence_min = 40, 60
            level = "90+ 顶刊级"
        elif score >= 80:
            reason_min, evidence_min = 15, 20
            level = "80+ 一区"
        else:
            reason_min, evidence_min = 4, 10
            level = "常规"
        if len(reason) < reason_min:
            raise HTTPException(
                status_code=422,
                detail=f"{key}: {level}评分理由至少 {reason_min} 字，当前 {len(reason)} 字",
            )
        if len(evidence) < evidence_min:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{key}: {level}正文证据至少 {evidence_min} 字，当前 {len(evidence)} 字；"
                    "需写清章节/段落/图号/表号/引用编号或可访问链接"
                ),
            )
        locator_hit = any(
            token in evidence
            for token in ("第", "§", "图", "表", "页", "段", "节", "引用", "文献", "附录", "http")
        )
        if not locator_hit:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{key}: 证据必须能定位到正文（例如“§3 第2段 / 图2 / 表1 / 参考文献[4]”），"
                    "不能只写主观印象"
                ),
            )
        parsed.append(DimensionScore(key=key, score=score, reason=reason, evidence=evidence))
    result = evaluate(parsed, track=track)
    return {
        "rubric_version": RUBRIC_VERSION,
        "track": track,
        "dimensions": {
            d.key: {
                "score": d.score,
                "reason": d.reason,
                "evidence": d.evidence,
                "label": result["breakdown"][d.key]["label"],  # type: ignore[index]
                "points": result["breakdown"][d.key]["points"],  # type: ignore[index]
            }
            for d in parsed
        },
        "score": result["score"],
        "uncapped_score": result["uncapped_score"],
        "cap": result["cap"],
        "cap_notes": result["cap_notes"],
        "grade": result["grade"],
        "grade_label": result["grade_label"],
        "quartile": result["quartile"],
        "complete": result["complete"],
        "incomplete_dimensions": result["incomplete_dimensions"],
        "completeness_note": result["completeness_note"],
        "editorial_completion_required": result["editorial_completion_required"],
        "completion_owner": result["completion_owner"],
        "rejected": result["rejected"],
        "integrity_veto": result["integrity_veto"],
    }


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
        report_id=a.report[0].id if a.report else None,
        attachments=(a.report[0].attachments or []) if a.report else [],
        round=a.round,
        slot=a.slot,
        is_adjudicator=a.is_adjudicator,
        is_external=a.is_external,
        external_affiliation=a.external_affiliation,
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
                selectinload(ReviewAssignment.report),
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
        .options(
            selectinload(ReviewAssignment.submission),
            selectinload(ReviewAssignment.report),
        )
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


_REVIEW_ATTACHMENT_MAX_BYTES = 50 * 1024 * 1024
_REVIEW_ATTACHMENT_EXTS = {
    ".pdf",
    ".docx",
    ".doc",
    ".md",
    ".txt",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".xlsx",
    ".csv",
}


def _report_response(report: ReviewReport) -> ReviewReportResponse:
    return ReviewReportResponse(
        id=report.id,
        assignment_id=report.assignment_id,
        recommendation=report.recommendation,
        scores=report.scores,
        comments_to_editor=report.comments_to_editor,
        comments_to_author=report.comments_to_author,
        attachments=report.attachments or [],
        submitted_at=report.submitted_at,
    )


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
    normalized_scores = _normalize_review_scores(body.scores)
    report = ReviewReport(
        tenant_id=current_user.tenant_id,
        assignment_id=a.id,
        recommendation=body.recommendation,
        scores=normalized_scores,
        comments_to_editor=body.comments_to_editor,
        comments_to_author=body.comments_to_author,
    )
    db.add(report)
    # 特别篇许可：审稿人在提交报告时可显式打标。只授予 true；撤标由编辑部
    # 走资源管理入口，避免一份普通审稿把既有特许误清掉。
    if body.special_issue and a.submission.resource_id:
        resource = (
            await db.execute(
                select(Resource).where(
                    Resource.id == a.submission.resource_id,
                    Resource.tenant_id == current_user.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if resource is not None:
            resource.is_special_issue = True
            resource.special_issue_reason = body.special_issue_reason or "审稿人确认篇幅特许"
            resource.special_issue_by = current_user.id
            resource.special_issue_at = utcnow()
    a.status = "completed"
    a.completed_at = utcnow()
    try:
        await db.flush()
        from app.modules.gamification import service as gamification

        await gamification.award(
            db, current_user, "review.completed", ref_type="assignment", ref_id=str(a.id)
        )
        # 等级轴：审稿人身份 +1（R 等级按完成审稿份数计）。幂等。
        from app.modules.gamification import levels_axis

        await levels_axis.award_points(
            db,
            current_user,
            "review.completed",
            ref_type="assignment",
            ref_id=str(a.id),
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

    return _report_response(report)


@router.post(
    "/reports/{report_id}/attachments",
    response_model=ReviewReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_review_attachment(
    report_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
) -> ReviewReportResponse:
    """审稿人上传批注件/补充材料。报告提交后仍可补传。"""
    report = (
        await db.execute(
            select(ReviewReport)
            .join(ReviewAssignment, ReviewAssignment.id == ReviewReport.assignment_id)
            .where(
                ReviewReport.id == report_id,
                ReviewReport.tenant_id == current_user.tenant_id,
                ReviewAssignment.reviewer_id == current_user.id,
            )
            .options(selectinload(ReviewReport.assignment))
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Review report not found")

    original_name = file.filename or "attachment"
    suffix = Path(original_name).suffix.lower()
    if suffix not in _REVIEW_ATTACHMENT_EXTS:
        raise HTTPException(
            status_code=400,
            detail="附件仅支持 PDF / Word / Markdown / 图片 / ZIP / Excel / CSV",
        )
    contents = await file.read()
    if len(contents) > _REVIEW_ATTACHMENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="附件不能超过 50 MB")
    if not contents:
        raise HTTPException(status_code=400, detail="附件为空")

    key = f"{current_user.tenant_id}/review/{report.id}/{uuid4().hex}{suffix}"
    stored_type = (
        file.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    )
    await get_storage().save(key, contents, content_type=stored_type)
    items = list(report.attachments or [])
    if len(items) >= 5:
        raise HTTPException(status_code=400, detail="每份审稿报告最多上传 5 个附件")
    items.append(
        {
            "filename": original_name,
            "path": key,
            "content_type": stored_type,
            "size": len(contents),
        }
    )
    report.attachments = items
    await db.commit()
    await db.refresh(report)
    return _report_response(report)


@router.get("/reports/{report_id}/attachments/{attachment_index}")
async def download_review_attachment(
    report_id: int,
    attachment_index: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """审稿人本人、编辑、管理员可下载批注附件；作者不可下载。"""
    report = (
        await db.execute(
            select(ReviewReport)
            .where(
                ReviewReport.id == report_id,
                ReviewReport.tenant_id == current_user.tenant_id,
            )
            .options(selectinload(ReviewReport.assignment))
        )
    ).scalar_one_or_none()
    if report is None or report.assignment is None:
        raise HTTPException(status_code=404, detail="Review report not found")
    allowed = report.assignment.reviewer_id == current_user.id
    if not allowed:
        allowed = bool(getattr(current_user, "is_admin", False)) or await user_has_role(
            db, current_user, "editor"
        )
    if not allowed:
        raise HTTPException(status_code=403, detail="没有权限下载该审稿附件")
    items = list(report.attachments or [])
    if attachment_index < 0 or attachment_index >= len(items):
        raise HTTPException(status_code=404, detail="Attachment not found")
    item = items[attachment_index]
    data = await get_storage().load(str(item["path"]))
    filename = str(item.get("filename") or "attachment")
    media_type = str(item.get("content_type") or "application/octet-stream")
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


# ============================================================================
# Editor-facing endpoints (P1：双人审稿闸门)
# ============================================================================

from pydantic import BaseModel, Field  # noqa: E402


class AssignReviewersBody(BaseModel):
    reviewer_ids: list[int] = Field(min_length=1, max_length=3)
    due_days: int = Field(default=14, ge=1, le=90)
    # 主编指定的外审专家：只记录邀请性质，不另建账号。
    is_external: bool = False
    external_affiliation: str | None = Field(default=None, max_length=120)


class AdjudicateBody(BaseModel):
    reviewer_id: int = Field(ge=1)
    due_days: int = Field(default=14, ge=1, le=90)
    reason: str = Field(default="", max_length=2000)


class EditorDecisionBody(BaseModel):
    decision: str = Field(pattern="^(accept|reject|revise)$")
    reason: str = Field(default="", max_length=2000)


def _completed_reports_count(assignments: list[ReviewAssignment]) -> int:
    return sum(1 for a in assignments if a.status == "completed")


def _distinct_reviewers_completed(assignments: Sequence[ReviewAssignment]) -> int:
    return len({a.reviewer_id for a in assignments if a.status == "completed"})


@router.post("/submissions/{submission_id}/assign", status_code=status.HTTP_201_CREATED)
async def assign_reviewers(
    submission_id: int,
    body: AssignReviewersBody,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
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

    existing_all = (
        (
            await db.execute(
                select(ReviewAssignment).where(
                    ReviewAssignment.submission_id == submission_id,
                    ReviewAssignment.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    # 轮次：上一轮还有 pending/accepted/completed 的，继续同一轮；
    # 全部 cancelled/declined（作者已重投）才进入下一轮。
    _rounds = [a.round or 1 for a in existing_all]
    _last_round = max(_rounds) if _rounds else 1
    _last_rows = [a for a in existing_all if (a.round or 1) == _last_round]
    if _last_rows and all(a.status in ("cancelled", "declined") for a in _last_rows):
        round_no = _last_round + 1
    else:
        round_no = _last_round
    existing = [
        a
        for a in existing_all
        if (a.round or 1) == round_no and a.status in ("pending", "accepted")
    ]
    used_slots = {a.slot for a in existing}
    next_slot = 1
    created = []
    for rid in body.reviewer_ids:
        reviewer = await db.get(User, rid)
        if reviewer is None or not reviewer.is_active:
            raise HTTPException(status_code=400, detail=f"Reviewer {rid} not found or inactive")
        if not (
            await user_has_role(db, reviewer, ROLE_REVIEWER)
            or await user_has_role(db, reviewer, ROLE_SENIOR_REVIEWER)
        ):
            raise HTTPException(status_code=422, detail=f"User {rid} is not a reviewer")
        # 同一轮内已邀请过的不重复；旧轮 cancelled/declined 不拦新一轮
        dup = await db.execute(
            select(ReviewAssignment).where(
                ReviewAssignment.submission_id == submission_id,
                ReviewAssignment.reviewer_id == rid,
                ReviewAssignment.round == round_no,
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
            round=round_no,
            slot=next_slot,
            is_external=body.is_external,
            external_affiliation=(body.external_affiliation or "").strip() or None,
        )
        db.add(a)
        created.append(a)

    if sub.status == "pending" and created:
        sub.status = "under_review"
    await db.flush()
    for a in created:
        reviewer = await db.get(User, a.reviewer_id)
        if reviewer is not None:
            await notifications.create(
                db,
                tenant_id=tenant_id,
                user_id=a.reviewer_id,
                type_="review.invited",
                title=f"您被邀请审稿：{sub.title}",
                body=(
                    f"稿件 #{sub.id} 已分配给您，截止 {(a.due_date.date().isoformat() if a.due_date else '—')}，"
                    "请前往审稿工作台回应。" + ("（外审专家邀请）" if a.is_external else "")
                ),
                related_type="review_assignment",
                related_id=str(a.id),
            )
    await db.commit()
    return {"assigned": len(created), "submission_id": submission_id}


@router.get("/submissions/{submission_id}/matrix")
async def review_matrix(
    submission_id: int,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """审稿矩阵：每位审稿人状态/推荐/截止/超期/冲突。"""
    tenant_id = require_tenant_id()
    assignments = (
        (
            await db.execute(
                select(ReviewAssignment)
                .where(
                    ReviewAssignment.submission_id == submission_id,
                    ReviewAssignment.tenant_id == tenant_id,
                )
                .options(selectinload(ReviewAssignment.report))
                .order_by(ReviewAssignment.slot)
            )
        )
        .scalars()
        .all()
    )

    current_round = max((a.round or 1) for a in assignments) if assignments else 1
    # 只统计当前轮；旧轮报告保留展示但不计入闸门，避免重投后拿旧意见放行。
    current = [a for a in assignments if (a.round or 1) == current_round]
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
        rows.append(
            {
                "reviewer_id": a.reviewer_id,
                "username": u.username if u else None,
                "slot": a.slot,
                "status": status,
                "recommendation": rec,
                "due_date": a.due_date.isoformat() if a.due_date else None,
                "is_overdue": status == "overdue",
                "is_adjudicator": a.is_adjudicator,
                "is_external": bool(getattr(a, "is_external", False)),
                "external_affiliation": getattr(a, "external_affiliation", None),
                "round": a.round,
                "is_current": (a.round or 1) == current_round,
            }
        )

    completed = _completed_reports_count(current)
    distinct = _distinct_reviewers_completed(current)
    accept_count = sum(1 for rec in recommendations if rec == "accept")
    reject_count = sum(1 for rec in recommendations if rec == "reject")
    major_count = sum(1 for rec in recommendations if rec == "major_revision")
    # 冲突：有录用推荐，同时有拒稿/大修；或两份意见方向完全相反。
    conflict = accept_count > 0 and (reject_count > 0 or major_count > 0)
    adjudicator_rows = [a for a in current if a.is_adjudicator]
    adjudicator_accepted = any(
        a.status == "completed" and a.report and a.report[0].recommendation == "accept"
        for a in adjudicator_rows
    )
    need_adjudication = bool(conflict and not adjudicator_accepted)

    return {
        "submission_id": submission_id,
        "assignments": rows,
        "reports_completed": completed,
        "distinct_reviewers": distinct,
        "accept_count": accept_count,
        "reject_count": reject_count,
        "major_revision_count": major_count,
        "can_decide": accept_count >= 2 and (not conflict or adjudicator_accepted),
        "conflict": conflict,
        "need_adjudication": need_adjudication,
        "adjudicator_assigned": bool(adjudicator_rows),
        "adjudicator_accepted": adjudicator_accepted,
    }


@router.post("/submissions/{submission_id}/adjudicate", status_code=status.HTTP_201_CREATED)
async def assign_adjudicator(
    submission_id: int,
    body: AdjudicateBody,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """复议：主编/编辑指定第三方裁决人，对冲突意见做独立裁决。

    只在已有至少 2 份 completed 报告时才允许发起；裁决人不能是作者，
    也不能已经参与过同一稿件的评审。裁决意见同样通过
    POST /review/assignments/{id}/submit 提交，recommendation 为 accept
    时，最终录用闸门才放行。
    """
    from datetime import timedelta

    from app.api.deps import ROLE_REVIEWER, ROLE_SENIOR_REVIEWER
    from app.models import AuditLog

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
    if sub.status not in ("pending", "under_review", "resubmitted"):
        raise HTTPException(status_code=400, detail=f"Cannot adjudicate in status '{sub.status}'")
    if body.reviewer_id == sub.submitted_by:
        raise HTTPException(status_code=403, detail="Cannot assign author as adjudicator")
    reviewer = (
        await db.execute(
            select(User).where(
                User.id == body.reviewer_id,
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if reviewer is None:
        raise HTTPException(status_code=400, detail="Reviewer not found or inactive")
    if not (
        await user_has_role(db, reviewer, ROLE_REVIEWER)
        or await user_has_role(db, reviewer, ROLE_SENIOR_REVIEWER)
    ):
        raise HTTPException(status_code=422, detail="Assigned user is not a reviewer")

    assignments = (
        (
            await db.execute(
                select(ReviewAssignment)
                .where(
                    ReviewAssignment.submission_id == submission_id,
                    ReviewAssignment.tenant_id == tenant_id,
                )
                .options(selectinload(ReviewAssignment.report))
                .order_by(ReviewAssignment.slot)
            )
        )
        .scalars()
        .all()
    )
    current_round = max((a.round or 1) for a in assignments) if assignments else 1
    current = [a for a in assignments if (a.round or 1) == current_round]
    distinct = _distinct_reviewers_completed(current)
    if distinct < 2:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "adjudication_requires_two_reviews",
                "message": f"第三方裁决前至少需要 2 位不同审稿人提交意见（当前 {distinct}/2）。",
                "distinct_reviewers": distinct,
            },
        )
    if any(a.reviewer_id == body.reviewer_id for a in assignments):
        raise HTTPException(status_code=409, detail="该审稿人已参与本稿评审，不能兼任第三方裁决人")

    due = utcnow() + timedelta(days=body.due_days)
    slot = max((a.slot or 0) for a in assignments) + 1
    # 裁决人与被裁决的意见必须同轮，否则矩阵当前轮只剩裁决人一份，
    # 录用闸门反而永远过不了。
    round_no = current_round
    a = ReviewAssignment(
        tenant_id=tenant_id,
        submission_id=submission_id,
        reviewer_id=body.reviewer_id,
        assigned_by=current_user.id,
        status="pending",
        due_date=due,
        round=round_no,
        slot=slot,
        is_adjudicator=True,
    )
    db.add(a)
    await db.flush()
    await notifications.create(
        db,
        tenant_id=tenant_id,
        user_id=body.reviewer_id,
        type_="review.adjudicator_invited",
        title=f"第三方裁决邀请：{sub.title}",
        body=(
            f"稿件 #{sub.id} 的审稿意见存在分歧，现邀请您作为第三方裁决人。"
            f"截止 {due.date().isoformat()}。" + (f" 说明：{body.reason}" if body.reason else "")
        ),
        related_type="review_assignment",
        related_id=str(a.id),
    )
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            action="review.adjudicator_assigned",
            target_type="submission",
            target_id=str(submission_id),
            payload={"reviewer_id": body.reviewer_id, "assignment_id": a.id, "reason": body.reason},
        )
    )
    await db.commit()
    return {
        "submission_id": submission_id,
        "assignment_id": a.id,
        "reviewer_id": body.reviewer_id,
        "due_date": due.isoformat(),
        "is_adjudicator": True,
    }


@router.post("/submissions/{submission_id}/decision")
async def editor_decision(
    submission_id: int,
    body: EditorDecisionBody,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """已废弃：最终裁决统一走 PATCH /submissions/{id}/decision。

    旧端点只写 AuditLog、不改业务状态，和投稿模块的真裁决端点形成两套
    互相矛盾的规则。保留路径是为了让旧客户端拿到明确指引，而不是静默
    记一条"已决定"却什么都没发生。
    """
    tenant_id = require_tenant_id()
    assignments = (
        (
            await db.execute(
                select(ReviewAssignment).where(
                    ReviewAssignment.submission_id == submission_id,
                    ReviewAssignment.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    distinct = _distinct_reviewers_completed(assignments)
    if distinct < 2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"还差 {2 - distinct} 份审稿报告（已收 {distinct}/2）",
        )
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "deprecated_use_submission_decision",
            "message": "最终裁决请使用 PATCH /api/submissions/{id}/decision（主编/执行编辑权限）。",
        },
    )
