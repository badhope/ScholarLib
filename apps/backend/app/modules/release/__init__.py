"""Release module: issue-level release gate, manifests and publish actions."""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry
from app.modules.release import models  # noqa: F401
from app.modules.release.routes import router

registry.register(
    ModuleManifest(
        name="release",
        version="0.1.0",
        description="Issue release gate, immutable manifests, and publish/schedule actions.",
        dependencies=frozenset({"catalog"}),
        router=router,
        admin_pages=("releases",),
    )
)

__all__ = ["router"]
