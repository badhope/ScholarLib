"""职员角色申请资格（L5 审稿人 / L6 资深审稿人）。

口径（冻结在代码里，与 /levels 页展示一致）：

- **L5 审稿人**：至少 1 篇稿件被本刊录用，且其中最高 RQS 质量分 ≥ 60
  （C 级及以上）。未评分的稿件不参与门槛——新作者不被历史数据卡死。
- **L6 资深审稿人**：已是审稿人，且完成审稿 ≥ 5 份。
- L7–L9（编辑职）不开放申请，仅编辑部直接提拔。

资格判定只读不改；申请写入 role_applications，管理员批准时才授角色。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.catalog.models import Resource
from app.domain.gamification.models import RoleApplication
from app.domain.review.models import ReviewAssignment, ReviewReport
from app.domain.submission.models import Submission
from app.models import User

# L5：最高 RQS 质量分门槛（C 级下限）。
SENIOR_RQS_THRESHOLD = 60
# L6：完成审稿份数门槛。
SENIOR_REVIEW_COUNT = 5

ELIGIBLE_TARGET_ROLES = ("reviewer", "senior_reviewer")


def _profile_payload(
    *,
    accepted_papers: int,
    best_rqs: float | None,
    reviews_completed: int,
    already_reviewer: bool,
) -> dict[str, object]:
    return {
        "accepted_papers": accepted_papers,
        "best_rqs": best_rqs,
        "reviews_completed": reviews_completed,
        "already_reviewer": already_reviewer,
    }


async def accepted_paper_count(db: AsyncSession, user: User) -> int:
    """该作者被本刊录用的稿件数（accepted / approved；供 L4 指标与 L5 画像共用）。"""
    return int(
        (
            await db.execute(
                select(func.count(Resource.id))
                .join(Submission, Submission.resource_id == Resource.id)
                .where(
                    Submission.submitted_by == user.id,
                    Submission.tenant_id == user.tenant_id,
                    Submission.status.in_(("accepted", "approved")),
                    Resource.tenant_id == user.tenant_id,
                )
            )
        ).scalar_one()
    )


async def reviewer_profile(db: AsyncSession, user: User) -> dict[str, object]:
    """L5 资格画像：已录用稿件数 + 最高 RQS。"""
    rows = (
        (
            await db.execute(
                select(Resource.quality_score)
                .join(Submission, Submission.resource_id == Resource.id)
                .where(
                    Submission.submitted_by == user.id,
                    Submission.tenant_id == user.tenant_id,
                    Submission.status.in_(("accepted", "approved")),
                    Resource.tenant_id == user.tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    scores = [float(s) for s in rows if s is not None]
    return _profile_payload(
        accepted_papers=len(rows),
        best_rqs=max(scores) if scores else None,
        reviews_completed=0,
        already_reviewer=False,
    )


def reviewer_eligible(profile: dict[str, object]) -> bool:
    """L5 门槛：≥1 篇录用 且 最高 RQS ≥ 60（未评分稿件不参与）。"""
    accepted_raw = profile.get("accepted_papers") or 0
    best = profile.get("best_rqs")
    if not isinstance(accepted_raw, int) or not isinstance(best, (int, float)):
        return False
    return accepted_raw >= 1 and float(best) >= SENIOR_RQS_THRESHOLD


async def senior_reviewer_profile(db: AsyncSession, user: User) -> dict[str, object]:
    """L6 资格画像：已完成审稿份数。"""
    reviews = int(
        (
            await db.execute(
                select(func.count(ReviewReport.id))
                .join(ReviewAssignment, ReviewAssignment.id == ReviewReport.assignment_id)
                .where(
                    ReviewReport.tenant_id == user.tenant_id,
                    ReviewAssignment.reviewer_id == user.id,
                )
            )
        ).scalar_one()
    )
    return _profile_payload(
        accepted_papers=0,
        best_rqs=None,
        reviews_completed=reviews,
        already_reviewer=False,
    )


def senior_reviewer_eligible(profile: dict[str, object]) -> bool:
    reviews = profile.get("reviews_completed") or 0
    return isinstance(reviews, int) and reviews >= SENIOR_REVIEW_COUNT


async def pending_application_exists(
    db: AsyncSession, user_id: int, tenant_id: object, target_role: str
) -> bool:
    stmt = select(RoleApplication.id).where(
        RoleApplication.tenant_id == tenant_id,
        RoleApplication.user_id == user_id,
        RoleApplication.target_role == target_role,
        RoleApplication.status == "pending",
    )
    # first() 而不是 scalar_one_or_none()：并发旧数据理论上可能留下多行，
    # 这里只关心「有没有」，不该因为历史脏数据抛 MultipleResultsFound。
    return (await db.execute(stmt.limit(1))).first() is not None


__all__ = [
    "ELIGIBLE_TARGET_ROLES",
    "SENIOR_REVIEW_COUNT",
    "SENIOR_RQS_THRESHOLD",
    "accepted_paper_count",
    "pending_application_exists",
    "reviewer_eligible",
    "reviewer_profile",
    "senior_reviewer_eligible",
    "senior_reviewer_profile",
]
