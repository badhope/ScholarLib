"""Rate limit middleware tests.

The middleware is disabled in test env via ``settings.is_test``. We test
the core logic directly against a middleware instance wrapping a stub
ASGI app, without booting the real FastAPI stack.
"""

from __future__ import annotations

import os

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

os.environ.setdefault("RUBBISH_ENVIRONMENT", "test")
os.environ.setdefault("RUBBISH_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.core import config as config_module
from app.middleware.rate_limit import RateLimitMiddleware


async def _stub_app(scope: Scope, receive: Receive, send: Send) -> None:
    """Minimal ASGI app that always returns 200 OK."""
    response: Response = JSONResponse({"ok": True})
    await response(scope, receive, send)


def _make_request(path: str, method: str = "POST", client_host: str = "1.2.3.4") -> Request:
    """Build a Starlette Request with a fake client + path."""
    scope: Scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": (client_host, 12345),
        "scheme": "http",
        "server": ("test", 80),
        "root_path": "",
        "app": None,
    }
    return Request(scope)


@pytest.fixture
def rate_limiter_with_strict_env(monkeypatch):
    """Build a fresh middleware with rate limiting enabled (is_test=False)."""
    monkeypatch.setattr(type(config_module.settings), "is_test", property(lambda self: False))
    mw = RateLimitMiddleware(_stub_app, default_per_minute=120)
    yield mw
    monkeypatch.setattr(
        type(config_module.settings),
        "is_test",
        property(lambda self: self.environment == "test"),
    )


@pytest.mark.asyncio
async def test_blocks_after_threshold(rate_limiter_with_strict_env) -> None:
    """After exceeding the strict limit, dispatch returns 429."""
    mw = rate_limiter_with_strict_env
    # login limit is 10/min
    for i in range(10):
        resp = await mw.dispatch(_make_request("/api/auth/login"), lambda req: _ok())
        assert resp.status_code == 200, f"req {i} blocked early"
    blocked = await mw.dispatch(_make_request("/api/auth/login"), lambda req: _ok())
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


@pytest.mark.asyncio
async def test_global_limit_uses_default(rate_limiter_with_strict_env) -> None:
    """Non-strict paths use the default per-minute limit."""
    mw = rate_limiter_with_strict_env
    # default is 120 — 5 requests should all pass
    for _ in range(5):
        resp = await mw.dispatch(_make_request("/api/health", method="GET"), lambda req: _ok())
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_options_bypasses(rate_limiter_with_strict_env) -> None:
    """OPTIONS requests (CORS preflight) are not counted."""
    mw = rate_limiter_with_strict_env
    for _ in range(30):
        resp = await mw.dispatch(
            _make_request("/api/auth/login", method="OPTIONS"), lambda req: _ok()
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_documents_and_static_assets_bypass(rate_limiter_with_strict_env) -> None:
    """SPA 文档与静态资源不计入限流。

    一次文章页加载会附带几十个静态资源请求；若与 API 共享 120/分 的
    桶，真人翻十几篇就会被 429，浏览器直接导航到的 HTML 路由还会把
    JSON 错误原样渲染在屏幕上。限流只对 /api 生效。
    """
    mw = rate_limiter_with_strict_env
    for i in range(200):
        for path in ("/catalog/291", "/assets/index-abc.js", "/uploads/x.webp"):
            resp = await mw.dispatch(_make_request(path, method="GET"), lambda req: _ok())
            assert resp.status_code == 200, f"{path} blocked at {i}"
    # API 桶不受影响，仍按原阈值拦截
    for _ in range(10):
        await mw.dispatch(_make_request("/api/auth/login"), lambda req: _ok())
    assert (await mw.dispatch(_make_request("/api/auth/login"), lambda req: _ok())).status_code == 429


@pytest.mark.asyncio
async def test_comments_read_not_strict(rate_limiter_with_strict_env) -> None:
    """评论列表（GET）不吃 20 次/分 的严格阈值，只有发表（POST）吃。

    每打开一篇文章都会拉一次评论列表；按写接口的阈值限读，会让正常
    翻页的读者看到「评论加载失败」。
    """
    mw = rate_limiter_with_strict_env
    for i in range(60):
        resp = await mw.dispatch(
            _make_request("/api/comments", method="GET"), lambda req: _ok()
        )
        assert resp.status_code == 200, f"GET blocked at {i}"
    for _ in range(20):
        resp = await mw.dispatch(_make_request("/api/comments", method="POST"), lambda req: _ok())
        assert resp.status_code == 200
    assert (await mw.dispatch(_make_request("/api/comments", method="POST"), lambda req: _ok())).status_code == 429


@pytest.mark.asyncio
async def test_test_env_skipped(client) -> None:
    """In test env, the real app skips rate limiting entirely."""
    for _ in range(15):
        r = await client.post(
            "/api/auth/login",
            json={"username": "x", "password": "wrongpass"},
        )
        assert r.status_code in (401, 422)


async def _ok() -> Response:
    return JSONResponse({"ok": True})
