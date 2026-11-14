"""Peer-review module — editor→reviewer assignment + review report workflow.

Single-blind by default: reviewer identity visible to editors but not
to authors. Author-visible comments go in ``comments_to_author``; the
reviewer identity is not disclosed in the author-facing payload.

Tables:

- ``review_assignments`` — editor→reviewer invite, with status lifecycle.
- ``review_reports`` — the actual report (1:1 with assignment).

Dependencies: ``submission`` (FK to submissions.id), ``notifications``
(fan-out on assignment/decision).
"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry

# Registering this package imports models so SQLAlchemy Base.metadata
# sees the review_* tables alongside the submission + catalog tables.
from app.domain.review import models  # noqa: F401
from app.interfaces.http.review.routes import router

registry.register(
    ModuleManifest(
        name="review",
        version="0.1.0",
        description="Peer-review assignment and report workflow.",
        # 不在 dependencies 里声明 submission / notifications：submission.routes
        # 反向 import review.models（编辑分配审稿人），声明依赖会循环。
        # review.models 通过 Base.metadata 与 submission 共表空间，无加载顺序约束。
        dependencies=frozenset(),
        router=router,
    )
)
