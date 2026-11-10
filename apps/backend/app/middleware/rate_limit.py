"""Per-IP rate limiting middleware.

Delegates bucket storage to ``app.core.rate_limit_store``. The
middleware itself is responsible for:

- Mapping incoming requests to ``(ip, path_bucket)`` keys.
- Picking the per-path limit from ``STRICT_PATHS`` or the global
  default from settings.
- Translating "denied" into a 429 with a sane ``Retry-After``.

The middleware never calls Redis directly; the store handles that.
This keeps the middleware unit-testable without a Redis dependency
and means swapping the backend never touches the middleware code.

Sensitive auth endpoints get a stricter limit than the global default.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.metrics import inc_rate_limit_rejection
from app.core.rate_limit_store import get_rate_limiter_store

# Per-endpoint stricter limits: path -> max requests per minute
#
# 取值原则：按「一个人正常能点多快」定，而不是按「脚本能点多快」。
# 同一办公网 / 校园网 / 运营商 NAT 后面的多个用户共享出口 IP，
# 阈值压得太低会误伤整层楼。真正的暴力破解由账号锁定与
# 6 位 2FA 的低尝试窗口兜住；发信轰炸由收件地址护栏
# （app.core.mail_guard）按收件人计数，换 IP 绕不过去。
STRICT_PATHS: dict[str, int] = {
    # 2FA 码只有 6 位数字：code 交换端点要比 /login 更紧，否则第二因子
    # 会在 pending token 的 5 分钟窗口内被暴力穷举。10 次/分 × 5 分 = 50 次
    # 尝试 vs 100 万组合，风险可接受。
    # M1 补齐：认证链路上的其余验证码端点此前漏配，只吃全局默认阈值。
    # - /api/auth/2fa/authenticate：与 /api/auth/login/2fa 同级（code 交换，
    #   6 位数字，pending token 5 分钟窗口内可穷举）；
    # - /api/auth/email-code/request：发信类从紧（对齐 resend-verification /
    #   forgot-password 的 8 次/分），发信轰炸另有 mail_guard 按收件人兜底；
    # - /api/auth/email-code/verify：验证码核对，对齐 reset-password 的 10 次/分。
    "/api/comments": 20,
    "/api/auth/2fa/authenticate": 10,
    "/api/auth/login/2fa": 10,
    "/api/auth/login": 10,
    "/api/auth/register": 10,
    "/api/auth/verify-email": 20,
    "/api/auth/resend-verification": 8,
    "/api/auth/forgot-password": 8,
    "/api/auth/reset-password": 10,
    "/api/auth/email-code/request": 8,
    "/api/auth/email-code/verify": 10,
    "/api/auth/refresh": 30,
}

_RATE_WINDOW_SECONDS = 60.0

# 这些路径的严格阈值只约束「写」：读请求回落到全局阈值。
#
# /api/comments 的 20 次/分 是为了防刷评（POST 才写库、才发通知），
# 但列表接口是 GET，而且**每打开一篇文章都会调一次**。20 次/分 等于
# 「一分钟最多看 20 篇带评论的文章」，超了评论区就显示「评论加载失败」——
# 正常翻页的读者会莫名其妙看到坏掉的评论区。读不该被当成写来限。
_READ_EXEMPT_PATHS = frozenset({"/api/comments"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter keyed by client IP + path.

    Single-node deployments use the in-memory store. Multi-node
    deployments should set ``RUBBISH_REDIS_URL`` so the bucket is
    shared across replicas; the middleware doesn't need to change.
    """

    def __init__(self, app: ASGIApp, default_per_minute: int) -> None:
        super().__init__(app)
        self._default = default_per_minute

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Test env: skip entirely. Single-IP sliding window would starve
        # the test client which reuses one connection for many requests.
        if settings.is_test or request.method == "OPTIONS":
            return await call_next(request)

        # 静态资源与 SPA 文档不计入限流。
        #
        # 为什么：全局桶是「每 IP 每分钟」的，而一次文章页加载要拉
        # index.js + index.css + 字体 + 若干图片，再加 6~8 个 API 调用。
        # 把这些都算进 120/分，意味着真人快速翻十几篇文章就会被拦，
        # 而且拦下来的是浏览器直接导航到的 /catalog/<id>，返回的是
        # JSON —— 用户看到的是一屏 `{"detail":"Too many requests..."}`，
        # 不是 404 也不是错误页，就是裸 JSON。这不属于要防的威胁模型：
        # 静态文件由前置反向代理直接吐，成本远低于任何 API。
        # 限流只应作用于 /api（真正的计算、写库、发信入口）。
        path = request.url.path
        if not path.startswith("/api"):
            return await call_next(request)
        limit = self._limit_for(path, request.method)
        if limit <= 0:
            return await call_next(request)

        ip = self._client_ip(request)
        bucket_key = f"{ip}|{self._path_key(path, request.method)}"
        store = get_rate_limiter_store()
        allowed, _depth = await store.hit_and_check(
            bucket_key=bucket_key,
            limit=limit,
            window_seconds=_RATE_WINDOW_SECONDS,
        )
        if not allowed:
            # Conservative Retry-After: full window. We don't track the
            # oldest entry's exact age here, so a one-window wait is the
            # safest single-shot response.
            inc_rate_limit_rejection(path)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down."},
                headers={"Retry-After": str(int(_RATE_WINDOW_SECONDS))},
            )

        response = await call_next(request)
        return response

    def _limit_for(self, path: str, method: str = "GET") -> int:
        for strict_path, limit in STRICT_PATHS.items():
            if path == strict_path:
                if method in ("GET", "HEAD") and strict_path in _READ_EXEMPT_PATHS:
                    return self._default
                return limit
        return self._default

    def _path_key(self, path: str, method: str = "GET") -> str:
        # Collapse exact strict paths to their key; everything else shares
        # a global bucket so one IP cannot bypass per-path limits by
        # hitting many distinct resource_id URLs.
        for strict_path in STRICT_PATHS:
            if path == strict_path:
                if method in ("GET", "HEAD") and strict_path in _READ_EXEMPT_PATHS:
                    return "_global"
                return strict_path
        return "_global"

    def _client_ip(self, request: Request) -> str:
        # Trust X-Forwarded-For only when trusted_proxies_count is set.
        # XFF format: client, proxy1, proxy2... — pick the Nth-from-the-right
        # entry (N = trusted_proxies_count), which is the IP the last trusted
        # proxy actually saw as the client.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded and settings.trusted_proxies_count > 0:
            parts = [p.strip() for p in forwarded.split(",")]
            idx = max(0, len(parts) - settings.trusted_proxies_count)
            return parts[idx]
        if request.client:
            return request.client.host
        return "unknown"
