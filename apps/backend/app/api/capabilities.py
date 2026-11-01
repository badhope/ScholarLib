"""Public capability probe.

The SPA needs to know which operator-level integrations are actually
live before it writes copy that promises them. The canonical example is
transactional email: with the console backend a verification or reset
mail is only written to the server log, so the UI must not tell the user
to check their inbox. Everything returned here is non-sensitive.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.core.email import ConsoleEmailSender, get_email_sender

router = APIRouter(prefix="/capabilities", tags=["public"])


class CapabilitiesResponse(BaseModel):
    email_backend: str
    email_delivery: bool
    email_verification_required: bool
    oidc_enabled: bool
    registration_open: bool
    # 上传约束对外暴露：前端不再把 50 MB / 扩展名列表写死在两处，
    # 后端改规则时前端自动跟随。
    upload_max_bytes: int
    upload_extensions: list[str]


@router.get("", response_model=CapabilitiesResponse)
async def get_capabilities() -> CapabilitiesResponse:
    """Return feature availability the frontend may safely advertise.

    Delivery is judged by the *actual* sender in use, not by the settings
    string: the E2E harness swaps in an in-memory sender while leaving
    ``email_backend=console`` untouched, and production falls back to
    console when SMTP is half-configured. Either way the console sender
    means "nothing leaves this process".
    """
    from app.modules.submission.routes_files import (
        _ALLOWED_UPLOAD_EXTENSIONS,
        _MAX_UPLOAD_BYTES,
    )

    sender = get_email_sender()
    delivers = not isinstance(sender, ConsoleEmailSender)
    return CapabilitiesResponse(
        email_backend=settings.email_backend,
        email_delivery=delivers,
        # Registration issues no tokens (uniform anti-enumeration response);
        # verification is recorded but never gates login, so the UI must not
        # block on it.
        email_verification_required=False,
        oidc_enabled=settings.oidc_enabled,
        registration_open=True,
        upload_max_bytes=_MAX_UPLOAD_BYTES,
        upload_extensions=list(_ALLOWED_UPLOAD_EXTENSIONS),
    )


__all__ = ["CapabilitiesResponse", "router"]
