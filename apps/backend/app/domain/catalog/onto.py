"""Discipline ontology access + validation helpers.

The catalog stores ``discipline`` and ``subdiscipline`` as strings on
each ``Resource`` row. These helpers check whether a given string
maps to an entry in the ``disciplines`` / ``subdisciplines`` tables
for the current tenant, and (when the discipline is set) whether the
subdiscipline actually belongs to that discipline.

Used by the catalog create / update endpoints so we reject obviously
wrong taxonomy input at the boundary instead of letting bad strings
silently land in the DB.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.catalog.models import Discipline, Subdiscipline

TenantUUID = uuid.UUID


class DisciplineNotFound(ValueError):
    """Raised when a discipline slug doesn't exist for the tenant."""


class SubdisciplineMismatch(ValueError):
    """Raised when subdiscipline doesn't belong to the given discipline."""


async def get_discipline_by_name(
    db: AsyncSession, *, tenant_id: TenantUUID, name: str
) -> Discipline | None:
    """Return the Discipline row whose ``name`` matches ``name``.

    The catalog stores the human-readable display name on each
    Resource, so we look up by name (case-sensitive exact match).
    """
    if not name:
        return None
    stmt = select(Discipline).where(Discipline.tenant_id == tenant_id, Discipline.name == name)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_subdiscipline_by_name(
    db: AsyncSession,
    *,
    tenant_id: TenantUUID,
    discipline_id: int,
    name: str,
) -> Subdiscipline | None:
    """Return the Subdiscipline row whose ``name`` matches ``name``
    under the given ``discipline_id``, or None."""
    if not name:
        return None
    stmt = select(Subdiscipline).where(
        Subdiscipline.tenant_id == tenant_id,
        Subdiscipline.discipline_id == discipline_id,
        Subdiscipline.name == name,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def assert_discipline_valid(
    db: AsyncSession, *, tenant_id: TenantUUID, discipline_name: str
) -> Discipline | None:
    """Look up ``discipline_name`` for the tenant.

    If the tenant has **zero** disciplines registered, the ontology is
    considered unconfigured and this check is a no-op (any discipline
    string is allowed). Once at least one discipline exists, the
    check becomes strict. This lets teams bootstrap resources before
    setting up the controlled vocabulary.
    """
    # Fast-path: no ontology configured for this tenant yet.
    count = await db.scalar(
        select(func.count(Discipline.id)).where(Discipline.tenant_id == tenant_id)
    )
    if count == 0:
        return None

    discipline = await get_discipline_by_name(db, tenant_id=tenant_id, name=discipline_name)
    if discipline is None:
        raise DisciplineNotFound(f"Unknown discipline: {discipline_name!r}")
    return discipline


async def assert_subdiscipline_matches(
    db: AsyncSession,
    *,
    tenant_id: TenantUUID,
    discipline: Discipline,
    subdiscipline_name: str,
) -> Subdiscipline:
    """Validate that ``subdiscipline_name`` exists under ``discipline``.

    Raises :class:`SubdisciplineMismatch` if the subdiscipline exists
    in the tenant but belongs to a different discipline, and
    :class:`DisciplineNotFound` if it doesn't exist at all.
    """
    sub = await get_subdiscipline_by_name(
        db,
        tenant_id=tenant_id,
        discipline_id=discipline.id,
        name=subdiscipline_name,
    )
    if sub is None:
        any_sub = (
            await db.execute(
                select(Subdiscipline).where(
                    Subdiscipline.tenant_id == tenant_id,
                    Subdiscipline.name == subdiscipline_name,
                )
            )
        ).scalar_one_or_none()
        if any_sub is None:
            raise DisciplineNotFound(f"Unknown subdiscipline: {subdiscipline_name!r}")
        raise SubdisciplineMismatch(
            f"Subdiscipline {subdiscipline_name!r} does not belong to "
            f"discipline {discipline.name!r}"
        )
    return sub


__all__ = [
    "DisciplineNotFound",
    "SubdisciplineMismatch",
    "assert_discipline_valid",
    "assert_subdiscipline_matches",
    "get_discipline_by_name",
    "get_subdiscipline_by_name",
]
