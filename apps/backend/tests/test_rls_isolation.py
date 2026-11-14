"""RLS isolation tests — must run against real PostgreSQL.

The main test suite uses SQLite in-memory (which has no Row Level
Security), so Rubbish's two-layer isolation claim is verified only
at the application-filter layer there. This file verifies the RLS layer
against a real PostgreSQL instance.

Skipped automatically when ``RUBBISH_DATABASE_URL`` does not
point to PostgreSQL. In CI, this is run as a separate job (see
``.github/workflows/ci.yml`` ``rls`` job) with a Postgres 17 service
container.

Experimental design:

  Experiment A — application filter correct, RLS enabled:
                user A queries own resources → expects N rows.

  Experiment B — application filter deliberately flawed, RLS enabled:
                user A queries tenant B's resources → expects 0 rows
                (RLS catches the leak).

  Experiment C — same flawed filter, RLS disabled:
                user A queries tenant B's resources → expects N rows
                (demonstrates the leak that RLS prevents).

Together B and C prove RLS is the layer doing the protection.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Skip the entire module when not on PostgreSQL.
DB_URL = os.environ.get("RUBBISH_DATABASE_URL", "")
if not DB_URL.startswith("postgresql"):
    pytest.skip(
        "RLS tests require PostgreSQL; set RUBBISH_DATABASE_URL=postgresql+asyncpg://...",
        allow_module_level=True,
    )

# Import models so Base.metadata includes catalog tables.
# These imports are intentional side-effects (model registration);
# the symbols themselves are unused, hence noqa: F401.
from app.domain.catalog.models import Resource  # noqa: E402, F401
from app.domain.library.models import ReadingListItem  # noqa: E402, F401
from app.models import Base  # noqa: E402


@pytest.fixture(scope="module")
async def pg_engine():
    """Real PostgreSQL engine, separate from conftest's SQLite override.

    Scope=module so the schema is created once and reused across tests
    in this file; teardown at module exit.
    """
    engine = create_async_engine(DB_URL, echo=False)
    # Create schema + enable RLS.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        # Apply RLS policies (mirror alembic/versions/001).
        await conn.execute(
            text(
                """
                ALTER TABLE resources ENABLE ROW LEVEL SECURITY;
                ALTER TABLE resources FORCE ROW LEVEL SECURITY;
                CREATE POLICY rls_resources ON resources
                    USING (tenant_id::text = current_setting('app.current_tenant_id', true));

                ALTER TABLE reading_list_items ENABLE ROW LEVEL SECURITY;
                ALTER TABLE reading_list_items FORCE ROW LEVEL SECURITY;
                CREATE POLICY rls_rli ON reading_list_items
                    USING (tenant_id::text = current_setting('app.current_tenant_id', true));
                """
            )
        )
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _seed_two_tenants(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert two tenants and return their UUIDs."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO tenants (id, slug, name, is_active, created_at, updated_at) "
            "VALUES (:id, :slug, :name, true, now(), now())"
        ),
        {"id": tenant_a, "slug": "tenant-a", "name": "Tenant A"},
    )
    await session.execute(
        text(
            "INSERT INTO tenants (id, slug, name, is_active, created_at, updated_at) "
            "VALUES (:id, :slug, :name, true, now(), now())"
        ),
        {"id": tenant_b, "slug": "tenant-b", "name": "Tenant B"},
    )
    await session.commit()
    return tenant_a, tenant_b


async def _seed_resources(session: AsyncSession, tenant_a: uuid.UUID, tenant_b: uuid.UUID) -> None:
    """Insert 5 resources per tenant."""
    for i in range(5):
        await session.execute(
            text(
                "INSERT INTO resources "
                "(tenant_id, doi, title, type, year, discipline, subdiscipline, "
                " publisher, external_url, created_at, updated_at) "
                "VALUES (:tid, :doi, :title, 'article', 2024, 'cs', 'ml', "
                " 'pub', NULL, now(), now())"
            ),
            {"tid": tenant_a, "doi": f"10.1000/a-{i}", "title": f"Tenant A resource {i}"},
        )
        await session.execute(
            text(
                "INSERT INTO resources "
                "(tenant_id, doi, title, type, year, discipline, subdiscipline, "
                " publisher, external_url, created_at, updated_at) "
                "VALUES (:tid, :doi, :title, 'article', 2024, 'cs', 'ml', "
                " 'pub', NULL, now(), now())"
            ),
            {"tid": tenant_b, "doi": f"10.1000/b-{i}", "title": f"Tenant B resource {i}"},
        )
    await session.commit()


@pytest.mark.asyncio
async def test_experiment_a_own_tenant_returns_all_rows(pg_engine):
    """Experiment A: user A queries own resources with RLS enabled.

    The app filter is correct (WHERE tenant_id = A) and RLS is enabled.
    Expected: all 5 of A's rows returned. RLS does not interfere with
    legitimate same-tenant queries.
    """
    Session = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        tenant_a, tenant_b = await _seed_two_tenants(session)
        await _seed_resources(session, tenant_a, tenant_b)

        # Set RLS context to tenant A.
        await session.execute(
            text(f"SELECT set_config('app.current_tenant_id', '{tenant_a}', true)")
        )
        result = await session.execute(
            text("SELECT count(*) FROM resources WHERE tenant_id = :tid"),
            {"tid": tenant_a},
        )
        count = result.scalar_one()
        assert count == 5, f"expected 5 own-tenant rows, got {count}"


@pytest.mark.asyncio
async def test_experiment_b_rls_catches_cross_tenant_leak(pg_engine):
    """Experiment B: deliberately flawed filter + RLS enabled → 0 leak.

    The app filter is *missing* the tenant_id WHERE clause (simulating a
    developer bug), but RLS is enabled. The query asks for tenant B's
    resources while the RLS context is tenant A. RLS should deny every
    row of tenant B, returning 0.

    This is the critical experiment proving the two-layer defense.
    """
    Session = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        # Re-seed (previous test's data persists at module scope, but
        # we re-seed deterministically per test for clarity).
        tenant_a, tenant_b = await _seed_two_tenants(session)
        await _seed_resources(session, tenant_a, tenant_b)

        # RLS context = tenant A.
        await session.execute(
            text(f"SELECT set_config('app.current_tenant_id', '{tenant_a}', true)")
        )
        # Deliberately flawed query: asks for tenant B's resources without
        # the correct app filter — only the tenant_id in the WHERE clause
        # is from the "attacker's" intent.
        result = await session.execute(
            text("SELECT count(*) FROM resources WHERE tenant_id = :tid_b"),
            {"tid_b": tenant_b},
        )
        count = result.scalar_one()
        assert count == 0, (
            f"RLS FAILED: cross-tenant leak detected — "
            f"tenant A context saw {count} of tenant B's rows"
        )


@pytest.mark.asyncio
async def test_experiment_c_disabling_rls_causes_leak(pg_engine):
    """Experiment C: same flawed filter + RLS disabled → leak confirmed.

    Same query as Experiment B, but RLS is disabled on `resources`.
    Without the RLS layer, the flawed filter returns tenant B's rows
    to tenant A's context — demonstrating that RLS is the layer
    providing the protection in Experiment B.

    After the test we re-enable RLS to leave the table in the
    expected state for subsequent tests.
    """
    Session = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        tenant_a, tenant_b = await _seed_two_tenants(session)
        await _seed_resources(session, tenant_a, tenant_b)

        # Disable RLS to demonstrate the leak.
        await session.execute(text("ALTER TABLE resources NO FORCE ROW LEVEL SECURITY"))
        # RLS context = tenant A (now irrelevant since FORCE is off).
        await session.execute(
            text(f"SELECT set_config('app.current_tenant_id', '{tenant_a}', true)")
        )
        # Flawed filter: asks for tenant B's resources.
        result = await session.execute(
            text("SELECT count(*) FROM resources WHERE tenant_id = :tid_b"),
            {"tid_b": tenant_b},
        )
        count = result.scalar_one()
        assert count == 5, (
            f"Expected leak of 5 rows with RLS disabled, got {count}. "
            "If this returns 0, the test setup is wrong."
        )
        # Restore RLS for subsequent tests.
        await session.execute(text("ALTER TABLE resources FORCE ROW LEVEL SECURITY"))
        await session.commit()


@pytest.mark.asyncio
async def test_rls_default_deny_when_no_context_set(pg_engine):
    """Default-deny: when no app.current_tenant_id is set, RLS returns 0 rows.

    ``current_setting('app.current_tenant_id', true)`` returns NULL when
    the setting is absent (the ``true`` arg = missing_ok). NULL never
    equals a non-null tenant_id, so RLS denies all rows. This is the
    fail-closed behavior that prevents data leaks if middleware fails
    to set the context.
    """
    Session = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        tenant_a, tenant_b = await _seed_two_tenants(session)
        await _seed_resources(session, tenant_a, tenant_b)

        # Do NOT set app.current_tenant_id — simulates middleware failure.
        # Use a fresh connection (not in a transaction that inherits a prior SET).
        await session.rollback()
        result = await session.execute(text("SELECT count(*) FROM resources"))
        count = result.scalar_one()
        assert count == 0, (
            f"Default-deny failed: RLS returned {count} rows when no "
            "tenant context was set. This is a fail-open vulnerability."
        )
