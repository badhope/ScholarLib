"""Tenant-scoped, admin-editable site switches.

These are runtime policy flags that must survive a restart and differ from
the process environment defaults. They live in ``tenants.settings`` next to
the existing ``review_mode`` key so a single deployment does not need a
second settings table.

Only booleans with an explicit default are accepted; unknown keys are
rejected at the API boundary instead of silently growing a settings blob.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Tenant


def _default_for(key: str) -> bool:
    """Process default, read live so tests / env reloads are reflected."""
    if key == "captcha_required_for_registration":
        return bool(settings.captcha_required_for_registration)
    if key == "doi_author_entry_enabled":
        return True
    raise KeyError(key)


SITE_FLAGS: tuple[str, ...] = (
    "captcha_required_for_registration",
    "doi_author_entry_enabled",
)


async def get_site_flag(
    db: AsyncSession,
    tenant_id: UUID,
    key: str,
) -> bool:
    """Read a flag, falling back to the process default when unset."""
    default = _default_for(key)
    blob = (
        await db.execute(select(Tenant.settings).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if isinstance(blob, dict) and isinstance(blob.get(key), bool):
        return bool(blob[key])
    return default


async def get_all_site_flags(db: AsyncSession, tenant_id: UUID) -> dict[str, bool]:
    return {key: await get_site_flag(db, tenant_id, key) for key in SITE_FLAGS}


async def set_site_flag(
    db: AsyncSession,
    tenant_id: UUID,
    key: str,
    value: bool,
) -> None:
    """Persist one boolean flag without clobbering other tenant settings."""
    if key not in SITE_FLAGS:
        raise KeyError(key)
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if tenant is None:
        raise LookupError("Tenant not found")
    merged: dict[str, Any] = dict(tenant.settings or {})
    merged[key] = bool(value)
    tenant.settings = merged
