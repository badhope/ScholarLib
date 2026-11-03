"""Forum API — 讨论区（发帖 / 回帖 / 版主操作）。

权限模型
--------
- 读：公开（未登录也能浏览，论坛是社区的橱窗）
- 发帖/回帖：登录即可（不设积分门槛——参考前面身份体系 3.0 的原则）
- 置顶/锁定/删除他人帖子：编辑或管理员（版主权限）

为什么不做"分类版块树"：本刊是期刊社区，不是大型论坛。四个平铺分类
（讨论/建议/求助/公告）已经够用，做树状版块只会让冷启动时每版都空。
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
    require_tenant_id,
    user_has_role,
)
from app.core.db import get_db, paginate
from app.core.time import utcnow
from app.models import AuditLog, User
from app.modules.forum.models import ForumReply, ForumTopic

router = APIRouter(prefix="/forum", tags=["forum"])

ForumCategory = Literal["discussion", "suggestion", "question", "notice"]

CATEGORY_LABELS: dict[str, str] = {
    "discussion": "讨论",
    "suggestion": "建议",
    "question": "求助",
    "notice": "公告",
}


class TopicCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=2, max_length=20000)
    category: ForumCategory = "discussion"


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
    category: str | None = Query(default=None, pattern=r"^(discussion|suggestion|question|notice)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> TopicListOut:
    """帖子列表：置顶优先，其次按最近活跃。"""
    tenant_id = require_tenant_id()
    stmt = select(ForumTopic).where(
        ForumTopic.tenant_id == tenant_id,
        ForumTopic.deleted_at.is_(None),
    )
    if category:
        stmt = stmt.where(ForumTopic.category == category)
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
