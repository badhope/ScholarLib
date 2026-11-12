"""Quality module — RQS v5.0 five-dimension, two-track rubric."""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry
from app.modules.quality.routes import router

registry.register(
    ModuleManifest(
        name="quality",
        version="1.0.0",
        description="RQS v5.0 paper quality rubric: five dimensions, two tracks, evidence required.",
        dependencies=frozenset(),
        router=router,
    )
)
