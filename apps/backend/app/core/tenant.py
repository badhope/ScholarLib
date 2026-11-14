"""Tenant resolution and request-scoped tenant context.

Two-layer design (see ARCHITECTURE.md §multi-tenant):

1. **Middleware** (``TenantContextMiddleware``) — runs before auth, resolves
   the tenant from host header (multi mode) or bootstrap slug (single mode),
   stores it in a ContextVar, returns 401 if no tenant can be resolved.

2. **DB dependency** (``app.core.db.get_db``) — reads the ContextVar and
   injects ``SET LOCAL app.current_tenant_id = :tid`` so PG RLS policies
   enforce isolation at the query planner level.

Why not just app-level filtering? RLS is the second line of defense: even
if a module forgets to add ``WHERE tenant_id = :tid``, RLS still denies
the row. ``SET LOCAL`` is transaction-scoped, so it's safe with PgBouncer
transaction pooling.
"""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar

from fastapi import HTTPException, status
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("rubbish.tenant")

# ---------------------------------------------------------------------------
# Host → tenant cache (in-memory, TTL-based)
# ---------------------------------------------------------------------------
# In multi-tenant mode, every request does a host-header lookup. Without a
# cache, this would hit the DB on every single request. The cache is a
# simple dict — no lock needed because writes are atomic in CPython, and
# even a stale read is harmless (worst case: one extra DB query).
#
# TTL is intentionally short so that an admin removing a host mapping takes
# effect within a few minutes. Long enough to absorb bursts, short enough
# to not require a cache-invalidation API for normal operations.
_HOST_CACHE_TTL_SECONDS = 300  # 5 minutes

_host_cache: dict[str, tuple[uuid.UUID | None, float]] = {}
"""Mapping of host (lowercased, port-stripped) → (tenant_id, expiry_ts)."""


def invalidate_host_cache(host: str | None = None) -> None:
    """Invalidate the host→tenant cache.

    If ``host`` is provided, remove only that entry. If ``None``, clear
    the entire cache. Called by the admin API after CRUD on tenant_hosts.
    """
    global _host_cache
    if host is None:
        _host_cache = {}
    else:
        _host_cache.pop(host.lower(), None)


# The current request's tenant id. Set by middleware, read by get_db.
# Default is None so non-HTTP contexts (background jobs, tests without
# middleware) fail safe — get_db skips the SET LOCAL, RLS denies rows.
TENANT_CONTEXT_VAR: ContextVar[uuid.UUID | None] = ContextVar(
    "tenant_id",
    default=None,
)

# Request id for log correlation (also set by middleware).
REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="-")


class TenantContextMiddleware:
    """Resolve tenant + request id, store in ContextVars.

    Single mode: resolve the bootstrap tenant once at startup, hardcode its
    UUID into the middleware. Multi mode: extract host header, look up the
    tenant in DB (cache the result). Both paths produce a ``uuid.UUID``
    that downstream code uses for ``SET LOCAL``.

    The first request to single mode will trigger bootstrap: if the
    bootstrap tenant does not yet exist, create it. This is idempotent.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        # In single mode, the tenant is fixed at startup. We resolve it
        # lazily on the first request because the DB may not be ready at
        # middleware construction time.
        self._single_mode_tenant_id: uuid.UUID | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Request id — reuse upstream header or generate.
        request_id = "-"
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                request_id = value.decode("ascii", errors="replace")
                break
        if request_id == "-":
            request_id = uuid.uuid4().hex[:16]
        request_id_token = REQUEST_ID_CTX.set(request_id)
        structlog_token = None
        try:
            from structlog.contextvars import bind_contextvars, clear_contextvars

            structlog_token = bind_contextvars(request_id=request_id)
        except Exception:
            # Diagnostics only — request-id binding must never break a request.
            logger.debug("request_id_bind_failed", exc_info=True)

        # Resolve tenant.
        tenant_id = await self._resolve_tenant(scope)
        tenant_token = TENANT_CONTEXT_VAR.set(tenant_id) if tenant_id else None

        if structlog_token is not None:
            try:
                from structlog.contextvars import bind_contextvars

                bind_contextvars(tenant_id=str(tenant_id) if tenant_id else "-")
            except Exception:
                # Diagnostics only.
                logger.debug("tenant_id_bind_failed", exc_info=True)

        try:
            await self.app(scope, receive, send)
        finally:
            if tenant_token is not None:
                TENANT_CONTEXT_VAR.reset(tenant_token)
            REQUEST_ID_CTX.reset(request_id_token)
            if structlog_token is not None:
                try:
                    from structlog.contextvars import clear_contextvars

                    clear_contextvars()
                except Exception:
                    # Context teardown is best-effort.
                    logger.debug("contextvars_clear_failed", exc_info=True)

    async def _resolve_tenant(self, scope: Scope) -> uuid.UUID | None:
        """Resolve the tenant id for this request.

        Returns ``None`` if no tenant can be resolved — in that case the
        downstream RLS policy will deny all rows (default-deny).
        """
        if settings.tenancy_mode == "single":
            if self._single_mode_tenant_id is None:
                self._single_mode_tenant_id = await self._ensure_bootstrap_tenant()
            return self._single_mode_tenant_id

        # Multi mode: extract host header, look up tenant.
        host = None
        for name, value in scope.get("headers", []):
            if name == b"host":
                host = value.decode("ascii", errors="replace")
                break
        if host is None:
            return None

        # Strip the port (e.g. "example.com:8080" → "example.com").
        host = host.split(":", 1)[0].strip().lower()
        if not host:
            return None

        return await self._resolve_tenant_by_host(host)

    async def _resolve_tenant_by_host(self, host: str) -> uuid.UUID | None:
        """Look up a tenant by host header, with in-memory caching.

        Cache hit: return the cached tenant_id if still valid.
        Cache miss: query the ``tenant_hosts`` table, cache the result
        (including negative results with a short TTL to avoid thundering
        on unknown hosts).
        """
        now = time.monotonic()

        # Check cache first.
        cached = _host_cache.get(host)
        if cached is not None:
            tenant_id, expiry = cached
            if now < expiry:
                return tenant_id
            # Expired — remove and fall through to DB query.
            _host_cache.pop(host, None)

        # Cache miss: query the DB.
        from sqlalchemy import select

        from app.core.db import async_session_factory
        from app.models import TenantHost

        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(TenantHost.tenant_id).where(
                        TenantHost.host == host,
                        TenantHost.is_active,
                    )
                )
                row = result.first()
        except Exception:
            logger.exception("tenant_host_lookup_failed", host=host)
            return None

        if row is None:
            # Negative cache: cache the miss for a short time so
            # repeated requests to unknown hosts don't hammer the DB.
            _host_cache[host] = (None, now + _HOST_CACHE_TTL_SECONDS)
            return None

        resolved: uuid.UUID | None = row[0]
        if resolved is None:
            return None
        _host_cache[host] = (resolved, now + _HOST_CACHE_TTL_SECONDS)
        return resolved

    async def _ensure_bootstrap_tenant(self) -> uuid.UUID:
        """Resolve (or lazily create) the bootstrap tenant in single mode.

        Idempotent: if the tenant already exists, return its id; otherwise
        create it. Safe to call from the first request.
        """
        from sqlalchemy import select

        from app.core.db import async_session_factory
        from app.models import Tenant

        slug = settings.bootstrap_tenant_slug
        async with async_session_factory() as session:
            result = await session.execute(select(Tenant).where(Tenant.slug == slug))
            tenant = result.scalar_one_or_none()
            if tenant is not None:
                return tenant.id
            tenant = Tenant(slug=slug, name=f"Bootstrap ({slug})", tenant_type="journal")
            session.add(tenant)
            await session.commit()
            await session.refresh(tenant)
            logger.info("bootstrap_tenant_created", slug=slug, tenant_id=str(tenant.id))
            return tenant.id


def get_current_tenant_id() -> uuid.UUID | None:
    """Return the current request's tenant id from the ContextVar."""
    return TENANT_CONTEXT_VAR.get()


def require_tenant_id() -> uuid.UUID:
    """Resolve tenant id or raise 400; write paths need an explicit scope."""
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context not resolved",
        )
    return tenant_id
