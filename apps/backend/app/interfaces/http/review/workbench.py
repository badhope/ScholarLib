# mypy: ignore-errors
"""Separate workbenches: reviewer vs editor-in-chief / section editor.

The two workbenches are intentionally *not* the same list component:

- **Reviewer workbench** (``GET /review/workbench``): only two columns —
  ``待审`` (pending/accepted) and ``已审`` (completed). No assign actions,
  no editor queue. Each row carries a human due-date countdown and an
  overdue flag.

- **Editor workbench** (``GET /editor/workbench``): a four-stage
  pipeline ``待指派 → 评审中 → 待裁决 → 已决定`` with per-column
  counts, plus batch-assign / conflict-check / manual-remind endpoints.

Routing is split so a reviewer can never reach the editor queue by
accident (``require_reviewer`` vs ``require_editor`` on separate paths).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    ROLE_REVIEWER,
    ROLE_SENIOR_REVIEWER,
    require_editor,
    require_reviewer,
    require_tenant_id,
    user_has_role,
)
from app.core.db import get_db
from app.core.time import utcnow
from app.domain.notifications import services as notifications
from app.domain.notifications.models import EmailDigestRecord
from app.domain.review.models import ReviewAssignment, ReviewReport
from app.domain.submission.models import Submission
from app.interfaces.http.review.coi import ensure_no_declared_conflict
from app.models import AuditLog, User

router = APIRouter(tags=["workbench"])

DECIDED_STATUSES = ("accepted", "approved", "rejected", "major_revision", "minor_revision")
ACTIVE_ASSIGNMENT_STATUSES = ("pending", "accepted")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _due_label(due_date: datetime | None, now: datetime) -> tuple[str | None, bool]:
    """Human countdown / overdue label for a due_date.

    Returns ``(label, is_overdue)``. ``(None, False)`` when no due date.
    Examples: "剩 2 天 6 小时" / "剩 3 小时" / "已超期 1 天".
    """
    if due_date is None:
        return None, False
    due_date = _as_utc(due_date) or due_date
    delta = due_date - now
    is_overdue = delta.total_seconds() < 0
    abs_seconds = abs(delta.total_seconds())
    days = int(abs_seconds // 86400)
    hours = int((abs_seconds % 86400) // 3600)
    if is_overdue:
        label = f"已超期 {days} 天" if days else "已超期"
    else:
        label = f"剩 {days} 天 {hours} 小时" if days else f"剩 {hours} 小时"
    return label, is_overdue


def _assignment_row(a: ReviewAssignment, now: datetime) -> dict[str, Any]:
    title = a.submission.title if a.submission else None
    atype = a.submission.type if a.submission else None
    due_label, is_overdue = _due_label(a.due_date, now)
    return {
        "assignment_id": a.id,
        "submission_id": a.submission_id,
        "title": title,
        "type": atype,
        "reviewer_id": a.reviewer_id,
        "reviewer_username": a.reviewer.username if a.reviewer else None,
        "status": a.status,
        "invited_at": a.invited_at,
        "due_date": a.due_date,
        "due_label": due_label,
        "is_overdue": is_overdue,
        "completed_at": a.completed_at,
        "reminder_count": a.reminder_count or 0,
        "report_id": a.report[0].id if a.report else None,
        "attachments": (a.report[0].attachments or []) if a.report else [],
    }


# ---------------------------------------------------------------------------
# Email digest side-channel status (honest "did it actually send?" summary)
# ---------------------------------------------------------------------------


def _smtp_fields_configured() -> bool:
    """True when the four SMTP credentials are all present.

    Deliberately *not* the same as ``core.email.smtp_configured()``: that
    function also requires ``email_outbound_enabled=True`` and
    ``email_backend=="smtp"``. The workbench banner answers a different
    question — "has the operator filled in host/port/user/password?" —
    so a half-configured box (credentials present but outbound switch
    off) still shows up as "configured" instead of silently looking
    identical to "never filled in".
    """
    return bool(
        settings.email_smtp_host
        and settings.email_smtp_port
        and settings.email_smtp_username
        and settings.email_smtp_password
    )


async def _email_digest_summary(db: AsyncSession, tenant_id: Any, now: datetime) -> dict[str, Any]:
    """Honest email-digest side-channel summary for the workbench banner.

    - ``enabled``         — operator switch ``email_review_digest_enabled``.
    - ``smtp_configured`` — host/port/user/password all filled (see above).
    - ``last_status``     — outcome of the most recent attempt, or null.
    - ``skipped_count``   — last-30d rows with status skipped_no_smtp / skipped_disabled.
    - ``failed_count``    — last-30d rows with status failed.
    - ``last_attempt_at`` — created_at of the most recent attempt, or null.

    Counts are tenant-scoped and windowed to the last 30 days so the
    banner stays current; the per-row audit trail lives behind
    ``GET /editor/workbench/email-digest/records``.
    """
    window = now - timedelta(days=30)

    skipped_count = int(
        (
            await db.execute(
                select(func.count(EmailDigestRecord.id)).where(
                    EmailDigestRecord.tenant_id == tenant_id,
                    EmailDigestRecord.created_at >= window,
                    EmailDigestRecord.status.in_(("skipped_no_smtp", "skipped_disabled")),
                )
            )
        ).scalar()
        or 0
    )
    failed_count = int(
        (
            await db.execute(
                select(func.count(EmailDigestRecord.id)).where(
                    EmailDigestRecord.tenant_id == tenant_id,
                    EmailDigestRecord.created_at >= window,
                    EmailDigestRecord.status == "failed",
                )
            )
        ).scalar()
        or 0
    )

    last = (
        await db.execute(
            select(EmailDigestRecord.status, EmailDigestRecord.created_at)
            .where(EmailDigestRecord.tenant_id == tenant_id)
            .order_by(desc(EmailDigestRecord.created_at))
            .limit(1)
        )
    ).first()

    return {
        "enabled": bool(settings.email_review_digest_enabled),
        "smtp_configured": _smtp_fields_configured(),
        "last_status": last[0] if last else None,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "last_attempt_at": last[1] if last else None,
    }


# ---------------------------------------------------------------------------
# Reviewer workbench — two columns only
# ---------------------------------------------------------------------------


@router.get("/review/workbench")
async def reviewer_workbench(
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """审稿人工作台：只有「待审」「已审」两栏。

    待审 = pending/accepted（待回应 + 已接受未交报告）；
    已审 = completed（已提交报告）。
    审稿人看不到主编的四栏与任何指派/裁决操作。
    """
    now = utcnow()
    rows = (
        (
            await db.execute(
                select(ReviewAssignment)
                .where(
                    ReviewAssignment.reviewer_id == current_user.id,
                    ReviewAssignment.tenant_id == current_user.tenant_id,
                )
                .options(
                    selectinload(ReviewAssignment.submission),
                    selectinload(ReviewAssignment.reviewer),
                    selectinload(ReviewAssignment.report),
                )
                .order_by(desc(ReviewAssignment.invited_at))
            )
        )
        .scalars()
        .all()
    )

    pending: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    for a in rows:
        if a.status in ACTIVE_ASSIGNMENT_STATUSES:
            pending.append(_assignment_row(a, now))
        elif a.status == "completed":
            row = _assignment_row(a, now)
            # 已审栏附带推荐结论，便于审稿人自查
            rec = None
            if a.report:
                rec = a.report[0].recommendation
            row["recommendation"] = rec
            completed.append(row)

    return {
        "pending": {"count": len(pending), "items": pending},
        "completed": {"count": len(completed), "items": completed},
    }


# ---------------------------------------------------------------------------
# Editor workbench — four columns
# ---------------------------------------------------------------------------


@router.get("/editor/workbench")
async def editor_workbench(
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """主编/栏目编辑工作台四栏：待指派 → 评审中 → 待裁决 → 已决定。

    每栏带计数。``评审中`` 展开每位审稿人的状态与剩余时间（超期整行高亮）；
    ``待裁决`` 汇总各审稿意见。两栏互斥按当前阶段归位。
    """
    now = utcnow()
    tenant_id = require_tenant_id()

    submissions = (
        (
            await db.execute(
                select(Submission)
                .where(Submission.tenant_id == tenant_id)
                .options(
                    selectinload(Submission.review_assignments).selectinload(
                        ReviewAssignment.reviewer
                    ),
                    selectinload(Submission.review_assignments).selectinload(
                        ReviewAssignment.report
                    ),
                )
            )
        )
        .scalars()
        .all()
    )

    # 一次性取所有 report，避免 N+1
    sub_ids = [s.id for s in submissions]
    reports_by_submission: dict[int, list[ReviewReport]] = {}
    if sub_ids:
        rep_rows = (
            await db.execute(
                select(ReviewReport, ReviewAssignment.submission_id, ReviewAssignment.reviewer_id)
                .join(ReviewAssignment, ReviewReport.assignment_id == ReviewAssignment.id)
                .where(
                    ReviewAssignment.submission_id.in_(sub_ids),
                    ReviewReport.tenant_id == tenant_id,
                )
            )
        ).all()
        for rep, sid, _rid in rep_rows:
            reports_by_submission.setdefault(sid, []).append(rep)

    to_assign: list[dict[str, Any]] = []
    in_review: list[dict[str, Any]] = []
    to_decide: list[dict[str, Any]] = []
    decided: list[dict[str, Any]] = []

    for s in submissions:
        active = [a for a in s.review_assignments if a.status in ACTIVE_ASSIGNMENT_STATUSES]
        done = [a for a in s.review_assignments if a.status == "completed"]
        distinct_done = {a.reviewer_id for a in done}

        base = {
            "submission_id": s.id,
            "title": s.title,
            "type": s.type,
            "submitted_by": s.submitted_by,
            "status": s.status,
            "submitted_at": s.submitted_at,
        }

        if s.status in DECIDED_STATUSES:
            decided.append(base)
            continue

        if s.status == "pending" and not active and not done:
            to_assign.append(base)
            continue

        if s.status == "under_review":
            assignment_items = []
            has_overdue = False
            for a in s.review_assignments:
                row = _assignment_row(a, now)
                assignment_items.append(row)
                if row["is_overdue"]:
                    has_overdue = True
            bucket = dict(base)
            bucket["assignments"] = assignment_items
            bucket["active_count"] = len(active)
            bucket["completed_count"] = len(done)
            bucket["is_overdue"] = has_overdue
            if len(distinct_done) >= 2:
                # 汇总各审稿意见供裁决
                recs = [{"reviewer_id": a.reviewer_id, "recommendation": _rec_of(a)} for a in done]
                bucket["recommendations"] = recs
                to_decide.append(bucket)
            else:
                in_review.append(bucket)
            continue

        # major/minor revision / resubmitted 等中间态归到评审中（仍需推进）
        if s.status in ("major_revision", "minor_revision", "resubmitted"):
            in_review.append(base)

    email_digest = await _email_digest_summary(db, tenant_id, now)

    # 每栏先给 50 篇，避免主编工作台一次渲染几百张卡片；count 仍是全量。
    def _page(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(items),
            "items": items[:50],
            "page_size": 50,
            "has_more": len(items) > 50,
        }

    return {
        "columns": {
            "to_assign": _page(to_assign),
            "in_review": _page(in_review),
            "to_decide": _page(to_decide),
            "decided": _page(decided),
        },
        "email_digest": email_digest,
    }


def _rec_of(a: ReviewAssignment) -> str | None:
    if a.report:
        return a.report[0].recommendation
    return None


# ---------------------------------------------------------------------------
# Email digest records audit trail (editor-only)
# ---------------------------------------------------------------------------


@router.get("/editor/workbench/email-digest/records")
async def editor_email_digest_records(
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """最近邮件摘要投递记录，便于排查"为什么没发到"。

    每条带事件类型、收件人、主题、状态与时间。可按 ``status`` 过滤
    （``sent`` / ``failed`` / ``skipped_no_smtp`` / ``skipped_disabled``）。
    仅 editor 及以上；审稿人不需要看运维侧审计。
    """
    tenant_id = require_tenant_id()
    allowed = {"sent", "failed", "skipped_no_smtp", "skipped_disabled"}
    where = [EmailDigestRecord.tenant_id == tenant_id]
    if status:
        if status not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"status must be one of {sorted(allowed)}",
            )
        where.append(EmailDigestRecord.status == status)

    rows = (
        (
            await db.execute(
                select(EmailDigestRecord)
                .where(*where)
                .order_by(desc(EmailDigestRecord.created_at))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return {
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "event_type": r.event_type,
                "user_id": r.user_id,
                "recipient_email": r.recipient_email,
                "subject": r.subject,
                "status": r.status,
                "related_type": r.related_type,
                "related_id": r.related_id,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Reviewer workload (editor-in-chief / admin)
# ---------------------------------------------------------------------------


@router.get("/editor/workbench/reviewers")
async def reviewer_workload(
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """审稿人负载与完成情况：接受中、已完成、逾期、累计邀请。

    只做聚合，不返回审稿报告内容；供主编决定把新稿派给谁。
    """
    tenant_id = require_tenant_id()
    now = utcnow()
    active = ReviewAssignment.status.in_(ACTIVE_ASSIGNMENT_STATUSES)
    overdue = active & (ReviewAssignment.due_date.is_not(None)) & (ReviewAssignment.due_date < now)
    rows = (
        await db.execute(
            select(
                ReviewAssignment.reviewer_id,
                User.username,
                func.count(ReviewAssignment.id).label("total_count"),
                func.count(ReviewAssignment.id).filter(active).label("active_count"),
                func.count(ReviewAssignment.id)
                .filter(ReviewAssignment.status == "completed")
                .label("completed_count"),
                func.count(ReviewAssignment.id).filter(overdue).label("overdue_count"),
            )
            .join(User, User.id == ReviewAssignment.reviewer_id)
            .where(ReviewAssignment.tenant_id == tenant_id)
            .group_by(ReviewAssignment.reviewer_id, User.username)
            .order_by(desc("active_count"), desc("total_count"))
        )
    ).all()
    return {
        "count": len(rows),
        "items": [
            {
                "reviewer_id": r.reviewer_id,
                "username": r.username,
                "active_count": int(r.active_count),
                "completed_count": int(r.completed_count),
                "overdue_count": int(r.overdue_count),
                "total_count": int(r.total_count),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Batch assign
# ---------------------------------------------------------------------------


class BatchAssignItem(BaseModel):
    submission_id: int = Field(ge=1)
    reviewer_ids: list[int] = Field(default_factory=list, max_length=3)


class BatchAssignBody(BaseModel):
    items: list[BatchAssignItem] = Field(min_length=1, max_length=20)
    due_days: int = Field(default=14, ge=1, le=90)


@router.post("/editor/workbench/batch-assign", status_code=status.HTTP_201_CREATED)
async def batch_assign(
    body: BatchAssignBody,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """批量勾选待指派稿件，一次选审稿人并设截止时间。

    同一事务内创建全部 assignment，逐篇给审稿人发站内通知 + 邮件摘要。
    禁止指派给稿件作者（自审）；重复指派跳过并记录原因。
    """
    tenant_id = require_tenant_id()
    now = utcnow()
    due = now + timedelta(days=body.due_days)

    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in body.items:
        sub = (
            await db.execute(
                select(Submission).where(
                    Submission.id == item.submission_id,
                    Submission.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if sub is None:
            skipped.append({"submission_id": item.submission_id, "reason": "not_found"})
            continue
        if sub.status not in ("pending", "under_review", "resubmitted"):
            skipped.append({"submission_id": item.submission_id, "reason": f"status_{sub.status}"})
            continue

        for rid in item.reviewer_ids:
            if rid == sub.submitted_by:
                skipped.append(
                    {
                        "submission_id": item.submission_id,
                        "reviewer_id": rid,
                        "reason": "is_author",
                    }
                )
                continue
            reviewer = (
                await db.execute(
                    select(User).where(
                        User.id == rid,
                        User.tenant_id == tenant_id,
                        User.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if reviewer is None:
                skipped.append(
                    {
                        "submission_id": item.submission_id,
                        "reviewer_id": rid,
                        "reason": "reviewer_not_found",
                    }
                )
                continue
            if not (
                await user_has_role(db, reviewer, ROLE_REVIEWER)
                or await user_has_role(db, reviewer, ROLE_SENIOR_REVIEWER)
            ):
                skipped.append(
                    {
                        "submission_id": item.submission_id,
                        "reviewer_id": rid,
                        "reason": "not_a_reviewer",
                    }
                )
                continue
            try:
                await ensure_no_declared_conflict(
                    db, tenant_id=tenant_id, reviewer_id=rid, submission=sub
                )
            except HTTPException as exc:
                skipped.append(
                    {
                        "submission_id": item.submission_id,
                        "reviewer_id": rid,
                        "reason": "declared_conflict",
                        "message": (
                            exc.detail.get("message")
                            if isinstance(exc.detail, dict)
                            else str(exc.detail)
                        ),
                    }
                )
                continue

            dup = (
                await db.execute(
                    select(ReviewAssignment).where(
                        ReviewAssignment.submission_id == sub.id,
                        ReviewAssignment.reviewer_id == rid,
                        ReviewAssignment.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                skipped.append(
                    {"submission_id": sub.id, "reviewer_id": rid, "reason": "already_assigned"}
                )
                continue

            a = ReviewAssignment(
                tenant_id=tenant_id,
                submission_id=sub.id,
                reviewer_id=rid,
                assigned_by=current_user.id,
                status="pending",
                due_date=due,
                round=1,
                slot=1,
            )
            db.add(a)
            await db.flush()
            if (sub.triage_status or "pending") in ("pending", "rework"):
                sub.triage_status = "passed"
                sub.triaged_at = utcnow()
                sub.triaged_by = current_user.id

            # 站内通知（同事务）
            await notifications.create(
                db,
                tenant_id=tenant_id,
                user_id=rid,
                type_="review.invited",
                title=f"您被邀请审稿：{sub.title}",
                body=f"稿件 #{sub.id} 已分配给您，截止 {due.date().isoformat()}，请前往审稿工作台回应。",
                related_type="review_assignment",
                related_id=str(a.id),
            )
            # 邮件摘要落库（未配置 SMTP 时记录 skipped_no_smtp，不假装已发）
            from app.core.email_templates import review_assigned

            subject, text, html = review_assigned(
                reviewer.username,
                sub.title,
                f"{settings.frontend_base_url.rstrip('/')}/review/assignments",
                body.due_days,
            )
            await notifications.record_email_digest(
                db,
                tenant_id=tenant_id,
                user_id=rid,
                event_type="assigned",
                recipient_email=reviewer.email,
                subject=subject,
                text=text,
                html=html,
                related_type="review_assignment",
                related_id=str(a.id),
            )

            if sub.status == "pending":
                sub.status = "under_review"

            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor_user_id=current_user.id,
                    action="review.batch_assign",
                    target_type="submission",
                    target_id=str(sub.id),
                    payload={"reviewer_id": rid, "assignment_id": a.id, "due_days": body.due_days},
                )
            )
            created.append(
                {
                    "submission_id": sub.id,
                    "reviewer_id": rid,
                    "assignment_id": a.id,
                    "due_date": due,
                }
            )

    await db.commit()
    return {"created": created, "skipped": skipped, "created_count": len(created)}


# ---------------------------------------------------------------------------
# Conflict check (provenance / COI hints)
# ---------------------------------------------------------------------------


class ConflictCheckBody(BaseModel):
    submission_id: int = Field(ge=1)
    reviewer_ids: list[int] = Field(min_length=1, max_length=20)


@router.post("/editor/workbench/conflicts")
async def check_conflicts(
    body: ConflictCheckBody,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """指派前的利益冲突提示：作者/共同作者 → 黄色警告默认不选；
    同单位无法从 User 字段判定（无 affiliation 列），退化为"该作者已有投稿"提示。
    """
    tenant_id = require_tenant_id()
    sub = (
        await db.execute(
            select(Submission).where(
                Submission.id == body.submission_id,
                Submission.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    author_names = {(n or "").strip().lower() for n in (sub.authors or []) if n}
    out: list[dict[str, Any]] = []
    for rid in body.reviewer_ids:
        reviewer = (
            await db.execute(select(User).where(User.id == rid, User.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if reviewer is None:
            out.append({"reviewer_id": rid, "exists": False, "warning": "用户不存在"})
            continue

        is_submitter = rid == sub.submitted_by
        name_match = bool(reviewer.username) and reviewer.username.strip().lower() in author_names
        own_count = (
            await db.execute(
                select(func.count(Submission.id)).where(
                    Submission.submitted_by == rid,
                    Submission.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
        own_count = int(own_count or 0)

        warnings: list[str] = []
        if is_submitter:
            warnings.append("禁止自审：该审稿人就是稿件提交人")
        if name_match:
            warnings.append("与稿件作者同名：疑似共同作者/自审")
        if own_count > 0:
            warnings.append(
                f"该用户已有 {own_count} 篇投稿（同单位/利益相关无法自动判定，请人工复核）"
            )

        # 默认不选：命中作者/共同作者硬警告；仅"已有投稿"黄警仍默选，由编辑人工决定。
        default_selected = not (is_submitter or name_match)
        out.append(
            {
                "reviewer_id": rid,
                "username": reviewer.username,
                "exists": True,
                "is_submitter": is_submitter,
                "name_matches_author": name_match,
                "own_submission_count": own_count,
                "warnings": warnings,
                "warning": bool(warnings),
                "default_selected": default_selected,
            }
        )
    return {"submission_id": body.submission_id, "candidates": out}


# ---------------------------------------------------------------------------
# Manual remind (催审)
# ---------------------------------------------------------------------------


class RemindBody(BaseModel):
    assignment_ids: list[int] = Field(min_length=1, max_length=50)


@router.post("/editor/workbench/remind")
async def remind_reviewers(
    body: RemindBody,
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """手动催审：给未交报告的审稿人发站内通知 + 邮件摘要。

    仅作用于 pending/accepted（未完成）的 assignment；completed/declined/cancelled 跳过。
    更新 last_reminded_at 与 reminder_count。
    """
    tenant_id = require_tenant_id()
    now = utcnow()
    reminded: list[dict[str, Any]] = []

    for aid in body.assignment_ids:
        a = (
            await db.execute(
                select(ReviewAssignment)
                .where(
                    ReviewAssignment.id == aid,
                    ReviewAssignment.tenant_id == tenant_id,
                )
                .options(
                    selectinload(ReviewAssignment.submission),
                    selectinload(ReviewAssignment.reviewer),
                )
            )
        ).scalar_one_or_none()
        if a is None:
            continue
        if a.status not in ACTIVE_ASSIGNMENT_STATUSES:
            continue
        reviewer = a.reviewer
        sub = a.submission
        title = sub.title if sub else f"#{a.submission_id}"

        await notifications.create(
            db,
            tenant_id=tenant_id,
            user_id=a.reviewer_id,
            type_="review.reminder",
            title=f"审稿催办：{title}",
            body=f"您有一份审稿任务尚未提交，截止 {a.due_date.date().isoformat() if a.due_date else '未定'}，请尽快处理。",
            related_type="review_assignment",
            related_id=str(a.id),
        )
        # 邮件摘要
        from app.core.email_templates import review_reminder

        invited = _as_utc(a.invited_at) or now
        days_pending = max(0, (now - invited).days)
        subject, text, html = review_reminder(
            reviewer.username if reviewer else "审稿人",
            title,
            f"{settings.frontend_base_url.rstrip('/')}/review/assignments",
            days_pending,
        )
        await notifications.record_email_digest(
            db,
            tenant_id=tenant_id,
            user_id=a.reviewer_id,
            event_type="reminder",
            recipient_email=reviewer.email if reviewer else "",
            subject=subject,
            text=text,
            html=html,
            related_type="review_assignment",
            related_id=str(a.id),
        )

        a.last_reminded_at = now
        a.reminder_count = (a.reminder_count or 0) + 1
        db.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=current_user.id,
                action="review.reminder_manual",
                target_type="review_assignment",
                target_id=str(a.id),
                payload={"reminder_count": a.reminder_count},
            )
        )
        reminded.append({"assignment_id": a.id, "reviewer_id": a.reviewer_id})

    await db.commit()
    return {"reminded": reminded, "reminded_count": len(reminded)}


# late import to avoid circular (settings needed for base URL)
from app.core.config import settings  # noqa: E402
