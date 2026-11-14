"""Gamification module — 9-tier ladder, XP ledger, achievements."""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry
from app.domain.gamification import models  # noqa: F401
from app.interfaces.http.gamification.routes import router

registry.register(
    ModuleManifest(
        name="gamification",
        version="1.0.0",
        description="Nine-tier permission ladder, XP ledger and achievement wall.",
        dependencies=frozenset(),
        router=router,
    )
)
