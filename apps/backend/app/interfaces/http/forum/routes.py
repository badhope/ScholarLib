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
from sqlalchemy import desc, func, or_, select
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
from app.core.moderation import rejection_detail
from app.core.storage import get_storage
from app.core.time import utcnow
from app.domain.forum.models import ForumBoard, ForumReaction, ForumReply, ForumReport, ForumTopic
from app.models import AuditLog, User

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
    # 树形版块：新客户端传 board_id；旧客户端只传 category 仍然兼容。
    board_id: int | None = Field(default=None, ge=1)
    board_slug: str | None = Field(default=None, max_length=40)
    paper_id: int | None = Field(default=None, ge=1)


REACTION_KINDS = ("agree", "helpful", "bookmark")


class ReplyCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    parent_id: int | None = Field(default=None, ge=1)


class AuthorBrief(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    avatar_url: str | None = None


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    category: str
    board_id: int | None = None
    board_slug: str | None = None
    board_name: str | None = None
    board_path: str | None = None
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
    rows = (
        await db.execute(
            select(User.id, User.username, User.display_name, User.avatar_url).where(
                User.id.in_(user_ids)
            )
        )
    ).all()
    return {
        r[0]: AuthorBrief(
            id=r[0],
            username=r[1],
            display_name=r[2],
            avatar_url=r[3],
        )
        for r in rows
    }


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


async def _board_index(db: AsyncSession, tenant_id) -> dict[int, ForumBoard]:
    """当前租户全部版块，供列表页一次解析名称/路径，避免 N+1。"""
    rows = (
        (
            await db.execute(
                select(ForumBoard)
                .where(ForumBoard.tenant_id == tenant_id)
                .order_by(ForumBoard.sort_order, ForumBoard.id)
            )
        )
        .scalars()
        .all()
    )
    return {b.id: b for b in rows}


def _board_path(board: ForumBoard | None, index: dict[int, ForumBoard]) -> str | None:
    if board is None:
        return None
    names: list[str] = []
    seen: set[int] = set()
    cursor: ForumBoard | None = board
    while cursor is not None and cursor.id not in seen:
        seen.add(cursor.id)
        names.append(cursor.name)
        cursor = index.get(cursor.parent_id) if cursor.parent_id else None
    return " / ".join(reversed(names))


def _topic_out(
    t: ForumTopic,
    authors: dict[int, AuthorBrief],
    reactions: dict[str, int] | None = None,
    viewer_reactions: list[str] | None = None,
    boards: dict[int, ForumBoard] | None = None,
) -> TopicOut:
    board = boards.get(t.board_id) if boards and t.board_id else None
    return TopicOut(
        id=t.id,
        title=t.title,
        body=t.body,
        category=t.category,
        board_id=t.board_id,
        board_slug=board.slug if board else None,
        board_name=board.name if board else None,
        board_path=_board_path(board, boards or {}),
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


def _subtree_ids(boards: list[ForumBoard], root: ForumBoard) -> set[int]:
    """父板块筛选时把全部子板块一起带上；3 层也只需一次内存遍历。"""
    children: dict[int, list[ForumBoard]] = {}
    for b in boards:
        if b.parent_id is not None:
            children.setdefault(b.parent_id, []).append(b)
    ids: set[int] = set()
    stack = [root]
    while stack:
        cur = stack.pop()
        if cur.id in ids:
            continue
        ids.add(cur.id)
        stack.extend(children.get(cur.id, []))
    return ids


def _ancestor_ids(boards: list[ForumBoard], board: ForumBoard) -> set[int]:
    index = {b.id: b for b in boards}
    ids: set[int] = set()
    cur: ForumBoard | None = board
    while cur is not None and cur.id not in ids:
        ids.add(cur.id)
        cur = index.get(cur.parent_id) if cur.parent_id else None
    return ids


async def _resolve_board(
    db: AsyncSession,
    tenant_id,
    *,
    board_id: int | None = None,
    board_slug: str | None = None,
) -> ForumBoard | None:
    stmt = select(ForumBoard).where(ForumBoard.tenant_id == tenant_id)
    if board_id is not None:
        stmt = stmt.where(ForumBoard.id == board_id)
    elif board_slug is not None:
        stmt = stmt.where(ForumBoard.slug == board_slug)
    else:
        return None
    return (await db.execute(stmt)).scalar_one_or_none()


@router.get("/topics", response_model=TopicListOut)
async def list_topics(
    # 兼容旧客户端：既接受旧分类别名，也接受新版树形版块的 slug
    # （academic / site / paper-reading …）。父板块会聚合全部后代。
    category: str | None = Query(default=None, pattern=r"^[a-z0-9-]{2,40}$"),
    board: str | None = Query(
        default=None,
        pattern=r"^[a-z0-9-]{2,40}$",
        description="树形版块 slug；父板块会聚合全部子板块",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    paper_id: int | None = Query(default=None, ge=1),
    sort: Literal["latest", "hot"] = Query(default="latest"),
    db: AsyncSession = Depends(get_db),
) -> TopicListOut:
    """帖子列表：置顶优先。latest 按最近活跃，hot 按回复数再按活跃。"""
    tenant_id = require_tenant_id()
    all_boards = (
        (
            await db.execute(
                select(ForumBoard)
                .where(ForumBoard.tenant_id == tenant_id)
                .order_by(ForumBoard.sort_order, ForumBoard.id)
            )
        )
        .scalars()
        .all()
    )
    stmt = select(ForumTopic).where(
        ForumTopic.tenant_id == tenant_id,
        ForumTopic.deleted_at.is_(None),
    )
    # board 优先；旧 category 仍可用。父板块筛选包含全部后代。
    selected_slugs: set[str] = set()
    selected_ids: set[int] = set()
    if board:
        root = next((b for b in all_boards if b.slug == board), None)
        if root is None:
            return TopicListOut(
                data=[], meta={"total": 0, "page": page, "page_size": page_size, "total_pages": 0}
            )
        subtree = _subtree_ids(list(all_boards), root)
        selected_ids = subtree
        selected_slugs = {b.slug for b in all_boards if b.id in subtree}
    elif category:
        # 旧分类别名映射到新版块，再带上子板块
        slug = next((b for b in all_boards if b.slug == category), None)
        if slug is None:
            slug = next(
                (
                    b
                    for b in all_boards
                    if b.slug
                    == next((k for k, v in CATEGORY_BOARD.items() if category in v), category)
                ),
                None,
            )
        if slug is not None:
            subtree = _subtree_ids(list(all_boards), slug)
            selected_ids = subtree
            selected_slugs = {b.slug for b in all_boards if b.id in subtree}
        else:
            selected_slugs = {category}

    if selected_ids or selected_slugs:
        clauses = []
        if selected_ids:
            clauses.append(ForumTopic.board_id.in_(selected_ids))
        if selected_slugs:
            clauses.append(ForumTopic.category.in_(selected_slugs))
        stmt = stmt.where(or_(*clauses))
    if paper_id is not None:
        stmt = stmt.where(ForumTopic.paper_id == paper_id)
    rows, meta = await paginate(
        db,
        stmt,
        page=page,
        page_size=page_size,
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
    boards = {b.id: b for b in all_boards}
    return TopicListOut(
        data=[_topic_out(r, authors, boards=boards) for r in rows],
        meta={
            "total": meta.total,
            "page": meta.page,
            "page_size": meta.page_size,
            "total_pages": meta.total_pages,
        },
    )


@router.get("/boards")
async def board_stats(db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    """树形版块及帖子数。

    ``data`` 保留旧的扁平结构（category = slug，兼容旧前端/测试），
    ``tree`` 给新前台按「父板块 → 子板块 → 子子板块」渲染。
    父板块的 ``total_topics`` 是整棵子树的合计。
    """
    tenant_id = require_tenant_id()
    boards = (
        (
            await db.execute(
                select(ForumBoard)
                .where(ForumBoard.tenant_id == tenant_id)
                .order_by(ForumBoard.sort_order, ForumBoard.id)
            )
        )
        .scalars()
        .all()
    )
    raw_counts = (
        await db.execute(
            select(
                ForumTopic.board_id,
                ForumTopic.category,
                func.count(ForumTopic.id),
                func.max(func.coalesce(ForumTopic.last_reply_at, ForumTopic.created_at)),
            )
            .where(
                ForumTopic.tenant_id == tenant_id,
                ForumTopic.deleted_at.is_(None),
            )
            .group_by(ForumTopic.board_id, ForumTopic.category)
        )
    ).all()
    direct: dict[int, dict[str, object]] = {
        b.id: {"topics": 0, "last_active": None} for b in boards
    }
    legacy_slugs = {b.slug for b in boards}
    for board_id, category, count, last in raw_counts:
        target = board_id if board_id in direct else None
        if target is None and category in legacy_slugs:
            target = next((b.id for b in boards if b.slug == category), None)
        if target is None:
            continue
        direct[target]["topics"] = int(str(direct[target]["topics"])) + int(str(count))
        current = direct[target]["last_active"]
        if last is not None and (current is None or last > current):
            direct[target]["last_active"] = last

    flat: list[dict[str, object]] = []
    for b in boards:
        row = {
            "id": b.id,
            "parent_id": b.parent_id,
            "slug": b.slug,
            "category": b.slug,
            "name": b.name,
            "description": b.description,
            "sort_order": b.sort_order,
            "is_active": b.is_active,
            "topics": direct[b.id]["topics"],
            "last_active": direct[b.id]["last_active"],
        }
        if row["last_active"] is not None:
            row["last_active"] = row["last_active"].isoformat()  # type: ignore[union-attr]
        flat.append(row)

    by_parent: dict[int | None, list[dict[str, object]]] = {}
    for row in flat:
        by_parent.setdefault(row["parent_id"], []).append(row)

    def build(parent_id: int | None) -> list[dict[str, object]]:
        nodes: list[dict[str, object]] = []
        for row in by_parent.get(parent_id, []):
            children = build(row["id"])  # type: ignore[arg-type]
            own = int(str(row["topics"]))
            total = own + sum(int(str(c["total_topics"])) for c in children)
            node = dict(row)
            node["total_topics"] = total
            node["children"] = children
            last_values = [row["last_active"]] + [c["last_active"] for c in children]
            node["last_active"] = max([v for v in last_values if v], default=None)
            nodes.append(node)
        return nodes

    return {"data": flat, "tree": build(None), "total": len(flat)}


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
    boards = await _board_index(db, tenant_id)
    return _topic_out(topic, authors, counts.get(topic.id), viewers.get(topic.id), boards)


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
    blocked = rejection_detail(f"{payload.title}\n{payload.body}")
    if blocked is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=blocked)
    tenant_id = require_tenant_id()
    board = await _resolve_board(
        db, tenant_id, board_id=payload.board_id, board_slug=payload.board_slug
    )
    if (payload.board_id is not None or payload.board_slug is not None) and board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版块不存在")
    if board is not None and not board.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="版块已关闭")
    category = board.slug if board is not None else payload.category
    # 公告类帖子只允许编辑/管理员发——否则任何人都能伪装成官方公告
    if category == "notice" or (board is not None and board.slug == "meta"):
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
        category=category,
        board_id=board.id if board is not None else None,
        paper_id=payload.paper_id,
    )
    db.add(topic)
    author = AuthorBrief(
        id=current_user.id,
        username=current_user.username,
        display_name=current_user.display_name,
        avatar_url=current_user.avatar_url,
    )
    await db.commit()
    await db.refresh(topic)
    # 社区活跃奖励：发主题按后台规则（默认 1 R 币）；失败不影响发帖本身。
    try:
        from app.domain.gamification import currency

        await currency.award(
            db,
            current_user,
            "forum.topic",
            ref_type="forum_topic",
            ref_id=str(topic.id),
            commit=True,
        )
    except Exception:
        await db.rollback()
    boards = await _board_index(db, tenant_id)
    return _topic_out(topic, {author.id: author}, boards=boards)


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
    blocked = rejection_detail(payload.body)
    if blocked is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=blocked)

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
    author = AuthorBrief(
        id=current_user.id,
        username=current_user.username,
        display_name=current_user.display_name,
        avatar_url=current_user.avatar_url,
    )
    db.add(reply)
    # 反冗余计数与最近活跃时间在同一事务里更新
    topic.reply_count += 1
    topic.last_reply_at = utcnow()
    await db.flush()
    # 回帖通知主题作者；自己回自己不通知。
    if topic.author_id != current_user.id:
        from app.domain.notifications import services as notifications

        author_user = (
            await db.execute(select(User).where(User.id == topic.author_id))
        ).scalar_one_or_none()
        if author_user is not None:
            prefs = notifications.merged_prefs(author_user)
            if prefs.get("in_app_forum"):
                await notifications.create(
                    db,
                    tenant_id=tenant_id,
                    user_id=author_user.id,
                    type_="forum.reply",
                    title=f"你的帖子「{topic.title[:80]}」有新回复",
                    body=f"{current_user.display_name or current_user.username}：{payload.body.strip()[:120]}",
                    related_type="forum_topic",
                    related_id=str(topic.id),
                )
            if prefs.get("email_forum") and author_user.email:
                await notifications.record_email_digest(
                    db,
                    tenant_id=tenant_id,
                    user_id=author_user.id,
                    event_type="forum.reply",
                    recipient_email=author_user.email,
                    subject=f"Rubbish：{topic.title[:80]} 有新回复",
                    text=f"{current_user.display_name or current_user.username} 回复了你的帖子：\n\n{payload.body.strip()[:500]}",
                    related_type="forum_topic",
                    related_id=str(topic.id),
                )
    await db.commit()
    await db.refresh(reply)
    # 回帖按后台规则（默认 0 R 币，防止灌水）；失败不影响回帖本身。
    try:
        from app.domain.gamification import currency

        await currency.award(
            db,
            current_user,
            "forum.reply",
            ref_type="forum_reply",
            ref_id=str(reply.id),
            commit=True,
        )
    except Exception:
        await db.rollback()
    return _reply_out(
        reply,
        {author.id: author},
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
    boards = await _board_index(db, tenant_id)
    return _topic_out(topic, authors, boards=boards)


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
    resolved_at: datetime | None = None
    source: str = "forum"
    target_type: str | None = None
    target_id: int | None = None
    target_excerpt: str | None = None
    target_author: AuthorBrief | None = None
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
            resolved_at=existing.resolved_at,
            target_type="reply" if existing.reply_id else "topic",
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
        resolved_at=report.resolved_at,
        target_type="reply" if report.reply_id else "topic",
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
    topic_ids = {r.topic_id for r in rows if r.topic_id}
    reply_ids = {r.reply_id for r in rows if r.reply_id}
    topics = (
        {
            t.id: t
            for t in (await db.execute(select(ForumTopic).where(ForumTopic.id.in_(topic_ids))))
            .scalars()
            .all()
        }
        if topic_ids
        else {}
    )
    replies = (
        {
            r.id: r
            for r in (await db.execute(select(ForumReply).where(ForumReply.id.in_(reply_ids))))
            .scalars()
            .all()
        }
        if reply_ids
        else {}
    )
    target_author_ids = {
        *(t.author_id for t in topics.values()),
        *(r.author_id for r in replies.values()),
    }
    authors = await _author_map(db, {r.reporter_id for r in rows} | target_author_ids)
    out: list[ReportOut] = []
    for r in rows:
        topic = topics.get(r.topic_id) if r.topic_id else None
        reply = replies.get(r.reply_id) if r.reply_id else None
        target = topic or reply
        excerpt = None
        if topic is not None:
            excerpt = f"{topic.title} · {topic.body[:120]}"
        elif reply is not None:
            excerpt = reply.body[:140]
        out.append(
            ReportOut(
                id=r.id,
                topic_id=r.topic_id,
                reply_id=r.reply_id,
                reason=r.reason,
                status=r.status,
                created_at=r.created_at,
                resolved_at=r.resolved_at,
                target_type="reply" if reply is not None else "topic",
                target_excerpt=excerpt,
                target_author=authors.get(target.author_id) if target is not None else None,
                reporter=authors.get(r.reporter_id),
            )
        )
    # 合并评论/投稿举报：与论坛举报同一队列、同一套处置动作。
    from app.domain.comments.models import Comment
    from app.domain.submission.models import Submission
    from app.models import ContentReport

    content_stmt = select(ContentReport).where(ContentReport.tenant_id == tenant_id)
    if status_filter:
        content_stmt = content_stmt.where(ContentReport.status == status_filter)
    content_rows = (
        (await db.execute(content_stmt.order_by(ContentReport.created_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    comment_ids = {r.target_id for r in content_rows if r.target_type == "comment"}
    submission_ids = {r.target_id for r in content_rows if r.target_type == "submission"}
    comments = (
        {
            c.id: c
            for c in (await db.execute(select(Comment).where(Comment.id.in_(comment_ids))))
            .scalars()
            .all()
        }
        if comment_ids
        else {}
    )
    submissions = (
        {
            x.id: x
            for x in (await db.execute(select(Submission).where(Submission.id.in_(submission_ids))))
            .scalars()
            .all()
        }
        if submission_ids
        else {}
    )
    content_author_ids = {
        *(c.user_id for c in comments.values()),
        *(x.submitted_by for x in submissions.values()),
    }
    content_authors = await _author_map(
        db, {r.reporter_id for r in content_rows} | content_author_ids
    )
    for r in content_rows:
        author_id: int | None = None
        excerpt: str | None = None
        if r.target_type == "comment":
            comment = comments.get(r.target_id)
            if comment is not None:
                author_id = comment.user_id
                excerpt = comment.body[:140]
        else:
            submission = submissions.get(r.target_id)
            if submission is not None:
                author_id = submission.submitted_by
                excerpt = f"{submission.title} · {submission.abstract[:120]}"
        out.append(
            ReportOut(
                id=r.id,
                topic_id=None,
                reply_id=None,
                source="content",
                target_type=r.target_type,
                target_id=r.target_id,
                reason=r.reason,
                status=r.status,
                created_at=r.created_at,
                resolved_at=r.resolved_at,
                target_excerpt=excerpt,
                target_author=content_authors.get(author_id) if author_id else None,
                reporter=content_authors.get(r.reporter_id),
            )
        )
    return out


class ContentReportCreate(BaseModel):
    target_type: Literal["comment", "submission"]
    target_id: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=200)


@router.post("/content-reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def create_content_report(
    payload: ContentReportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportOut:
    """举报评论或投稿。登录即可；同一用户同一对象只保留一条 open。"""
    from app.domain.comments.models import Comment
    from app.domain.submission.models import Submission
    from app.models import ContentReport

    tenant_id = require_tenant_id()
    target_author_id: int
    excerpt: str
    if payload.target_type == "comment":
        target = (
            await db.execute(
                select(Comment).where(
                    Comment.id == payload.target_id, Comment.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if target is None or target.status == "rejected":
            raise HTTPException(status_code=404, detail="评论不存在")
        target_author_id = target.user_id
        excerpt = target.body[:140]
    else:
        target = (
            await db.execute(
                select(Submission).where(
                    Submission.id == payload.target_id,
                    Submission.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="投稿不存在")
        is_staff = current_user.is_admin or await user_has_role(db, current_user, ROLE_EDITOR)
        if target.submitted_by != current_user.id and not is_staff:
            raise HTTPException(status_code=403, detail="无权举报该投稿")
        target_author_id = target.submitted_by
        excerpt = f"{target.title} · {target.abstract[:120]}"
    if target_author_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能举报自己的内容")

    existing = (
        (
            await db.execute(
                select(ContentReport).where(
                    ContentReport.tenant_id == tenant_id,
                    ContentReport.reporter_id == current_user.id,
                    ContentReport.target_type == payload.target_type,
                    ContentReport.target_id == payload.target_id,
                    ContentReport.status == "open",
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        authors = await _author_map(db, {existing.reporter_id, target_author_id})
        return ReportOut(
            id=existing.id,
            topic_id=None,
            reply_id=None,
            source="content",
            target_type=existing.target_type,
            target_id=existing.target_id,
            reason=existing.reason,
            status=existing.status,
            created_at=existing.created_at,
            resolved_at=existing.resolved_at,
            target_excerpt=excerpt,
            target_author=authors.get(target_author_id),
            reporter=authors.get(existing.reporter_id),
        )

    report = ContentReport(
        tenant_id=tenant_id,
        reporter_id=current_user.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        reason=payload.reason.strip(),
        status="open",
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    authors = await _author_map(db, {current_user.id, target_author_id})
    return ReportOut(
        id=report.id,
        topic_id=None,
        reply_id=None,
        source="content",
        target_type=report.target_type,
        target_id=report.target_id,
        reason=report.reason,
        status=report.status,
        created_at=report.created_at,
        resolved_at=report.resolved_at,
        target_excerpt=excerpt,
        target_author=authors.get(target_author_id),
        reporter=authors.get(report.reporter_id),
    )


@router.patch("/content-reports/{report_id}", response_model=ReportOut)
async def handle_content_report(
    report_id: int,
    payload: ReportAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ReportOut:
    """评论/投稿举报处置：驳回 / 下架 / 停用作者。"""
    from app.domain.comments.models import Comment
    from app.domain.submission.models import Submission
    from app.models import ContentReport

    tenant_id = require_tenant_id()
    report = (
        await db.execute(
            select(ContentReport).where(
                ContentReport.id == report_id, ContentReport.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="举报不存在")
    if report.status != "open":
        raise HTTPException(status_code=409, detail="该举报已处理")
    author: User | None = None
    excerpt: str | None = None
    if report.target_type == "comment":
        target = (
            await db.execute(
                select(Comment).where(
                    Comment.id == report.target_id, Comment.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="被举报评论已被删除")
        author = (
            await db.execute(select(User).where(User.id == target.user_id))
        ).scalar_one_or_none()
        excerpt = target.body[:140]
    else:
        target = (
            await db.execute(
                select(Submission).where(
                    Submission.id == report.target_id, Submission.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="被举报投稿已被删除")
        author = (
            await db.execute(select(User).where(User.id == target.submitted_by))
        ).scalar_one_or_none()
        excerpt = f"{target.title} · {target.abstract[:120]}"

    now = utcnow()
    if payload.action == "dismiss":
        report.status = "rejected"
    else:
        if report.target_type == "comment":
            target.status = "rejected"
            target.moderated_by = current_user.id
            target.moderated_at = now
            target.moderation_note = payload.note
        else:
            target.status = "rejected"
            target.admin_note = payload.note or "举报处置：下架"
            target.reviewed_at = now
        report.status = "resolved"
    report.resolved_at = now
    if payload.action == "suspend_author" and author is not None:
        if author.id != current_user.id:
            author.is_active = False
            author.token_version = (author.token_version or 0) + 1
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor_user_id=current_user.id,
                    action="content.report.suspend_author",
                    target_type="user",
                    target_id=str(author.id),
                    payload={"report_id": report.id, "note": payload.note},
                )
            )
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            action=f"content.report.{payload.action}",
            target_type=report.target_type,
            target_id=str(report.target_id),
            payload={"report_id": report.id, "note": payload.note},
        )
    )
    await db.commit()
    await db.refresh(report)
    authors = await _author_map(
        db, {report.reporter_id, author.id} if author is not None else {report.reporter_id}
    )
    return ReportOut(
        id=report.id,
        topic_id=None,
        reply_id=None,
        source="content",
        target_type=report.target_type,
        target_id=report.target_id,
        reason=report.reason,
        status=report.status,
        created_at=report.created_at,
        resolved_at=report.resolved_at,
        target_excerpt=excerpt,
        target_author=authors.get(author.id) if author is not None else None,
        reporter=authors.get(report.reporter_id),
    )


class ReportAction(BaseModel):
    action: Literal["dismiss", "remove_content", "suspend_author"]
    note: str | None = Field(default=None, max_length=500)


@router.patch("/reports/{report_id}", response_model=ReportOut)
async def handle_report(
    report_id: int,
    payload: ReportAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ReportOut:
    """举报处置：驳回 / 移除内容 / 暂停作者账号。

    - dismiss：举报不成立，标记 rejected，不动内容；
    - remove_content：软删被举报帖子或回复，标记 resolved；
    - suspend_author：停用被举报内容作者（token_version+1，立即踢下线），
      并移除内容。处罚本身写 AuditLog，后台可追溯。
    """
    tenant_id = require_tenant_id()
    report = (
        await db.execute(
            select(ForumReport).where(
                ForumReport.id == report_id, ForumReport.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="举报不存在")
    if report.status != "open":
        raise HTTPException(status_code=409, detail="该举报已处理")

    topic = None
    reply = None
    if report.topic_id:
        topic = (
            await db.execute(
                select(ForumTopic).where(
                    ForumTopic.id == report.topic_id, ForumTopic.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
    if report.reply_id:
        reply = (
            await db.execute(
                select(ForumReply).where(
                    ForumReply.id == report.reply_id, ForumReply.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
    target = topic or reply
    if target is None:
        raise HTTPException(status_code=404, detail="被举报内容已被删除")

    now = utcnow()
    action = payload.action
    if action == "dismiss":
        report.status = "rejected"
        report.resolved_at = now
    else:
        if topic is not None:
            topic.deleted_at = now
        if reply is not None:
            reply.deleted_at = now
        report.status = "resolved"
        report.resolved_at = now
    if action == "suspend_author":
        author = (
            await db.execute(select(User).where(User.id == target.author_id))
        ).scalar_one_or_none()
        if author is not None and author.id != current_user.id:
            author.is_active = False
            author.token_version = (author.token_version or 0) + 1
            db.add(
                AuditLog(
                    tenant_id=tenant_id,
                    actor_user_id=current_user.id,
                    action="forum.report.suspend_author",
                    target_type="user",
                    target_id=str(author.id),
                    payload={"report_id": report.id, "note": payload.note},
                )
            )
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            action=f"forum.report.{action}",
            target_type="forum_report",
            target_id=str(report.id),
            payload={
                "topic_id": report.topic_id,
                "reply_id": report.reply_id,
                "note": payload.note,
            },
        )
    )
    await db.commit()
    await db.refresh(report)
    authors = await _author_map(db, {report.reporter_id, target.author_id})
    excerpt = (
        f"{topic.title} · {topic.body[:120]}"
        if topic is not None
        else (reply.body[:140] if reply is not None else None)
    )
    return ReportOut(
        id=report.id,
        topic_id=report.topic_id,
        reply_id=report.reply_id,
        reason=report.reason,
        status=report.status,
        created_at=report.created_at,
        resolved_at=report.resolved_at,
        target_type="reply" if reply is not None else "topic",
        target_excerpt=excerpt,
        target_author=authors.get(target.author_id),
        reporter=authors.get(report.reporter_id),
    )


# ---------------------------------------------------------------------------
# 版块管理（管理员）
# ---------------------------------------------------------------------------

_BOARD_SLUG = re.compile(r"^[a-z0-9-]{2,40}$")


class BoardCreate(BaseModel):
    parent_id: int | None = Field(default=None, ge=1)
    slug: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)
    sort_order: int = Field(default=0, ge=0, le=9999)
    is_active: bool = True


class BoardUpdate(BaseModel):
    parent_id: int | None = Field(default=None, ge=1)
    slug: str | None = Field(default=None, min_length=2, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    is_active: bool | None = None


@router.get("/admin/boards")
async def admin_list_boards(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, object]:
    """管理员版块列表（含停用项，方便恢复）。"""
    tenant_id = require_tenant_id()
    rows = (
        (
            await db.execute(
                select(ForumBoard)
                .where(ForumBoard.tenant_id == tenant_id)
                .order_by(ForumBoard.sort_order, ForumBoard.id)
            )
        )
        .scalars()
        .all()
    )
    return {
        "data": [
            {
                "id": b.id,
                "parent_id": b.parent_id,
                "slug": b.slug,
                "name": b.name,
                "description": b.description,
                "sort_order": b.sort_order,
                "is_active": b.is_active,
            }
            for b in rows
        ]
    }


@router.post("/admin/boards", status_code=status.HTTP_201_CREATED)
async def create_board(
    payload: BoardCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    tenant_id = require_tenant_id()
    slug = payload.slug.strip().lower()
    if not _BOARD_SLUG.match(slug):
        raise HTTPException(status_code=422, detail="slug 只能是小写字母、数字、连字符（2-40 位）")
    if payload.parent_id is not None:
        parent = (
            await db.execute(
                select(ForumBoard).where(
                    ForumBoard.id == payload.parent_id, ForumBoard.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise HTTPException(status_code=404, detail="父版块不存在")
    exists = (
        await db.execute(
            select(ForumBoard.id).where(ForumBoard.tenant_id == tenant_id, ForumBoard.slug == slug)
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="slug 已存在")
    board = ForumBoard(
        tenant_id=tenant_id,
        parent_id=payload.parent_id,
        slug=slug,
        name=payload.name.strip(),
        description=(payload.description or "").strip() or None,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    db.add(board)
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            action="forum.board.create",
            target_type="forum_board",
            target_id=slug,
            payload={"name": board.name, "parent_id": payload.parent_id},
        )
    )
    await db.commit()
    await db.refresh(board)
    return {
        "id": board.id,
        "parent_id": board.parent_id,
        "slug": board.slug,
        "name": board.name,
        "description": board.description,
        "sort_order": board.sort_order,
        "is_active": board.is_active,
    }


@router.patch("/admin/boards/{board_id}")
async def update_board(
    board_id: int,
    payload: BoardUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    tenant_id = require_tenant_id()
    board = (
        await db.execute(
            select(ForumBoard).where(ForumBoard.id == board_id, ForumBoard.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if board is None:
        raise HTTPException(status_code=404, detail="版块不存在")
    before = {
        "parent_id": board.parent_id,
        "slug": board.slug,
        "name": board.name,
        "description": board.description,
        "sort_order": board.sort_order,
        "is_active": board.is_active,
    }
    if payload.parent_id is not None:
        if payload.parent_id == board.id:
            raise HTTPException(status_code=422, detail="版块不能挂到自己下面")
        parent = (
            await db.execute(
                select(ForumBoard).where(
                    ForumBoard.id == payload.parent_id, ForumBoard.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise HTTPException(status_code=404, detail="父版块不存在")
        # 防环：父链上不能出现自己
        cursor: ForumBoard | None = parent
        seen: set[int] = set()
        while cursor is not None and cursor.id not in seen:
            if cursor.id == board.id:
                raise HTTPException(status_code=422, detail="父版块会形成循环")
            seen.add(cursor.id)
            cursor = (
                (
                    await db.execute(
                        select(ForumBoard).where(
                            ForumBoard.id == cursor.parent_id,
                            ForumBoard.tenant_id == tenant_id,
                        )
                    )
                ).scalar_one_or_none()
                if cursor.parent_id
                else None
            )
        board.parent_id = payload.parent_id
    if payload.name is not None:
        board.name = payload.name.strip()
    if payload.description is not None:
        board.description = payload.description.strip() or None
    if payload.sort_order is not None:
        board.sort_order = payload.sort_order
    if payload.is_active is not None:
        board.is_active = payload.is_active
    if payload.slug is not None:
        slug = payload.slug.strip().lower()
        if not _BOARD_SLUG.match(slug):
            raise HTTPException(
                status_code=422, detail="slug 只能是小写字母、数字、连字符（2-40 位）"
            )
        if slug != board.slug:
            exists = (
                await db.execute(
                    select(ForumBoard.id).where(
                        ForumBoard.tenant_id == tenant_id, ForumBoard.slug == slug
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                raise HTTPException(status_code=409, detail="slug 已存在")
            board.slug = slug
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            action="forum.board.update",
            target_type="forum_board",
            target_id=str(board.id),
            payload={
                "before": before,
                "after": {
                    "parent_id": board.parent_id,
                    "slug": board.slug,
                    "name": board.name,
                    "description": board.description,
                    "sort_order": board.sort_order,
                    "is_active": board.is_active,
                },
            },
        )
    )
    await db.commit()
    await db.refresh(board)
    return {
        "id": board.id,
        "parent_id": board.parent_id,
        "slug": board.slug,
        "name": board.name,
        "description": board.description,
        "sort_order": board.sort_order,
        "is_active": board.is_active,
    }


@router.delete("/admin/boards/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_board(
    board_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除空版块；有子版块或帖子时拒绝，避免帖子失去归属。"""
    tenant_id = require_tenant_id()
    board = (
        await db.execute(
            select(ForumBoard).where(ForumBoard.id == board_id, ForumBoard.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if board is None:
        raise HTTPException(status_code=404, detail="版块不存在")
    child_count = (
        await db.execute(
            select(func.count(ForumBoard.id)).where(
                ForumBoard.tenant_id == tenant_id, ForumBoard.parent_id == board.id
            )
        )
    ).scalar_one()
    topic_count = (
        await db.execute(
            select(func.count(ForumTopic.id)).where(
                ForumTopic.tenant_id == tenant_id, ForumTopic.board_id == board.id
            )
        )
    ).scalar_one()
    if child_count or topic_count:
        raise HTTPException(
            status_code=409,
            detail=f"版块下还有 {int(child_count)} 个子版块、{int(topic_count)} 个帖子，不能直接删除",
        )
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            action="forum.board.delete",
            target_type="forum_board",
            target_id=str(board.id),
            payload={"slug": board.slug, "name": board.name},
        )
    )
    await db.delete(board)
    await db.commit()
