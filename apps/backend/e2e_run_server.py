"""E2E test server bootstrap script.

启动一个为 E2E 测试用的后端:SQLite + test 模式(让 lifespan 跳过 RLS、
让 rate_limit 中间件整体跳过 — 单 IP 滑动窗口会让顺序 E2E 测试相互饿死)。

额外注入两个 dev-only 资源(无论 environment 都会注册,production 不会执行此脚本):
- MemoryEmailSender: 替换 ConsoleEmailSender,把每封邮件存到内存列表
- GET /api/dev/email-outbox: 返回最近 N 封邮件正文(用于 E2E 提取验证 token)
- POST /api/dev/verify-email-by-email: 通过邮箱直接置 is_email_verified=true

Usage:
    uv run python e2e_run_server.py
"""

from __future__ import annotations

import asyncio
import os
import secrets

# 在导入 app 之前设好 env。
# environment="test" 而非 "development"：rate_limit 中间件在 test 模式下整体跳过
# （见 app/middleware/rate_limit.py:52 的 `if settings.is_test`）。
# STRICT_PATHS 中 /api/auth/login 限 10/min，56 个 E2E 测试都用 admin 登录 + 注册
# 新用户登录，几分钟内必然超 10 次，会触发 429 让 loginViaUi 的 waitForURL(/dashboard)
# 超时。test 模式还让 email_backend 默认走 console（覆盖在 _mem_sender 之前）。
os.environ["RUBBISH_ENVIRONMENT"] = "test"
# F7：per-worker DB 分片。E2E_DB_PATH 让 CI 多 lane / 多 worker 各自持有独立
# SQLite 文件，避免共享单库在并发写时锁竞争；默认路径保持原样（兼容单 lane）。
_db_path = os.environ.get("E2E_DB_PATH", "./e2e_test.db")
os.environ["RUBBISH_DATABASE_URL"] = f"sqlite+aiosqlite:///{_db_path}"
# Use a strong random key (per-run) — required because development mode rejects weak keys.
os.environ["RUBBISH_SECRET_KEY"] = secrets.token_hex(32)
os.environ["RUBBISH_ADMIN_PASSWORD"] = "e2e_admin_pw_12345678"
os.environ["RUBBISH_ADMIN_EMAIL"] = "admin@e2e.test"
os.environ["RUBBISH_ADMIN_USERNAME"] = "admin"
os.environ["RUBBISH_CORS_ORIGINS"] = (
    "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173"
)
os.environ["RUBBISH_ALLOWED_HOSTS"] = "localhost,127.0.0.1"
os.environ["RUBBISH_RATE_LIMIT_PER_MINUTE"] = "600"
os.environ["RUBBISH_DEBUG"] = "true"
os.environ["RUBBISH_LOG_LEVEL"] = "WARNING"
os.environ["RUBBISH_JSON_LOGS"] = "false"
os.environ["RUBBISH_EMAIL_BACKEND"] = "console"
# outbound guard 默认关闭；E2E 用内存 sender 捕获邮件，不触网。
# 不打开这个开关，get_email_sender() 会把 _mem_sender 换回 Console，
# capabilities.email_delivery=false，注册页就会直接跳登录而不是验证页。
os.environ["RUBBISH_EMAIL_OUTBOUND_ENABLED"] = "true"
# 文件存储必须显式指到本目录：默认值 /data/uploads 在 CI runner（非 root）
# 上不可写，权限拒绝会让上传接口 500，对应 E2E 用例等不到"文件已上传"。
# 本地开发不炸只是因为 .env 恰好配置了可写路径。
os.environ["RUBBISH_STORAGE_BACKEND"] = "local"
os.environ["RUBBISH_STORAGE_PATH"] = "./storage"

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import email as email_module
from app.models import Base


class MemoryEmailSender:
    """Dev-only email sender that captures messages in-memory for E2E."""

    def __init__(self) -> None:
        self.outbox: list[dict[str, str]] = []

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        html: str | None = None,
    ) -> None:
        self.outbox.append({"to": to, "subject": subject, "body": body, "html": html or ""})

    def reset(self) -> None:
        self.outbox.clear()


# 全局实例:e2e_run_server 进程内只有一个,_dev_email_router 会引用它
_mem_sender = MemoryEmailSender()
email_module._sender = _mem_sender


async def _prepare_db() -> None:
    """Drop + recreate all tables so each E2E run starts fresh."""
    # 模块用自己的 Base 子类，import 后才会注册到 core Base.metadata。
    # 否则 create_all 只会建 core 6 张表（tenants/users/roles/...），
    # catalog/submissions/reviews 等模块表全缺。
    from app.core.modules import load_all

    load_all()

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{_db_path}",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("[e2e] DB prepared (SQLite, all tables created)")


async def _run_bootstrap_manual() -> None:
    """手动执行 bootstrap，绕过 run_bootstrap() 的 is_test 短路。

    test 模式下 lifespan 调用的 run_bootstrap() 会直接 return（设计给
    pytest fixture 自己建用户）。E2E 走完整 lifespan + UI 登录，必须
    有 bootstrap admin；这里手动调底层函数复用同一份逻辑。
    """
    from app.core.bootstrap import (
        _ensure_admin_roles,
        _ensure_admin_user,
        _ensure_bootstrap_tenant,
        _ensure_review_roles,
    )
    from app.core.db import async_session_factory

    async with async_session_factory() as session:
        tenant = await _ensure_bootstrap_tenant(session)
        await _ensure_admin_user(session, tenant)
        await _ensure_review_roles(session, tenant)
        await _ensure_admin_roles(session, tenant)
    print("[e2e] bootstrap completed (tenant + admin + roles)")


def _install_dev_routes() -> None:
    """Register dev-only endpoints on the FastAPI app.

    These endpoints exist ONLY when the server is started via this script
    (development mode + e2e_run_server.py). The main app factory never
    registers them, so production deployments cannot expose them.
    """
    from sqlalchemy import select, update

    from app.core.db import async_session_factory
    from app.models import User

    router = APIRouter(prefix="/api/dev", tags=["dev-e2e-only"])

    @router.get("/email-outbox")
    async def email_outbox(limit: int = 10) -> dict:
        """Return up to ``limit`` most recent captured emails."""
        return {
            "count": len(_mem_sender.outbox),
            "emails": list(reversed(_mem_sender.outbox[-limit:])),
        }

    @router.post("/email-outbox/reset")
    async def email_outbox_reset() -> dict:
        _mem_sender.reset()
        return {"ok": True}

    @router.post("/verify-email-by-email")
    async def verify_email_by_email(request: Request) -> dict:
        """Mark a user's email as verified directly (skip the email flow).

        E2E tests use this as a fallback when extracting the token from
        the email body is impractical.
        """
        payload = await request.json()
        email = (payload or {}).get("email")
        if not email:
            raise HTTPException(status_code=400, detail="email required")
        async with async_session_factory() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if user is None:
                raise HTTPException(status_code=404, detail="user not found")
            if not user.is_email_verified:
                await session.execute(
                    update(User).where(User.id == user.id).values(is_email_verified=True)
                )
                await session.commit()
            return {"ok": True, "user_id": user.id, "email": user.email}

    # 延迟 import 避免触发 lifespan
    from app.main import app

    app.include_router(router)
    print("[e2e] dev-only routes installed: /api/dev/email-outbox, /api/dev/verify-email-by-email")


if __name__ == "__main__":
    import uvicorn

    # 默认每次启动都重建数据库（E2E 需要干净起点）。
    # E2E_KEEP_DB=1 时保留已有数据：给截图/录屏这类"先灌演示数据再重启后端"
    # 的场景用，避免刚灌好的数据被删掉。CI 走默认值，行为不变。
    if os.environ.get("E2E_KEEP_DB") == "1":
        print("[e2e] E2E_KEEP_DB=1 — 保留现有数据库")
    else:
        if os.path.exists(_db_path):
            os.remove(_db_path)
        asyncio.run(_prepare_db())
    # test 模式下 lifespan 的 run_bootstrap() 会直接 return（见
    # app/core/bootstrap.py:103 的 `if settings.is_test: return`）。
    # 这里手动调用底层函数绕过 is_test 检查，确保 bootstrap tenant + admin
    # user + reviewer/editor roles 都被创建。
    asyncio.run(_run_bootstrap_manual())
    _install_dev_routes()
    port = int(os.environ.get("E2E_PORT", "8000"))
    print(f"[e2e] admin password: {os.environ['RUBBISH_ADMIN_PASSWORD']}")
    print(f"[e2e] Starting uvicorn on http://localhost:{port} (DB: {_db_path})")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False,
    )
