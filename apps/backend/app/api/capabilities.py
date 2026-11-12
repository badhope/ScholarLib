"""Public capability probe.

The SPA needs to know which operator-level integrations are actually
live before it writes copy that promises them. The canonical example is
transactional email: with the console backend a verification or reset
mail is only written to the server log, so the UI must not tell the user
to check their inbox. Everything returned here is non-sensitive.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id
from app.core.config import settings
from app.core.db import get_db
from app.core.email import ConsoleEmailSender, get_email_sender
from app.core.site_settings import get_all_site_flags

router = APIRouter(prefix="/capabilities", tags=["public"])


class CapabilitiesResponse(BaseModel):
    email_backend: str
    email_delivery: bool
    email_verification_required: bool
    oidc_enabled: bool
    registration_open: bool
    # 运营开关：注册是否必须答验证码、投稿是否允许作者填写官方 DOI。
    captcha_required_for_registration: bool
    doi_author_entry_enabled: bool
    # 上传约束对外暴露：前端不再把 50 MB / 扩展名列表写死在两处，
    # 后端改规则时前端自动跟随。
    upload_max_bytes: int
    upload_extensions: list[str]


@router.get("", response_model=CapabilitiesResponse)
async def get_capabilities(
    db: AsyncSession = Depends(get_db),
) -> CapabilitiesResponse:
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
    tenant_id = get_current_tenant_id()
    flags = (
        await get_all_site_flags(db, UUID(str(tenant_id)))
        if tenant_id is not None
        else {
            "captcha_required_for_registration": settings.captcha_required_for_registration,
            "doi_author_entry_enabled": True,
        }
    )
    return CapabilitiesResponse(
        email_backend=settings.email_backend,
        email_delivery=delivers,
        # Registration issues no tokens (uniform anti-enumeration response);
        # verification is recorded but never gates login, so the UI must not
        # block on it.
        email_verification_required=False,
        oidc_enabled=settings.oidc_enabled,
        registration_open=True,
        captcha_required_for_registration=flags["captcha_required_for_registration"],
        doi_author_entry_enabled=flags["doi_author_entry_enabled"],
        upload_max_bytes=_MAX_UPLOAD_BYTES,
        upload_extensions=list(_ALLOWED_UPLOAD_EXTENSIONS),
    )


__all__ = ["CapabilitiesResponse", "router"]
