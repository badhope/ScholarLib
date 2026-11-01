"""Submission API routes — 编辑与审稿侧（送审 / 分配 / 报告 / 裁决 / 匿名稿）。

从 routes.py（52KB 单文件）拆出。router 来自 routes.py，本模块在其上
追加端点；注册顺序见 routes.py 文件末尾的底部 import。
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    ROLE_EDITOR,
    ROLE_REVIEWER,
    ROLE_SENIOR_REVIEWER,
    get_current_user,
    require_admin,
    require_chief_editor,
    require_editor,
    require_tenant_id,
    user_has_role,
)
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.schemas import PaginationMeta
from app.core.time import utcnow
from app.models import AuditLog, Role, User, UserRole
from app.modules.catalog.models import Resource
from app.modules.notifications import services as notifications
from app.modules.review.models import ReviewAssignment, ReviewReport
from app.modules.review.schemas import (
    AssignmentCreate,
    AssignmentListResponse,
    AssignmentResponse,
    ReviewReportResponse,
)
from app.modules.submission._helpers import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    _get_or_404,
    _list_submissions,
    _materialize_resource_from_submission,
    _to_response,
)
from app.modules.submission.models import Submission
from app.modules.submission.routes import router
from app.modules.submission.schemas import (
    AnonymizedFileUpdate,
    MessageResponse,
    ReviewerCandidate,
    ReviewerCandidateListResponse,
    SubmissionDecision,
    SubmissionListResponse,
    SubmissionResponse,
    SubmissionReview,
)

logger = get_logger("rubbish.submission.editor")


@router.get("/pending", response_model=SubmissionListResponse)
async def list_pending_submissions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    _: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> SubmissionListResponse:
    """List pending submissions awaiting review (editor+).

    包含 pending（待分配审稿人）与 under_review（已分配审稿人但未出决定）。
    """
    tenant_id = require_tenant_id()
    query = select(Submission).where(
        Submission.status.in_(("pending", "under_review")),
        Submission.tenant_id == tenant_id,
    )
    return await _list_submissions(db, query, page, page_size)


@router.get("/reviewer-candidates", response_model=ReviewerCandidateListResponse)
async def list_reviewer_candidates(
    limit: int = Query(default=200, ge=1, le=200),
    _: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> ReviewerCandidateListResponse:
    """可被指派的审稿人（持 reviewer / senior_reviewer 角色且账号启用）。

    供编辑工作台的下拉使用：之前走 /admin/users，非 admin 的 editor
    会拿到 403，导致「没有可指派的审稿人」。此端点只暴露分配所需的最小
    字段（id / username / email），且同样要求 editor 权限。L6 资深审稿人
    与 L5 共用候选池（与 require_reviewer 同口径）。
    """
    tenant_id = require_tenant_id()
    rows = (
        await db.execute(
            select(User.id, User.username, User.email)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
                UserRole.tenant_id == tenant_id,
                Role.tenant_id == tenant_id,
                Role.name.in_([ROLE_REVIEWER, ROLE_SENIOR_REVIEWER]),
            )
            .order_by(User.username.asc())
            .limit(limit)
        )
    ).all()
    return ReviewerCandidateListResponse(
        data=[ReviewerCandidate(id=row.id, username=row.username, email=row.email) for row in rows]
    )


@router.get("", response_model=SubmissionListResponse)
async def list_submissions(
    status_filter: str = Query(
        default=None,
        alias="status",
        pattern=r"^(pending|under_review|major_revision|minor_revision|resubmitted|accepted|approved|rejected)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    _: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> SubmissionListResponse:
    """List all submissions in the tenant (editor+)."""
    tenant_id = require_tenant_id()
    query = select(Submission).where(Submission.tenant_id == tenant_id)
    if status_filter is not None:
        query = query.where(Submission.status == status_filter)
    return await _list_submissions(db, query, page, page_size)


@router.patch(
    "/{submission_id}/review",
    response_model=SubmissionResponse,
)
async def review_submission(
    submission_id: int,
    body: SubmissionReview,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """Approve or reject a pending submission (admin only).

    Terminal: once reviewed, a submission cannot be re-reviewed.
    """
    entry = await _get_or_404(db, submission_id)
    if entry.submitted_by == current_user.id:
        raise HTTPException(status_code=403, detail="Cannot review own submission")
    if entry.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Submission has already been reviewed",
        )

    now = utcnow()
    entry.status = body.status
    entry.admin_note = body.admin_note
    entry.reviewed_by = current_user.id
    entry.reviewed_at = now

    if body.status == "approved":
        if body.resource_id is not None:
            # Link to existing catalog Resource — must exist in this tenant.
            existing = (
                await db.execute(
                    select(Resource).where(
                        Resource.id == body.resource_id,
                        Resource.tenant_id == current_user.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Provided resource_id does not exist",
                )
            entry.resource_id = existing.id
        else:
            # Materialize a new catalog Resource from the submission payload.
            new_resource = await _materialize_resource_from_submission(db, entry)
            entry.resource_id = new_resource.id

    # Audit: reviewer's approve/reject decision is a destructive state
    # transition (terminal). Log actor + outcome so the trail survives
    # even if the submission row is later purged. Written in the SAME
    # transaction as the state change (before commit) per S-3.
    db.add(
        AuditLog(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            action="submission.review",
            target_type="submission",
            target_id=str(entry.id),
            payload={
                "status": entry.status,
                "resource_id": entry.resource_id,
                "admin_note_present": bool(entry.admin_note),
            },
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission could not be reviewed (concurrent update)",
        ) from exc
    await db.refresh(entry)
    return _to_response(entry)


@router.post(
    "/{submission_id}/assignments",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_reviewer(
    submission_id: int,
    body: AssignmentCreate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> AssignmentResponse:
    """编辑分配审稿人。submission 必须处于 pending / under_review / resubmitted。

    分配后 submission 自动从 pending → under_review（仅 pending 时）。
    """
    entry = await _get_or_404(db, submission_id)
    if entry.status not in ("pending", "under_review", "resubmitted"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot assign reviewer in status '{entry.status}'",
        )
    if current_user.id == entry.submitted_by:
        raise HTTPException(status_code=403, detail="Cannot assign reviewers to own submission")
    if body.reviewer_id == entry.submitted_by:
        raise HTTPException(status_code=403, detail="Cannot assign author as reviewer")
    # 审稿人必须存在且属于当前租户
    reviewer = (
        await db.execute(
            select(User).where(
                User.id == body.reviewer_id,
                User.tenant_id == entry.tenant_id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if reviewer is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reviewer not found or inactive",
        )
    # 被指派者必须持有 reviewer / senior_reviewer 角色；否则该用户在所有
    # /review 端点都会卡死（require_reviewer 直接 403），分配毫无意义。
    # L6 资深审稿人与 L5 共用同一个评审端点与候选池，这里必须同口径，
    # 否则候选下拉里能选到、点下去却 422。
    if not (
        await user_has_role(db, reviewer, ROLE_REVIEWER)
        or await user_has_role(db, reviewer, ROLE_SENIOR_REVIEWER)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Assigned user is not a reviewer",
        )
    assignment = ReviewAssignment(
        tenant_id=entry.tenant_id,
        submission_id=entry.id,
        reviewer_id=reviewer.id,
        assigned_by=current_user.id,
        status="pending",
        due_date=body.due_date,
    )
    try:
        db.add(assignment)
        if entry.status == "pending":
            entry.status = "under_review"
        # 先 flush：重复分配会在此触发唯一约束（而非在 notifications/commit
        # 内部，那样会绕过下面的 409 处理），同时让 assignment.id 可用于通知。
        await db.flush()
        # 通知审稿人（与状态变更同事务，遵循 S-3：通知/审计并入主事务）
        await notifications.create(
            db,
            tenant_id=entry.tenant_id,
            user_id=reviewer.id,
            type_="review.invited",
            title=f"您被邀请审稿：{entry.title}",
            body=f"Submission #{entry.id} 已分配给您，请前往审稿工作台回应。",
            related_type="review_assignment",
            related_id=str(assignment.id),
        )
        # S-3：审计写入并入主事务（commit 前 add）。
        db.add(
            AuditLog(
                tenant_id=current_user.tenant_id,
                actor_user_id=current_user.id,
                action="submission.assign_reviewer",
                target_type="submission",
                target_id=str(entry.id),
                payload={
                    "reviewer_id": reviewer.id,
                    "assignment_id": assignment.id,
                },
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reviewer already assigned or concurrent update",
        ) from exc
    await db.refresh(assignment)
    # 邮件通知审稿人（best-effort：未配置 SMTP 时静默跳过，不影响指派）
    from app.modules.submission.review_reminders import send_assignment_email

    await send_assignment_email(reviewer, submission_title=entry.title, assignment_id=assignment.id)
    return AssignmentResponse(
        id=assignment.id,
        submission_id=assignment.submission_id,
        reviewer_id=assignment.reviewer_id,
        assigned_by=assignment.assigned_by,
        status=assignment.status,
        due_date=assignment.due_date,
        invited_at=assignment.invited_at,
        responded_at=assignment.responded_at,
        completed_at=assignment.completed_at,
        reviewer_username=reviewer.username,
        submission_title=entry.title,
        last_reminded_at=assignment.last_reminded_at,
        reminder_count=assignment.reminder_count,
    )


@router.get(
    "/{submission_id}/assignments",
    response_model=AssignmentListResponse,
)
async def list_assignments(
    submission_id: int,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> AssignmentListResponse:
    """列出 submission 的所有审稿分配（编辑视角，含审稿人身份）。"""
    entry = await _get_or_404(db, submission_id)
    if entry.submitted_by == current_user.id:
        raise HTTPException(status_code=403, detail="Cannot manage own submission reviews")
    rows = (
        (
            await db.execute(
                select(ReviewAssignment)
                .where(
                    ReviewAssignment.submission_id == entry.id,
                    ReviewAssignment.tenant_id == entry.tenant_id,
                )
                .options(
                    selectinload(ReviewAssignment.reviewer),
                    selectinload(ReviewAssignment.submission),
                )
                .order_by(ReviewAssignment.invited_at.desc())
            )
        )
        .scalars()
        .all()
    )

    total = len(rows)
    page_size = total or 1
    return AssignmentListResponse(
        data=[
            AssignmentResponse(
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
                submission_title=entry.title,
                last_reminded_at=a.last_reminded_at,
                reminder_count=a.reminder_count,
            )
            for a in rows
        ],
        meta=PaginationMeta(total=total, page=1, page_size=page_size, total_pages=1),
    )


@router.delete(
    "/{submission_id}/assignments/{assignment_id}",
    response_model=MessageResponse,
)
async def cancel_assignment(
    submission_id: int,
    assignment_id: int,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """编辑撤销审稿人邀请。已 completed 的不可撤销（保留审稿历史）。"""
    entry = await _get_or_404(db, submission_id)
    if entry.submitted_by == current_user.id:
        raise HTTPException(status_code=403, detail="Cannot manage own submission reviews")
    a = (
        await db.execute(
            select(ReviewAssignment).where(
                ReviewAssignment.id == assignment_id,
                ReviewAssignment.submission_id == entry.id,
                ReviewAssignment.tenant_id == entry.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if a is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found",
        )
    if a.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel a completed assignment (review report exists)",
        )
    a.status = "cancelled"
    # S-3：审计写入并入主事务（commit 前 add）。
    db.add(
        AuditLog(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            action="submission.cancel_reviewer",
            target_type="submission",
            target_id=str(entry.id),
            payload={"assignment_id": a.id, "reviewer_id": a.reviewer_id},
        )
    )
    await db.commit()
    return MessageResponse(message="Assignment cancelled")


@router.get(
    "/{submission_id}/reports",
    response_model=list[ReviewReportResponse],
)
async def list_review_reports(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReviewReportResponse]:
    """列出 submission 的所有审稿报告。

    - 编辑（admin/editor）：看完整报告（含 editor-only comments）
    - 作者：只看 comments_to_author（单盲：不暴露审稿人身份）
    - 审稿人自己：看自己的报告
    """
    entry = await _get_or_404(db, submission_id)
    # 单盲：编辑（admin 或有 editor 角色）看完整报告；
    # 作者只看 comments_to_author；被指派审稿人可看自己评审的稿件报告
    # （含自己写的 editor-only comments）。无上述身份者 403。
    is_editor = current_user.is_admin or await user_has_role(db, current_user, ROLE_EDITOR)
    is_author = entry.submitted_by == current_user.id
    is_reviewer = False
    if not is_editor and not is_author:
        assignment = (
            await db.execute(
                select(ReviewAssignment).where(
                    ReviewAssignment.submission_id == entry.id,
                    ReviewAssignment.reviewer_id == current_user.id,
                    ReviewAssignment.status.in_(("pending", "accepted", "completed")),
                )
            )
        ).scalar_one_or_none()
        is_reviewer = assignment is not None
        if not is_reviewer:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

    rows = (
        await db.execute(
            select(ReviewReport, ReviewAssignment.reviewer_id)
            .join(ReviewAssignment, ReviewReport.assignment_id == ReviewAssignment.id)
            .where(
                ReviewAssignment.submission_id == entry.id,
                ReviewReport.tenant_id == entry.tenant_id,
                ReviewAssignment.status == "completed",
            )
        )
    ).all()

    out: list[ReviewReportResponse] = []
    for r, reviewer_id in rows:
        # 审稿人（非编辑非作者）：只能看**自己**那一份报告。
        # 修复前的代码让任何有 assignment 的人落进 else 分支，把该稿件全部
        # 已完成报告的 comments_to_editor（编辑机密）原样返回——甚至包括
        # 只是被邀请、尚未接受邀请的审稿人。编辑机密改为显式白名单。
        if is_reviewer and not is_editor and not is_author:
            if reviewer_id != current_user.id:
                continue
        # 作者：剥离 editor-only comments
        if is_author:
            out.append(
                ReviewReportResponse(
                    id=r.id,
                    assignment_id=r.assignment_id,
                    recommendation=r.recommendation,
                    scores=r.scores,
                    comments_to_editor=None,
                    comments_to_author=r.comments_to_author,
                    submitted_at=r.submitted_at,
                )
            )
        else:
            out.append(
                ReviewReportResponse(
                    id=r.id,
                    assignment_id=r.assignment_id,
                    recommendation=r.recommendation,
                    scores=r.scores,
                    comments_to_editor=r.comments_to_editor,
                    comments_to_author=r.comments_to_author,
                    submitted_at=r.submitted_at,
                )
            )
    return out


@router.patch(
    "/{submission_id}/decision",
    response_model=SubmissionResponse,
)
async def editor_decision(
    submission_id: int,
    body: SubmissionDecision,
    current_user: User = Depends(require_chief_editor),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """编辑最终决定（4 元）。

    accept: 自动物化 catalog Resource（除非 resource_id 指定现有资源），
            submission.status = 'accepted'。默认录用即刊（published）；
            body.publication_status='draft' 时暂存为草稿，进入刊前整理
            阶段（编辑/作者可预览，admin 刊出）。
    minor_revision / major_revision: status = 对应值，等作者 resubmit
    reject: status = 'rejected'（终态）

    approved / rejected 是旧 review 端点的别名，等价于 accept / reject。

    权限：仅 L8 执行编辑 / L9 主编（require_chief_editor）。L7 栏目编辑
    按分工只有初审、送审与推荐权，无最终裁决权。
    """
    entry = await _get_or_404(db, submission_id)
    # 仅 pending / under_review / resubmitted 可决断
    if entry.status not in ("pending", "under_review", "resubmitted"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot decide in status '{entry.status}'",
        )

    if entry.submitted_by == current_user.id:
        raise HTTPException(status_code=403, detail="Cannot decide own submission")

    decision = body.decision
    # 旧别名归一化
    if decision == "approved":
        decision = "accept"
    elif decision == "rejected":
        decision = "reject"

    now = utcnow()
    entry.editor_note = body.editor_note
    entry.reviewed_by = current_user.id
    entry.reviewed_at = now

    if decision == "accept":
        if body.resource_id is not None:
            existing = (
                await db.execute(
                    select(Resource).where(
                        Resource.id == body.resource_id,
                        Resource.tenant_id == entry.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Provided resource_id does not exist",
                )
            entry.resource_id = existing.id
        else:
            new_resource = await _materialize_resource_from_submission(
                db, entry, publication_status=body.publication_status
            )
            entry.resource_id = new_resource.id
        entry.status = "accepted"
    elif decision in ("major_revision", "minor_revision"):
        entry.status = decision
    elif decision == "reject":
        entry.status = "rejected"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown decision: {decision}",
        )

    # 积分结算：作者侧（录用 60 / 拒稿 5）+ 编辑侧（每次裁决 8）。
    # 与业务同一事务，决策失败不会留下孤立积分。
    from app.modules.gamification import service as gamification

    author = (
        await db.execute(select(User).where(User.id == entry.submitted_by))
    ).scalar_one_or_none()
    if author is not None:
        await gamification.award(
            db,
            author,
            "submission.accepted" if decision == "accept" else "submission.rejected",
            ref_type="submission",
            ref_id=str(entry.id),
        )
    await gamification.award(
        db,
        current_user,
        "editor.decision",
        ref_type="submission",
        ref_id=str(entry.id),
    )

    # 通知作者。录用时 related 指向物化出的公开目录条目而非 submission，
    # 作者点通知即可直达自己已发表的文章（目录详情页对访客也公开）。
    decision_labels = {
        "accept": "录用",
        "reject": "拒稿",
        "minor_revision": "小修",
        "major_revision": "大修",
    }
    accepted = decision == "accept" and entry.resource_id is not None
    await notifications.create(
        db,
        tenant_id=entry.tenant_id,
        user_id=entry.submitted_by,
        type_="submission.decision",
        title=f"稿件决定通知：{entry.title}",
        body=(
            f"您的稿件 #{entry.id} 收到编辑决定：{decision_labels.get(decision, decision)}。"
            + (f" 编辑备注：{body.editor_note}" if body.editor_note else "")
            + ("（文章已收录进公开目录，点击查看发表页面）" if accepted else "")
        ),
        related_type="resource" if accepted else "submission",
        related_id=str(entry.resource_id) if accepted else str(entry.id),
    )
    # S-3：审计写入并入主事务（commit 前 add）。
    db.add(
        AuditLog(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            action="submission.decision",
            target_type="submission",
            target_id=str(entry.id),
            payload={
                "decision": decision,
                "resource_id": entry.resource_id,
                "editor_note_present": bool(body.editor_note),
            },
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not apply decision (concurrent update)",
        ) from exc
    await db.refresh(entry)
    # 裁决邮件通知作者（best-effort；未配置 SMTP 时静默跳过）
    try:
        author = (
            await db.execute(select(User).where(User.id == entry.submitted_by))
        ).scalar_one_or_none()
        if author is not None:
            from app.modules.submission.review_reminders import send_decision_email

            await send_decision_email(
                author,
                submission_title=entry.title,
                decision=decision,
                note=body.editor_note,
            )
    except Exception:
        logger.warning("decision_email_dispatch_failed", submission_id=entry.id, exc_info=True)
    return _to_response(entry)


@router.put(
    "/{submission_id}/anonymized-file",
    response_model=SubmissionResponse,
)
async def set_anonymized_file(
    submission_id: int,
    body: AnonymizedFileUpdate,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """编辑设置/清除双盲评审用的匿名稿外链。

    背景（双盲绕过修复）：``download_url`` / ``external_url`` 都是**作者
    可控**字段（创建端点与作者编辑端点均可写）。双盲下若把审稿人放行到
    这些链接，作者填一条带身份的 URL 即可直穿双盲。因此审稿人视角只认
    本端点写入的 ``anonymized_file_url``。

    传 ``null`` 清除（例如作者补充了合规的匿名稿链接后不再需要）。
    """
    entry = await _get_or_404(db, submission_id)
    if entry.submitted_by == current_user.id:
        raise HTTPException(status_code=403, detail="Cannot manage own submission reviews")

    url = str(body.anonymized_file_url) if body.anonymized_file_url else None
    if url is not None and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="anonymized_file_url must be an http(s) URL",
        )

    entry.anonymized_file_url = url
    db.add(
        AuditLog(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            action="submission.anonymized_file",
            target_type="submission",
            target_id=str(entry.id),
            payload={"set": url is not None},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not update anonymized file URL (concurrent change)",
        ) from exc
    await db.refresh(entry)
    return _to_response(entry)
