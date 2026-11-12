"""First-party anonymous page-view collection (server-side minimal patch).

No IP, no User-Agent, no user id: only the public path and the referrer the
browser already sends. Insert goes through raw SQL so this module does not
add a model to the server fork's metadata.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id
from app.core.db import get_db

router = APIRouter(tags=["telemetry"])


class PageViewIn(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    referrer: str | None = Field(default=None, max_length=500)


@router.post("/telemetry/pageview", status_code=204)
async def record_page_view(
    payload: PageViewIn,
    db: AsyncSession = Depends(get_db),
) -> None:
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant context not resolved")
    # 只接受站内路径，避免被当作任意 URL 存储。
    path: str = payload.path.split("?", 1)[0].split("#", 1)[0][:300]
    if not path.startswith("/"):
        return None
    await db.execute(
        text(
            "INSERT INTO page_views (tenant_id, path, referrer, created_at) "
            "VALUES (:tenant_id, :path, :referrer, now())"
        ),
        {"tenant_id": str(tenant_id), "path": path, "referrer": payload.referrer or None},
    )
    await db.commit()
    return None
