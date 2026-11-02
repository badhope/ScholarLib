"""Optional Meilisearch full-text search integration.

Design mirrors ``app/core/monitoring.py`` (Sentry): the integration is
strictly opt-in and fail-open.

- ``settings.meilisearch_url`` empty  → everything here is a no-op and the
  catalog keeps using its built-in DB ILIKE search. The SDK is never
  imported, so self-hosters pay nothing for a feature they don't use.
- SDK missing / server down / index error → log a warning and degrade to
  DB search. Index-sync failures NEVER block the write path (a resource
  must save even if the search server is having a bad day).

Index layout: one index per deployment (``{prefix}_resources``) with a
``tenant_id`` filterable attribute — same multi-tenancy model as the DB
(application-layer tenant filter on every query).
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.core.config import settings as _cached_settings

logger = logging.getLogger(__name__)

# Lazily created async client; None until first successful init.
_client: Any | None = None
_init_failed = False

# Fields the index stores and searches. Kept minimal on purpose: the
# search result only needs ids (rows are re-fetched from the DB, which
# remains the source of truth and applies RLS).
_SEARCHABLE = ["title", "abstract", "authors", "keywords", "tags"]
_FILTERABLE = ["tenant_id", "type", "track", "discipline", "year"]


def search_enabled() -> bool:
    """True when a Meilisearch URL is configured (regardless of health)."""
    return bool(_cached_settings.meilisearch_url)


def _index_name() -> str:
    return f"{get_settings().meilisearch_index_prefix}_resources"


async def _get_client() -> Any | None:
    """Return a cached async client, or None when disabled/unavailable."""
    global _client, _init_failed
    if not search_enabled() or _init_failed:
        return None
    if _client is not None:
        return _client
    settings = get_settings()
    try:
        from meilisearch_python_sdk import AsyncClient
    except ImportError:
        logger.warning(
            "RUBBISH_MEILISEARCH_URL is set but the SDK is not installed; "
            "run 'uv sync --extra search'. Falling back to DB search."
        )
        _init_failed = True
        return None
    try:
        _client = AsyncClient(
            url=settings.meilisearch_url,
            api_key=settings.meilisearch_api_key or None,
        )
        index = _client.index(_index_name())
        # Idempotent settings push; creates the index on first use.
        await index.update_searchable_attributes(_SEARCHABLE)
        await index.update_filterable_attributes(_FILTERABLE)
    except Exception:
        logger.warning("Meilisearch init failed; falling back to DB search", exc_info=True)
        _client = None
        _init_failed = True
        return None
    return _client


def _to_document(resource: Any) -> dict[str, Any]:
    return {
        "id": resource.id,
        "tenant_id": str(resource.tenant_id),
        "title": resource.title,
        "abstract": resource.abstract or "",
        "authors": resource.authors or [],
        "keywords": resource.keywords or [],
        "tags": resource.tags or [],
        "type": resource.type,
        # track 进索引：目录的「正经/荒诞」筛选是主维度之一，若只在回表
        # 阶段过滤，搜索分页总数会与实际可见条数对不上。
        "track": getattr(resource, "track", "serious"),
        "discipline": resource.discipline,
        "year": resource.year,
    }


async def index_resource(resource: Any) -> None:
    """Add/update one resource in the index. Best-effort, never raises."""
    client = await _get_client()
    if client is None:
        return
    try:
        await client.index(_index_name()).add_documents([_to_document(resource)])
    except Exception:
        logger.warning("Meilisearch index_resource(%s) failed", resource.id, exc_info=True)


async def unindex_resource(resource_id: int) -> None:
    """Remove one resource from the index. Best-effort, never raises."""
    client = await _get_client()
    if client is None:
        return
    try:
        await client.index(_index_name()).delete_document(str(resource_id))
    except Exception:
        logger.warning("Meilisearch unindex_resource(%s) failed", resource_id, exc_info=True)


async def search_resource_ids(
    *,
    tenant_id: str,
    q: str,
    type_: str | None = None,
    track: str | None = None,
    discipline: str | None = None,
    year: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[int], int] | None:
    """Full-text search returning (ranked ids, total hits).

    Returns None when the feature is disabled or unavailable — callers
    MUST treat None as "fall back to DB search".
    """
    client = await _get_client()
    if client is None:
        return None
    filters = [f"tenant_id = {_quote(str(tenant_id))}"]
    if type_ is not None:
        filters.append(f"type = {_quote(type_)}")
    if track is not None:
        filters.append(f"track = {_quote(track)}")
    if discipline is not None:
        filters.append(f"discipline = {_quote(discipline)}")
    if year is not None:
        filters.append(f"year = {year}")
    try:
        result = await client.index(_index_name()).search(
            q,
            filter=" AND ".join(filters),
            offset=(page - 1) * page_size,
            limit=page_size,
            attributes_to_retrieve=["id"],
        )
    except Exception:
        logger.warning("Meilisearch search failed; falling back to DB", exc_info=True)
        return None
    ids = [int(hit["id"]) for hit in result.hits]
    total = int(result.estimated_total_hits or 0)
    return ids, total


def _quote(value: str) -> str:
    """Quote a string literal for a Meilisearch filter expression."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def reset_for_tests() -> None:
    """Test hook: drop the cached client/failure flag."""
    global _client, _init_failed
    _client = None
    _init_failed = False
