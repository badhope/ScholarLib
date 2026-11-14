"""Recommendations module — content-based resource recommendations.

Depends on catalog (``Resource``) and reader (``ReadingHistory``). Owns
no tables; recommendations are computed on demand from existing catalog
+ reader data. The scoring engine lives in ``engine.py``; the single
``GET /me`` endpoint lives in ``routes.py``.
"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry
from app.interfaces.http.recommendations.routes import router

registry.register(
    ModuleManifest(
        name="recommendations",
        version="0.1.0",
        description="Content-based resource recommendations from reading history.",
        dependencies=frozenset({"catalog", "reader"}),
        router=router,
    )
)
