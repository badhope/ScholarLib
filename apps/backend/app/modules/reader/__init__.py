"""Reader module — reading history + cross-device progress + PDF asset metadata.

Defines the reader model in a module-shaped home, with these deliberate
design choices:

- Both tables carry ``tenant_id`` (UUID FK) and rely on PostgreSQL RLS
  for isolation, matching ARCHITECTURE.md §Tenancy.
- ReadingHistory uses a "one row per (user, resource) pair" shape with
  embedded progress fields (page / progress_percent / duration_sec /
  last_read_at / completed). Splitting progress into a separate table
  would be over-engineering: they share the same lifecycle and
  visit_count already lives on the same row.
- FileAsset is tenant-scoped and owns no FK back to ``resources`` — the
  optional ``resources.pdf_file_id`` column is reserved for a future
  catalog-side migration that the reader module cannot make unilaterally
  (ARCHITECTURE.md: "Migrations are owned by the module that creates the
  table; another module cannot alter another module's tables").
- Upsert / IntegrityError retry pattern (the ``PUT /progress`` endpoint)
  is preserved: ``duration_sec`` accumulates, never overwrites.
"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry

# Importing this package registers FileAsset / ReadingHistory with the
# shared core Base.metadata, so Alembic and tests see the reader tables
# alongside the core tables without extra wiring.
from app.domain.reader import models  # noqa: F401
from app.interfaces.http.reader.routes import router

registry.register(
    ModuleManifest(
        name="reader",
        version="0.1.0",
        description="In-browser reader: reading history, cross-device progress, and PDF asset metadata.",
        dependencies=frozenset({"catalog"}),
        router=router,
    )
)
