"""Catalog module — resource records, disciplines, metadata.

The first real domain module. Defines the resource model in a
module-shaped home, with these deliberate design choices:

- Resource PK is int autoincrement (+ nullable ``slug`` for stable URLs)
  for sort stability and FK performance.
- ``authors`` stays as JSON list[str] (primary storage); an optional
  ``Author`` table is reserved for ORCID/affiliation enrichment.
- ``citation`` JSON column is dropped — export module renders citations
  at request time.
- ``view_count`` / ``download_count`` / ``citations`` move to a separate
  ``ResourceStat`` table to avoid write hotspots on the catalog row.
"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry

# Importing this package registers Resource / ResourceStat with the
# shared core Base.metadata, so Alembic and tests see the catalog tables
# alongside the core tables without extra wiring.
from app.domain.catalog import models  # noqa: F401
from app.interfaces.http.catalog.routes import router

registry.register(
    ModuleManifest(
        name="catalog",
        version="0.1.0",
        description="Resource records, disciplines, and metadata for the catalog.",
        dependencies=frozenset(),
        router=router,
    )
)

__all__ = ["router"]
