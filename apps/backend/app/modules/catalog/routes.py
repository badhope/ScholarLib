"""Catalog API routes — CRUD + stats + facets for resource records.

Read endpoints are public (no auth required) so anonymous users can
browse the catalog. Write endpoints require admin. Per-tenant scoping
is enforced at the application layer (explicit ``tenant_id`` filter
on every query) AND by RLS in production.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    PERMISSION_RANK,
    ROLE_EDITOR,
    effective_permission_role,
    get_current_user_optional,
    require_admin,
    require_editor,
    require_tenant_id,
    user_has_role,
)
from app.core import search as fulltext
from app.core.db import get_db, paginate
from app.core.logging import get_logger

logger = get_logger("rubbish.catalog")
from app.core.schemas import PaginationMeta
from app.core.time import utcnow
from app.models import AuditLog, Role, User, UserRole
from app.modules.catalog.engagement import compute_engagement, journal_metrics
from app.modules.catalog.models import AuthorClaim, Resource
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
    VolumeSummary,
    VolumeSummaryList,
    IssueSummary,
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

    # 一篇资源可能关联多条投稿（重新投稿/合并链接），不能 scalar_one——
    # 否则详情页对这些资源直接 500（MultipleResultsFound，线上实锤事故）。
    # 语义是「作者是任一关联投稿的提交者即可预览」。
    submitter_ids = set(
        (
            await db.execute(
                select(Submission.submitted_by).where(
                    Submission.resource_id == resource_id,
                    Submission.tenant_id == tenant_id,
                )
            )
        ).scalars().all()
    )
    return viewer.id in submitter_ids


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


def _expand_categories(category: str | None) -> set[str] | None:
    """把 ?category= 归一化为 content_category 集合。

    接受单值（academic/fun/rant/essay）或逗号多值（如 ``fun,rant``）。
    ``essay`` 是前端「娱乐」tab 的语义口径，等价于 ``fun,rant``——
    之前前端发 ``category=fun`` 会漏掉 rant 稿，这里统一在后端展开。
    返回 None 表示不过滤；非法 token 直接忽略（不报错，保持宽松）。
    """
    if not category:
        return None
    allowed = {"academic", "fun", "rant"}
    out: set[str] = set()
    for token in category.split(","):
        t = token.strip().lower()
        if t == "essay":
            out.update({"fun", "rant"})
        elif t in allowed:
            out.add(t)
    return out or None


@router.get("", response_model=ResourceListResponse)
async def list_resources(
    type: str | None = None,
    # 内容类别筛选（v1.11）：academic/fun/rant；v1.15 起接受逗号多值与
    # essay（=fun+rant，前端「娱乐」tab 的完整口径）。
    category: str | None = Query(default=None),
    # 轨道筛选（v1.15.1）：按 content_track 过滤，paper=论文 / essay=娱乐（fun+rant）。
    # 与 content_category 解耦：历史稿件的 category 可能未随 track 迁移。
    track: str | None = Query(default=None, pattern=r"^(paper|essay)$"),
    discipline: str | None = None,
    year: int | None = None,
    volume: str | None = None,
    issue: str | None = None,
    # 中图分类号前缀筛选（P0）：?clc=TP 命中 TP / TP3 / TP311.13 等。
    clc: str | None = Query(default=None, pattern=r"^[A-Za-z]{1,2}\d{0,3}$"),
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
    cats = _expand_categories(category)
    if cats is not None:
        stmt = stmt.where(Resource.content_category.in_(cats))
    if track:
        stmt = stmt.where(Resource.content_track == track)
    if discipline is not None:
        stmt = stmt.where(Resource.discipline == discipline)
    if year is not None:
        stmt = stmt.where(Resource.year == year)
    # 卷/期筛选：目录页与卷期归档页共用。空串按 None 处理（前端清空下拉框会传 ""）。
    if volume:
        stmt = stmt.where(Resource.volume == volume)
    if issue:
        stmt = stmt.where(Resource.issue == issue)
    # 中图分类号前缀筛选：?clc=TP → clc_code 以 TP 开头（大小写不敏感）。
    if clc:
        stmt = stmt.where(Resource.clc_code.ilike(f"{clc.upper()}%"))
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


@router.get("/volumes/stats", response_model=VolumeSummaryList)
async def get_volume_stats(
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> VolumeSummaryList:
    """按卷聚合期数与文章数（全量，不受列表分页上限影响）。

    旧实现由前端取一页 100 条自己数，期刊超过 100 篇后后台显示的
    「文章数」就永远停在 100，还要在页面上挂一句免责说明。聚合本该
    在数据库做：一次 group by，成本与页数无关。
    """
    tenant_id = require_tenant_id()
    base_filter = Resource.tenant_id == tenant_id
    if not (viewer and viewer.is_admin):
        for condition in public_conditions():
            base_filter = base_filter & condition
    base_filter = base_filter & Resource.volume.is_not(None) & (Resource.volume != "")

    rows = await db.execute(
        select(
            Resource.volume,
            Resource.issue,
            func.count(Resource.id).label("article_count"),
            func.min(Resource.year).label("first_year"),
            func.max(Resource.year).label("last_year"),
        )
        .where(base_filter)
        .group_by(Resource.volume, Resource.issue)
    )

    volumes: dict[str, VolumeSummary] = {}
    for volume, issue, article_count, first_year, last_year in rows.all():
        key = str(volume)
        summary = volumes.setdefault(
            key, VolumeSummary(volume=key, issue_count=0, article_count=0, issues=[])
        )
        summary.article_count += int(article_count or 0)
        if issue:
            summary.issue_count += 1
            summary.issues.append(
                IssueSummary(
                    issue=str(issue),
                    article_count=int(article_count or 0),
                    first_year=int(first_year) if first_year is not None else None,
                    last_year=int(last_year) if last_year is not None else None,
                )
            )

    data = sorted(volumes.values(), key=lambda v: v.volume, reverse=True)
    for summary in data:
        summary.issues.sort(key=lambda i: i.issue, reverse=True)
    return VolumeSummaryList(data=data)


@router.get("/facets", response_model=ResourceFacets)
async def get_facets(
    type: str | None = None,
    category: str | None = Query(default=None),
    track: str | None = Query(default=None, pattern=r"^(paper|essay)$"),
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
    cats = _expand_categories(category)
    if cats is not None:
        stmt = stmt.where(Resource.content_category.in_(cats))
    if track:
        stmt = stmt.where(Resource.content_track == track)
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
    tentative release dates, so a reader can see how the rolling publication
    schedule is currently organized. The journal does not commit to a fixed
    periodicity: issues are released as soon as peer review completes, and
    the queued dates are archival/organizational hints that may change at
    any time. Counts only; no drafts leak.
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


ISSUE_SIZE_DEFAULT = 60


class IssueRebalanceRequest(BaseModel):
    """整卷重排：每期固定篇数、按质量顺序逐期发布。"""

    volume: str = "1"
    issue_size: int = Field(default=ISSUE_SIZE_DEFAULT, ge=1, le=200)
    dry_run: bool = False


@router.post("/issues/rebalance")
async def rebalance_issues(
    payload: IssueRebalanceRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """把已发布资源重排为「每期固定 ``issue_size`` 篇」的顺序刊期（管理员）。

    口径（2026-11 编辑部决议）：

    - 排序键：``quality_score`` 降序（NULL 最后）→ ``id`` 升序，质量高的
      先进第 1 期；分数与排版格式无关，格式只是入场券。
    - 期号零填充两位（``01``、``02``…），``pages`` 保留原值不动；DOI 与
      slug 不变，外部链接不断。
    - ``dry_run=true`` 只返回分组预览，不写库。
    """
    from sqlalchemy import nullslast

    tenant_id = current_admin.tenant_id
    rows = (
        (
            await db.execute(
                select(Resource)
                .where(
                    Resource.tenant_id == tenant_id,
                    Resource.publication_status == "published",
                )
                .order_by(
                    nullslast(Resource.quality_score.desc()),
                    Resource.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No published resources")

    groups: dict[str, list[int]] = {}
    assignments: list[dict[str, object]] = []
    for seq, resource in enumerate(rows, start=1):
        issue_no = (seq - 1) // payload.issue_size + 1
        issue_label = f"{issue_no:02d}"
        if not payload.dry_run:
            resource.volume = payload.volume
            resource.issue = issue_label
        groups.setdefault(issue_label, []).append(resource.id)
        assignments.append(
            {
                "resource_id": resource.id,
                "score": float(resource.quality_score) if resource.quality_score is not None else None,
                "volume": payload.volume,
                "issue": issue_label,
                "order": seq,
            }
        )
    if not payload.dry_run:
        db.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=current_admin.id,
                action="catalog.issues_rebalanced",
                target_type="catalog",
                target_id=f"volume:{payload.volume}",
                payload={
                    "issue_size": payload.issue_size,
                    "total": len(rows),
                    "issues": {k: len(v) for k, v in sorted(groups.items())},
                },
            )
        )
        await db.commit()
    return {
        "dry_run": payload.dry_run,
        "volume": payload.volume,
        "issue_size": payload.issue_size,
        "total": len(rows),
        "issues": {k: len(v) for k, v in sorted(groups.items())},
        "assignments": assignments[:100],
        "truncated": len(assignments) > 100,
    }


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
                    # 2.0：一篇资源可能关联多条投稿（重复投稿/合并链接），
                    # 必须取有正文的那条且结果确定——空正文路径与无序 first()
                    # 会让 manuscript/download 命中空投稿而 404（线上 34 实锤）。
                    Submission.markdown_path.is_not(None),
                    Submission.markdown_path != "",
                ).order_by(Submission.id.asc())
            )
        )
        .scalars()
        .first()
    )

    # 下载计数（R 指数的 0.3 权重项）：仅 published 资源计数——刊前预览
    # 不得污染指标；且只在真正返回内容前自增一次。
    if is_published:
        await db.execute(
            update(Resource)
            .where(Resource.id == resource_id)
            .values(download_count=Resource.download_count + 1)
        )
        await db.commit()

    # 2.0 起「原稿 PDF」退役：原 PDF 已按编辑部决议归档清除，下载一律给
    # 「规范化 Word 下载件」——由在线正文 Markdown 经品牌化 docx 模板
    # 实时生成（绿色 logo 页眉、楷体书名号、标题层级），与在线阅读所见
    # 一致。存储里的旧原件不再参与下载。
    if submission is not None and submission.markdown_path:
        from fastapi.responses import Response as FastAPIResponse

        from app.core.storage import get_storage
        from app.modules.submission.docx_template import Meta as DocxMeta, build as build_docx

        try:
            md_data = await get_storage().load(submission.markdown_path)
        except FileNotFoundError:
            md_data = None
        if md_data is not None:
            md_text = md_data.decode("utf-8", errors="replace")
            meta = DocxMeta(
                title=resource.title,
                authors=[f"Rubbish 编辑部 · {resource.id} 号稿"]
                if not resource.authors
                else list(resource.authors),
                affiliations=[f"Rubbish 期刊 · 第 {resource.volume or '1'} 卷 第 {resource.issue or '—'} 期"]
                if not resource.venue
                else [resource.venue],
                abstract=resource.abstract or "",
                keywords=list(resource.keywords or []) + list(resource.tags or []),
            )
            try:
                blob = build_docx(md_text, meta)
            except Exception:  # noqa: BLE001 — 转换失败回退旧文件下载
                blob = None
            if blob is not None:
                readable = _download_name(resource.title, "docx")
                return FastAPIResponse(
                    content=blob,
                    media_type=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                    headers={
                        "Content-Disposition": (
                            f'attachment; filename="{resource.id}-manuscript.docx"; '
                            f"filename*=UTF-8''{quote(readable)}"
                        )
                    },
                )

    if submission is None or not submission.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This resource has no downloadable file",
        )

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
    （published 公开；未刊稿仅刊前预览者，无权限 404）。

    P0：无 Markdown 时不再假装回退 pdf.js 渲染——若该稿件被质量闸门判为
    needs_docx（加密/扫描件/老 .doc/乱码），明确返回 409 + 原因 + 可下载原件，
    由前端引导作者另存为 .docx。
    """
    from fastapi.responses import JSONResponse, Response

    from app.core.storage import get_storage
    from app.modules.submission.manuscript import needs_docx_storage_key

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

    # 取一篇带正文的投稿：优先有 Markdown 的；没有就退而取带 file_path 的那篇，
    # 用于判定 needs_docx 原因侧car。
    submission = (
        (
            await db.execute(
                select(Submission).where(
                    Submission.resource_id == resource_id,
                    Submission.tenant_id == tenant_id,
                    Submission.markdown_path.is_not(None),
                    Submission.markdown_path != "",
                ).order_by(Submission.id.asc())
            )
        )
        .scalars()
        .first()
    )
    if submission is None or not submission.markdown_path:
        # 无 Markdown：查 needs_docx 侧car，明确告知"不可在线阅读 + 可下载原件"。
        any_sub = (
            (
                await db.execute(
                    select(Submission).where(
                        Submission.resource_id == resource_id,
                        Submission.tenant_id == tenant_id,
                        Submission.file_path.is_not(None),
                    ).order_by(Submission.id.asc())
                )
            )
            .scalars()
            .first()
        )
        reason: str | None = None
        if any_sub is not None:
            sidecar = needs_docx_storage_key(any_sub.file_path)
            try:
                raw = await get_storage().load(sidecar)
                reason = raw.decode("utf-8", errors="replace").strip() or None
            except FileNotFoundError:
                reason = None
        if reason is not None:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "readable": False,
                    "reason": reason,
                    "downloadable": any_sub is not None,
                    "download_url": f"/api/catalog/{resource_id}/file",
                },
            )
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
    # 1.14.1：220dpi 抽取把整图 base64 内嵌进 Markdown，单篇可达 1MB+，
    # 首屏正文被图片字节拖到 ~11s。读时把 `![alt](data:...)` 就地改写成
    # `/api/catalog/{id}/img/{n}`（原图不迁移、不改存储），正文体积从 MB 级
    # 降到几十 KB；图片由 /img/{n} 按序号抽字节返回，浏览器端懒加载。
    # 兜底：任何异常都回退原始字节，不得丢图、不得报错。
    from app.modules.submission.manuscript import rewrite_embedded_images

    out_data = data
    try:
        md_text = data.decode("utf-8")
        rewritten = rewrite_embedded_images(md_text, resource_id)
        if rewritten != md_text:
            out_data = rewritten.encode("utf-8")
    except Exception:  # noqa: BLE001
        logger.warning("manuscript_rewrite_failed resource_id=%s", resource_id, exc_info=True)
        out_data = data
    # 1.6.0：稿件含 220dpi 内嵌图（单篇可达 1-2MB），给协商缓存——
    # 内容 sha256 作 ETag，重复阅读命中 304 不再重拉。
    etag = f'W/"{hashlib.sha256(out_data).hexdigest()[:32]}"'
    if if_none_match and etag in if_none_match:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return Response(
        content=out_data,
        media_type="text/markdown; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "ETag": etag,
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/{resource_id}/img/{n}")
async def get_resource_manuscript_image(
    resource_id: int,
    n: int,
    if_none_match: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> Response:
    """内嵌图片只读端点（1.14.1）：按序号从原 Markdown 抽出第 n 个 data URI
    （n 从 1 开始，文档顺序）返回图片字节。

    - 归属/可见性与 /manuscript 完全一致（published 公开；未刊稿仅刊前预览者，
      无权限 404）——按 resource 归属校验，n 越界同样 404，读不到别的文件。
    - 原图不迁移、不改存储；字节内容不变，故长缓存不可变 + ETag/304。
    """
    from app.core.storage import get_storage
    from app.modules.submission.manuscript import extract_embedded_images
    from app.modules.submission.models import Submission

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

    submission = (
        (
            await db.execute(
                select(Submission).where(
                    Submission.resource_id == resource_id,
                    Submission.tenant_id == tenant_id,
                    Submission.markdown_path.is_not(None),
                    Submission.markdown_path != "",
                ).order_by(Submission.id.asc())
            )
        )
        .scalars()
        .first()
    )
    if submission is None or not submission.markdown_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    try:
        raw_md = await get_storage().load(submission.markdown_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Stored manuscript is missing"
        ) from exc

    if n < 1:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    images = extract_embedded_images(raw_md.decode("utf-8", errors="replace"))
    if n > len(images):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    img = images[n - 1]
    etag = f'W/"{hashlib.sha256(img.data).hexdigest()[:32]}"'
    if if_none_match and etag in if_none_match:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return Response(
        content=img.data,
        media_type=img.media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "ETag": etag,
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


@router.get("/{resource_id}/manuscript.jats")
async def get_resource_manuscript_jats(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> Response:
    """NISO JATS 1.3 全文 XML（2.0 新增）：机器可读的全文交换格式。

    可见性边界与 /manuscript 完全一致。PubMed Central / Crossref / 馆藏
    系统都吃 JATS；XML 由纯函数 ``markdown_to_jats`` 生成，well-formed
    由生成器保证（所有文本节点经 XML 转义）。
    """
    from fastapi.responses import Response

    from app.core.storage import get_storage
    from app.modules.export.jats import JatsMeta, markdown_to_jats

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
                    # 2.0：一篇资源可能关联多条投稿（重复投稿/合并链接），
                    # 必须取有正文的那条且结果确定——空正文路径与无序 first()
                    # 会让 manuscript/download 命中空投稿而 404（线上 34 实锤）。
                    Submission.markdown_path.is_not(None),
                    Submission.markdown_path != "",
                ).order_by(Submission.id.asc())
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

    md_text = data.decode("utf-8", errors="replace")
    meta = JatsMeta(
        title=resource.title,
        authors=list(resource.authors or []),
        abstract=resource.abstract or "",
        keywords=list(resource.keywords or []) + list(resource.tags or []),
        volume=resource.volume or "",
        issue=resource.issue or "",
        pages=resource.pages or "",
        doi=resource.doi or "",
        year=resource.year,
        article_id=str(resource.id),
        language=resource.language or "zh",
    )
    xml = markdown_to_jats(md_text, meta)
    filename = f"{resource.id}-manuscript.jats.xml"
    return Response(
        content=xml,
        media_type="application/xml; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=300",
        },
    )


# 导出件缓存：PDF 生成线上实测 40s/13MB，同一篇第二次点下载不该再烧 CPU。
# 缓存键 = 内容哈希，正文/标题/署名任一变化都会自然失效。
_EXPORT_CACHE_TTL_SECONDS = 14 * 24 * 3600


def _export_cache_root() -> Path:
    root = Path(
        os.environ.get("RUBBISH_EXPORT_CACHE_DIR")
        or (Path(tempfile.gettempdir()) / "rubbish-export-cache")
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _export_cache_path(cache_key: str, ext: str) -> Path:
    return _export_cache_root() / f"{cache_key}.{ext}"


def _prune_export_cache(root: Path) -> None:
    import time

    cutoff = time.time() - _EXPORT_CACHE_TTL_SECONDS
    try:
        for f in root.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except OSError:
        pass


@router.get("/{resource_id}/export")
async def export_resource_manuscript(
    resource_id: int,
    request: Request,
    format: str = Query(default="pdf", pattern="^(pdf|docx)$"),
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> Response:
    """规范化文档导出（1.10.0）：把线上阅读版 Markdown 生成干净排版的
    PDF / Word 供下载。可见性边界与 /manuscript 完全一致（published 公开，
    未刊稿仅刊前预览者）。与「原稿 PDF」（作者投稿版式）互补——导出版是
    统一版式的规范化文档，字体、标题层级、表格与图片均已清洗。
    """
    import asyncio
    import hashlib
    from urllib.parse import quote

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
                    # 2.0：一篇资源可能关联多条投稿（重复投稿/合并链接），
                    # 必须取有正文的那条且结果确定——空正文路径与无序 first()
                    # 会让 manuscript/download 命中空投稿而 404（线上 34 实锤）。
                    Submission.markdown_path.is_not(None),
                    Submission.markdown_path != "",
                ).order_by(Submission.id.asc())
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

    from app.modules.submission.export_docs import (
        html_to_pdf,
        md_to_docx,
        md_to_html,
        preprocess_md,
    )

    md_text = preprocess_md(data.decode("utf-8", errors="replace"))
    # 署名行：作者 · 发表日期（来自 Resource 元数据）
    authors_str = "、".join(resource.authors or [])
    pub_date = as_aware(resource.publish_at) if resource.publish_at else as_aware(resource.created_at)
    date_str = pub_date.strftime("%Y 年 %-m 月 %-d 日") if pub_date else ""
    byline = " · ".join(x for x in (authors_str, date_str) if x) or None

    ext = "pdf" if format == "pdf" else "docx"
    media = "application/pdf" if format == "pdf" else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    try:
        readable = _download_name(resource.title, ext)
    except Exception:
        readable = f"rubbish-{resource.id}"

    # "v2" 是产物版本：导出实现变了（字体子集化）必须让旧缓存失效，
    # 否则用户还会拿到 2 MB 的旧 PDF。改实现时递增这个前缀。
    cache_key = hashlib.sha256(
        f"v2\x00{format}\x00{resource.title}\x00{byline}\x00".encode("utf-8")
        + md_text.encode("utf-8")
    ).hexdigest()[:40]
    etag = f'W/"{cache_key}"'

    headers = {
        "Content-Disposition": (
            f'attachment; filename="{resource.id}-formatted.{ext}"; '
            f"filename*=UTF-8''{quote(readable)}"
        ),
        "ETag": etag,
        "Cache-Control": "private, max-age=86400",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    cache_path = _export_cache_path(cache_key, ext)
    if cache_path.is_file():
        payload = cache_path.read_bytes()
        headers["X-Export-Cache"] = "hit"
    else:
        def _convert():
            if format == "docx":
                return md_to_docx(md_text, resource.title, byline)
            return html_to_pdf(md_to_html(md_text), resource.title, byline)

        payload = await asyncio.wait_for(asyncio.to_thread(_convert), timeout=120)
        tmp_path = cache_path.with_suffix(cache_path.suffix + f".{os.getpid()}.tmp")
        try:
            tmp_path.write_bytes(payload)
            tmp_path.replace(cache_path)
            _prune_export_cache(cache_path.parent)
        except OSError:
            tmp_path.unlink(missing_ok=True)
        headers["X-Export-Cache"] = "miss"

    return Response(content=payload, media_type=media, headers=headers)


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
    # 评分细则与分区口径只对审稿/编辑端可见：作者与普通读者（含匿名）
    # 不下发 quality_* / quartile。前端再按角色 gate 渲染，避免占位卡片。
    can_see_scores = viewer is not None and (
        PERMISSION_RANK[await effective_permission_role(db, viewer)]
        >= PERMISSION_RANK["reviewer"]
    )
    if not can_see_scores:
        response.quality_score = None
        response.quality_grade = None
        response.quality_breakdown = None
        response.quartile = None
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

    # 单一权威口径：content_track 权威，content_category 由 track 推导。
    # paper 强制 academic；essay 只允许 fun/rant（缺省 fun）。
    from app.core.tracks import canonicalize_track_category

    ct_track, ct_category = canonicalize_track_category(
        payload.content_track, payload.content_category
    )
    resource = Resource(
        tenant_id=tenant_id,
        slug=payload.slug,
        type=payload.type,
        track=payload.track,
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
        content_track=ct_track,
        content_category=ct_category,
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

    # 单一权威口径：PATCH 动了 track / category 任一者，落库前统一规范化。
    # track 权威胜出；只传 category 时按类别回推赛道（academic→paper，
    # fun/rant→essay）；paper 恒 academic，essay 缺省 fun。
    if "content_track" in update_data or "content_category" in update_data:
        from app.core.tracks import canonicalize_track_category

        resource.content_track, resource.content_category = (
            canonicalize_track_category(
                update_data.get("content_track", resource.content_track),
                update_data.get("content_category", resource.content_category),
            )
        )

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


# ---------------------------------------------------------------------------
# 作者认领（Author Claim）
#
# 早期文章由编辑部批量导入，authors 是字符串数组、与站内账号无关。
# 本组端点让作者能认领这类"无人认领"的文章：登录用户对资源发起认领
# → 编辑部批准后自动创建一条关联投稿（submitted_by = 认领人），从此
# "我的文章"、录用统计、刊前预览等基于 Submission 链路的功能全部生效。
# ---------------------------------------------------------------------------


class ClaimCreate(BaseModel):
    note: str | None = None
    # P1：申请人认领的作者位（1-based）与认领证据。
    author_position: int | None = None
    evidence_type: Literal["email", "orcid", "manuscript_id"] | None = None
    evidence_value: str | None = None


async def _notify_editors(
    db: AsyncSession, tenant_id: UUID, *, title: str, body: str, type_: str, related_id: str
) -> None:
    """给本租户全部活跃编辑（含 admin）发一条通知（随调用方事务提交）。"""
    from app.modules.notifications import services as notifications

    editor_ids = (
        select(UserRole.user_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            UserRole.tenant_id == tenant_id,
            Role.tenant_id == tenant_id,
            Role.name == "editor",
        )
    )
    editors = (
        (
            await db.execute(
                select(User)
                .where(
                    User.tenant_id == tenant_id,
                    User.is_active.is_(True),
                    (User.id.in_(editor_ids)) | (User.is_admin.is_(True)),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    for editor in editors:
        await notifications.create(
            db,
            tenant_id=tenant_id,
            user_id=editor.id,
            type_=type_,
            title=title,
            body=body,
            related_type="resource",
            related_id=related_id,
        )


async def _resource_claim_state(
    db: AsyncSession, resource: Resource, viewer: User | None
) -> dict[str, object]:
    """汇总一篇资源当前的认领状态（claim-status 与 claim 共用）。

    P0 口径：
    - ``owner_id`` 已绑定（发布时写入或认领批准时写入）→ 已认领，不可再认；
    - ``owner_id`` 为 NULL 且无 pending 申请 → 才可认领；
    - 有 pending 申请 → 审批中（不再"点一下就认领"）。
    """
    # 已绑定作者：以 owner_id 为准（这是新的唯一权威归属）。
    if resource.owner_id is not None:
        owner_name = (
            await db.execute(select(User.username).where(User.id == resource.owner_id))
        ).scalar_one_or_none()
        owner = {
            "user_id": resource.owner_id,
            "username": owner_name,
            "claimed": True,
        }
        return {"claimable": False, "state": "claimed", "claimer": owner_name, "owner": owner}

    # owner_id 未绑定：检查是否有 pending 申请（审批流）。
    pending = (
        await db.execute(
            select(AuthorClaim).where(
                AuthorClaim.resource_id == resource.id,
                AuthorClaim.tenant_id == resource.tenant_id,
                AuthorClaim.status == "pending",
            ).order_by(AuthorClaim.created_at.asc())
        )
    ).scalars().all()

    mine = None
    if viewer is not None:
        for row in pending:
            if row.user_id == viewer.id:
                mine = {"id": row.id, "status": row.status, "created_at": row.created_at}
                break

    if pending:
        # 有 pending 申请：审批中，不再开放认领。
        return {"claimable": False, "state": "pending_review", "mine": mine, "owner": None}
    return {"claimable": True, "state": "open", "mine": None, "owner": None}


@router.get("/{resource_id}/claim-status")
async def get_claim_status(
    resource_id: int,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> dict[str, object]:
    """查询一篇资源可否被认领（登录后文章页据此显示认领入口）。"""
    tenant_id = require_tenant_id()
    resource = (
        await db.execute(
            select(Resource).where(
                Resource.id == resource_id, Resource.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return await _resource_claim_state(db, resource, viewer)


@router.post("/{resource_id}/claim")
async def claim_resource(
    resource_id: int,
    body: ClaimCreate | None = None,
    db: AsyncSession = Depends(get_db),
    viewer: User = Depends(get_current_user_optional),
) -> dict[str, object]:
    """发起认领：创建 pending 申请并通知编辑部。

    P0：
    - ``owner_id`` 已绑定 → 403（文章已归属，不能再认）；
    - 已有 pending 申请 → 409（审批中）；
    - 批准权仍在编辑部（author_claims 审批流），不再点一下就认领。
    """
    tenant_id = require_tenant_id()
    if viewer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    resource = (
        await db.execute(
            select(Resource).where(
                Resource.id == resource_id, Resource.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    # P0：已绑定 owner_id 的文章一律 403，前端隐藏不隐藏都拦得住。
    if resource.owner_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该文章已归属作者，不可再被认领",
        )

    state = await _resource_claim_state(db, resource, viewer)
    if not state["claimable"]:
        if state.get("state") == "pending_review":
            msg = "你已提交过认领申请，请等待编辑部处理" if state.get("mine") else "该文章已有认领申请在审批中"
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该文章已被认领")

    note = (body.note if body else None) or None
    author_position = body.author_position if body else None
    evidence_type = body.evidence_type if body else None
    evidence_value = body.evidence_value if body else None
    claim = AuthorClaim(
        tenant_id=tenant_id,
        resource_id=resource_id,
        user_id=viewer.id,
        note=note,
        status="pending",
        author_position=author_position,
        evidence_type=evidence_type,
        evidence_value=evidence_value,
    )
    db.add(claim)
    await db.flush()

    await _notify_editors(
        db,
        tenant_id,
        type_="claim.created",
        title=f"新的认领申请：{resource.title}",
        body=(
            f"{viewer.username}（#{viewer.id}）申请认领本文。"
            + (f"申请说明：{note}" if note else "")
        ),
        related_id=str(resource_id),
    )
    await db.commit()
    return {"id": claim.id, "status": claim.status}


@router.get("/admin/overview")
async def admin_overview(
    _: User = Depends(require_editor),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(require_tenant_id),
) -> dict[str, object]:
    """管理端实时概览（2.0 主编要求）：在线人数 / 今日与累计阅读 / 下载 /
    稿件流水线 / 最热文章。数据全部来自真实阅读记录（ReadingHistory），
    30 秒轮询刷新由前端负责。"""
    from datetime import timedelta

    from sqlalchemy import func

    from app.api.deps import require_editor, require_tenant_id  # noqa: F401
    from app.modules.reader.models import ReadingHistory

    now = utcnow()
    online_rows = (
        await db.execute(
            select(func.count(func.distinct(ReadingHistory.user_id))).where(
                ReadingHistory.tenant_id == tenant_id,
                ReadingHistory.viewed_at >= now - timedelta(minutes=5),
            )
        )
    ).scalar_one()
    today_rows = (
        await db.execute(
            select(func.count(func.distinct(ReadingHistory.user_id))).where(
                ReadingHistory.tenant_id == tenant_id,
                ReadingHistory.viewed_at >= now - timedelta(hours=24),
            )
        )
    ).scalar_one()
    total_reads = (
        await db.execute(
            select(func.coalesce(func.sum(ReadingHistory.visit_count), 0)).where(
                ReadingHistory.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    total_downloads = (
        await db.execute(
            select(func.coalesce(func.sum(Resource.download_count), 0)).where(
                Resource.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    published = (
        await db.execute(
            select(func.count(Resource.id)).where(
                Resource.tenant_id == tenant_id,
                Resource.publication_status == "published",
            )
        )
    ).scalar_one()
    pending = (
        await db.execute(
            select(func.count(Submission.id)).where(
                Submission.tenant_id == tenant_id,
                Submission.status.in_(("pending", "under_review")),
            )
        )
    ).scalar_one()
    top_rows = (
        await db.execute(
            select(Resource.id, Resource.title, func.sum(ReadingHistory.visit_count))
            .join(ReadingHistory, ReadingHistory.resource_id == Resource.id)
            .where(Resource.tenant_id == tenant_id)
            .group_by(Resource.id, Resource.title)
            .order_by(func.sum(ReadingHistory.visit_count).desc())
            .limit(10)
        )
    ).all()
    return {
        "online_users": int(online_rows or 0),
        "active_24h": int(today_rows or 0),
        "total_reads": int(total_reads or 0),
        "total_downloads": int(total_downloads or 0),
        "published_resources": int(published or 0),
        "pending_submissions": int(pending or 0),
        "top_read": [
            {"id": rid, "title": title, "reads": int(n or 0)} for rid, title, n in top_rows
        ],
    }


class FeedbackIn(BaseModel):
    """全站问题反馈（2.0 主编要求：每个页面都可提 bug，交主编处理）。"""

    kind: str = Field(default="bug", max_length=20)  # bug / suggestion / appeal_help
    title: str = Field(min_length=2, max_length=120)
    body: str = Field(min_length=5, max_length=2000)
    page_url: str = Field(default="", max_length=300)


@router.post("/feedback")
async def submit_feedback(
    body: FeedbackIn,
    viewer: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(require_tenant_id),
) -> dict[str, object]:
    """任何读者/作者/审稿人都能提问题，落审计并向主编/编辑推送通知。"""
    from app.modules.notifications import services as _notify

    entry = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=viewer.id if viewer else None,
        action=f"feedback.{body.kind}",
        target_type="site",
        target_id=body.page_url or "unknown",
        payload={"title": body.title, "body": body.body},
        created_at=utcnow(),
    )
    db.add(entry)
    # 收件人 = 主编账号（bigbad, id=5）。角色表结构在不同版本间有差异，
    # 直接锁定主编账号最可靠；反馈本身已落审计，通知失败不影响入库。
    editors = (
        await db.execute(select(User.id).where(User.username == "bigbad"))
    ).scalars().all()
    for uid in set(editors):
        try:
            await _notify.create(
                db,
                tenant_id=tenant_id,
                user_id=uid,
                type_="site.feedback",
                title=f"站点反馈：{body.title}",
                body=f"{body.body}\n\n页面：{body.page_url or '—'}\n提交人：{viewer.username if viewer else '游客'}",
                related_type="site",
                related_id=body.page_url or "unknown",
            )
        except Exception:  # noqa: BLE001 — 通知失败不影响反馈入库
            logger.warning("feedback_notify_failed", user_id=uid, exc_info=True)
    await db.commit()
    await db.refresh(entry)
    return {"id": entry.id, "status": "received"}


@router.post("/{resource_id}/appeal")
async def submit_appeal(
    resource_id: int,
    body: FeedbackIn,
    viewer: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(require_tenant_id),
) -> dict[str, object]:
    """作者申诉：对评审/决定有异议 → 记录并推送给编辑，由编辑指派审稿人复审。"""
    from app.modules.notifications import services as _notify
    from app.modules.submission.models import Submission as _Submission

    if viewer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    owned = (
        await db.execute(
            select(_Submission.id).where(
                _Submission.resource_id == resource_id,
                _Submission.submitted_by == viewer.id,
                _Submission.tenant_id == tenant_id,
            )
        )
    ).scalars().all()
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=viewer.id,
        action="submission.appeal",
        target_type="resource",
        target_id=str(resource_id),
        payload={"owned_submissions": list(owned), "title": body.title, "body": body.body},
        created_at=utcnow(),
    )
    db.add(entry)
    # 收件人 = 主编账号（bigbad, id=5）。角色表结构在不同版本间有差异，
    # 直接锁定主编账号最可靠；反馈本身已落审计，通知失败不影响入库。
    editors = (
        await db.execute(select(User.id).where(User.username == "bigbad"))
    ).scalars().all()
    for uid in set(editors):
        try:
            await _notify.create(
                db,
                tenant_id=tenant_id,
                user_id=uid,
                type_="submission.appeal",
                title=f"作者申诉待处理：资源 #{resource_id}",
                body=f"{body.title}\n\n{body.body}\n\n申诉人：{viewer.username}（请指派审稿人复审）",
                related_type="resource",
                related_id=str(resource_id),
            )
        except Exception:  # noqa: BLE001
            logger.warning("appeal_notify_failed", user_id=uid, exc_info=True)
    await db.commit()
    await db.refresh(entry)
    return {"id": entry.id, "status": "received", "review_required": True}
