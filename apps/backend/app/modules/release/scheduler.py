"""Tiny in-process scheduler for due release manifests.

The main scheduler interval is six hours because review reminders are
expensive; a scheduled issue cannot wait six hours.  This loop is separate,
runs every 30 seconds, and only touches manifests that are already due.

Failure policy: never publish a changed issue silently.  If the content hash
no longer matches, or the gate is blocked, the manifest is superseded and an
audit row records why.  The editor then re-checks and re-approves.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import async_session_factory
from app.core.logging import get_logger
from app.core.tenant import TENANT_CONTEXT_VAR
from app.core.time import utcnow
from app.models import AuditLog, Tenant
from app.modules.release.gate import check_issue
from app.modules.release.models import ReleaseManifest

logger = get_logger("rubbish.release_scheduler")

TICK_SECONDS = 30
STARTUP_DELAY_SECONDS = 10
_task: asyncio.Task[None] | None = None


async def _due_manifests(session: AsyncSession, tenant_id: Any) -> list[ReleaseManifest]:
    return list(
        (
            await session.execute(
                select(ReleaseManifest)
                .where(
                    ReleaseManifest.tenant_id == tenant_id,
                    ReleaseManifest.status == "scheduled",
                    ReleaseManifest.scheduled_for.is_not(None),
                    ReleaseManifest.scheduled_for <= utcnow(),
                )
                .order_by(ReleaseManifest.scheduled_for.asc())
            )
        )
        .scalars()
        .all()
    )


async def publish_due_manifests() -> dict[str, int]:
    """Publish every due, still-valid manifest.  Idempotent."""
    totals = {"due": 0, "published": 0, "failed": 0, "tenants": 0}
    async with async_session_factory() as tenant_session:
        tenant_ids = list((await tenant_session.execute(select(Tenant.id))).scalars().all())

    for tenant_id in tenant_ids:
        TENANT_CONTEXT_VAR.set(tenant_id)
        async with async_session_factory() as session:
            due = await _due_manifests(session, tenant_id)
            totals["tenants"] += 1
            totals["due"] += len(due)
            for manifest in due:
                current = await check_issue(session, tenant_id, manifest.volume, manifest.issue)
                if current["content_hash"] != manifest.content_hash:
                    manifest.status = "superseded"
                    manifest.payload = {
                        **manifest.payload,
                        "scheduler_failure": "content_changed",
                        "scheduler_failed_at": utcnow().isoformat(),
                    }
                    session.add(
                        AuditLog(
                            tenant_id=tenant_id,
                            actor_user_id=manifest.created_by,
                            action="release.scheduled_failed",
                            target_type="issue",
                            target_id=f"{manifest.volume}/{manifest.issue}",
                            payload={
                                "manifest_id": manifest.id,
                                "reason": "content_changed",
                                "manifest_hash": manifest.content_hash,
                                "current_hash": current["content_hash"],
                            },
                        )
                    )
                    totals["failed"] += 1
                    continue
                if current["status"] != "ready":
                    manifest.status = "superseded"
                    manifest.payload = {
                        **manifest.payload,
                        "scheduler_failure": "gate_blocked",
                        "scheduler_failed_at": utcnow().isoformat(),
                    }
                    session.add(
                        AuditLog(
                            tenant_id=tenant_id,
                            actor_user_id=manifest.created_by,
                            action="release.scheduled_failed",
                            target_type="issue",
                            target_id=f"{manifest.volume}/{manifest.issue}",
                            payload={
                                "manifest_id": manifest.id,
                                "reason": "gate_blocked",
                                "errors": current["error_count"],
                            },
                        )
                    )
                    totals["failed"] += 1
                    continue
                manifest.status = "published"
                manifest.published_at = utcnow()
                session.add(
                    AuditLog(
                        tenant_id=tenant_id,
                        actor_user_id=manifest.created_by,
                        action="release.scheduled_publish",
                        target_type="issue",
                        target_id=f"{manifest.volume}/{manifest.issue}",
                        payload={
                            "manifest_id": manifest.id,
                            "scheduled_for": manifest.scheduled_for.isoformat()
                            if manifest.scheduled_for
                            else None,
                            "resources": manifest.resource_count,
                        },
                    )
                )
                totals["published"] += 1
            await session.commit()
    return totals


async def _loop() -> None:
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            stats = await publish_due_manifests()
            if stats["due"]:
                logger.info("release_scheduler_done", **stats)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("release_scheduler_failed", exc_info=True)
        await asyncio.sleep(TICK_SECONDS)


def start_release_scheduler() -> None:
    global _task
    if settings.is_test or not settings.scheduler_enabled:
        return
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="rubbish-release-scheduler")
    logger.info("release_scheduler_started", tick_seconds=TICK_SECONDS)


async def stop_release_scheduler() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    logger.info("release_scheduler_stopped")


__all__ = [
    "publish_due_manifests",
    "start_release_scheduler",
    "stop_release_scheduler",
]
