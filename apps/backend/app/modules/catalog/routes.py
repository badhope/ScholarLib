"""Catalog API routes — CRUD + stats + facets for resource records.

Read endpoints are public (no auth required) so anonymous users can
browse the catalog. Write endpoints require admin. Per-tenant scoping
is enforced at the application layer (explicit ``tenant_id`` filter
on every query) AND by RLS in production.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import desc, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ROLE_EDITOR,
    get_current_user_optional,
    require_admin,
    require_tenant_id,
    user_has_role,
)
from app.core import search as fulltext
from app.core.db import get_db, paginate
from app.core.schemas import PaginationMeta
from app.core.time import utcnow
from app.models import AuditLog, User
from app.modules.catalog.engagement import compute_engagement, journal_metrics
from app.modules.catalog.models import Resource
from app.modules.catalog.ontology_routes import router as ontology_router
from app.modules.catalog.schemas import (
    FacetBucket,
    JournalMetrics,
    ResourceCreate,
    ResourceFacets,
    ResourceListResponse,
    ResourceResponse,
    ResourceStats,
    ResourceUpdate,
)
from app.modules.catalog.visibility import as_aware, is_public, public_conditions

router = APIRouter(prefix="/catalog", tags=["catalog"])

# Attach ontology sub-router so static ``/disciplines`` paths are
# tried before the dynamic ``/{resource_id}`` catch-all below.
router.include_router(ontology_router)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _download_name(title: str, suffix: str) -> str:
    """把资源标题变成可读的下载文件名（不含路径分隔符，长度受限）。"""
    cleaned = "".join(ch for ch in (title or "manuscript") if ch not in '\\/:*?"<>|\r\n\t')
    cleaned = " ".join(cleaned.split())[:80] or "manuscript"
    return f"{cleaned}.{suffix}"


async def _can_preview_unpublished(
    db: AsyncSession, viewer: User | None, resource_id: int, tenant_id: UUID
) -> bool:
    """Whether ``viewer`` may see an unpublished (draft/in_review) record.

    刊前预览授权边界：editor 角色（deps 对 admin 直接放行）可预览全部
    未刊稿；与该条目关联投稿的作者本人可预览自己的稿子。其余访问者
    （含匿名）返回 False，调用方以 404 拒绝——不向公众确认未刊条目的
    存在。
    """
    if viewer is None:
        return False
    if viewer.is_admin:
        return True
    if await user_has_role(db, viewer, ROLE_EDITOR):
        return True
    from app.modules.submission.models import Submission

    submitter_id = (
        await db.execute(
            select(Submission.submitted_by).where(
                Submission.resource_id == resource_id,
                Submission.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    return submitter_id is not None and submitter_id == viewer.id


def _conflict_detail(exc: IntegrityError) -> str:
    """Name the field that actually collided.

    Both ``slug`` and ``doi`` carry unique constraints; reporting every
    IntegrityError as "slug taken" sent users hunting for a duplicate
    slug when the real problem was a reused DOI.
    """
    message = str(getattr(exc, "orig", exc)).lower()
    if "doi" in message:
        return "DOI already exists in this catalog"
    if "slug" in message:
        return "Slug already taken in this tenant"
    return "Record conflicts with an existing entry"


@router.get("", response_model=ResourceListResponse)
async def list_resources(
    type: str | None = None,
    discipline: str | None = None,
    year: int | None = None,
    volume: str | None = None,
    issue: str | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    sort: str | None = Query(default=None, pattern=r"^(year|title|created_at|issue)$"),
    order: str | None = Query(default=None, pattern=r"^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> ResourceListResponse:
    """List resources with pagination, filtering, and basic search.

    When Meilisearch is configured and a query string is present, the
    search is delegated to it (typo tolerance + relevance ranking) and
    rows are re-fetched from the DB by id. Otherwise — including any
    Meilisearch failure — the original DB ILIKE path runs unchanged.
    """
    tenant_id = require_tenant_id()
    is_admin = bool(viewer and viewer.is_admin)

    # Meilisearch documents carry no publication_status, so the relevance
    # ids are re-fetched through the same publication filter as the DB path
    # below — an indexed draft can never leak just because it ranked high.
    if q is not None and fulltext.search_enabled():
        hit = await fulltext.search_resource_ids(
            tenant_id=str(tenant_id),
            q=q,
            type_=type,
            discipline=discipline,
            year=year,
            page=page,
            page_size=page_size,
        )
        if hit is not None:
            ids, total = hit
            rows_by_id: dict[int, Resource] = {}
            hidden = 0
            if ids:
                fetched = (
                    await db.execute(
                        select(Resource).where(
                            Resource.tenant_id == tenant_id, Resource.id.in_(ids)
                        )
                    )
                ).scalars()
                for resource in fetched:
                    # 索引里没有可见性字段：命中结果回表后按公开面过滤，
                    # 否则排期中（publish_at 未来）或草稿会因搜索而泄漏。
                    if is_admin or is_public(resource):
                        rows_by_id[resource.id] = resource
                    else:
                        hidden += 1
            # Preserve Meilisearch relevance order.
            ranked = [rows_by_id[i] for i in ids if i in rows_by_id]
            # 只扣除「确实存在但当前不可见」的条数；索引里的幽灵 id（已被
            # 删除）维持原有口径，不改 total —— 那是搜索端的一致性问题，
            # 不是可见性问题。
            effective_total = max(len(ranked), total - hidden)
            return ResourceListResponse(
                data=await _with_engagement(db, ranked),
                meta=PaginationMeta(
                    total=effective_total,
                    page=page,
                    page_size=page_size,
                    total_pages=max(1, (effective_total + page_size - 1) // page_size),
                ),
            )

    stmt = select(Resource).where(Resource.tenant_id == tenant_id)
    if not is_admin:
        # 公开面：只存在「已刊出且已到发布时刻」的记录。排期中的期号
        # （publish_at 在未来）对读者不可见，也不确认存在性。
        for condition in public_conditions():
            stmt = stmt.where(condition)
    if type is not None:
        stmt = stmt.where(Resource.type == type)
    if discipline is not None:
        stmt = stmt.where(Resource.discipline == discipline)
    if year is not None:
        stmt = stmt.where(Resource.year == year)
    # 卷/期筛选：目录页与卷期归档页共用。空串按 None 处理（前端清空下拉框会传 ""）。
    if volume:
        stmt = stmt.where(Resource.volume == volume)
    if issue:
        stmt = stmt.where(Resource.issue == issue)
    # 排序扩展：卷期归档按「卷 → 期 → 期内序号」排（pages 存三位期内序号）。
    # 注意不能先 stmt.order_by(...) 再交给 paginate：paginate 会以传入的
    # order_by 覆盖（空元组等于清空排序）。
    if q is not None:
        pattern = f"%{q}%"
        if db.get_bind().dialect.name == "postgresql":
            authors = (
                func.jsonb_array_elements_text(Resource.authors)
                .table_valued("value")
                .render_derived()
            )
        else:
            authors = func.json_each(Resource.authors).table_valued("value")
        author_match = select(1).select_from(authors).where(authors.c.value.ilike(pattern)).exists()
        stmt = stmt.where(
            (Resource.title.ilike(pattern))
            | (Resource.abstract.ilike(pattern))
            | (Resource.venue.ilike(pattern))
            | (Resource.discipline.ilike(pattern))
            | author_match
        )
    if sort == "issue":
        rows, meta = await paginate(
            db,
            stmt,
            page=page,
            page_size=page_size,
            order_by=(Resource.volume.asc(), Resource.issue.asc(), Resource.pages.asc()),
        )
        return ResourceListResponse(data=await _with_engagement(db, rows), meta=meta)

    # Sort with deterministic tiebreaker — order_by is applied by paginate.
    sort_col = getattr(Resource, sort, Resource.created_at) if sort else Resource.created_at
    order_by = (
        sort_col.asc() if order == "asc" else sort_col.desc(),
        Resource.id.asc(),
    )

    rows, meta = await paginate(
        db,
        stmt,
        page=page,
        page_size=page_size,
        order_by=order_by,
    )
    return ResourceListResponse(
        data=await _with_engagement(db, rows),
        meta=meta,
    )


@router.get("/stats", response_model=ResourceStats)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> ResourceStats:
    """Aggregate stats: total count + breakdowns by type and discipline."""
    tenant_id = require_tenant_id()
    base_filter = Resource.tenant_id == tenant_id
    if not (viewer and viewer.is_admin):
        for condition in public_conditions():
            base_filter = base_filter & condition
    total = (await db.execute(select(func.count(Resource.id)).where(base_filter))).scalar_one()
    by_type_rows = await db.execute(
        select(Resource.type, func.count(Resource.id)).where(base_filter).group_by(Resource.type)
    )
    by_discipline_rows = await db.execute(
        select(Resource.discipline, func.count(Resource.id))
        .where(base_filter)
        .group_by(Resource.discipline)
    )
    downloads_total = (
        await db.execute(
            select(func.coalesce(func.sum(Resource.download_count), 0)).where(base_filter)
        )
    ).scalar_one()
    from app.modules.reader.models import ReadingHistory

    reads_total = (
        await db.execute(
            select(func.coalesce(func.sum(ReadingHistory.visit_count), 0)).where(
                ReadingHistory.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    return ResourceStats(
        total=total,
        by_type={t: c for t, c in by_type_rows.all()},
        by_discipline={d: c for d, c in by_discipline_rows.all()},
        downloads_total=int(downloads_total or 0),
        reads_total=int(reads_total or 0),
    )


@router.get("/facets", response_model=ResourceFacets)
async def get_facets(
    type: str | None = None,
    discipline: str | None = None,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> ResourceFacets:
    """Year + tag facet buckets for the current filter."""
    tenant_id = require_tenant_id()
    is_admin = bool(viewer and viewer.is_admin)
    stmt = select(Resource).where(Resource.tenant_id == tenant_id)
    if not is_admin:
        # 公开面：已刊出 + 已到发布时刻（见 catalog/visibility.py）
        for condition in public_conditions():
            stmt = stmt.where(condition)
    if type is not None:
        stmt = stmt.where(Resource.type == type)
    if discipline is not None:
        stmt = stmt.where(Resource.discipline == discipline)

    year_rows = await db.execute(
        select(Resource.year, func.count(Resource.id))
        .where(Resource.id.in_(select(stmt.subquery().c.id)))
        .group_by(Resource.year)
        .order_by(desc(Resource.year))
    )
    years = [FacetBucket(value=str(y), count=c) for y, c in year_rows.all() if y is not None]

    # Tags are JSON; aggregate in Python (small N).
    # F2 服务端优化：限定在过滤范围内拉取（type/discipline 命中后行数已收敛），
    # 并对拉取行数做上限保护（10k 行足够 facet 50 个 top tag），避免匿名浏览
    # 全表 tags 物化的 O(N×M) 开销。若未来 data > 10k 需引入 SQL 端 JSON 展开。
    stmt_tags = select(Resource.tags).where(Resource.tenant_id == tenant_id)
    if not is_admin:
        for condition in public_conditions():
            stmt_tags = stmt_tags.where(condition)
    if type is not None:
        stmt_tags = stmt_tags.where(Resource.type == type)
    if discipline is not None:
        stmt_tags = stmt_tags.where(Resource.discipline == discipline)
    stmt_tags = stmt_tags.limit(10000)
    rows = (await db.execute(stmt_tags)).scalars().all()
    tag_counts: dict[str, int] = {}
    for tags in rows:
        for tag in tags or []:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    tags_sorted = sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:50]
    return ResourceFacets(
        years=years,
        tags=[FacetBucket(value=t, count=c) for t, c in tags_sorted],
    )


async def _with_engagement(db: AsyncSession, rows: Any) -> list[ResourceResponse]:
    """Serialize rows and attach R-index engagement in one extra pass."""
    responses = [ResourceResponse.model_validate(r) for r in rows]
    engagement = await compute_engagement(db, list(rows))
    for response in responses:
        metrics = engagement.get(response.id)
        if metrics is None:
            continue
        response.reads = metrics.reads
        response.downloads = metrics.downloads
        response.saves = metrics.saves
        response.r_index = metrics.r_index
        response.quartile = metrics.quartile
    if responses:
        # 列表行的 has_file：与详情一致地按"挂了带文件稿件的 submission"
        # 判定，一次 IN 查询整页取完（此前恒为 False，UI 无法提示可下载）。
        from app.modules.submission.models import Submission

        tenant_id = require_tenant_id()
        rows = (
            await db.execute(
                select(
                    Submission.resource_id,
                    Submission.file_path,
                    Submission.markdown_path,
                ).where(
                    Submission.tenant_id == tenant_id,
                    Submission.resource_id.in_([r.id for r in responses]),
                )
            )
        ).all()
        with_file: set[int] = set()
        with_md: set[int] = set()
        for resource_id, file_path, markdown_path in rows:
            if file_path:
                with_file.add(resource_id)
            if markdown_path:
                with_md.add(resource_id)
        for response in responses:
            response.has_file = response.id in with_file
            response.has_markdown = response.id in with_md
    return responses


class IssuePlanEntry(BaseModel):
    """One issue in the publication calendar."""

    volume: str
    issue: str
    label: str
    publish_at: datetime | None
    total: int
    published: int
    scheduled: int
    state: str  # live | scheduled | empty


class IssuePlanResponse(BaseModel):
    volume: str
    now: datetime
    entries: list[IssuePlanEntry]


@router.get("/issue-plan", response_model=IssuePlanResponse)
async def get_issue_plan(db: AsyncSession = Depends(get_db)) -> IssuePlanResponse:
    """Publication calendar: what is live now and what is queued.

    Public on purpose — the archive page shows upcoming issues with their
    release dates, so a reader can see the journal is monthly rather than
    wondering why only one issue exists. Counts only; no drafts leak.
    """
    tenant_id = require_tenant_id()
    now = utcnow()
    rows = (
        await db.execute(
            select(
                Resource.volume,
                Resource.issue,
                Resource.publish_at,
                Resource.publication_status,
                func.count(Resource.id),
            )
            # 只统计「已刊出」的记录：草稿（刊前整理中）连篇数都不该露出，
            # 否则公开日历的 total 就是一把数草稿的尺子。
            .where(
                Resource.tenant_id == tenant_id,
                Resource.volume.is_not(None),
                Resource.publication_status == "published",
            )
            .group_by(
                Resource.volume,
                Resource.issue,
                Resource.publish_at,
                Resource.publication_status,
            )
            .order_by(Resource.volume.asc(), Resource.issue.asc())
        )
    ).all()

    totals: dict[tuple[str, str], int] = {}
    live: dict[tuple[str, str], int] = {}
    queued: dict[tuple[str, str], int] = {}
    first_release: dict[tuple[str, str], datetime] = {}
    for volume, issue, publish_at, pub_status, count in rows:
        key = (volume or "", issue or "")
        totals[key] = totals.get(key, 0) + int(count)
        if pub_status != "published":
            continue
        release = as_aware(publish_at)
        if release is not None:
            current_release = first_release.get(key)
            if current_release is None or release < current_release:
                first_release[key] = release
        if release is None or release <= now:
            live[key] = live.get(key, 0) + int(count)
        else:
            queued[key] = queued.get(key, 0) + int(count)

    entries: list[IssuePlanEntry] = []
    for volume, issue in sorted(totals):
        published_count = live.get((volume, issue), 0)
        scheduled_count = queued.get((volume, issue), 0)
        state = "live" if published_count else ("scheduled" if scheduled_count else "empty")
        entries.append(
            IssuePlanEntry(
                volume=volume,
                issue=issue,
                label=(
                    f"第 {volume} 卷 第 {int(issue)} 期"
                    if issue.isdigit()
                    else f"{volume} 卷 {issue} 期"
                ),
                publish_at=first_release.get((volume, issue)),
                total=totals[(volume, issue)],
                published=published_count,
                scheduled=scheduled_count,
                state=state,
            )
        )
    return IssuePlanResponse(volume="1", now=now, entries=entries)


class IssueScheduleRequest(BaseModel):
    publish_at: datetime | None = None


@router.post("/issues/{volume}/{issue}/publish", response_model=IssuePlanEntry)
async def publish_issue(
    volume: str,
    issue: str,
    payload: IssueScheduleRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> IssuePlanEntry:
    """L9: release an issue now (``publish_at=null``) or reschedule it.

    Publisher convenience for the monthly cadence: one call moves a whole
    issue instead of PATCHing 27 records. Writes one audit row.

    只作用于**已刊出**的记录：期号里仍在刊前整理（draft）的稿件不随整期
    发布一起上线——「一键发整期」不该顺带把未定稿的稿子推给公众，那是
    编辑逐篇确认的环节。需要连草稿一起发时，先逐篇 PATCH 成 published。
    """
    tenant_id = require_tenant_id()
    target = payload.publish_at
    result = await db.execute(
        update(Resource)
        .where(
            Resource.tenant_id == tenant_id,
            Resource.volume == volume,
            Resource.issue == issue,
            Resource.publication_status == "published",
        )
        .values(publish_at=target)
    )
    rows_changed = int(getattr(result, "rowcount", 0) or 0)
    if rows_changed == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found")
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_admin.id,
            action="catalog.issue_schedule",
            target_type="issue",
            target_id=f"{volume}/{issue}",
            payload={"publish_at": target.isoformat() if target else None, "rows": rows_changed},
        )
    )
    await db.commit()
    now = utcnow()
    count = rows_changed
    live = target is None or target <= now
    return IssuePlanEntry(
        volume=volume,
        issue=issue,
        label=f"第 {volume} 卷 第 {int(issue)} 期"
        if issue.isdigit()
        else f"{volume} 卷 {issue} 期",
        publish_at=target,
        total=count,
        published=count if live else 0,
        scheduled=0 if live else count,
        state="live" if live else "scheduled",
    )


@router.get("/journal-metrics", response_model=JournalMetrics)
async def get_journal_metrics(db: AsyncSession = Depends(get_db)) -> JournalMetrics:
    """Public, self-computed journal metrics (see /journal-metrics page).

    Deliberately NOT an impact factor: no citation data exists here, so
    every number comes from this deployment's own event tables; the
    formulas are editorial methodology and deliberately not published.
    """
    tenant_id = require_tenant_id()
    return JournalMetrics(**await journal_metrics(db, tenant_id))


@router.get("/{resource_id}/file")
async def download_resource_file(
    resource_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> Response:
    """流式返回资源文件：published 公开可读；draft/in_review 仅限刊前
    预览（编辑角色或关联投稿作者本人）。

    这是替代原 `/uploads` 静态挂载的通道。区别是：
    - 已刊出（published）的资源任何人都可在这里读到文件；
    - 未刊出的稿件对无权限者一律 404（不确认存在性），不再能经此端点
      流出；在审稿件作者/审稿人仍可走鉴权端点 `GET /api/submissions/{id}/files`。

    换句话说，公开取稿的授权边界是刊出状态本身；未刊稿仅对编辑与作者开放刊前预览。
    """
    import mimetypes

    from fastapi.responses import RedirectResponse, StreamingResponse

    from app.core.storage import get_storage

    tenant_id = require_tenant_id()
    result = await db.execute(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.tenant_id == tenant_id,
        )
    )
    resource = result.scalar_one_or_none()
    # 纵深防御：published 公开取稿；draft/in_review 仅限编辑（含 admin）
    # 与关联投稿的作者本人（刊前预览），无权限者（含匿名）404，不确认
    # 未刊条目存在。编辑在 "接受" 决定里可把投稿对接到任一带 resource_id
    # 的现有条目（submission/routes.py accept 分支），此时预览走同一端点。
    is_published = is_public(resource)
    if resource is None or (
        not is_published and not await _can_preview_unpublished(db, viewer, resource_id, tenant_id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    # 延迟导入避免与 submission 模块形成循环依赖（submission 依赖 catalog）。
    from app.modules.submission.models import Submission

    submission = (
        (
            await db.execute(
                select(Submission).where(
                    Submission.resource_id == resource_id,
                    Submission.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if submission is None or not submission.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This resource has no downloadable file",
        )

    # 下载计数（R 指数的 0.3 权重项）：仅 published 资源计数——刊前预览
    # 不得污染指标；且只在真正返回内容前自增一次，404/302 预签名跳转
    # 都不算，避免把外部存储的鉴权失败算成一次下载。
    if is_published:
        await db.execute(
            update(Resource)
            .where(Resource.id == resource_id)
            .values(download_count=Resource.download_count + 1)
        )
        await db.commit()

    storage = get_storage()
    url = storage.presigned_url(submission.file_path)
    if url:
        return RedirectResponse(url, status_code=status.HTTP_302_FOUND)

    try:
        data = await storage.load(submission.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Stored file is missing"
        ) from exc

    filename = submission.file_path.rsplit("/", 1)[-1]
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    # 存储键是 uuid，直接返回会让用户下载到 `9cd5d1a3....pdf`。
    # 用资源标题生成可读文件名（RFC 5987 的 filename* 支持中文），
    # 同时保留 ASCII 回退名给不认 filename* 的老客户端。
    suffix = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    readable = _download_name(resource.title, suffix)
    disposition = (
        f'attachment; filename="{resource.id}-manuscript.{suffix}"; '
        f"filename*=UTF-8''{quote(readable)}"
    )

    range_header = request.headers.get("Range")
    if range_header and range_header.startswith("bytes="):
        spec = range_header[len("bytes=") :]
        try:
            if "-" in spec:
                start_s, end_s = spec.split("-", 1)
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else len(data) - 1
            else:
                start = int(spec)
                end = len(data) - 1
            start = max(start, 0)
            end = min(end, len(data) - 1)
            if start > end or start >= len(data):
                raise ValueError("invalid range")
            chunk = data[start : end + 1]
            return Response(
                content=chunk,
                status_code=status.HTTP_206_PARTIAL_CONTENT,
                media_type=media_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{len(data)}",
                    "Accept-Ranges": "bytes",
                    "Content-Disposition": disposition,
                },
            )
        except ValueError:
            pass  # Range 非法 → 退回 200 全量

    return StreamingResponse(
        iter([data]),
        media_type=media_type,
        headers={"Accept-Ranges": "bytes", "Content-Disposition": disposition},
    )


@router.get("/{resource_id}/manuscript")
async def get_resource_manuscript(
    resource_id: int,
    if_none_match: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> Response:
    """在线阅读用 Markdown 稿件（0.6.2）：可见性边界与 /file 完全一致
    （published 公开；未刊稿仅刊前预览者，无权限 404）。无 md 的资源
    返回 404，前端回退 PDF 视图。
    """
    from fastapi.responses import Response

    from app.core.storage import get_storage

    tenant_id = require_tenant_id()
    result = await db.execute(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.tenant_id == tenant_id,
        )
    )
    resource = result.scalar_one_or_none()
    is_published = is_public(resource)
    if resource is None or (
        not is_published and not await _can_preview_unpublished(db, viewer, resource_id, tenant_id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    from app.modules.submission.models import Submission

    submission = (
        (
            await db.execute(
                select(Submission).where(
                    Submission.resource_id == resource_id,
                    Submission.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if submission is None or not submission.markdown_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This resource has no online manuscript",
        )

    try:
        data = await get_storage().load(submission.markdown_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Stored manuscript is missing"
        ) from exc
    # 1.6.0：稿件含 220dpi 内嵌图（单篇可达 1-2MB），给协商缓存——
    # 内容 sha256 作 ETag，重复阅读命中 304 不再重拉。
    etag = f'W/"{hashlib.sha256(data).hexdigest()[:32]}"'
    if if_none_match and etag in if_none_match:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return Response(
        content=data,
        media_type="text/markdown; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "ETag": etag,
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/{resource_id}", response_model=ResourceResponse)
async def get_resource(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> ResourceResponse:
    """Get a single resource by id (published-only for the public; editors
    and the linked submission's author may preview unpublished records)."""
    tenant_id = require_tenant_id()
    stmt = select(Resource).where(
        Resource.id == resource_id,
        Resource.tenant_id == tenant_id,
    )
    if viewer is None or not viewer.is_admin:
        # 404 rather than 403: an unpublished record should not even
        # confirm its existence to the public. Editors and the linked
        # submission's author may preview drafts (刊前预览).
        if not await _can_preview_unpublished(db, viewer, resource_id, tenant_id):
            for condition in public_conditions():
                stmt = stmt.where(condition)
    result = await db.execute(stmt)
    resource = result.scalar_one_or_none()
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    response = ResourceResponse.model_validate(resource)
    # Whether a downloadable manuscript exists: the file endpoint only
    # serves resources backed by a submission, so check that link once
    # here instead of letting the UI probe and collect a 404.
    from app.modules.submission.models import Submission

    has_file = (
        await db.execute(
            select(Submission.id)
            .where(
                Submission.resource_id == resource.id,
                Submission.tenant_id == tenant_id,
                Submission.file_path.is_not(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    response.has_file = has_file is not None
    has_markdown = (
        await db.execute(
            select(Submission.id)
            .where(
                Submission.resource_id == resource.id,
                Submission.tenant_id == tenant_id,
                Submission.markdown_path.is_not(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    response.has_markdown = has_markdown is not None
    engagement = (await compute_engagement(db, [resource])).get(resource.id)
    if engagement is not None:
        response.reads = engagement.reads
        response.downloads = engagement.downloads
        response.saves = engagement.saves
        response.r_index = engagement.r_index
        response.quartile = engagement.quartile
    return response


@router.post("", response_model=ResourceResponse, status_code=status.HTTP_201_CREATED)
async def create_resource(
    payload: ResourceCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> ResourceResponse:
    """Create a new resource (admin only)."""
    tenant_id = require_tenant_id()
    # AnyHttpUrl → str：SQLite 默认 DBAPI 不识别 Pydantic 的 Url 类型，
    # PostgreSQL 那边 asyncpg 倒是接受，但为保持两库行为一致统一转 str。
    # Ontology check: discipline must exist; if subdiscipline is
    # given, it must belong to the chosen discipline. Fails with
    # HTTP 422 on miss so the client gets a clear, actionable
    # error instead of a silent typo landing in the DB.
    from app.modules.catalog.onto import (
        DisciplineNotFound,
        SubdisciplineMismatch,
        assert_discipline_valid,
        assert_subdiscipline_matches,
    )

    try:
        discipline_row = await assert_discipline_valid(
            db,
            tenant_id=tenant_id,
            discipline_name=payload.discipline,
        )
        # If ontology is unconfigured (no disciplines registered),
        # discipline_row is None — skip subdiscipline check too.
        if payload.subdiscipline and discipline_row is not None:
            await assert_subdiscipline_matches(
                db,
                tenant_id=tenant_id,
                discipline=discipline_row,
                subdiscipline_name=payload.subdiscipline,
            )
    except DisciplineNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except SubdisciplineMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    resource = Resource(
        tenant_id=tenant_id,
        slug=payload.slug,
        type=payload.type,
        title=payload.title,
        authors=payload.authors,
        year=payload.year,
        venue=payload.venue,
        discipline=payload.discipline,
        subdiscipline=payload.subdiscipline,
        tags=payload.tags,
        abstract=payload.abstract,
        preview=payload.preview,
        download_url=str(payload.download_url) if payload.download_url else None,
        external_url=str(payload.external_url) if payload.external_url else None,
        doi=payload.doi,
        volume=payload.volume,
        issue=payload.issue,
        pages=payload.pages,
        issn=payload.issn,
        isbn=payload.isbn,
        publisher=payload.publisher,
        short_container_title=payload.short_container_title,
        keywords=payload.keywords,
        language=payload.language,
        publication_status=payload.publication_status,
        publish_at=payload.publish_at,
        authors_meta=(
            [m.model_dump() for m in payload.authors_meta]
            if payload.authors_meta is not None
            else None
        ),
    )
    db.add(resource)
    try:
        # flush 触发唯一约束（slug/doi 撞车）：必须在 try 内，让 IntegrityError
        # 转成 409 而不是 500；begin_nested 让 flush 失败后事务仍可回滚续用。
        async with db.begin_nested():
            await db.flush()
        # Audit: log identifiers only — full payload is the Resource row itself.
        # 与资源写入同一事务（S-3）：第二个 commit 挂掉不会留下「有变更无审计」。
        db.add(
            AuditLog(
                tenant_id=current_admin.tenant_id,
                actor_user_id=current_admin.id,
                action="catalog.resource.create",
                target_type="resource",
                target_id=str(resource.id),
                payload={"slug": resource.slug, "title": resource.title},
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(exc),
        ) from exc
    await db.refresh(resource)
    await fulltext.index_resource(resource)  # best-effort, never raises
    return ResourceResponse.model_validate(resource)


@router.patch("/{resource_id}", response_model=ResourceResponse)
async def update_resource(
    resource_id: int,
    payload: ResourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> ResourceResponse:
    """Update an existing resource (admin only)."""
    tenant_id = require_tenant_id()
    result = await db.execute(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.tenant_id == tenant_id,
        )
    )
    resource = result.scalar_one_or_none()
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    update_data: dict[str, Any] = payload.model_dump(exclude_unset=True)
    # AnyHttpUrl → str（同 create_resource 的处理）
    for url_field in ("download_url", "external_url"):
        if url_field in update_data and update_data[url_field] is not None:
            update_data[url_field] = str(update_data[url_field])

    # Ontology check on update: if discipline is being changed (or
    # subdiscipline alone is being changed while discipline is
    # carried over from the existing row), validate both against
    # the controlled vocabulary.
    if "discipline" in update_data or "subdiscipline" in update_data:
        from app.modules.catalog.onto import (
            DisciplineNotFound,
            SubdisciplineMismatch,
            assert_discipline_valid,
            assert_subdiscipline_matches,
        )

        effective_discipline = update_data.get("discipline", resource.discipline)
        effective_subdiscipline = update_data.get("subdiscipline", resource.subdiscipline)
        try:
            discipline_row = await assert_discipline_valid(
                db,
                tenant_id=tenant_id,
                discipline_name=effective_discipline,
            )
            # If ontology is unconfigured (no disciplines registered),
            # discipline_row is None — skip subdiscipline check too.
            if effective_subdiscipline and discipline_row is not None:
                await assert_subdiscipline_matches(
                    db,
                    tenant_id=tenant_id,
                    discipline=discipline_row,
                    subdiscipline_name=effective_subdiscipline,
                )
        except DisciplineNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        except SubdisciplineMismatch as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    for field, value in update_data.items():
        setattr(resource, field, value)

    # Audit: record which fields the admin touched (values may be large,
    # so we log field names only; the Resource row keeps the new state).
    # 与业务变更同一事务：审计失败 = 变更失败，不留无审计的静默修改。
    db.add(
        AuditLog(
            tenant_id=current_admin.tenant_id,
            actor_user_id=current_admin.id,
            action="catalog.resource.update",
            target_type="resource",
            target_id=str(resource.id),
            payload={"fields": list(update_data.keys())},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(exc),
        ) from exc
    await db.refresh(resource)
    await fulltext.index_resource(resource)  # best-effort, never raises
    return ResourceResponse.model_validate(resource)


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> None:
    """Delete a resource (admin only)."""
    tenant_id = require_tenant_id()
    result = await db.execute(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.tenant_id == tenant_id,
        )
    )
    resource = result.scalar_one_or_none()
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    # Capture identifying info before the row is deleted so the audit
    # entry can still describe what was removed.
    deleted_slug = resource.slug
    deleted_title = resource.title
    await db.delete(resource)
    await fulltext.unindex_resource(resource_id)  # best-effort, never raises
    db.add(
        AuditLog(
            tenant_id=current_admin.tenant_id,
            actor_user_id=current_admin.id,
            action="catalog.resource.delete",
            target_type="resource",
            target_id=str(resource_id),
            payload={"slug": deleted_slug, "title": deleted_title},
        )
    )
    await db.commit()
