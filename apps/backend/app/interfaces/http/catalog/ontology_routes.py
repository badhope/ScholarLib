"""Discipline + Subdiscipline admin CRUD endpoints.

Read endpoints (``GET /catalog/disciplines`` and
``GET /catalog/disciplines/{slug}``) are public so the frontend can
build a directory page. Write endpoints (``POST`` / ``PATCH`` /
``DELETE``) require admin because they shape the controlled
vocabulary that all new resources are validated against.

Public endpoint returns a bare ``list[DisciplineResponse]`` with
subdisciplines inline. Cached client-side for the duration of a
typical browse session.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_admin, require_tenant_id
from app.core.db import get_db
from app.domain.catalog.models import Discipline, Subdiscipline
from app.models import User

router = APIRouter(prefix="/disciplines", tags=["ontology"])


# --- Schemas ---------------------------------------------------------------


class SubdisciplineIn(BaseModel):
    """Body for creating a subdiscipline alongside its parent."""

    slug: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)


class SubdisciplineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str


class DisciplineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: str | None = None
    subdisciplines: list[SubdisciplineOut] = Field(default_factory=list)


class DisciplineCreate(BaseModel):
    """Body for POST /catalog/disciplines."""

    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    subdisciplines: list[SubdisciplineIn] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _unique_subdiscipline_slugs(self) -> DisciplineCreate:
        seen: set[str] = set()
        for s in self.subdisciplines:
            if s.slug in seen:
                raise ValueError(f"Duplicate subdiscipline slug: {s.slug!r}")
            seen.add(s.slug)
        return self


class DisciplineUpdate(BaseModel):
    """Body for PATCH /catalog/disciplines/{slug}."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class SubdisciplineCreate(BaseModel):
    """Body for POST /catalog/disciplines/{slug}/subdisciplines."""

    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    name: str = Field(min_length=1, max_length=200)


# --- Helpers ---------------------------------------------------------------


def _to_discipline_out(d: Discipline) -> DisciplineOut:
    """Materialize a Discipline row into a DisciplineOut response model.

    The ``subdisciplines`` relationship must already be eagerly
    loaded (via ``selectinload``). This helper exists so response
    construction has exactly one shape and we never trigger lazy
    loading on a session whose state has been cleared by
    ``commit()``.
    """
    return DisciplineOut.model_validate(
        {
            "id": d.id,
            "slug": d.slug,
            "name": d.name,
            "description": d.description,
            "subdisciplines": [SubdisciplineOut.model_validate(s) for s in d.subdisciplines],
        }
    )


# --- Public read endpoints --------------------------------------------------


@router.get("", response_model=list[DisciplineOut])
async def list_disciplines(
    db: AsyncSession = Depends(get_db),
) -> list[DisciplineOut]:
    """Return all disciplines with their subdisciplines inline."""
    tenant_id = require_tenant_id()
    rows = (
        (
            await db.execute(
                select(Discipline)
                .options(selectinload(Discipline.subdisciplines))
                .where(Discipline.tenant_id == tenant_id)
                .order_by(Discipline.name.asc())
            )
        )
        .scalars()
        .all()
    )
    return [_to_discipline_out(d) for d in rows]


@router.get("/{slug}", response_model=DisciplineOut)
async def get_discipline(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> DisciplineOut:
    tenant_id = require_tenant_id()
    d = (
        await db.execute(
            select(Discipline)
            .options(selectinload(Discipline.subdisciplines))
            .where(Discipline.tenant_id == tenant_id, Discipline.slug == slug)
        )
    ).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discipline not found")
    return _to_discipline_out(d)


# --- Admin write endpoints --------------------------------------------------


@router.post("", response_model=DisciplineOut, status_code=status.HTTP_201_CREATED)
async def create_discipline(
    payload: DisciplineCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> DisciplineOut:
    tenant_id = require_tenant_id()
    discipline = Discipline(
        tenant_id=tenant_id,
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
    )
    db.add(discipline)
    try:
        await db.flush()  # get the id
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Discipline {payload.slug!r} already exists",
        ) from exc
    for s in payload.subdisciplines:
        db.add(
            Subdiscipline(
                tenant_id=tenant_id,
                discipline_id=discipline.id,
                slug=s.slug,
                name=s.name,
            )
        )
    try:
        # 子学科 slug 重复的唯一约束在 commit 触发（不是在 flush），
        # try 必须包住 commit，否则 500 而不是 409。
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Discipline or subdiscipline slug already exists",
        ) from exc
    # Re-fetch with eager loading so subdisciplines are available
    # for the response without triggering lazy-load on a session
    # whose state has just been cleared by ``commit()``.
    reloaded = (
        await db.execute(
            select(Discipline)
            .options(selectinload(Discipline.subdisciplines))
            .where(Discipline.id == discipline.id)
        )
    ).scalar_one()
    return _to_discipline_out(reloaded)


@router.patch("/{slug}", response_model=DisciplineOut)
async def update_discipline(
    slug: str,
    payload: DisciplineUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> DisciplineOut:
    tenant_id = require_tenant_id()
    discipline = (
        await db.execute(
            select(Discipline).where(Discipline.tenant_id == tenant_id, Discipline.slug == slug)
        )
    ).scalar_one_or_none()
    if discipline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discipline not found")
    if payload.name is not None:
        discipline.name = payload.name
    if payload.description is not None:
        discipline.description = payload.description
    await db.commit()
    reloaded = (
        await db.execute(
            select(Discipline)
            .options(selectinload(Discipline.subdisciplines))
            .where(Discipline.id == discipline.id)
        )
    ).scalar_one()
    return _to_discipline_out(reloaded)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_discipline(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> None:
    """Delete a discipline and (via CASCADE) its subdisciplines.

    Existing Resources that referenced this discipline keep their
    stored string values; new writes to those rows will start
    failing 422 until the discipline is recreated or the resource
    moves to a valid one. This is the intended behaviour: silent
    re-mapping would hide a taxonomy drift problem.
    """
    tenant_id = require_tenant_id()
    discipline = (
        await db.execute(
            select(Discipline).where(Discipline.tenant_id == tenant_id, Discipline.slug == slug)
        )
    ).scalar_one_or_none()
    if discipline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discipline not found")
    await db.delete(discipline)
    await db.commit()


@router.post(
    "/{slug}/subdisciplines",
    response_model=SubdisciplineOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_subdiscipline(
    slug: str,
    payload: SubdisciplineCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> SubdisciplineOut:
    tenant_id = require_tenant_id()
    discipline = (
        await db.execute(
            select(Discipline).where(Discipline.tenant_id == tenant_id, Discipline.slug == slug)
        )
    ).scalar_one_or_none()
    if discipline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discipline not found")
    sub = Subdiscipline(
        tenant_id=tenant_id,
        discipline_id=discipline.id,
        slug=payload.slug,
        name=payload.name,
    )
    db.add(sub)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Subdiscipline {payload.slug!r} already exists under {slug!r}",
        ) from exc
    await db.refresh(sub)
    return SubdisciplineOut.model_validate(sub)


@router.delete(
    "/{slug}/subdisciplines/{sub_slug}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_subdiscipline(
    slug: str,
    sub_slug: str,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> None:
    tenant_id = require_tenant_id()
    sub = (
        await db.execute(
            select(Subdiscipline)
            .join(Discipline, Subdiscipline.discipline_id == Discipline.id)
            .where(
                Subdiscipline.tenant_id == tenant_id,
                Discipline.slug == slug,
                Subdiscipline.slug == sub_slug,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subdiscipline not found")
    await db.delete(sub)
    await db.commit()


__all__ = [
    "DisciplineCreate",
    "DisciplineOut",
    "DisciplineUpdate",
    "SubdisciplineCreate",
    "SubdisciplineIn",
    "SubdisciplineOut",
    "router",
]
