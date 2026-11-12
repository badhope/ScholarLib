"""Forum API — 讨论区（发帖 / 回帖 / 版主操作）。

权限模型
--------
- 读：公开（未登录也能浏览，论坛是社区的橱窗）
- 发帖/回帖：登录即可（不设积分门槛——参考前面身份体系 3.0 的原则）
- 置顶/锁定/删除他人帖子：编辑或管理员（版主权限）

版块设计：五个**平铺**版块（论文沙龙/方法与写作/学术生存/组队招募/站务公告），
不做树状子版。本刊是期刊社区，不是大型论坛；五个版块足够让帖子有归属，
又不会在冷启动阶段把每个子版都做成空壳。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ROLE_EDITOR,
    get_current_user,
    get_current_user_optional,
    require_admin,
    require_tenant_id,
    user_has_role,
)
from app.core.db import get_db, paginate
from app.core.time import utcnow
from app.models import AuditLog, User
from app.modules.forum.models import ForumReply, ForumReport, ForumTopic

router = APIRouter(prefix="/forum", tags=["forum"])

# 五个平铺版块：论文沙龙 / 方法与写作 / 学术生存 / 组队招募 / 站务公告。
# 旧分类保留为兼容别名（历史帖子和既有测试仍可直接写入），列表查询按版块聚合。
ForumCategory = Literal[
    "paper",
    "method",
    "life",
    "collab",
    "meta",
    "notice",
    "discussion",
    "question",
    "suggestion",
]

CATEGORY_LABELS: dict[str, str] = {
    "paper": "论文沙龙",
    "method": "方法与写作",
    "life": "学术生存",
    "collab": "组队招募",
    "meta": "站务公告",
    "notice": "公告",
    "discussion": "讨论",
    "question": "求助",
    "suggestion": "建议",
}

# 版块 -> 实际落库的分类集合。旧帖不用搬家也能出现在新版块下。
CATEGORY_BOARD: dict[str, tuple[str, ...]] = {
    "paper": ("paper", "discussion"),
    "method": ("method", "question"),
    "meta": ("meta", "notice", "suggestion"),
}


class TopicCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=2, max_length=20000)
    category: ForumCategory = "paper"
    paper_id: int | None = Field(default=None, ge=1)


class ReplyCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class AuthorBrief(BaseModel):
    id: int
    username: str


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    category: str
    is_pinned: bool
    is_locked: bool
    reply_count: int
    created_at: datetime
    last_reply_at: datetime | None
    paper_id: int | None = None
    author: AuthorBrief | None = None


class TopicListOut(BaseModel):
    data: list[TopicOut]
    meta: dict[str, object]


class ReplyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int
    body: str
    created_at: datetime
    author: AuthorBrief | None = None


async def _author_map(db: AsyncSession, user_ids: set[int]) -> dict[int, AuthorBrief]:
    """批量查作者，避免列表页 N+1。"""
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.username).where(User.id.in_(user_ids))
        )
    ).all()
    return {r[0]: AuthorBrief(id=r[0], username=r[1]) for r in rows}


def _topic_out(t: ForumTopic, authors: dict[int, AuthorBrief]) -> TopicOut:
    return TopicOut(
        id=t.id,
        title=t.title,
        body=t.body,
        category=t.category,
        is_pinned=t.is_pinned,
        is_locked=t.is_locked,
        reply_count=t.reply_count,
        created_at=t.created_at,
        last_reply_at=t.last_reply_at,
        paper_id=t.paper_id,
        author=authors.get(t.author_id),
    )


def _reply_out(r: ForumReply, authors: dict[int, AuthorBrief]) -> ReplyOut:
    return ReplyOut(
        id=r.id,
        topic_id=r.topic_id,
        body=r.body,
        created_at=r.created_at,
        author=authors.get(r.author_id),
    )


@router.get("/topics", response_model=TopicListOut)
async def list_topics(
    category: str | None = Query(
        default=None,
        pattern=r"^(paper|method|life|collab|meta|notice|discussion|question|suggestion)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    paper_id: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> TopicListOut:
    """帖子列表：置顶优先，其次按最近活跃。"""
    tenant_id = require_tenant_id()
    stmt = select(ForumTopic).where(
        ForumTopic.tenant_id == tenant_id,
        ForumTopic.deleted_at.is_(None),
    )
    if category:
        board = CATEGORY_BOARD.get(category, (category,))
        stmt = stmt.where(ForumTopic.category.in_(board))
    if paper_id is not None:
        stmt = stmt.where(ForumTopic.paper_id == paper_id)
    rows, meta = await paginate(
        db,
        stmt,
        page=page,
        page_size=page_size,
        # 置顶优先：desc(True) > desc(False)，然后最近活跃
        order_by=(
            desc(ForumTopic.is_pinned),
            desc(func.coalesce(ForumTopic.last_reply_at, ForumTopic.created_at)),
            ForumTopic.id.desc(),
        ),
    )
    authors = await _author_map(db, {r.author_id for r in rows})
    return TopicListOut(
        data=[_topic_out(r, authors) for r in rows],
        meta={
            "total": meta.total,
            "page": meta.page,
            "page_size": meta.page_size,
            "total_pages": meta.total_pages,
        },
    )


@router.get("/boards")
async def board_stats(db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    """五个版块的帖子数与最近活跃时间。

    冷启动阶段版块卡片如果只写定位、不写“有多少人在聊”，社区会显得空。
    这里按版块聚合（旧分类按 CATEGORY_BOARD 归并），一次返回五条。
    """
    tenant_id = require_tenant_id()
    rows = (
        await db.execute(
            select(
                ForumTopic.category,
                func.count(ForumTopic.id),
                func.max(func.coalesce(ForumTopic.last_reply_at, ForumTopic.created_at)),
            ).where(
                ForumTopic.tenant_id == tenant_id,
                ForumTopic.deleted_at.is_(None),
            ).group_by(ForumTopic.category)
        )
    ).all()
    buckets: dict[str, dict[str, object]] = {
        b: {"category": b, "topics": 0, "last_active": None}
        for b in ("paper", "method", "life", "collab", "meta")
    }
    for raw, count, last in rows:
        board = next((b for b, raws in CATEGORY_BOARD.items() if raw in raws), raw)
        if board not in buckets:
            continue
        buckets[board]["topics"] = int(buckets[board]["topics"]) + int(count)
        current = buckets[board]["last_active"]
        if last is not None and (current is None or last > current):
            buckets[board]["last_active"] = last
    for b in buckets.values():
        if b["last_active"] is not None:
            b["last_active"] = b["last_active"].isoformat()
    return {"data": list(buckets.values())}


@router.get("/topics/{topic_id}", response_model=TopicOut)
async def get_topic(topic_id: int, db: AsyncSession = Depends(get_db)) -> TopicOut:
    tenant_id = require_tenant_id()
    topic = (
        await db.execute(
            select(ForumTopic).where(
                ForumTopic.id == topic_id,
                ForumTopic.tenant_id == tenant_id,
                ForumTopic.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    authors = await _author_map(db, {topic.author_id})
    return _topic_out(topic, authors)


@router.get("/topics/{topic_id}/replies", response_model=list[ReplyOut])
async def list_replies(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[ReplyOut]:
    """回帖按时间正序（讨论要按上下文读，倒序会读不懂）。"""
    tenant_id = require_tenant_id()
    rows = (
        await db.execute(
            select(ForumReply)
            .where(
                ForumReply.topic_id == topic_id,
                ForumReply.tenant_id == tenant_id,
                ForumReply.deleted_at.is_(None),
            )
            .order_by(ForumReply.created_at.asc(), ForumReply.id.asc())
            .limit(500)
        )
    ).scalars().all()
    authors = await _author_map(db, {r.author_id for r in rows})
    return [_reply_out(r, authors) for r in rows]


@router.post("/topics", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
async def create_topic(
    payload: TopicCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TopicOut:
    """发帖。登录即可，不设积分门槛。"""
    tenant_id = require_tenant_id()
    # 公告类帖子只允许编辑/管理员发——否则任何人都能伪装成官方公告
    if payload.category == "notice":
        allowed = current_user.is_admin or await user_has_role(db, current_user, ROLE_EDITOR)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="「公告」分类仅限编辑与管理员发布",
            )
    topic = ForumTopic(
        tenant_id=tenant_id,
        author_id=current_user.id,
        title=payload.title.strip(),
        body=payload.body.strip(),
        category=payload.category,
        paper_id=payload.paper_id,
    )
    db.add(topic)
    await db.commit()
    await db.refresh(topic)
    return _topic_out(topic, {current_user.id: AuthorBrief(id=current_user.id, username=current_user.username)})


@router.post(
    "/topics/{topic_id}/replies",
    response_model=ReplyOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_reply(
    topic_id: int,
    payload: ReplyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReplyOut:
    tenant_id = require_tenant_id()
    topic = (
        await db.execute(
            select(ForumTopic).where(
                ForumTopic.id == topic_id,
                ForumTopic.tenant_id == tenant_id,
                ForumTopic.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    if topic.is_locked:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该帖已锁定，无法回复")

    reply = ForumReply(
        tenant_id=tenant_id,
        topic_id=topic_id,
        author_id=current_user.id,
        body=payload.body.strip(),
    )
    db.add(reply)
    # 反冗余计数与最近活跃时间在同一事务里更新
    topic.reply_count += 1
    topic.last_reply_at = utcnow()
    await db.commit()
    await db.refresh(reply)
    return _reply_out(
        reply, {current_user.id: AuthorBrief(id=current_user.id, username=current_user.username)}
    )


class ModerateRequest(BaseModel):
    is_pinned: bool | None = None
    is_locked: bool | None = None


async def _require_moderator(db: AsyncSession, user: User) -> None:
    if user.is_admin or await user_has_role(db, user, ROLE_EDITOR):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要编辑或管理员权限")


@router.patch("/topics/{topic_id}", response_model=TopicOut)
async def moderate_topic(
    topic_id: int,
    payload: ModerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TopicOut:
    """版主操作：置顶 / 锁定。"""
    await _require_moderator(db, current_user)
    tenant_id = require_tenant_id()
    topic = (
        await db.execute(
            select(ForumTopic).where(
                ForumTopic.id == topic_id, ForumTopic.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    if payload.is_pinned is not None:
        topic.is_pinned = payload.is_pinned
    if payload.is_locked is not None:
        topic.is_locked = payload.is_locked
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            action="forum.moderate",
            target_type="forum_topic",
            target_id=str(topic.id),
            payload={"is_pinned": topic.is_pinned, "is_locked": topic.is_locked},
        )
    )
    await db.commit()
    await db.refresh(topic)
    authors = await _author_map(db, {topic.author_id})
    return _topic_out(topic, authors)


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_topic(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除帖子（软删除）：作者本人或版主。"""
    tenant_id = require_tenant_id()
    topic = (
        await db.execute(
            select(ForumTopic).where(
                ForumTopic.id == topic_id, ForumTopic.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    is_moderator = current_user.is_admin or await user_has_role(db, current_user, ROLE_EDITOR)
    if topic.author_id != current_user.id and not is_moderator:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权删除该帖")
    topic.deleted_at = utcnow()
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            action="forum.delete",
            target_type="forum_topic",
            target_id=str(topic.id),
            payload={"moderator": is_moderator},
        )
    )
    await db.commit()


# ---------------------------------------------------------------------------
# 举报（forum_reports）
# ---------------------------------------------------------------------------

class ReportCreate(BaseModel):
    topic_id: int | None = None
    reply_id: int | None = None
    reason: str = Field(default="", max_length=200)


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int | None
    reply_id: int | None
    reason: str
    status: str
    created_at: datetime
    reporter: AuthorBrief | None = None


@router.post("/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def create_report(
    payload: ReportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportOut:
    """举报帖子或回复。登录即可。

    幂等：同一用户对同一对象（topic 或 reply）已有 open 举报时直接返回
    已存在的记录（HTTP 200 语义上是"已存在"，但用 201 也无妨——
    这里统一用 200 让前端区分"新提交"与"重复提交"）。
    """
    tenant_id = require_tenant_id()
    if payload.topic_id is None and payload.reply_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="必须指定 topic_id 或 reply_id",
        )
    # 校验目标存在且未软删
    if payload.topic_id is not None:
        topic = (
            await db.execute(
                select(ForumTopic).where(
                    ForumTopic.id == payload.topic_id,
                    ForumTopic.tenant_id == tenant_id,
                    ForumTopic.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if topic is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
    if payload.reply_id is not None:
        reply = (
            await db.execute(
                select(ForumReply).where(
                    ForumReply.id == payload.reply_id,
                    ForumReply.tenant_id == tenant_id,
                    ForumReply.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if reply is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reply not found")

    # 幂等：查同一用户对同一对象是否已有 open 记录
    target_clause = (
        ForumReport.reply_id == payload.reply_id
        if payload.reply_id is not None
        else ForumReport.topic_id == payload.topic_id
    )
    existing = (
        await db.execute(
            select(ForumReport).where(
                ForumReport.tenant_id == tenant_id,
                ForumReport.reporter_id == current_user.id,
                ForumReport.status == "open",
                target_clause,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # 重复举报：返回 200 + 已有记录，前端 toast 提示"已举报过"
        authors = await _author_map(db, {current_user.id})
        return ReportOut(
            id=existing.id,
            topic_id=existing.topic_id,
            reply_id=existing.reply_id,
            reason=existing.reason,
            status=existing.status,
            created_at=existing.created_at,
            reporter=authors.get(current_user.id),
        )

    report = ForumReport(
        tenant_id=tenant_id,
        reporter_id=current_user.id,
        topic_id=payload.topic_id,
        reply_id=payload.reply_id,
        reason=payload.reason.strip()[:200],
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    authors = await _author_map(db, {current_user.id})
    return ReportOut(
        id=report.id,
        topic_id=report.topic_id,
        reply_id=report.reply_id,
        reason=report.reason,
        status=report.status,
        created_at=report.created_at,
        reporter=authors.get(current_user.id),
    )


@router.get("/reports", response_model=list[ReportOut])
async def list_reports(
    status_filter: str | None = Query(default="open", pattern=r"^(open|resolved|rejected)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> list[ReportOut]:
    """管理端：查看举报队列。仅管理员。"""
    tenant_id = require_tenant_id()
    stmt = select(ForumReport).where(ForumReport.tenant_id == tenant_id)
    if status_filter:
        stmt = stmt.where(ForumReport.status == status_filter)
    stmt = stmt.order_by(ForumReport.created_at.desc()).limit(200)
    rows = (await db.execute(stmt)).scalars().all()
    authors = await _author_map(db, {r.reporter_id for r in rows})
    return [
        ReportOut(
            id=r.id,
            topic_id=r.topic_id,
            reply_id=r.reply_id,
            reason=r.reason,
            status=r.status,
            created_at=r.created_at,
            author=authors.get(r.reporter_id),
        )
        for r in rows
    ]
