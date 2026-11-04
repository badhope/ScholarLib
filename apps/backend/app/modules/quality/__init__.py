"""Quality module — RQS v3.0 scoring rubric."""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry
from app.modules.quality.routes import router

registry.register(
    ModuleManifest(
        name="quality",
        version="1.0.0",
        description="RQS v3.0 paper quality rubric and per-article score surface.",
        dependencies=frozenset(),
        router=router,
    )
)
