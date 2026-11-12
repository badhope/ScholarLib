# mypy: ignore-errors
"""批量重审引擎（2.0）：存量逐篇重打分、重分类、荒诞指数落库。

背景：v1.11 之前的质量分是旧口径批量跑出来的（74–94，A- 偏多），
2026-11 起按 RQS v4.0 逐篇人工/AI 复核。本模块提供「一条 = 一篇」的
批量落库通道：

- 每条必须带该赛道**全部五个维度**的分数、理由与正文证据（复用 ``evaluate``，缺维度/缺证据 422）；
- ``absurdity_index``（0–10 风格坐标）**必填**——编辑部的口径是：审核时
  必须明确判定每篇的风格坐标（0 = 纯学术，7.5+ = 吐槽向），它不进质量
  分、不参与排序（铁律），但必须实打实记录；
- ``content_category`` 可选显式指定（判定顺序：编辑部显式 > 荒诞折算 >
  类型兜底，见 docs/CONTENT-ECOSYSTEM.md 第二节）；
- ``verdict`` 记录处置建议（keep/rewrite/reject/delete），只写审计与
  返回值，不直接执行删除——删除走独立流程并先备份；
- 全部写入 ``audit_logs``（action=``quality.batch_rescore``），可追溯。

权限：仅管理员（主/副主编视同）。批量大小上限 100，超出 422。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import AuditLog
from app.modules.quality.rubric import DimensionScore, evaluate

logger = get_logger("rubbish.quality.batch")

MAX_BATCH_ITEMS = 100

ContentCategory = Literal["academic", "fun", "rant"]
Verdict = Literal["keep", "rewrite", "reject", "delete"]


class BatchDimensionInput(BaseModel):
    key: Literal[
        "question",
        "argument",
        "method",
        "evidence",
        "integrity",
        "concept",
        "coherence",
        "execution",
        "material",
        "voice",
    ]
    score: int = Field(ge=0, le=100)
    reason: str = Field(min_length=4, max_length=2000)
    evidence: str = Field(min_length=8, max_length=2000)


class BatchItem(BaseModel):
    resource_id: int = Field(ge=1)
    track: Literal["academic", "absurd"] = "academic"
    article_type: Literal["research", "review", "essay", "note"] = "research"
    dimensions: list[BatchDimensionInput] = Field(min_length=5, max_length=5)
    # 0–10 风格坐标：审核必填项。不进质量分、不参与排序（铁律）。
    absurdity_index: float = Field(ge=0, le=10)
    content_category: ContentCategory | None = None
    verdict: Verdict | None = None
    note: str | None = Field(default=None, max_length=2000)


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=MAX_BATCH_ITEMS)


async def apply_review_items(
    db: AsyncSession,
    *,
    tenant_id: object,
    actor_user_id: int,
    items: list[BatchItem],
) -> dict[str, object]:
    """逐条落库：重算分数 → 更新 Resource → 写审计。返回逐条结果。

    幂等：同一批重复提交 = 覆盖为最新审核结果（审计保留历史）。
    """
    from sqlalchemy import select

    from app.modules.catalog.models import Resource

    by_id: dict[int, Resource] = {}
    missing: list[int] = []
    ids = [item.resource_id for item in items]
    rows = (
        (
            await db.execute(
                select(Resource).where(
                    Resource.id.in_(ids),
                    Resource.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {r.id: r for r in rows}
    missing = [rid for rid in ids if rid not in by_id]

    results: list[dict[str, object]] = []
    updated = 0
    for item in items:
        if item.resource_id not in by_id:
            results.append({"resource_id": item.resource_id, "ok": False, "error": "not_found"})
            continue
        resource = by_id[item.resource_id]
        try:
            scores = [
                DimensionScore(key=d.key, score=d.score, reason=d.reason, evidence=d.evidence)
                for d in item.dimensions
            ]
            evaluation = evaluate(scores, track=item.track, article_type=item.article_type)
        except ValueError as exc:
            results.append({"resource_id": item.resource_id, "ok": False, "error": str(exc)[:300]})
            continue

        resource.quality_score = float(evaluation["score"])  # type: ignore[arg-type,assignment]
        resource.quality_grade = str(evaluation["grade"])
        resource.quality_breakdown = evaluation  # JSON 列：保留完整明细可追溯
        resource.absurdity_index = float(item.absurdity_index)  # type: ignore[assignment]
        # 单一权威口径：content_track 权威，content_category 由 track 推导。
        # 编辑部显式类别 = 赛道子类型声明（academic→paper，fun/rant→essay）；
        # 未显式指定时，仅在现有 track 合法的前提下按 track 校正 category，
        # 修历史 paper+fun / essay+academic 漂移；track 缺失不擅自改判。
        from app.core.tracks import canonicalize_track_category

        if item.content_category is not None:
            new_track, new_category = canonicalize_track_category(None, item.content_category)
        elif resource.content_track in ("paper", "essay"):
            new_track, new_category = canonicalize_track_category(
                resource.content_track, resource.content_category
            )
        else:
            new_track, new_category = resource.content_track, resource.content_category
        category_changed = (
            new_category != resource.content_category or new_track != resource.content_track
        )
        resource.content_track = new_track  # type: ignore[assignment]
        resource.content_category = new_category  # type: ignore[assignment]
        updated += 1

        db.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="quality.batch_rescore",
                target_type="resource",
                target_id=str(item.resource_id),
                payload={
                    "score": float(evaluation["score"]),  # type: ignore[arg-type]
                    "grade": evaluation["grade"],
                    "absurdity_index": item.absurdity_index,
                    "content_category": item.content_category,
                    "category_changed": category_changed,
                    "verdict": item.verdict,
                    "track": item.track,
                    "article_type": item.article_type,
                    "note": item.note,
                    "rubric_version": evaluation["rubric_version"],
                },
            )
        )
        results.append(
            {
                "resource_id": item.resource_id,
                "ok": True,
                "score": float(evaluation["score"]),  # type: ignore[arg-type]
                "grade": evaluation["grade"],
                "absurdity_index": item.absurdity_index,
                "content_category": item.content_category or resource.content_category,
                "category_changed": category_changed,
                "verdict": item.verdict,
            }
        )

    await db.commit()
    logger.info(
        "quality_batch_rescore_done",
        requested=len(items),
        updated=updated,
        missing=len(missing),
    )
    return {
        "requested": len(items),
        "updated": updated,
        "missing_ids": missing,
        "results": results,
    }


__all__ = [
    "MAX_BATCH_ITEMS",
    "BatchDimensionInput",
    "BatchItem",
    "BatchRequest",
    "apply_review_items",
]
