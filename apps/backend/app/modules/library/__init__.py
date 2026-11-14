"""Library module — member-curated reading lists.

A reading list is a named, ordered collection of catalog resources
owned by a user. Items are added (idempotent) and removed (idempotent).
Lists are private to their owner; ``is_public`` is intentionally not
implemented (YAGNI — add when a sharing feature actually lands).

Depends on the catalog module (Resource FK).
"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry
from app.domain.library import models  # noqa: F401
from app.interfaces.http.library.routes import router

registry.register(
    ModuleManifest(
        name="library",
        version="0.1.0",
        description="Member-curated reading lists.",
        dependencies=frozenset({"catalog"}),
        router=router,
    )
)
