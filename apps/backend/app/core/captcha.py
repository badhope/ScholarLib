"""CAPTCHA verification hook.

Goal: a pluggable point where any provider (Cloudflare Turnstile,
hCaptcha, reCAPTCHA) can verify a token. We do **not** bundle a
specific provider's SDK by default — operators wire up their own
verifier via the ``captcha_verifier`` setting (a dotted path to a
``async def verify(token: str, *, remote_ip: str | None) -> bool``
callable). When unset the hook is a no-op so the registration flow
keeps working in dev / CI without external dependencies.

The hook is invoked directly by the registration endpoint via
``verify_captcha_token`` when ``settings.captcha_required_for_registration``
is True.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import inspect
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Protocol, cast, runtime_checkable

from fastapi import HTTPException, Request, status

from app.core.config import settings


@runtime_checkable
class CaptchaVerifier(Protocol):
    """The contract operators must satisfy when wiring up a provider."""

    async def verify(self, token: str, *, remote_ip: str | None) -> bool: ...


class _AlwaysPassVerifier:
    """Default dev/CI verifier. Logs a warning at first call."""

    _warned: bool = False

    async def verify(self, token: str, *, remote_ip: str | None) -> bool:
        if not _AlwaysPassVerifier._warned:
            _AlwaysPassVerifier._warned = True
            # Lazy import — logging module is heavy and we want this
            # to import cleanly even before configure_logging() runs.
            from app.core.logging import get_logger

            get_logger("rubbish.captcha").warning(
                "captcha_disabled_using_passthrough",
                provider="dev-passthrough",
            )
        return True


def _is_verifier(obj: object) -> bool:
    """Return True if ``obj`` satisfies the ``CaptchaVerifier`` protocol."""
    verify = getattr(obj, "verify", None)
    return callable(verify) and inspect.iscoroutinefunction(verify)


class _FunctionVerifier:
    """Adapt a bare ``async def verify(token, *, remote_ip)`` function to the
    ``CaptchaVerifier`` protocol so callers can use it uniformly."""

    def __init__(self, fn: Callable[..., Awaitable[bool]]) -> None:
        self._fn = fn

    async def verify(self, token: str, *, remote_ip: str | None) -> bool:
        return bool(await self._fn(token, remote_ip=remote_ip))


def _resolve_verifier(dotted: str) -> CaptchaVerifier:
    """Resolve a dotted ``captcha_verifier`` path to a ``CaptchaVerifier``.

    Resolution order (covers every shape the docstring promises):

    1. A verifier **instance** — an object with an ``async def verify(...)``
       method. Used as-is.
    2. A bare ``async def verify(token, *, remote_ip)`` module-level function.
       Wrapped into a protocol object automatically.
    3. A **factory** (function or class) returning a verifier instance.
    """
    module_name, _, attr = dotted.rpartition(".")
    if not module_name:
        raise RuntimeError(f"Invalid captcha_verifier path: {dotted!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(f"captcha_verifier {dotted!r} could not be imported: {exc}") from exc
    obj = getattr(module, attr, None)
    if obj is None:
        raise RuntimeError(f"captcha_verifier {dotted!r} does not resolve to an attribute")

    # A class is a factory, not an instance: instantiate it before the
    # protocol check, otherwise its unbound ``verify`` is mistaken for a
    # verifier and every call fails with "missing token".
    if inspect.isclass(obj):
        obj = obj()

    # 1) Already a verifier instance.
    if _is_verifier(obj):
        return cast("CaptchaVerifier", obj)
    # 2) A bare async verify() function.
    if inspect.iscoroutinefunction(obj):
        return _FunctionVerifier(obj)
    # 3) A factory / class producing a verifier.
    if callable(obj):
        produced = obj()
        if _is_verifier(produced):
            return cast("CaptchaVerifier", produced)
    raise RuntimeError(
        f"captcha_verifier {dotted!r} must be a CaptchaVerifier instance, "
        "a bare async verify() function, or a factory returning one"
    )


# --- 自建算术验证码 ---------------------------------------------------------
# 不依赖任何第三方 SaaS：签发一个带 HMAC 的短时 token + 一道算术题，
# 注册时把答案一并回传。足够挡住脚本批量注册，且没有外部网络依赖。
_CAPTCHA_TTL_SECONDS = 600


def _captcha_sign(nonce: str, expiry: int, answer: str) -> str:
    key = settings.secret_key.encode("utf-8")
    msg = f"{nonce}.{expiry}.{answer}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:32]


def issue_captcha() -> dict[str, str]:
    a = secrets.randbelow(9) + 1
    b = secrets.randbelow(9) + 1
    nonce = secrets.token_hex(8)
    expiry = int(time.time()) + _CAPTCHA_TTL_SECONDS
    answer = str(a + b)
    return {
        "token": f"{nonce}.{expiry}.{_captcha_sign(nonce, expiry, answer)}",
        "question": f"{a} + {b} = ?",
    }


def verify_self_hosted(token: str | None, answer: str | None) -> bool:
    if not token or not answer:
        return False
    try:
        nonce, expiry_s, sig = token.split(".")
        expiry = int(expiry_s)
    except ValueError:
        return False
    if expiry < int(time.time()):
        return False
    expected = _captcha_sign(nonce, expiry, answer.strip())
    return hmac.compare_digest(sig, expected)


class SelfHostedCaptchaVerifier:
    """Adapter so the generic CAPTCHA hook can call the self-hosted check."""

    async def verify(
        self, token: str, *, remote_ip: str | None = None, answer: str | None = None
    ) -> bool:
        return verify_self_hosted(token, answer)


# Cache the configured verifier so registration requests do not re-import /
# re-instantiate it on every call. Populated on first resolution of a
# non-empty ``captcha_verifier``; the dev/CI passthrough is intentionally
# NOT cached so toggling the setting mid-process is reflected immediately.
_verifier_cache: CaptchaVerifier | None = None
_verifier_cache_key: str | None = None


def _load_verifier() -> CaptchaVerifier:
    """Resolve the configured verifier or return the passthrough default."""
    dotted = settings.captcha_verifier
    if not dotted:
        # No verifier configured: dev/CI passthrough.
        return _AlwaysPassVerifier()
    global _verifier_cache, _verifier_cache_key
    if _verifier_cache is not None and _verifier_cache_key == dotted:
        return _verifier_cache
    _verifier_cache = _resolve_verifier(dotted)
    _verifier_cache_key = dotted
    return _verifier_cache


async def verify_captcha_token(
    request: Request, token: str | None, answer: str | None = None
) -> None:
    """Validate the CAPTCHA token against the configured verifier.

    Call directly from the endpoint body (NOT a Depends), so the
    request body has already been parsed and we don't double-deserialize.

    Raises ``HTTPException(400)`` when the token is missing or fails
    verification. Returns ``None`` when verification succeeds or
    when the policy is off.
    """
    if not settings.captcha_required_for_registration:
        return
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CAPTCHA token required",
        )
    verifier = _load_verifier()
    remote_ip = request.client.host if request.client else None
    try:
        ok = await verifier.verify(token, remote_ip=remote_ip, answer=answer)
    except TypeError:
        # 兼容旧的自定义 verifier（只接收 token / remote_ip）。
        ok = await verifier.verify(token, remote_ip=remote_ip)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CAPTCHA verification failed",
        )
