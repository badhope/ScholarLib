"""Announcements module — first-visit notice board."""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry
from app.domain.announcements import models  # noqa: F401
from app.interfaces.http.announcements.routes import router

registry.register(
    ModuleManifest(
        name="announcements",
        version="1.0.0",
        description="Site announcements shown as a first-visit welcome notice.",
        dependencies=frozenset(),
        router=router,
    )
)
