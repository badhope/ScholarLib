"""Security headers middleware.

Adds baseline security headers (X-Content-Type-Options, X-Frame-Options,
HSTS in production). 不再回显 ``X-API-Version``：版本号属于部署信息，
公开响应头里没有任何业务价值，只会帮攻击者挑已知漏洞。
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings


class SecurityHeadersMiddleware:
    """Add baseline security headers and API version to every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (
                            b"permissions-policy",
                            b"geolocation=(), microphone=(), camera=()",
                        ),
                        (
                            b"content-security-policy",
                            # frame-ancestors 才是"谁能嵌入我"（点击劫持防护），
                            # 之前的 frame-src 控制的是"我能嵌入谁"，方向相反、
                            # 完全没有防住点击劫持；同时补 base-uri 与 form-action。
                            b"default-src 'self'; "
                            b"script-src 'self'; "
                            b"style-src 'self' 'unsafe-inline'; "
                            b"frame-ancestors 'none'; "
                            b"base-uri 'self'; "
                            b"form-action 'self'; "
                            b"connect-src 'self' blob:; "
                            b"img-src 'self' data: https:; "
                            b"font-src 'self' data:; "
                            b"worker-src 'self' blob:; "
                            b"object-src 'self' blob:",
                        ),
                    ]
                )
                # API responses are dynamic and often user-scoped. Without an
                # explicit directive browsers may heuristically cache them;
                # a stale permission or submission list is worse than a refetch.
                if scope["path"].startswith("/api/"):
                    headers.append((b"cache-control", b"no-store"))
                elif not scope["path"].startswith(("/assets/", "/covers/")):
                    # HTML 壳、sitemap、RSS 都是动态生成的：没有显式指令时
                    # 浏览器会启发式缓存，发版后手机端仍可能拿旧壳。静态资源
                    # 走内容哈希长缓存，不在这里覆盖。
                    headers.append((b"cache-control", b"no-cache, must-revalidate"))
                if settings.is_production:
                    headers.append(
                        (
                            b"strict-transport-security",
                            b"max-age=31536000; includeSubDomains",
                        )
                    )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
