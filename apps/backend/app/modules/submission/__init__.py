"""Submission module — author → editor → catalog workflow.

Implements the ``resource_submissions`` flow in a module-shaped home,
with these deliberate design choices:

- Tenant-scoped (``tenant_id`` + RLS).
- ``resource_id`` is an integer FK to ``catalog.resources.id``; the
  catalog module uses int PKs everywhere.
- The approval path always creates a catalog ``Resource`` from the
  submission payload (``_materialize_resource_from_submission`` builds
  the ORM object and commits it in the same transaction as the status
  change — it does not go through an HTTP call to the catalog module).
- Notifications ARE wired: assignment / decision handlers call
  ``notifications.services.create()`` in the same transaction. Follower
  fan-out (notifying the *author's* followers) is not implemented.
"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry

# Importing this package registers Submission with the shared core
# Base.metadata, so Alembic and tests see it alongside the catalog tables
# without extra wiring.
from app.domain.submission import models  # noqa: F401
from app.interfaces.http.submission.routes import router

registry.register(
    ModuleManifest(
        name="submission",
        version="0.1.0",
        description="Author submission and editor review workflow.",
        dependencies=frozenset({"catalog"}),
        router=router,
    )
)
