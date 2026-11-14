"""Notifications module — in-app notification stream.

Implements the ``notifications`` flow in a module-shaped home.

Design choices:

- Tenant-scoped (``tenant_id`` + RLS).
- Cross-module fan-out IS wired: the submission module's assignment /
  decision handlers and the review module's report handler call
  ``notifications.services.create()`` inside the same transaction as
  the state change (see submission/routes.py, review/routes.py).
  Producers always go through the service helper — nothing writes
  Notification rows directly.
- No rate limiting in this module — the base spine does not wire one
  in yet, and adding it is a separate concern (cross-cutting
  middleware, not module-local).
"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry

# Importing this package registers Notification with the shared core
# Base.metadata so Alembic and tests see it alongside the core tables.
from app.domain.notifications import models  # noqa: F401
from app.interfaces.http.notifications.routes import router

registry.register(
    ModuleManifest(
        name="notifications",
        version="0.1.0",
        description="In-app notifications stream.",
        dependencies=frozenset(),
        router=router,
    )
)
