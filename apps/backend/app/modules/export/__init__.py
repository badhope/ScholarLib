"""Export module — citation export (BibTeX / RIS / CSV / JSON).

A thin module: ``exporters.py`` is a set of pure serialization functions
duck-typed on an ``Exportable`` protocol; ``routes.py`` fetches resources
from the catalog module and pipes them through the serializers. The
module owns no database tables.

Depends on ``catalog`` for the Resource table — declared in the manifest
so the registry enforces load order.
"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry
from app.interfaces.http.export.routes import router

registry.register(
    ModuleManifest(
        name="export",
        version="0.1.0",
        description="Citation export in BibTeX / RIS / CSV / JSON formats.",
        dependencies=frozenset({"catalog"}),
        router=router,
    )
)
