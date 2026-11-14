"""Comments module — reader discussion on published resources.

Design choices:

- Tenant-scoped (``tenant_id`` + RLS, migration 007).
- 游客可读（GET 公开），登录可评（POST 要求 auth），本人或管理员可删
  （DELETE + ``comment.delete`` 审计）。不可编辑——时间线保持诚实。
- 只能评论已刊出资源（未刊稿一律 404，与目录预览边界一致）。
- 限流走共享 RateLimitMiddleware（/api/comments 在 STRICT_PATHS）。
"""

from __future__ import annotations

from app.core.modules import ModuleManifest, registry

# Importing this package registers Comment with the shared core
# Base.metadata so Alembic and tests see it.
from app.domain.comments import models  # noqa: F401
from app.interfaces.http.comments.routes import router

registry.register(
    ModuleManifest(
        name="comments",
        version="0.1.0",
        description="Reader comments on published resources.",
        dependencies=frozenset(),
        router=router,
    )
)
