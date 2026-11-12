"""Admin release gate and manifest endpoints.

Flow:
  POST /admin/releases/check    -> create a manifest (ready | blocked)
  POST /admin/releases/publish  -> re-hash, require ready + unchanged, publish
  GET  /admin/releases/issues   -> all issues including drafts
  GET  /admin/releases/manifests-> history for one issue

The publish endpoint deliberately refuses a stale manifest.  If an editor
changes a title, swaps a PDF or adds a draft after the gate ran, the release
must be re-checked; that is the whole point of a manifest.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_tenant_id
from app.core.config import settings
from app.core.db import get_db
from app.core.time import utcnow
from app.models import AuditLog, User
from app.modules.catalog.models import Resource
from app.modules.release.gate import check_issue
from app.modules.release.models import ReleaseManifest

router = APIRouter(prefix="/admin/releases", tags=["release"])

MANIFEST_TRANSITIONS = {
    "blocked": {"ready"},
    "ready": {"scheduled", "published", "superseded"},
    "scheduled": {"published", "superseded"},
    "published": set(),
    "superseded": set(),
}


class ReleaseCheckRequest(BaseModel):
    volume: str = Field(min_length=1, max_length=50)
    issue: str = Field(min_length=1, max_length=50)


class ReleasePublishRequest(BaseModel):
    volume: str = Field(min_length=1, max_length=50)
    issue: str = Field(min_length=1, max_length=50)
    manifest_id: int
    publish_at: datetime | None = None


class ReleaseApproveRequest(BaseModel):
    manifest_id: int
    note: str | None = Field(default=None, max_length=500)


class ReleaseRollbackRequest(BaseModel):
    volume: str = Field(min_length=1, max_length=50)
    issue: str = Field(min_length=1, max_length=50)
    manifest_id: int
    reason: str = Field(min_length=3, max_length=500)


def _utc_second(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0)


def _approval_payload(
    manifest: ReleaseManifest,
    approved_by: int,
    approved_at: datetime,
) -> str:
    # Approval time is stored at second precision and normalized to UTC so
    # the signature survives SQLite/Postgres round-trips unchanged.
    return (
        f"{manifest.id}|{manifest.volume}|{manifest.issue}|{manifest.content_hash}|"
        f"{approved_by}|{_utc_second(approved_at).isoformat()}"
    )


def _sign_approval(
    manifest: ReleaseManifest,
    approved_by: int,
    approved_at: datetime,
) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        _approval_payload(manifest, approved_by, approved_at).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _approval_valid(manifest: ReleaseManifest) -> bool:
    if not manifest.approved_at or not manifest.approved_by or not manifest.approval_signature:
        return False
    expected = _sign_approval(manifest, manifest.approved_by, manifest.approved_at)
    return hmac.compare_digest(expected, manifest.approval_signature)


def _serialize(manifest: ReleaseManifest) -> dict[str, Any]:
    return {
        "id": manifest.id,
        "volume": manifest.volume,
        "issue": manifest.issue,
        "status": manifest.status,
        "content_hash": manifest.content_hash,
        "resource_count": manifest.resource_count,
        "error_count": manifest.error_count,
        "warning_count": manifest.warning_count,
        "created_by": manifest.created_by,
        "created_at": manifest.created_at.isoformat() if manifest.created_at else None,
        "published_at": manifest.published_at.isoformat() if manifest.published_at else None,
        "approved_by": manifest.approved_by,
        "approved_at": manifest.approved_at.isoformat() if manifest.approved_at else None,
        "approval_note": manifest.approval_note,
        "approval_signature": manifest.approval_signature,
        "scheduled_for": manifest.scheduled_for.isoformat() if manifest.scheduled_for else None,
        "rollback_of": manifest.rollback_of,
        "payload": manifest.payload,
    }


async def _issue_rows(db: AsyncSession, tenant_id: UUID, volume: str, issue: str) -> list[Resource]:
    return list(
        (
            await db.execute(
                select(Resource)
                .where(
                    Resource.tenant_id == tenant_id,
                    Resource.volume == volume,
                    Resource.issue == issue,
                )
                .order_by(Resource.id.asc())
            )
        )
        .scalars()
        .all()
    )


@router.get("/issues")
async def list_release_issues(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict[str, Any]:
    """Every issue, including drafts, for the release dashboard."""
    tenant_id = require_tenant_id()
    rows = (
        (
            await db.execute(
                select(Resource).where(
                    Resource.tenant_id == tenant_id,
                    Resource.volume.is_not(None),
                    Resource.volume != "",
                    Resource.issue.is_not(None),
                    Resource.issue != "",
                )
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for resource in rows:
        key = (str(resource.volume), str(resource.issue))
        item = grouped.setdefault(
            key,
            {
                "volume": key[0],
                "issue": key[1],
                "total": 0,
                "draft": 0,
                "published": 0,
                "scheduled": 0,
                "publish_at": None,
            },
        )
        item["total"] += 1
        if resource.publication_status != "published":
            item["draft"] += 1
        elif resource.publish_at is not None and resource.publish_at > utcnow():
            item["scheduled"] += 1
        else:
            item["published"] += 1
        current = item["publish_at"]
        if resource.publish_at is not None and (current is None or resource.publish_at < current):
            item["publish_at"] = resource.publish_at

    items = []
    for item in grouped.values():
        if item["draft"]:
            state = "draft"
        elif item["published"]:
            state = "live"
        elif item["scheduled"]:
            state = "scheduled"
        else:
            state = "empty"
        item["state"] = state
        item["publish_at"] = item["publish_at"].isoformat() if item["publish_at"] else None
        items.append(item)
    items.sort(key=lambda x: (x["volume"], x["issue"]), reverse=True)
    return {"items": items}


@router.get("/manifests")
async def list_manifests(
    volume: str = Query(min_length=1, max_length=50),
    issue: str = Query(min_length=1, max_length=50),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict[str, Any]:
    tenant_id = require_tenant_id()
    rows = (
        (
            await db.execute(
                select(ReleaseManifest)
                .where(
                    ReleaseManifest.tenant_id == tenant_id,
                    ReleaseManifest.volume == volume,
                    ReleaseManifest.issue == issue,
                )
                .order_by(ReleaseManifest.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_serialize(m) for m in rows]}


@router.get("/latest")
async def latest_manifest(
    volume: str = Query(min_length=1, max_length=50),
    issue: str = Query(min_length=1, max_length=50),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict[str, Any]:
    tenant_id = require_tenant_id()
    manifest = (
        await db.execute(
            select(ReleaseManifest)
            .where(
                ReleaseManifest.tenant_id == tenant_id,
                ReleaseManifest.volume == volume,
                ReleaseManifest.issue == issue,
            )
            .order_by(ReleaseManifest.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if manifest is None:
        raise HTTPException(status_code=404, detail="No release manifest for this issue")
    return _serialize(manifest)


@router.post("/check")
async def create_release_check(
    payload: ReleaseCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Run the gate and persist the result as a manifest."""
    tenant_id = require_tenant_id()
    result = await check_issue(db, tenant_id, payload.volume, payload.issue)

    # A new check makes earlier unpublished manifests obsolete. Published
    # manifests are history and must never be overwritten.
    await db.execute(
        update(ReleaseManifest)
        .where(
            ReleaseManifest.tenant_id == tenant_id,
            ReleaseManifest.volume == payload.volume,
            ReleaseManifest.issue == payload.issue,
            ReleaseManifest.status.in_(("ready", "blocked", "scheduled")),
        )
        .values(status="superseded")
    )

    manifest = ReleaseManifest(
        tenant_id=tenant_id,
        volume=payload.volume,
        issue=payload.issue,
        status=result["status"],
        content_hash=result["content_hash"],
        resource_count=result["resource_count"],
        error_count=result["error_count"],
        warning_count=result["warning_count"],
        payload=result,
        created_by=current_admin.id,
    )
    db.add(manifest)
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_admin.id,
            action="release.check",
            target_type="issue",
            target_id=f"{payload.volume}/{payload.issue}",
            payload={
                "status": result["status"],
                "errors": result["error_count"],
                "warnings": result["warning_count"],
                "resources": result["resource_count"],
                "content_hash": result["content_hash"],
            },
        )
    )
    await db.commit()
    await db.refresh(manifest)
    return _serialize(manifest)


@router.post("/approve")
async def approve_release(
    payload: ReleaseApproveRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Approve one ready manifest by its exact content hash.

    A new check after any content change creates a new manifest; the old
    approval is therefore invalidated together with the old manifest.
    """
    tenant_id = require_tenant_id()
    manifest = (
        await db.execute(
            select(ReleaseManifest).where(
                ReleaseManifest.id == payload.manifest_id,
                ReleaseManifest.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Release manifest not found")
    if manifest.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Manifest is {manifest.status}; only a ready manifest can be approved",
        )
    if manifest.approved_at is not None:
        raise HTTPException(status_code=409, detail="Manifest is already approved")

    approved_at = _utc_second(utcnow())
    manifest.approved_by = current_admin.id
    manifest.approved_at = approved_at
    manifest.approval_note = payload.note
    manifest.approval_signature = _sign_approval(manifest, current_admin.id, approved_at)
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_admin.id,
            action="release.approve",
            target_type="issue",
            target_id=f"{manifest.volume}/{manifest.issue}",
            payload={
                "manifest_id": manifest.id,
                "content_hash": manifest.content_hash,
                "note": payload.note,
            },
        )
    )
    await db.commit()
    await db.refresh(manifest)
    return _serialize(manifest)


@router.post("/publish")
async def publish_release(
    payload: ReleasePublishRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Publish or schedule an issue using a still-valid ready manifest."""
    tenant_id = require_tenant_id()
    manifest = (
        await db.execute(
            select(ReleaseManifest).where(
                ReleaseManifest.id == payload.manifest_id,
                ReleaseManifest.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Release manifest not found")
    if manifest.volume != payload.volume or manifest.issue != payload.issue:
        raise HTTPException(status_code=400, detail="Manifest does not match issue")
    if manifest.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Manifest is {manifest.status}; only a ready manifest can publish",
        )
    if not _approval_valid(manifest):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_approved",
                "message": "这份 Manifest 还没有编辑批准，或批准签名已失效",
                "manifest_id": manifest.id,
            },
        )

    current = await check_issue(db, tenant_id, payload.volume, payload.issue)
    if current["content_hash"] != manifest.content_hash:
        manifest.status = "superseded"
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "manifest_stale",
                "message": "期内容在门禁后发生变化，必须重新检查",
                "manifest_hash": manifest.content_hash,
                "current_hash": current["content_hash"],
                "errors": current["error_count"],
            },
        )
    if current["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "gate_blocked",
                "message": "当前期仍有错误，不能发布",
                "errors": current["error_count"],
            },
        )

    target = payload.publish_at or utcnow()
    if target <= utcnow():
        target = utcnow()
    rows = await _issue_rows(db, tenant_id, payload.volume, payload.issue)
    if not rows:
        raise HTTPException(status_code=404, detail="Issue has no resources")
    await db.execute(
        update(Resource)
        .where(
            Resource.tenant_id == tenant_id,
            Resource.volume == payload.volume,
            Resource.issue == payload.issue,
            Resource.publication_status == "published",
        )
        .values(publish_at=target)
    )

    next_status = "scheduled" if target > utcnow() else "published"
    if next_status not in MANIFEST_TRANSITIONS[manifest.status]:
        raise HTTPException(status_code=409, detail="Illegal manifest transition")
    manifest.status = next_status
    manifest.scheduled_for = target if next_status == "scheduled" else None
    manifest.published_at = utcnow() if next_status == "published" else None
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_admin.id,
            action="release.publish",
            target_type="issue",
            target_id=f"{payload.volume}/{payload.issue}",
            payload={
                "manifest_id": manifest.id,
                "publish_at": target.isoformat(),
                "status": next_status,
                "resources": len(rows),
            },
        )
    )
    await db.commit()
    await db.refresh(manifest)
    result = _serialize(manifest)
    result["publish_at"] = target.isoformat()
    return result


@router.post("/rollback")
async def rollback_release(
    payload: ReleaseRollbackRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Re-publish an earlier published issue snapshot.

    Rollback restores the *issue timeline* (each resource's publish_at does
    not invent new content.  It deliberately bypasses the current gate:
    the target manifest was already published; reusing it is the point of a
    rollback.  A new manifest records who rolled back what and why.
    """
    tenant_id = require_tenant_id()
    target = (
        await db.execute(
            select(ReleaseManifest).where(
                ReleaseManifest.id == payload.manifest_id,
                ReleaseManifest.tenant_id == tenant_id,
                ReleaseManifest.volume == payload.volume,
                ReleaseManifest.issue == payload.issue,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Rollback target manifest not found")
    if target.status != "published":
        raise HTTPException(
            status_code=409, detail="Only a published manifest can be rolled back to"
        )

    snapshot = target.payload.get("resources") or []
    wanted: dict[int, datetime | None] = {}
    for item in snapshot:
        try:
            rid = int(item["id"])
            raw = item.get("publish_at")
            wanted[rid] = datetime.fromisoformat(raw) if raw else None
        except (KeyError, TypeError, ValueError):
            continue
    if not wanted:
        raise HTTPException(status_code=409, detail="Rollback target has no resource snapshot")

    rows = await _issue_rows(db, tenant_id, payload.volume, payload.issue)
    restored = 0
    missing: list[int] = []
    for resource in rows:
        if resource.id not in wanted:
            continue
        if resource.publication_status != "published":
            continue
        resource.publish_at = wanted[resource.id]
        restored += 1
    if restored == 0:
        raise HTTPException(status_code=409, detail="None of the target resources still exist")
    for rid in wanted:
        if rid not in {r.id for r in rows}:
            missing.append(rid)

    now = _utc_second(utcnow())
    manifest = ReleaseManifest(
        tenant_id=tenant_id,
        volume=payload.volume,
        issue=payload.issue,
        status="published",
        content_hash=target.content_hash,
        resource_count=target.resource_count,
        error_count=target.error_count,
        warning_count=target.warning_count,
        payload={
            **target.payload,
            "rollback_of": target.id,
            "rollback_reason": payload.reason,
            "rollback_restored": restored,
            "rollback_missing": missing,
        },
        created_by=current_admin.id,
        published_at=now,
        approved_by=current_admin.id,
        approved_at=now,
        approval_note=f"rollback to #{target.id}: {payload.reason}",
        rollback_of=target.id,
    )
    db.add(manifest)
    await db.flush()
    manifest.approval_signature = _sign_approval(manifest, current_admin.id, now)
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_admin.id,
            action="release.rollback",
            target_type="issue",
            target_id=f"{payload.volume}/{payload.issue}",
            payload={
                "manifest_id": manifest.id,
                "rollback_of": target.id,
                "restored": restored,
                "missing": missing,
                "reason": payload.reason,
            },
        )
    )
    await db.commit()
    await db.refresh(manifest)
    result = _serialize(manifest)
    result["restored"] = restored
    result["missing"] = missing
    return result
