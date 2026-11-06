"""批量重审结果落库脚本（运维用，2026-11 存量重审）。

在服务器应用容器内执行（已带全部依赖与 DATABASE_URL）：

    docker compose exec -T app python /app/scripts/apply_rescore.py \
        /tmp/verdicts-normalized.json --rebalance 60

输入 JSON 由编辑部评审汇总生成（见 work/review-verdicts/），每条：

    {"resource_id": 24, "article_type": "research",
     "dimensions": {"problem": {"score": 70, "reason": "..."}, ...×7},
     "absurdity_index": 3.5, "content_category": "fun",
     "verdict": "keep", "verdict_note": "..."}

行为：

1. 服务端用 ``evaluate`` 重算总分（口径唯一，不信 JSON 里的 score）；
2. 更新 ``resources``：quality_score / quality_grade / quality_breakdown /
   absurdity_index / content_category；
3. 逐条写 ``audit_logs``（action=quality.batch_rescore，含 verdict）；
4. ``--rebalance N``：重审完成后按质量分顺序把已发布资源重排为每期
   N 篇（volume 1，issue 零填充两位），并写审计（与 API 端点同一口径）。

不删除任何资源：delete/reject 处置只落审计与报告，删除走独立备份流程。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 容器内 /app 是工作目录；宿主机直跑时把 apps/backend 加进 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "backend"))
sys.path.insert(0, "/app")

from sqlalchemy import select, update  # noqa: E402

from app.core.db import async_session_factory  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.models import AuditLog, User  # noqa: E402
from app.modules.catalog.models import Resource  # noqa: E402
from app.modules.quality.rubric import DimensionScore, evaluate  # noqa: E402

logger = get_logger("rubbish.rescore.apply")

DIM_KEYS = (
    "problem",
    "argument",
    "method",
    "evidence",
    "novelty",
    "integrity",
    "presentation",
)


async def _admin_actor_id(db, tenant_id) -> int:
    row = (
        await db.execute(select(User.id).where(User.tenant_id == tenant_id, User.is_admin.is_(True)).limit(1))
    ).first()
    return int(row[0]) if row else 0


async def apply(path: str, rebalance: int | None) -> None:
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    async with async_session_factory() as db:
        tenants = (
            await db.execute(select(Resource.tenant_id).distinct())
        ).scalars().all()
        tenant_id = tenants[0] if tenants else None
        actor = await _admin_actor_id(db, tenant_id) if tenant_id else 0

        ids = [int(it["resource_id"]) for it in items]
        resources = {
            r.id: r
            for r in (
                await db.execute(
                    select(Resource).where(Resource.id.in_(ids), Resource.tenant_id == tenant_id)
                )
            ).scalars().all()
        }

        updated = skipped = 0
        verdict_counts: dict[str, int] = {}
        for it in items:
            rid = int(it["resource_id"])
            resource = resources.get(rid)
            if resource is None:
                skipped += 1
                logger.warning("rescore_skip_missing", resource_id=rid)
                continue
            dims = it.get("dimensions", {})
            if set(dims.keys()) != set(DIM_KEYS):
                skipped += 1
                logger.warning("rescore_skip_dims", resource_id=rid)
                continue
            try:
                ds = [
                    DimensionScore(key=k, score=float(dims[k]["score"]), reason=str(dims[k]["reason"]))
                    for k in DIM_KEYS
                ]
                ev = evaluate(ds, article_type=it.get("article_type", "research"))
            except ValueError as exc:
                skipped += 1
                logger.warning("rescore_skip_evaluate", resource_id=rid, error=str(exc)[:200])
                continue

            absurd = float(it["absurdity_index"])
            cat = it.get("content_category")
            if cat not in ("academic", "fun", "rant"):
                cat = resource.content_category
            verdict = it.get("verdict", "keep")
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1

            resource.quality_score = float(ev["score"])
            resource.quality_grade = str(ev["grade"])
            resource.quality_breakdown = ev
            resource.absurdity_index = absurd
            resource.content_category = cat
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor_user_id=actor,
                    action="quality.batch_rescore",
                    target_type="resource",
                    target_id=str(rid),
                    payload={
                        "score": float(ev["score"]),
                        "grade": ev["grade"],
                        "absurdity_index": absurd,
                        "content_category": cat,
                        "verdict": verdict,
                        "verdict_note": it.get("verdict_note"),
                        "article_type": it.get("article_type"),
                        "source": "bulk-rescore-2026-11",
                    },
                )
            )
            updated += 1
        await db.commit()
        logger.info("rescore_applied", updated=updated, skipped=skipped, verdicts=verdict_counts)
        print(f"[rescore] updated={updated} skipped={skipped} verdicts={verdict_counts}")

        if rebalance:
            from sqlalchemy import nullslast

            rows = (
                (
                    await db.execute(
                        select(Resource)
                        .where(
                            Resource.tenant_id == tenant_id,
                            Resource.publication_status == "published",
                        )
                        .order_by(nullslast(Resource.quality_score.desc()), Resource.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            groups: dict[str, int] = {}
            for seq, resource in enumerate(rows, start=1):
                issue_no = (seq - 1) // rebalance + 1
                label = f"{issue_no:02d}"
                resource.volume = "1"
                resource.issue = label
                groups[label] = groups.get(label, 0) + 1
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor_user_id=actor,
                    action="catalog.issues_rebalanced",
                    target_type="catalog",
                    target_id="volume:1",
                    payload={"issue_size": rebalance, "total": len(rows), "issues": groups,
                             "source": "bulk-rescore-2026-11"},
                )
            )
            await db.commit()
            print(f"[rebalance] total={len(rows)} issues={dict(sorted(groups.items()))}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_path", help="评审结果 JSON 路径")
    parser.add_argument("--rebalance", type=int, default=None,
                        help="重审后按每期 N 篇重排卷期（可选）")
    args = parser.parse_args()
    configure_logging()
    asyncio.run(apply(args.json_path, args.rebalance))


if __name__ == "__main__":
    main()
