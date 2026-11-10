"""First-party anonymous page-view collection.

No IP, no User-Agent, no user id: only the public path and the referrer
the browser already sends. The table is tenant-scoped and RLS-protected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, require_admin
from app.core.db import get_db
from app.modules.catalog.models import PageView

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
    # 只接受站内路径，避免被当作任意 URL 存储/回显。
    path = payload.path.split("?", 1)[0].split("#", 1)[0][:300]
    if not path.startswith("/"):
        return None
    db.add(
        PageView(
            tenant_id=tenant_id,
            path=path,
            referrer=(payload.referrer or None),
        )
    )
    await db.commit()
    return None


@router.get("/admin/analytics/summary")
async def analytics_summary(
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
) -> dict[str, object]:
    since = datetime.now(UTC) - timedelta(days=days)
    total = (
        await db.execute(
            select(func.count(PageView.id)).where(
                PageView.tenant_id == get_current_tenant_id(),
                PageView.created_at >= since,
            )
        )
    ).scalar_one()
    top_paths = (
        await db.execute(
            select(PageView.path, func.count(PageView.id).label("views"))
            .where(PageView.tenant_id == get_current_tenant_id(), PageView.created_at >= since)
            .group_by(PageView.path)
            .order_by(func.count(PageView.id).desc())
            .limit(20)
        )
    ).all()
    top_refs = (
        await db.execute(
            select(func.coalesce(PageView.referrer, ""), func.count(PageView.id))
            .where(PageView.tenant_id == get_current_tenant_id(), PageView.created_at >= since)
            .group_by(PageView.referrer)
            .order_by(func.count(PageView.id).desc())
            .limit(10)
        )
    ).all()
    return {
        "days": days,
        "total": total,
        "paths": [{"path": p, "views": c} for p, c in top_paths],
        "referrers": [{"referrer": r, "views": c} for r, c in top_refs],
    }
