"""Submission 模块共享辅助函数与常量（从 routes.py 拆出，供各路由文件复用）。

拆分说明：routes.py 曾是 52KB 单文件（作者侧 + 编辑侧 + 文件侧混在一起）。
现按工作流拆为 routes.py（作者侧）/ routes_editor.py（编辑与审稿侧）/
routes_files.py（文件上传下载），本模块承载三者共享的纯辅助逻辑。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_tenant_id
from app.core import search as fulltext
from app.core.db import paginate
from app.core.tracks import canonicalize_track_category, normalize_track
from app.modules.catalog import cover_defaults
from app.modules.catalog.genre import classify_essay_genre
from app.modules.catalog.models import Resource as ResourceORM
from app.modules.submission.models import Submission, SubmissionVersion
from app.modules.submission.schemas import SubmissionListResponse, SubmissionResponse

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "_VERSIONED_FIELDS",
    "_get_or_404",
    "_list_submissions",
    "_materialize_resource_from_submission",
    "_snapshot_submission",
    "_to_response",
    "_try_delete_storage",
    "_version_payload",
]


async def _try_delete_storage(key: str | None) -> None:
    """Best-effort storage cleanup.

    A failed delete must never block the caller's primary operation
    (e.g. deleting a submission). Orphaned objects are rare — they only
    appear when the storage backend is momentarily unreachable — and the
    operator can spot the warning in the logs.
    """
    if not key:
        return
    from app.core.storage import get_storage

    try:
        await get_storage().delete(key)
    except Exception:
        logger.warning("storage_delete_failed", extra={"key": key}, exc_info=True)


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


async def _get_or_404(db: AsyncSession, submission_id: int) -> Submission:
    """Fetch a submission by id (scoped to current tenant) or raise 404."""
    tenant_id = require_tenant_id()
    entry = (
        await db.execute(
            select(Submission).where(
                Submission.id == submission_id,
                Submission.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )
    return entry


async def _materialize_resource_from_submission(
    db: AsyncSession, submission: Submission, *, publication_status: str = "published"
) -> ResourceORM:
    """Create a catalog Resource from a submission payload.

    Calls the same shape the catalog admin POST endpoint expects, so the
    conversion logic (preview truncation, defaults, etc.) stays where
    Resource creation belongs. We construct the ORM Resource directly
    rather than re-routing through the HTTP layer to keep it
    transactional with the review commit.

    ``publication_status`` 支持录用即刊（默认 published，兼容旧行为）或
    暂存草稿（draft）——后者进入刊前整理阶段，由 admin 刊出。
    """
    # 本地稿件文件：不再使用 /uploads 静态路径（该挂载无鉴权，任何人都能
    # 下载在审稿件，见 app/main.py 的说明）。改为物化后在下方写入指向
    # 公开端点 /api/catalog/{id}/file 的 download_url——只有进入公开目录的
    # 资源才能读到文件，未公开的投稿仍然只走鉴权端点。
    resource = ResourceORM(
        tenant_id=submission.tenant_id,
        publication_status=publication_status,
        type=submission.type,
        title=submission.title,
        # 发布即绑定作者（P0）：owner_id = 投稿人。已绑定的文章不再可被他人
        # 认领（POST claim 返回 403）；历史批量导入稿 owner_id 为 NULL 才可走认领。
        owner_id=submission.submitted_by,
        # 赛道随物化带过去。目录的公开面按 track 分组，丢失这一列等于
        # 让读者无法区分"这是真研究"与"这是荒诞研究"——本刊的立身之本。
        track=normalize_track(getattr(submission, "track", None)),
        authors=submission.authors,
        year=submission.year,
        venue=submission.venue,
        discipline=submission.discipline,
        subdiscipline=submission.subdiscipline,
        article_section=getattr(submission, "article_section", None),
        issue_part=getattr(submission, "issue_part", None),
        tags=submission.tags,
        abstract=submission.abstract,
        preview=submission.preview,
        # download_url 在 flush 拿到 id 后回填（见下方），此处先留空。
        download_url=submission.download_url,
        external_url=submission.external_url,
        doi=submission.doi,
        # 物化时把 submission 的 keywords 带过去，与 catalog.Resource 对齐。
        # jel_codes 不在此物化——catalog.Resource 没有该列（功能未落地），
        # 此处不声称不存在的字段对齐。
        keywords=submission.keywords or None,
        # 中图分类号（P0）：随稿件一并带到目录。
        clc_code=getattr(submission, "clc_code", None),
        clc_label=getattr(submission, "clc_label", None),
        # 封面随物化带到目录；空则按学科回填默认封面——「已发布必有封面」
        # 是 v1.11 生态规范的硬约束，无封面的内容不允许以裸态上线。
        cover_image=submission.cover_image
        or cover_defaults.default_cover_for(
            submission.discipline,
            seed=sum(ord(c) for c in (submission.title or "x")),
        ),
    )
    # 内容赛道（唯一权威）：以 submission.content_track 为准（缺省 paper），
    # content_category 由 track 推导——paper→academic，essay→fun。
    # submissions 表无 content_category 列；编辑部要 rant 可在目录后台改口。
    resource.content_track, resource.content_category = canonicalize_track_category(
        getattr(submission, "content_track", None), None
    )
    if resource.content_track == "essay":
        resource.content_genre = classify_essay_genre(
            submission.title, category=resource.content_category
        )
    db.add(resource)
    await db.flush()
    if not resource.download_url and submission.file_path:
        # 稿件带着本地上传文件时，暴露一个"只读已发表资源"的公开端点，
        # 而不是把 storage 目录整个挂出去。阅读器（pdf.js）与详情页都走它。
        resource.download_url = f"/api/catalog/{resource.id}/file"
    # 同步全文索引（best-effort）。即使后续事务回滚产生幽灵文档也无害：
    # 搜索路由按 id 回读 DB，查不到的命中会被静默丢弃。
    await fulltext.index_resource(resource)
    return resource


def _to_response(entry: Submission, review_stats: dict | None = None) -> SubmissionResponse:
    stats = review_stats or {}
    return SubmissionResponse(
        id=entry.id,
        title=entry.title,
        type=entry.type,
        track=normalize_track(getattr(entry, "track", None)),
        authors=entry.authors,
        year=entry.year,
        venue=entry.venue,
        discipline=entry.discipline,
        subdiscipline=entry.subdiscipline,
        article_section=getattr(entry, "article_section", None),
        issue_part=getattr(entry, "issue_part", None),
        keywords=entry.keywords or [],
        jel_codes=entry.jel_codes or [],
        tags=entry.tags,
        abstract=entry.abstract,
        preview=entry.preview,
        download_url=entry.download_url,
        external_url=entry.external_url,
        anonymized_file_url=entry.anonymized_file_url,
        doi=entry.doi,
        corresponding_author_email=entry.corresponding_author_email,
        status=entry.status,
        admin_note=entry.admin_note,
        editor_note=entry.editor_note,
        resource_id=entry.resource_id,
        cover_image=entry.cover_image,
        file_path=entry.file_path,
        markdown_path=entry.markdown_path,
        submitted_by=entry.submitted_by,
        submitted_at=entry.submitted_at,
        reviewed_by=entry.reviewed_by,
        reviewed_at=entry.reviewed_at,
        reports_completed=stats.get("reports_completed", 0),
        distinct_reviewers=stats.get("distinct_reviewers", 0),
        accept_recommendations=stats.get("accept_recommendations", 0),
        reject_recommendations=stats.get("reject_recommendations", 0),
        can_decide=stats.get("can_decide", False),
        conflict=stats.get("conflict", False),
        adjudicator_assigned=stats.get("adjudicator_assigned", False),
        adjudicator_accepted=stats.get("adjudicator_accepted", False),
    )


async def _review_stats_for_submissions(
    db: AsyncSession, ids: list[int], tenant_id: str
) -> dict[int, dict]:
    """批量算当前轮审稿进度，避免列表把“已有 1 份意见”显示成 0。"""
    if not ids:
        return {}
    from app.modules.review.models import ReviewAssignment, ReviewReport

    rows = (
        await db.execute(
            select(
                ReviewAssignment.submission_id,
                ReviewAssignment.reviewer_id,
                ReviewAssignment.round,
                ReviewAssignment.is_adjudicator,
                ReviewReport.recommendation,
            )
            .join(ReviewReport, ReviewReport.assignment_id == ReviewAssignment.id, isouter=True)
            .where(
                ReviewAssignment.submission_id.in_(ids),
                ReviewAssignment.tenant_id == tenant_id,
            )
        )
    ).all()
    by_sub: dict[int, list] = {}
    for r in rows:
        by_sub.setdefault(r[0], []).append(r)
    out: dict[int, dict] = {}
    for sid, rs in by_sub.items():
        current_round = max((x[2] or 1) for x in rs)
        cur = [x for x in rs if (x[2] or 1) == current_round and x[4] is not None]
        accept_ids = {x[1] for x in cur if x[4] == "accept"}
        reject = sum(1 for x in cur if x[4] == "reject")
        major = sum(1 for x in cur if x[4] == "major_revision")
        adj_rows = [x for x in rs if (x[2] or 1) == current_round and x[3]]
        adj_accept = any(x[4] == "accept" for x in adj_rows)
        conflict = bool(accept_ids) and (reject > 0 or major > 0)
        out[sid] = {
            "reports_completed": len(cur),
            "distinct_reviewers": len({x[1] for x in cur}),
            "accept_recommendations": len(accept_ids),
            "reject_recommendations": reject,
            "conflict": conflict,
            "adjudicator_assigned": bool(adj_rows),
            "adjudicator_accepted": adj_accept,
            "can_decide": len(accept_ids) >= 2 and (not conflict or adj_accept),
        }
    return out


# 参与版本快照的书目字段。故意不含 status / editor_note / resource_id ——
# 那些是工作流状态而非「作者写了什么」，把它们塞进快照会让 diff 充满
# 与稿件内容无关的噪音。
_VERSIONED_FIELDS = (
    "title",
    "type",
    # 赛道进快照：作者从荒诞改成正经（或反之）是一次实质的内容变更，
    # 版本 diff 必须能看出来，否则「我投的时候明明是正经的」无法追溯。
    "track",
    "authors",
    "year",
    "venue",
    "discipline",
    "subdiscipline",
    # 栏目/分部也是作者可改的实质元数据：版本回滚时必须一起恢复，
    # 否则会出现“回滚了正文但栏目仍留在新版本”的静默错位。
    "article_section",
    "issue_part",
    "keywords",
    "jel_codes",
    "tags",
    "abstract",
    "preview",
    "download_url",
    "external_url",
    "doi",
    "corresponding_author_email",
)


def _version_payload(entry: Submission) -> dict[str, Any]:
    """Extract the versioned bibliographic payload from a submission."""
    return {field: getattr(entry, field) for field in _VERSIONED_FIELDS}


async def _snapshot_submission(
    db: AsyncSession,
    entry: Submission,
    *,
    created_by: int | None,
    note: str | None = None,
) -> SubmissionVersion:
    """Append an immutable snapshot of ``entry`` to its version history.

    版本号取「当前最大版本 + 1」。并发重投理论上可能撞号，此时
    (submission_id, version) 唯一约束会抛 IntegrityError —— 交给调用方
    转成 409，比静默写重号安全。

    调用方负责 commit：快照必须与触发它的状态变更在同一事务里，
    否则可能出现「状态变了但没留版本」的空洞。
    """
    current_max = (
        await db.execute(
            select(func.max(SubmissionVersion.version)).where(
                SubmissionVersion.submission_id == entry.id
            )
        )
    ).scalar()
    snapshot = SubmissionVersion(
        tenant_id=entry.tenant_id,
        submission_id=entry.id,
        version=(current_max or 0) + 1,
        payload=_version_payload(entry),
        file_path=entry.file_path,
        note=note,
        created_by=created_by,
    )
    db.add(snapshot)
    return snapshot


async def _list_submissions(
    db: AsyncSession,
    base_query: Any,
    page: int,
    page_size: int,
) -> SubmissionListResponse:
    """Paginate + serialize a submission query."""
    rows, meta = await paginate(
        db,
        base_query,
        page=page,
        page_size=page_size,
        order_by=(desc(Submission.submitted_at), Submission.id.asc()),
    )
    tenant_id = rows[0].tenant_id if rows else None
    stats = (
        await _review_stats_for_submissions(db, [r.id for r in rows], tenant_id)
        if tenant_id
        else {}
    )
    return SubmissionListResponse(
        data=[_to_response(r, stats.get(r.id)) for r in rows],
        meta=meta,
    )
