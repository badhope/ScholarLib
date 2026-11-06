"""评审复核落库：regrade-out-*.json 七维原始分 → evaluate 加权 → 更新资源。

主编要求（2026-11-06）：评分必须客观拉开、每篇必须有评审总评（breakdown.comment）。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from app.core.db import async_session_factory  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.core.time import utcnow  # noqa: E402
from app.models import AuditLog  # noqa: E402
from app.modules.catalog.models import Resource  # noqa: E402
from app.modules.quality.rubric import DimensionScore, evaluate  # noqa: E402

logger = get_logger("rubbish.review.regrade")

DIM_KEYS = ("problem", "argument", "method", "evidence", "novelty", "integrity", "presentation")


async def main() -> None:
    items = []
    for p in sorted(Path("/tmp/regrade").glob("regrade-out-*.json")):
        items.extend(json.loads(p.read_text(encoding="utf-8")))
    seen: dict[int, dict] = {}
    for it in items:
        seen[int(it["id"])] = it  # 后批覆盖同 id（无重复，稳妥）
    async with async_session_factory() as db:
        admin = (
            await db.execute(select(AuditLog.actor_user_id).order_by(AuditLog.id.desc()).limit(1))
        ).first()
        actor = int(admin[0]) if admin else None
        updated = 0
        for rid, it in sorted(seen.items()):
            res = (
                await db.execute(select(Resource).where(Resource.id == rid))
            ).scalars().first()
            if res is None:
                logger.warning("regrade_skip_missing", resource_id=rid)
                continue
            dims = it.get("dimensions", {})
            ds = [
                DimensionScore(key=k, score=float(dims[k]["score"]), reason=str(dims[k]["reason"])[:120])
                for k in DIM_KEYS
                if k in dims
            ]
            if len(ds) < 7:
                logger.warning("regrade_skip_dims", resource_id=rid, dims=len(ds))
                continue
            ev = evaluate(ds, article_type=it.get("article_type", "research"))
            breakdown = dict(ev)
            breakdown["comment"] = str(it.get("comment", "")).strip()[:600]
            res.quality_score = float(ev["score"])
            res.quality_grade = str(ev["grade"])
            res.quality_breakdown = breakdown
            db.add(
                AuditLog(
                    tenant_id=res.tenant_id,
                    actor_user_id=actor,
                    action="review.regrade_objective",
                    target_type="resource",
                    target_id=str(rid),
                    payload={"score": float(ev["score"]), "grade": ev["grade"]},
                    created_at=utcnow(),
                )
            )
            updated += 1
        await db.commit()
        print(f"[regrade] updated={updated}")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(main())
