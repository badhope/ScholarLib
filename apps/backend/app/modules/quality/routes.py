"""Quality module API — rubric, review form, AI prompt spec, scoring, rework.

权限分层（每一层都比上一层更"有权改结果"）：

- 公开：``/rubric``、``/form``、``/prompt`` —— 口径必须公开，作者才能自查，
  外部 AI 才能复现。
- 审稿人：``/score`` —— 提交维度评分，系统按权重算出总分与等级。
- 编辑：``/rework-queue`` —— 查看不合格（<40 分）待打回稿件。
- 管理员：``/override`` —— 直接改分（必须写理由，写审计）。

为什么把"算分"做成服务端端点而不是前端计算：前端算分意味着口径在
客户端，任何人改一行 JS 就能改自己的分。服务端算分 + 审计留痕，才是
"这个分数是谁给的、依据什么"可追溯的前提。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_editor, require_reviewer
from app.core.db import get_db
from app.core.logging import get_logger
from app.models import AuditLog, User
from app.modules.quality.batch import MAX_BATCH_ITEMS, BatchRequest, apply_review_items
from app.modules.quality.review_form import form_payload, prompt_payload, score_answers
from app.modules.quality.rubric import (
    RUBRIC_VERSION,
    DimensionScore,
    evaluate,
    rubric_payload,
)

router = APIRouter(prefix="/quality", tags=["quality"])
logger = get_logger("rubbish.quality")

_ACADEMIC_KEYS = ("question", "argument", "method", "evidence", "integrity")
_ABSURD_KEYS = ("concept", "coherence", "execution", "material", "voice")


class DimensionInput(BaseModel):
    """一个维度的评分输入。理由与证据必填——没证据的分数不受理。"""

    key: Literal[
        "question", "argument", "method", "evidence", "integrity",
        "concept", "coherence", "execution", "material", "voice",
    ]
    score: int = Field(ge=0, le=100)
    reason: str = Field(min_length=4, max_length=2000)
    evidence: str = Field(min_length=8, max_length=2000)


class ScoreRequest(BaseModel):
    track: Literal["academic", "absurd"] = "academic"
    article_type: Literal["research", "review", "essay", "note"] = "research"
    dimensions: list[DimensionInput] = Field(min_length=5, max_length=5)
    # 0–10 风格坐标（荒诞指数）：审核流程的必填事实。不进质量分、
    # 不参与排序（铁律）；这里可选——仅实时预览时可省略，落库必须给。
    absurdity_index: float | None = Field(default=None, ge=0, le=10)


class AnswersRequest(BaseModel):
    """只给检查项答案，由服务端折算建议分（作者自查 / AI 预跑用）。"""

    answers: dict[str, str]
    track: Literal["academic", "absurd"] = "academic"


class OverrideRequest(BaseModel):
    score: float = Field(ge=0, le=100)
    reason: str = Field(min_length=10, max_length=1000)


@router.get("/rubric")
async def get_rubric() -> dict[str, object]:
    """评分口径（公开）：作者自查、审稿人对照、外部 AI 复现。"""
    return rubric_payload()


@router.get("/form")
async def get_review_form(
    track: str = Query(default="academic", pattern=r"^(academic|absurd)$"),
) -> dict[str, object]:
    """审稿评分表单（公开）：按赛道返回五维下的逐条事实检查项。"""
    return form_payload(track)


@router.get("/prompt")
async def get_ai_prompt(
    article_type: str = Query(default="research", pattern=r"^(research|review|essay|note)$"),
    track: str = Query(default="academic", pattern=r"^(academic|absurd)$"),
) -> dict[str, object]:
    """给外部 AI 的完整判分规格。

    公开是刻意的：作者想知道"我的稿子会被怎么评"，第三方工具想复现我们的
    结论，都应该能拿到同一份规格。口径不公开的评分体系无法自证公正。
    """
    return prompt_payload(article_type, track)


@router.post("/suggest")
async def suggest_scores(payload: AnswersRequest) -> dict[str, object]:
    """按检查项答案折算七个维度的建议分（不落库）。

    审稿人先勾检查项，拿到建议分后再决定是否覆盖——先事实、后判断，
    比一上来就拖滑杆更不容易拍脑袋。此端点无需登录：作者自查也要能用。
    """
    return {"dimensions": score_answers(payload.answers, payload.track)}


@router.post("/score")
async def compute_score(
    payload: ScoreRequest,
    _: User = Depends(require_reviewer),
) -> dict[str, object]:
    """按维度评分计算总分与等级（不落库，供审稿页实时预览）。

    缺维度会直接 422（Pydantic 已保证 7 个），而不是把缺失维度当 0 分——
    "漏填"与"很差"必须区分开。
    """
    try:
        scores = [
            DimensionScore(
                key=d.key,
                score=d.score,
                reason=d.reason,
                evidence=d.evidence,
            )
            for d in payload.dimensions
        ]
        result = evaluate(scores, track=payload.track, article_type=payload.article_type)
        result["absurdity_index"] = payload.absurdity_index
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/batch-rescore")
async def batch_rescore(
    payload: BatchRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """存量逐篇重审落库（管理员）。

    一条 = 一篇：七维分数 + 荒诞指数（必填）+ 可选显式类别与处置建议。
    分数经 ``evaluate`` 重算（口径唯一），荒诞指数只落库不打分，处置
    建议只写审计不直接执行。单批 ≤ ``MAX_BATCH_ITEMS`` 条。
    """
    if len(payload.items) > MAX_BATCH_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Batch too large: {len(payload.items)} > {MAX_BATCH_ITEMS}",
        )
    return await apply_review_items(
        db,
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.id,
        items=payload.items,
    )


@router.post("/override")
async def override_score(
    payload: OverrideRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """管理员直接改分（必须写理由）。

    存在的理由：AI 综合打分与人工复核都需要一个"最终能拍板"的入口。
    但改分必须留痕——否则分数体系就退化成"谁权限大听谁的"。
    审计记录包含新分、理由、操作人。
    """
    db.add(
        AuditLog(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            action="quality.score_override",
            target_type="rubric",
            target_id=RUBRIC_VERSION,
            payload={"score": payload.score, "reason": payload.reason},
        )
    )
    await db.commit()
    logger.info("quality_score_override", actor=current_user.id, score=payload.score)
    return {
        "rubric_version": RUBRIC_VERSION,
        "score": payload.score,
        "overridden": True,
        "reason": payload.reason,
    }


@router.get("/rework-queue")
async def rework_queue(
    include_published: bool = Query(default=False),
    current_user: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """不合格稿件打回队列：等待审稿人补审或作者修改的稿件。

    读未刊出且总分低于 40（不合格，rubric v5.0 的 ``rejected`` 语义）的
    条目。编辑部在通知栏看到的「待处理」就是这一批——不合格不是终点，
    是"必须有人推进"的状态。

    ``?include_published=true``：存量重审时已发布稿件也可能被判 <40
    （复核发现旧口径虚高），编辑需要看到完整处置面；默认仍只看未刊出。
    """
    from app.modules.catalog.models import Resource

    conditions = [
        Resource.tenant_id == current_user.tenant_id,
        Resource.quality_score < 40,
    ]
    if not include_published:
        conditions.append(Resource.publication_status != "published")
    rows = (
        await db.execute(
            select(Resource.id, Resource.title, Resource.quality_score, Resource.quality_grade)
            .where(*conditions)
            .order_by(Resource.updated_at.desc())
            .limit(100)
        )
    ).all()
    return {
        "data": [
            {
                "id": r[0],
                "title": r[1],
                "score": float(r[2]) if r[2] is not None else None,
                "grade": r[3],
            }
            for r in rows
        ],
        "count": len(rows),
    }
