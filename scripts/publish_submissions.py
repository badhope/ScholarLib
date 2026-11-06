"""新投稿批量录用与发布脚本（编辑部代审通道，2026-11）。

输入 JSON（终审评审员产出）：[{"id": <submission_id>, "verdict": "accept",
"article_type": "research", "score": 68.5, "dimensions": {...7 维 score+reason...},
"absurdity_index": 4.5, "content_category": "fun", "note": "决定理由"}]

对 ``accept``：

1. 服务端 ``evaluate`` 重算总分（口径唯一）；
2. 创建 Resource：published、滚动发布（publish_at=now）、卷 1 / 第 5 期
   （本期为逐篇滚动刊出，不凑整期）、按学科回填确定性默认封面；
3. submission → accepted 并关联 resource_id；
4. 全程审计（submission.bulk_accepted）。

对 ``rework``：submission → rework_requested，note 写入 admin_note，同样留痕。

用法：docker compose exec -T app python /tmp/publish_submissions.py /tmp/verdicts.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from app.core.db import async_session_factory  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.core.time import utcnow  # noqa: E402
from app.models import AuditLog  # noqa: E402
from app.modules.catalog.cover_defaults import default_cover_for  # noqa: E402
from app.modules.catalog.models import Resource  # noqa: E402
from app.modules.quality.rubric import DimensionScore, evaluate  # noqa: E402
from app.modules.submission.models import Submission  # noqa: E402

logger = get_logger("rubbish.publish.bulk")

DIM_KEYS = (
    "problem",
    "argument",
    "method",
    "evidence",
    "novelty",
    "integrity",
    "presentation",
)


async def main(path: str) -> None:
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    async with async_session_factory() as db:
        tenants = (await db.execute(select(Resource.tenant_id).distinct())).scalars().all()
        tenant_id = tenants[0]
        admin = (
            await db.execute(
                select(AuditLog.actor_user_id).order_by(AuditLog.id.desc()).limit(1)
            )
        ).first()
        actor = int(admin[0]) if admin else None

        accepted = reworked = congrat = 0
        for it in items:
            sid = int(it["id"])
            submission = (
                await db.execute(select(Submission).where(Submission.id == sid))
            ).scalars().first()
            if submission is None:
                logger.warning("publish_skip_missing", submission_id=sid)
                continue
            verdict = it.get("verdict")

            if verdict == "rework":
                submission.status = "rework_requested"
                submission.admin_note = str(it.get("note", ""))[:500] or "编辑部复审未通过"
                db.add(
                    AuditLog(
                        tenant_id=tenant_id,
                        actor_user_id=actor,
                        action="submission.bulk_rework",
                        target_type="submission",
                        target_id=str(sid),
                        payload={"note": it.get("note"), "source": "bulk-2026-11"},
                        created_at=utcnow(),
                    )
                )
                reworked += 1
                continue

            dims = it.get("dimensions", {})
            ds = [
                DimensionScore(key=k, score=float(dims[k]["score"]), reason=str(dims[k]["reason"]))
                for k in DIM_KEYS
            ]
            ev = evaluate(ds, article_type=it.get("article_type", "research"))

            resource = Resource(
                slug=f"sub-{sid}-{uuid4().hex[:8]}",
                type=submission.type or "paper",
                title=submission.title,
                authors=list(submission.authors or []),
                year=submission.year,
                venue=submission.venue,
                discipline=submission.discipline,
                subdiscipline=submission.subdiscipline,
                tags=list(submission.tags or []),
                abstract=submission.abstract,
                preview=(submission.preview or submission.abstract or "")[:200],
                keywords=list(submission.keywords or []),
                language="zh",
                publication_status="published",
                publish_at=utcnow(),  # 滚动发布：过审即刊出
                volume="1",
                issue="05",  # 最新一期（第 5 期为逐篇滚动刊出期）
                tenant_id=tenant_id,
                content_category=it.get("content_category"),
                absurdity_index=float(it["absurdity_index"]),
                quality_score=float(ev["score"]),
                quality_grade=str(ev["grade"]),
                quality_breakdown=ev,
                cover_image=default_cover_for(submission.discipline, seed=sid),
            )
            db.add(resource)
            await db.flush()
            submission.status = "accepted"
            submission.resource_id = resource.id
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor_user_id=actor,
                    action="submission.bulk_accepted",
                    target_type="submission",
                    target_id=str(sid),
                    payload={
                        "resource_id": resource.id,
                        "score": float(ev["score"]),
                        "grade": ev["grade"],
                        "absurdity_index": float(it["absurdity_index"]),
                        "content_category": it.get("content_category"),
                        "note": it.get("note"),
                        "source": "bulk-2026-11",
                    },
                    created_at=utcnow(),
                )
            )
            accepted += 1
            logger.info("submission_published", submission_id=sid, resource_id=resource.id)
            # 恭喜邮件（主编授权的录用祝贺通道，不受总闸约束）
            try:
                from app.models import User
                from app.modules.submission.review_reminders import send_decision_email

                author = (
                    await db.execute(select(User).where(User.id == submission.submitted_by))
                ).scalar_one_or_none()
                if author is not None:
                    await send_decision_email(
                        author,
                        submission_title=submission.title,
                        decision="accept",
                        note=it.get("note"),
                    )
                    congrat += 1
            except Exception:  # noqa: BLE001 — 邮件是 best-effort
                logger.warning("publish_congrat_email_failed", submission_id=sid, exc_info=True)
        await db.commit()
        print(f"[publish] accepted={accepted} reworked={reworked} congrat_emails={congrat}")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(main(sys.argv[1]))
