"""Forum module — 社区讨论区（发帖 / 回帖 / 版主操作）。"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry
from app.domain.forum import models  # noqa: F401
from app.interfaces.http.forum.routes import router

registry.register(
    ModuleManifest(
        name="forum",
        version="1.0.0",
        description="Community discussion board: topics, replies, moderation.",
        dependencies=frozenset(),
        router=router,
    )
)
