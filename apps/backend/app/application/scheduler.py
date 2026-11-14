"""In-process periodic maintenance jobs (0.8.0).

A single asyncio task started with the app lifespan. It is deliberately
simple: one loop, fixed interval, all job bodies are idempotent and
tenant-scoped. For a single-node deployment (this journal) an in-process
scheduler is the right size — no Redis/Celery broker to operate.

Jobs:

- ``review_reminders``: nudge reviewers on stale assignments (in-app
  notification always; email when SMTP is configured).

Design notes:

- The loop never raises: each job is wrapped, failures logged and retried
  on the next tick, so a bad row cannot kill the scheduler.
- First run is delayed by ``STARTUP_DELAY_SECONDS`` so a deploy is not
  competing with migrations/bootstrap.
- Tenants are enumerated explicitly; each tenant gets its own DB session
  with ``set_config('app.current_tenant_id')`` so RLS policies apply.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.db import async_session_factory
from app.core.logging import get_logger
from app.models import Tenant

logger = get_logger("rubbish.scheduler")

STARTUP_DELAY_SECONDS = settings.scheduler_startup_delay_seconds
INTERVAL_SECONDS = settings.scheduler_interval_seconds

_task: asyncio.Task[None] | None = None


async def _tenant_ids() -> list[Any]:
    async with async_session_factory() as session:
        rows = (await session.execute(select(Tenant.id))).scalars().all()
        return list(rows)


async def _run_review_reminders() -> dict[str, int]:
    from app.core.tenant import TENANT_CONTEXT_VAR
    from app.domain.submission.review_reminders import run_overdue_reminders

    totals = {"checked": 0, "reminded": 0, "emailed": 0, "tenants": 0}
    for tenant_id in await _tenant_ids():
        TENANT_CONTEXT_VAR.set(tenant_id)
        async with async_session_factory() as session:
            stats = await run_overdue_reminders(session, tenant_id=tenant_id)
        totals["tenants"] += 1
        for key in ("checked", "reminded", "emailed"):
            totals[key] += stats.get(key, 0)
    return totals


Job = tuple[str, Callable[[], Awaitable[dict[str, int]]]]

JOBS: list[Job] = [
    ("review_reminders", _run_review_reminders),
]


async def _loop() -> None:
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        for name, job in JOBS:
            try:
                stats = await job()
                logger.info("scheduler_job_done", job=name, **stats)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("scheduler_job_failed", job=name, exc_info=True)
        try:
            await asyncio.sleep(INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise


def start_scheduler() -> None:
    """Start the background loop (no-op in tests / when disabled)."""
    global _task
    if settings.is_test or not settings.scheduler_enabled:
        return
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop(), name="rubbish-scheduler")
    logger.info(
        "scheduler_started",
        startup_delay_seconds=STARTUP_DELAY_SECONDS,
        interval_seconds=INTERVAL_SECONDS,
    )


async def stop_scheduler() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    logger.info("scheduler_stopped")


async def run_job_now(name: str) -> dict[str, int]:
    """Manual trigger (used by an admin endpoint and by tests)."""
    for job_name, job in JOBS:
        if job_name == name:
            return await job()
    raise KeyError(name)


__all__ = ["INTERVAL_SECONDS", "JOBS", "run_job_now", "start_scheduler", "stop_scheduler"]
