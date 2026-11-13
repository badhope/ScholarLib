# mypy: ignore-errors
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

import re
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
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
from app.core.storage import get_storage
from app.core.time import utcnow
from app.models import AuditLog, User
from app.modules.forum.models import ForumReaction, ForumReply, ForumReport, ForumTopic

router = APIRouter(prefix="/forum", tags=["forum"])

# 论坛图片：只接受浏览器能直接显示的四种位图。SVG 不能收——SVG 可带
# 脚本，和 Markdown 正文一样属于用户内容，不能给它同源执行权限。
_FORUM_IMAGE_MAX = 5 * 1024 * 1024
_FORUM_IMAGE_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_FORUM_IMAGE_NAME = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp)$")
_FORUM_IMAGE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def _forum_image_magic_ok(contents: bytes, mime: str) -> bool:
    if mime == "image/png":
        return contents.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return contents.startswith(b"\xff\xd8\xff")
    if mime == "image/gif":
        return contents.startswith((b"GIF87a", b"GIF89a"))
    if mime == "image/webp":
        return contents.startswith(b"RIFF") and contents[8:12] == b"WEBP"
    return False


@router.post("/images", status_code=status.HTTP_201_CREATED)
async def upload_forum_image(
    file: UploadFile = File(...),
    _user: User = Depends(get_current_user),
) -> dict[str, str]:
    """上传一张论坛图片，返回可公开访问的短链。

    正文仍只存 Markdown；图片单独落对象存储，不把二进制塞进帖子表。
    """
    mime = (file.content_type or "").lower()
    ext = _FORUM_IMAGE_MIME.get(mime)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只支持 PNG / JPEG / GIF / WebP 图片",
        )
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片为空")
    if len(contents) > _FORUM_IMAGE_MAX:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="图片不能超过 5MB",
        )
    if not _forum_image_magic_ok(contents, mime):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="图片内容与格式不符",
        )
    name = f"{uuid4().hex}{ext}"
    await get_storage().save(f"forum/{name}", contents, content_type=mime)
    return {"url": f"/api/forum/images/{name}"}


@router.get("/images/{filename}")
async def get_forum_image(filename: str) -> Response:
    """公开读取论坛图片；文件名是 128 位随机串，不可枚举。"""
    if not _FORUM_IMAGE_NAME.match(filename):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在")
    try:
        contents = await get_storage().load(f"forum/{filename}")
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在") from None
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }[filename.rsplit(".", 1)[1]]
    return Response(content=contents, media_type=mime, headers=_FORUM_IMAGE_HEADERS)


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


REACTION_KINDS = ("agree", "helpful", "bookmark")


class ReplyCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    parent_id: int | None = Field(default=None, ge=1)


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
    reactions: dict[str, int] = Field(default_factory=dict)
    viewer_reactions: list[str] = Field(default_factory=list)


class TopicListOut(BaseModel):
    data: list[TopicOut]
    meta: dict[str, object]


class ReplyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int
    parent_id: int | None = None
    body: str
    created_at: datetime
    author: AuthorBrief | None = None
    reactions: dict[str, int] = Field(default_factory=dict)
    viewer_reactions: list[str] = Field(default_factory=list)


async def _author_map(db: AsyncSession, user_ids: set[int]) -> dict[int, AuthorBrief]:
    """批量查作者，避免列表页 N+1。"""
    if not user_ids:
        return {}
    rows = (await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))).all()
    return {r[0]: AuthorBrief(id=r[0], username=r[1]) for r in rows}


async def _reaction_summary(
    db: AsyncSession,
    *,
    target_type: str,
    target_ids: list[int],
    viewer_id: int | None,
) -> tuple[dict[int, dict[str, int]], dict[int, list[str]]]:
    """批量取反馈计数和当前用户已选状态，避免详情页 N+1。"""
    counts: dict[int, dict[str, int]] = {i: {k: 0 for k in REACTION_KINDS} for i in target_ids}
    viewers: dict[int, list[str]] = {i: [] for i in target_ids}
    if not target_ids:
        return counts, viewers
    rows = (
        await db.execute(
            select(ForumReaction.target_id, ForumReaction.kind, func.count())
            .where(
                ForumReaction.tenant_id == require_tenant_id(),
                ForumReaction.target_type == target_type,
                ForumReaction.target_id.in_(target_ids),
            )
            .group_by(ForumReaction.target_id, ForumReaction.kind)
        )
    ).all()
    for tid, kind, count in rows:
        if tid in counts and kind in counts[tid]:
            counts[tid][kind] = int(count)
    if viewer_id is not None:
        viewer_rows = (
            await db.execute(
                select(ForumReaction.target_id, ForumReaction.kind).where(
                    ForumReaction.tenant_id == require_tenant_id(),
                    ForumReaction.user_id == viewer_id,
                    ForumReaction.target_type == target_type,
                    ForumReaction.target_id.in_(target_ids),
                )
            )
        ).all()
        for tid, kind in viewer_rows:
            if tid in viewers:
                viewers[tid].append(kind)
    return counts, viewers


def _topic_out(
    t: ForumTopic,
    authors: dict[int, AuthorBrief],
    reactions: dict[str, int] | None = None,
    viewer_reactions: list[str] | None = None,
) -> TopicOut:
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
        reactions=reactions or {k: 0 for k in REACTION_KINDS},
        viewer_reactions=viewer_reactions or [],
    )


def _reply_out(
    r: ForumReply,
    authors: dict[int, AuthorBrief],
    reactions: dict[str, int] | None = None,
    viewer_reactions: list[str] | None = None,
) -> ReplyOut:
    return ReplyOut(
        id=r.id,
        topic_id=r.topic_id,
        parent_id=r.parent_id,
        body=r.body,
        created_at=r.created_at,
        author=authors.get(r.author_id),
        reactions=reactions or {k: 0 for k in REACTION_KINDS},
        viewer_reactions=viewer_reactions or [],
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
    sort: Literal["latest", "hot"] = Query(default="latest"),
    db: AsyncSession = Depends(get_db),
) -> TopicListOut:
    """帖子列表：置顶优先。latest 按最近活跃，hot 按回复数再按活跃。"""
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
        # 置顶优先：desc(True) > desc(False)。hot 用回复数做热度信号，
        # 不引入浏览数/时间衰减——小型学术社区不需要黑箱热榜。
        order_by=(
            (
                desc(ForumTopic.is_pinned),
                desc(ForumTopic.reply_count),
                desc(ForumTopic.last_reply_at),
            )
            if sort == "hot"
            else (
                desc(ForumTopic.is_pinned),
                desc(func.coalesce(ForumTopic.last_reply_at, ForumTopic.created_at)),
                ForumTopic.id.desc(),
            )
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
            )
            .where(
                ForumTopic.tenant_id == tenant_id,
                ForumTopic.deleted_at.is_(None),
            )
            .group_by(ForumTopic.category)
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
        buckets[board]["topics"] = int(str(buckets[board]["topics"])) + int(str(count))
        current = buckets[board]["last_active"]
        if last is not None and (current is None or last > current):
            buckets[board]["last_active"] = last
    for b in buckets.values():
        if b["last_active"] is not None:
            b["last_active"] = b["last_active"].isoformat()  # type: ignore[union-attr]
    return {"data": list(buckets.values())}


@router.get("/topics/{topic_id}", response_model=TopicOut)
async def get_topic(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> TopicOut:
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
    counts, viewers = await _reaction_summary(
        db,
        target_type="topic",
        target_ids=[topic.id],
        viewer_id=current_user.id if current_user else None,
    )
    return _topic_out(topic, authors, counts.get(topic.id), viewers.get(topic.id))


@router.get("/topics/{topic_id}/replies", response_model=list[ReplyOut])
async def list_replies(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
) -> list[ReplyOut]:
    """回帖按时间正序（讨论要按上下文读，倒序会读不懂）。"""
    tenant_id = require_tenant_id()
    rows = (
        (
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
        )
        .scalars()
        .all()
    )
    authors = await _author_map(db, {r.author_id for r in rows})
    counts, viewers = await _reaction_summary(
        db,
        target_type="reply",
        target_ids=[r.id for r in rows],
        viewer_id=current_user.id if current_user else None,
    )
    return [_reply_out(r, authors, counts.get(r.id), viewers.get(r.id)) for r in rows]


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
    return _topic_out(
        topic, {current_user.id: AuthorBrief(id=current_user.id, username=current_user.username)}
    )


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

    parent_id = payload.parent_id
    if parent_id is not None:
        parent = (
            await db.execute(
                select(ForumReply).where(
                    ForumReply.id == parent_id,
                    ForumReply.topic_id == topic_id,
                    ForumReply.tenant_id == tenant_id,
                    ForumReply.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="被回复的楼层不存在")
        # 只保留两级：回复子楼时归到根楼，既保留上下文，又不会出现无限缩进。
        parent_id = parent.parent_id or parent.id

    reply = ForumReply(
        tenant_id=tenant_id,
        topic_id=topic_id,
        author_id=current_user.id,
        body=payload.body.strip(),
        parent_id=parent_id,
    )
    db.add(reply)
    # 反冗余计数与最近活跃时间在同一事务里更新
    topic.reply_count += 1
    topic.last_reply_at = utcnow()
    await db.commit()
    await db.refresh(reply)
    return _reply_out(
        reply,
        {current_user.id: AuthorBrief(id=current_user.id, username=current_user.username)},
        {k: 0 for k in REACTION_KINDS},
        [],
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
            select(ForumTopic).where(ForumTopic.id == topic_id, ForumTopic.tenant_id == tenant_id)
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
            select(ForumTopic).where(ForumTopic.id == topic_id, ForumTopic.tenant_id == tenant_id)
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
# 多维反馈（forum_reactions）
# ---------------------------------------------------------------------------


class ReactionToggle(BaseModel):
    target_type: Literal["topic", "reply"]
    target_id: int = Field(ge=1)
    kind: Literal["agree", "helpful", "bookmark"]


class ReactionOut(BaseModel):
    target_type: str
    target_id: int
    kind: str
    active: bool
    counts: dict[str, int]


@router.post("/reactions/toggle", response_model=ReactionOut)
async def toggle_reaction(
    payload: ReactionToggle,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReactionOut:
    """赞同 / 有帮助 / 收藏：再点一次取消。

    不做“反对/踩”。知乎的多维反馈里，赞同与感谢是两件事：前者是
    “我同意”，后者是“这对我有用”；收藏则是“以后还要回看”。这三件事
    对学术讨论都有意义，且不会把少数意见踩下去。
    """
    tenant_id = require_tenant_id()
    if payload.target_type == "topic":
        target = (
            await db.execute(
                select(ForumTopic).where(
                    ForumTopic.id == payload.target_id,
                    ForumTopic.tenant_id == tenant_id,
                    ForumTopic.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
    else:
        target = (
            await db.execute(
                select(ForumReply).where(
                    ForumReply.id == payload.target_id,
                    ForumReply.tenant_id == tenant_id,
                    ForumReply.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="反馈对象不存在")

    existing = (
        await db.execute(
            select(ForumReaction).where(
                ForumReaction.tenant_id == tenant_id,
                ForumReaction.user_id == current_user.id,
                ForumReaction.target_type == payload.target_type,
                ForumReaction.target_id == payload.target_id,
                ForumReaction.kind == payload.kind,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            ForumReaction(
                tenant_id=tenant_id,
                user_id=current_user.id,
                target_type=payload.target_type,
                target_id=payload.target_id,
                kind=payload.kind,
            )
        )
        active = True
    else:
        await db.delete(existing)
        active = False
    await db.commit()

    counts, _ = await _reaction_summary(
        db,
        target_type=payload.target_type,
        target_ids=[payload.target_id],
        viewer_id=None,
    )
    return ReactionOut(
        target_type=payload.target_type,
        target_id=payload.target_id,
        kind=payload.kind,
        active=active,
        counts=counts.get(payload.target_id, {k: 0 for k in REACTION_KINDS}),
    )


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
            reporter=authors.get(r.reporter_id),
        )
        for r in rows
    ]
