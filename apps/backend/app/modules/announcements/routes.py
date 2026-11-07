"""Announcements API — public read of the active notice, admin CRUD."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_tenant_id
from app.core.db import get_db
from app.core.time import utcnow
from app.models import AuditLog, User
from app.modules.announcements.models import Announcement

router = APIRouter(prefix="/announcements", tags=["announcements"])


class AnnouncementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    body: str
    level: str
    is_active: bool
    starts_at: datetime
    ends_at: datetime | None


class AnnouncementIn(BaseModel):
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    level: str = Field(default="info", pattern=r"^(info|success|warning|critical)$")
    is_active: bool = True
    ends_at: datetime | None = None


@router.get("/active", response_model=AnnouncementOut | None)
async def active_announcement(db: AsyncSession = Depends(get_db)) -> AnnouncementOut | None:
    """The notice shown on first visit (newest active one, inside its window)."""
    tenant_id = require_tenant_id()
    now = utcnow()
    row = (
        await db.execute(
            select(Announcement)
            .where(
                Announcement.tenant_id == tenant_id,
                Announcement.is_active.is_(True),
                Announcement.starts_at <= now,
                or_(Announcement.ends_at.is_(None), Announcement.ends_at > now),
            )
            .order_by(Announcement.starts_at.desc(), Announcement.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return AnnouncementOut.model_validate(row) if row is not None else None


@router.get("", response_model=list[AnnouncementOut])
async def list_announcements(
    db: AsyncSession = Depends(get_db),
) -> list[AnnouncementOut]:
    tenant_id = require_tenant_id()
    rows = (
        (
            await db.execute(
                select(Announcement)
                .where(Announcement.tenant_id == tenant_id)
                .order_by(Announcement.created_at.desc(), Announcement.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [AnnouncementOut.model_validate(r) for r in rows]


@router.post("", response_model=AnnouncementOut, status_code=status.HTTP_201_CREATED)
async def create_announcement(
    payload: AnnouncementIn,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AnnouncementOut:
    tenant_id = require_tenant_id()
    row = Announcement(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Announcement slug already exists"
        ) from exc
    await db.refresh(row)
    return AnnouncementOut.model_validate(row)


@router.patch("/{announcement_id}", response_model=AnnouncementOut)
async def update_announcement(
    announcement_id: int,
    payload: AnnouncementIn,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AnnouncementOut:
    tenant_id = require_tenant_id()
    row = (
        await db.execute(
            select(Announcement).where(
                Announcement.id == announcement_id, Announcement.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_admin.id,
            action="announcement.update",
            target_type="announcement",
            target_id=str(announcement_id),
            payload={"slug": payload.slug, "is_active": payload.is_active},
        )
    )
    await db.commit()
    await db.refresh(row)
    return AnnouncementOut.model_validate(row)


@router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement(
    announcement_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    tenant_id = require_tenant_id()
    row = (
        await db.execute(
            select(Announcement).where(
                Announcement.id == announcement_id, Announcement.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await db.delete(row)
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_admin.id,
            action="announcement.delete",
            target_type="announcement",
            target_id=str(announcement_id),
            payload=None,
        )
    )
    await db.commit()
