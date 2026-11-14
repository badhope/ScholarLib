"""Scheduler lifecycle and job-loop tests (0.8.0 in-process maintenance).

The scheduler is a no-op under ``settings.is_test`` so these tests drive
the guards, the loop, and the job dispatch directly with monkeypatched
timings — no real 90s startup delay or 6h interval is ever awaited.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import scheduler
from app.core import db as db_module
from app.core.config import settings


@pytest.mark.asyncio
async def test_run_job_now_unknown_name_raises() -> None:
    with pytest.raises(KeyError):
        await scheduler.run_job_now("does-not-exist")


@pytest.mark.asyncio
async def test_run_job_now_dispatches_to_matching_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_job() -> dict[str, int]:
        calls.append("ran")
        return {"checked": 3, "reminded": 1, "emailed": 0}

    monkeypatch.setattr(scheduler, "JOBS", [("fake", fake_job)])
    stats = await scheduler.run_job_now("fake")
    assert stats == {"checked": 3, "reminded": 1, "emailed": 0}
    assert calls == ["ran"]


@pytest.mark.asyncio
async def test_start_scheduler_is_noop_in_test_environment() -> None:
    assert settings.is_test is True
    scheduler.start_scheduler()
    assert scheduler._task is None


@pytest.mark.asyncio
async def test_start_scheduler_noop_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    scheduler.start_scheduler()
    assert scheduler._task is None


@pytest.mark.asyncio
async def test_start_and_stop_scheduler_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(scheduler, "STARTUP_DELAY_SECONDS", 3600)
    try:
        scheduler.start_scheduler()
        task = scheduler._task
        assert task is not None and not task.done()

        # Double start keeps the existing task instead of spawning another.
        scheduler.start_scheduler()
        assert scheduler._task is task

        await scheduler.stop_scheduler()
        assert task.done()
        assert scheduler._task is None

        # Stopping with no task is a no-op, not an error.
        await scheduler.stop_scheduler()
    finally:
        if scheduler._task is not None:
            await scheduler.stop_scheduler()


@pytest.mark.asyncio
async def test_loop_runs_jobs_every_tick_and_swallows_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counters = {"ok": 0, "bad": 0}

    async def ok_job() -> dict[str, int]:
        counters["ok"] += 1
        return {"checked": 1}

    async def bad_job() -> dict[str, int]:
        counters["bad"] += 1
        raise ValueError("boom")

    monkeypatch.setattr(scheduler, "STARTUP_DELAY_SECONDS", 0)
    monkeypatch.setattr(scheduler, "INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(scheduler, "JOBS", [("ok", ok_job), ("bad", bad_job)])

    task = asyncio.create_task(scheduler._loop())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert counters["ok"] >= 2
    assert counters["bad"] >= 2


@pytest.mark.asyncio
async def test_tenant_ids_returns_all_tenants(
    client: Any,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models import Tenant

    warmup = await client.get("/api/health")
    warmup.raise_for_status()
    db_session.add(Tenant(slug="alpha", name="Alpha"))
    await db_session.commit()

    monkeypatch.setattr(scheduler, "async_session_factory", db_module.async_session_factory)
    ids = await scheduler._tenant_ids()
    assert len(ids) == 2  # bootstrap "default" + "alpha"


@pytest.mark.asyncio
async def test_run_review_reminders_aggregates_across_tenants(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.tenant import TENANT_CONTEXT_VAR
    from app.domain.submission import review_reminders as rr

    tenant_a: Any = object()
    tenant_b: Any = object()
    seen: list[tuple[Any, Any]] = []

    async def fake_ids() -> list[Any]:
        return [tenant_a, tenant_b]

    async def fake_reminders(session: AsyncSession, *, tenant_id: Any) -> dict[str, int]:
        seen.append((tenant_id, TENANT_CONTEXT_VAR.get()))
        return {"checked": 2, "reminded": 1, "emailed": 1}

    @asynccontextmanager
    async def fake_factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(scheduler, "_tenant_ids", fake_ids)
    monkeypatch.setattr(scheduler, "async_session_factory", fake_factory)
    monkeypatch.setattr(rr, "run_overdue_reminders", fake_reminders)

    totals = await scheduler._run_review_reminders()
    assert totals == {"checked": 4, "reminded": 2, "emailed": 2, "tenants": 2}
    # The tenant ContextVar is set around each per-tenant run so RLS applies.
    assert seen[0][0] is tenant_a and seen[0][1] is tenant_a
    assert seen[1][0] is tenant_b and seen[1][1] is tenant_b
