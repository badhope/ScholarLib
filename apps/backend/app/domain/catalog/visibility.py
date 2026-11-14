"""Public visibility rules for catalog records.

Two independent gates decide whether a record exists as far as the public is
concerned:

1. ``publication_status == "published"`` — editorial state (draft / in_review
   are never public).
2. ``publish_at`` — scheduled release. A published record whose ``publish_at``
   lies in the future is not yet visible: the issue sits in the editorial
   backlog and goes live on its date.

Keeping both conditions in one helper means every public surface (catalog
list, stats, facets, file, manuscript, comments, SEO, OAI, engagement) uses
the same rule. Divergence here is how a scheduled issue leaks.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ColumnElement, or_

from app.core.time import utcnow
from app.domain.catalog.models import Resource


def as_aware(value: datetime | None) -> datetime | None:
    """Normalise a stored timestamp to UTC-aware.

    SQLite (tests, local stack) drops tzinfo on round-trip; PostgreSQL returns
    aware values. Comparing naive with aware raises TypeError, so every
    Python-side comparison goes through this helper.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def public_conditions(now: datetime | None = None) -> list[ColumnElement[bool]]:
    """SQL conditions a record must satisfy to be publicly visible."""
    moment = now or utcnow()
    return [
        Resource.publication_status == "published",
        or_(Resource.publish_at.is_(None), Resource.publish_at <= moment),
    ]


def is_public(resource: Resource | None, now: datetime | None = None) -> bool:
    """Python-side equivalent of ``public_conditions`` for a loaded row."""
    if resource is None:
        return False
    if resource.publication_status != "published":
        return False
    moment = now or utcnow()
    publish_at = as_aware(resource.publish_at)
    return publish_at is None or publish_at <= moment


__all__ = ["as_aware", "is_public", "public_conditions"]
