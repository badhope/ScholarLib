"""Reviewer annual conflict-of-interest declarations.

P1-8：每位审稿人每年声明一次冲突对象（作者姓名、邮箱、机构、项目等）。
分派时只做可解释匹配：投稿表里有作者姓名与通讯邮箱，因此能证明的冲突
直接 409 拦截；机构等投稿表没有的字段不猜测，只在声明里留档。

没有声明不阻止分派，编辑侧会显示“未声明”。这样既不会让存量审稿流程
因为一次迁移集体停摆，也不会假装平台已经知道所有人的利益关系。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_reviewer, require_tenant_id
from app.core.db import get_db
from app.core.time import utcnow
from app.domain.review.models import ReviewerConflictDeclaration
from app.domain.submission.models import Submission
from app.models import AuditLog, User

router = APIRouter(prefix="/conflicts", tags=["review-coi"])

MAX_CONFLICTS = 30
MAX_CONFLICT_LENGTH = 120


class CoiDeclarationBody(BaseModel):
    conflicts: list[str] = Field(default_factory=list, max_length=MAX_CONFLICTS)
    notes: str | None = Field(default=None, max_length=2000)


class CoiDeclarationResponse(BaseModel):
    year: int
    declared: bool
    conflicts: list[str] = Field(default_factory=list)
    notes: str | None = None
    declared_at: datetime | None = None
    updated_at: datetime | None = None


def current_coi_year() -> int:
    return datetime.now(UTC).year


def _norm(value: str) -> str:
    """Normalize names/emails for substring matching.

    Keeping only letters/digits/CJK makes ``Alice  Author``, ``alice.author``
    and ``Alice-Author`` comparable without pretending to be a fuzzy matcher.
    """

    return re.sub(r"[\s\W_]+", "", str(value).casefold())


def normalize_conflicts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        text = " ".join(str(raw).split()).strip(" ,;，；")
        if not text:
            continue
        if len(text) > MAX_CONFLICT_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"冲突对象最多 {MAX_CONFLICT_LENGTH} 字：{text[:20]}…",
            )
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    if len(out) > MAX_CONFLICTS:
        raise HTTPException(status_code=422, detail=f"最多声明 {MAX_CONFLICTS} 个冲突对象")
    return out


def declaration_matches(
    declaration: ReviewerConflictDeclaration, submission: Submission
) -> list[str]:
    """Return declared terms that match author names / corresponding email.

    Only terms with at least 2 normalized characters participate; a one-letter
    surname would otherwise match almost every Chinese author and turn the
    guard into a false-positive machine.
    """

    haystacks = [*(submission.authors or []), submission.corresponding_author_email or ""]
    haystacks = [_norm(item) for item in haystacks if item]
    matches: list[str] = []
    for term in declaration.conflicts or []:
        needle = _norm(term)
        if len(needle) < 2:
            continue
        if any(needle in hay for hay in haystacks):
            matches.append(term)
    return matches


async def declarations_for_reviewers(
    db: AsyncSession, *, tenant_id: Any, reviewer_ids: list[int], year: int
) -> dict[int, ReviewerConflictDeclaration]:
    if not reviewer_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(ReviewerConflictDeclaration).where(
                    ReviewerConflictDeclaration.tenant_id == tenant_id,
                    ReviewerConflictDeclaration.user_id.in_(reviewer_ids),
                    ReviewerConflictDeclaration.year == year,
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.user_id: row for row in rows}


async def latest_declaration(
    db: AsyncSession, *, tenant_id: Any, user_id: int, year: int | None = None
) -> ReviewerConflictDeclaration | None:
    stmt = select(ReviewerConflictDeclaration).where(
        ReviewerConflictDeclaration.tenant_id == tenant_id,
        ReviewerConflictDeclaration.user_id == user_id,
    )
    if year is not None:
        stmt = stmt.where(ReviewerConflictDeclaration.year == year)
    return (
        (await db.execute(stmt.order_by(desc(ReviewerConflictDeclaration.year)))).scalars().first()
    )


async def ensure_no_declared_conflict(
    db: AsyncSession, *, tenant_id: Any, reviewer_id: int, submission: Submission
) -> None:
    declaration = await latest_declaration(db, tenant_id=tenant_id, user_id=reviewer_id)
    if declaration is None:
        return
    matches = declaration_matches(declaration, submission)
    if not matches:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "reviewer_declared_conflict",
            "message": (
                f"审稿人已申报与作者存在利益冲突：{', '.join(matches)}。"
                "请更换审稿人，或先由主编在声明中解除该冲突。"
            ),
            "matched_terms": matches,
            "year": declaration.year,
        },
    )


def _to_response(
    declaration: ReviewerConflictDeclaration | None, year: int
) -> CoiDeclarationResponse:
    if declaration is None:
        return CoiDeclarationResponse(year=year, declared=False)
    return CoiDeclarationResponse(
        year=declaration.year,
        declared=True,
        conflicts=list(declaration.conflicts or []),
        notes=declaration.notes,
        declared_at=declaration.declared_at,
        updated_at=declaration.updated_at,
    )


@router.get("/me", response_model=CoiDeclarationResponse)
async def get_my_coi(
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
) -> CoiDeclarationResponse:
    tenant_id = require_tenant_id()
    year = current_coi_year()
    declaration = await latest_declaration(
        db, tenant_id=tenant_id, user_id=current_user.id, year=year
    )
    return _to_response(declaration, year)


@router.put("/me", response_model=CoiDeclarationResponse)
async def save_my_coi(
    body: CoiDeclarationBody,
    current_user: User = Depends(require_reviewer),
    db: AsyncSession = Depends(get_db),
) -> CoiDeclarationResponse:
    tenant_id = require_tenant_id()
    year = current_coi_year()
    conflicts = normalize_conflicts(body.conflicts)
    notes = (body.notes or "").strip() or None
    declaration = await latest_declaration(
        db, tenant_id=tenant_id, user_id=current_user.id, year=year
    )
    now = utcnow()
    if declaration is None:
        declaration = ReviewerConflictDeclaration(
            tenant_id=tenant_id,
            user_id=current_user.id,
            year=year,
            conflicts=conflicts,
            notes=notes,
            declared_at=now,
            updated_at=now,
        )
        db.add(declaration)
    else:
        declaration.conflicts = conflicts
        declaration.notes = notes
        declaration.updated_at = now
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            action="reviewer.coi_declaration",
            target_type="user",
            target_id=str(current_user.id),
            payload={"year": year, "conflicts": conflicts},
        )
    )
    await db.commit()
    await db.refresh(declaration)
    return _to_response(declaration, year)
