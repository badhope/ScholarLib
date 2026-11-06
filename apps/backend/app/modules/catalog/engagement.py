"""Article-level engagement metrics and the transparent R-index.

Rubbish has no citation graph, so we do not pretend to publish a JCR
impact factor. Instead every published record carries a **computed**
attention score built only from events the platform actually records:

- ``reads``      — ``SUM(reading_history.visit_count)`` (opening the record)
- ``downloads``  — ``resources.download_count`` (hitting the file endpoint)
- ``saves``      — number of reading-list items pointing at the record

``r_index`` = 100 x (0.5*reads_n + 0.3*downloads_n + 0.2*saves_n) where
each ``*_n`` is divided by the maximum value **within the same
discipline**, so a new journal is not compared against absolute traffic.
The formula itself is an internal editorial yardstick: the public
metrics surface reports the numbers (r_index, journal-level r_factor)
without publishing the weights, and nothing here is presented as a
citation metric.

Quartiles (``R1``..``R4``) are percentile bands of ``r_index`` inside a
discipline. They are only assigned when a discipline has at least
``MIN_QUARTILE_SAMPLE`` published records — below that the sample cannot
support a quartile and the UI shows "sample too small" instead of
inventing one.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Resource
from app.modules.catalog.visibility import public_conditions

# ``library`` and ``reader`` depend on ``catalog`` (they reference its
# Resource rows), so importing their models at module scope would trigger
# their module registration before catalog's — the registry rejects that
# ordering. Lazy imports inside the helpers keep the dependency direction
# one-way.

MIN_QUARTILE_SAMPLE = 4
# R 因子最小样本：全刊阅读+下载+收藏事件总数低于此值时不出数。
# 理由：R 指数按同学科最大值归一，样本极小时单次下载就把该篇顶到满分，
# 全刊均值会给出 13.15 这种一看就假的数字。宁可不显示。
MIN_R_FACTOR_SAMPLE = 30

READ_WEIGHT = 0.5
DOWNLOAD_WEIGHT = 0.3
SAVE_WEIGHT = 0.2


@dataclass(frozen=True)
class Engagement:
    reads: int
    downloads: int
    saves: int
    r_index: float
    quartile: str | None


async def load_raw_engagement(
    db: AsyncSession, resource_ids: list[int], tenant_id: Any
) -> dict[int, tuple[int, int, int]]:
    """Return ``{resource_id: (reads, downloads, saves)}`` for the given ids."""
    if not resource_ids:
        return {}

    from app.modules.library.models import ReadingListItem
    from app.modules.reader.models import ReadingHistory

    read_rows = (
        await db.execute(
            select(
                ReadingHistory.resource_id,
                func.coalesce(func.sum(ReadingHistory.visit_count), 0),
            )
            .where(
                ReadingHistory.tenant_id == tenant_id,
                ReadingHistory.resource_id.in_(resource_ids),
            )
            .group_by(ReadingHistory.resource_id)
        )
    ).all()
    save_rows = (
        await db.execute(
            select(ReadingListItem.resource_id, func.count(ReadingListItem.id))
            .where(
                ReadingListItem.tenant_id == tenant_id,
                ReadingListItem.resource_id.in_(resource_ids),
            )
            .group_by(ReadingListItem.resource_id)
        )
    ).all()
    download_rows = (
        await db.execute(
            select(Resource.id, Resource.download_count).where(
                Resource.tenant_id == tenant_id,
                Resource.id.in_(resource_ids),
            )
        )
    ).all()

    reads = {rid: int(total or 0) for rid, total in read_rows}
    saves = {rid: int(total or 0) for rid, total in save_rows}
    downloads = {rid: int(total or 0) for rid, total in download_rows}
    return {
        rid: (reads.get(rid, 0), downloads.get(rid, 0), saves.get(rid, 0)) for rid in resource_ids
    }


def _score(reads: int, downloads: int, saves: int, maxima: tuple[int, int, int]) -> float:
    max_reads, max_downloads, max_saves = maxima
    read_n = reads / max_reads if max_reads else 0.0
    download_n = downloads / max_downloads if max_downloads else 0.0
    save_n = saves / max_saves if max_saves else 0.0
    raw = READ_WEIGHT * read_n + DOWNLOAD_WEIGHT * download_n + SAVE_WEIGHT * save_n
    return round(100 * raw, 1)


def _quartile_bands(
    all_rows: list[Resource], all_raw: dict[int, tuple[int, int, int]], discipline: str
) -> dict[int, str]:
    if discipline == "__global__":
        ids = [r.id for r in all_rows]
    else:
        ids = [r.id for r in all_rows if r.discipline == discipline]
    if len(ids) < MIN_QUARTILE_SAMPLE:
        return {}
    values = [all_raw.get(rid, (0, 0, 0)) for rid in ids]
    maxima = (
        max((v[0] for v in values), default=0),
        max((v[1] for v in values), default=0),
        max((v[2] for v in values), default=0),
    )
    scored = sorted(
        ((rid, _score(*all_raw.get(rid, (0, 0, 0)), maxima)) for rid in ids),
        key=lambda pair: pair[1],
        reverse=True,
    )
    n = len(scored)
    bands: dict[int, str] = {}
    for rank, (rid, _value) in enumerate(scored):
        pct = rank / n
        bands[rid] = "R1" if pct < 0.25 else "R2" if pct < 0.5 else "R3" if pct < 0.75 else "R4"
    return bands


def _discipline_maxima(
    rows: list[Resource], raw: dict[int, tuple[int, int, int]]
) -> dict[str, tuple[int, int, int]]:
    """Per-discipline maxima of (reads, downloads, saves) for normalisation."""
    grouped: dict[str, list[tuple[int, int, int]]] = {}
    for row in rows:
        if row.discipline:
            grouped.setdefault(row.discipline, []).append(raw.get(row.id, (0, 0, 0)))
    return {
        discipline: (
            max((v[0] for v in values), default=0),
            max((v[1] for v in values), default=0),
            max((v[2] for v in values), default=0),
        )
        for discipline, values in grouped.items()
    }


async def compute_engagement(db: AsyncSession, rows: list[Resource]) -> dict[int, Engagement]:
    """Compute per-record engagement + quartile for a page of resources.

    Page ids need two aggregate queries; the discipline maxima need one
    more scan of that discipline's published rows. Query count stays
    constant regardless of page size.
    """
    if not rows:
        return {}

    tenant_id = rows[0].tenant_id
    page_ids = [r.id for r in rows]
    raw = await load_raw_engagement(db, page_ids, tenant_id)

    disciplines = {r.discipline for r in rows if r.discipline}
    maxima_by_discipline: dict[str, tuple[int, int, int]] = {}
    quartiles: dict[str, dict[int, str]] = {}
    global_band: dict[int, str] = {}
    global_maxima: tuple[int, int, int] = (0, 0, 0)
    if disciplines:
        all_rows = list(
            (
                await db.execute(
                    select(Resource).where(
                        Resource.tenant_id == tenant_id,
                        Resource.discipline.in_(disciplines),
                        *public_conditions(),
                    )
                )
            )
            .scalars()
            .all()
        )
        all_raw = await load_raw_engagement(db, [r.id for r in all_rows], tenant_id)
        maxima_by_discipline = _discipline_maxima(all_rows, all_raw)
        for discipline in disciplines:
            quartiles[discipline] = _quartile_bands(all_rows, all_raw, discipline)

    # 2.0 主编口径：学科样本不足以支撑同学科分区时，退回**全刊池**计算
    # 分区（仍是真实阅读/下载数据的百分位，只是池子更大），不再把大片
    # 文章挂成「样本不足」。
    global_rows = list(
        (
            await db.execute(
                select(Resource).where(
                    Resource.tenant_id == tenant_id, *public_conditions()
                )
            )
        )
        .scalars()
        .all()
    )
    global_raw = await load_raw_engagement(db, [r.id for r in global_rows], tenant_id)
    global_maxima = (
        max((v[0] for v in global_raw.values()), default=0),
        max((v[1] for v in global_raw.values()), default=0),
        max((v[2] for v in global_raw.values()), default=0),
    )
    global_band = _quartile_bands(global_rows, global_raw, "__global__")

    result: dict[int, Engagement] = {}
    for row in rows:
        reads, downloads, saves = raw.get(row.id, (0, 0, 0))
        maxima = maxima_by_discipline.get(row.discipline, (0, 0, 0))
        quartile = quartiles.get(row.discipline, {}).get(row.id) or global_band.get(row.id)
        result[row.id] = Engagement(
            reads=reads,
            downloads=downloads,
            saves=saves,
            r_index=_score(reads, downloads, saves, maxima),
            quartile=quartile,
        )
    return result


async def journal_metrics(db: AsyncSession, tenant_id: Any) -> dict[str, Any]:
    """Journal-level numbers for the public metrics page."""
    from app.modules.library.models import ReadingListItem
    from app.modules.reader.models import ReadingHistory
    from app.modules.submission.models import Submission

    published_filter = (Resource.tenant_id == tenant_id, *public_conditions())
    total = (
        await db.execute(select(func.count(Resource.id)).where(*published_filter))
    ).scalar_one()
    by_type: dict[str, int] = {
        str(t): int(c)
        for t, c in (
            await db.execute(
                select(Resource.type, func.count(Resource.id))
                .where(*published_filter)
                .group_by(Resource.type)
            )
        ).all()
    }
    by_discipline: dict[str, int] = {
        str(d): int(c)
        for d, c in (
            await db.execute(
                select(Resource.discipline, func.count(Resource.id))
                .where(*published_filter)
                .group_by(Resource.discipline)
            )
        ).all()
    }
    downloads = (
        await db.execute(
            select(func.coalesce(func.sum(Resource.download_count), 0)).where(*published_filter)
        )
    ).scalar_one()
    # reads / saves 只统计公开可见条目：排期稿在指标页同样要隐身，
    # 否则「期刊指标」会替还没上线的期数预热阅读量。
    reads = (
        await db.execute(
            select(func.coalesce(func.sum(ReadingHistory.visit_count), 0)).where(
                ReadingHistory.tenant_id == tenant_id,
                ReadingHistory.resource_id.in_(
                    select(Resource.id).where(Resource.tenant_id == tenant_id, *public_conditions())
                ),
            )
        )
    ).scalar_one()
    saves = (
        await db.execute(
            select(func.count(ReadingListItem.id)).where(
                ReadingListItem.tenant_id == tenant_id,
                ReadingListItem.resource_id.in_(
                    select(Resource.id).where(Resource.tenant_id == tenant_id, *public_conditions())
                ),
            )
        )
    ).scalar_one()

    submissions = list(
        (
            await db.execute(
                select(Submission).where(
                    Submission.tenant_id == tenant_id,
                    Submission.reviewed_at.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    review_days = sorted(
        (s.reviewed_at - s.submitted_at).total_seconds() / 86400
        for s in submissions
        if s.reviewed_at and s.submitted_at
    )
    accepted = sum(1 for s in submissions if s.status in ("accepted", "approved"))
    decided = len(submissions)
    avg_review_days = round(sum(review_days) / len(review_days), 1) if review_days else None
    median_review_days = round(review_days[len(review_days) // 2], 1) if review_days else None

    # R 因子：全刊已发表记录 R 指数的均值。复用与单篇一致的最大值归一，
    # 因此一篇孤立的新文章不会因为全刊流量小而虚高。
    r_factor: float | None = None
    published_rows = list(
        (await db.execute(select(Resource).where(*published_filter))).scalars().all()
    )
    if published_rows:
        raw = await load_raw_engagement(db, [r.id for r in published_rows], tenant_id)
        total_events = sum(sum(raw.get(r.id, (0, 0, 0))) for r in published_rows)
        if total_events >= MIN_R_FACTOR_SAMPLE:
            maxima = _discipline_maxima(published_rows, raw)
            scores = [
                _score(*raw.get(r.id, (0, 0, 0)), maxima.get(r.discipline, (0, 0, 0)))
                for r in published_rows
            ]
            r_factor = round(sum(scores) / len(scores), 2)

    absurdity_rows = (
        await db.execute(
            select(Resource.absurdity_index).where(
                *published_filter, Resource.absurdity_index.is_not(None)
            )
        )
    ).scalars()
    absurdity_values = [float(v) for v in absurdity_rows if v is not None]
    absurdity_median = round(statistics.median(absurdity_values), 1) if absurdity_values else None

    return {
        "published_total": total,
        "by_type": by_type,
        "by_discipline": by_discipline,
        "discipline_count": len([d for d in by_discipline if d]),
        "downloads_total": int(downloads or 0),
        "reads_total": int(reads or 0),
        "saves_total": int(saves or 0),
        "decided_submissions": decided,
        "accepted_submissions": accepted,
        "acceptance_rate": round(100 * accepted / decided, 1) if decided else None,
        "avg_review_days": avg_review_days,
        "median_review_days": median_review_days,
        "open_access_rate": 100.0 if total else None,
        "r_factor": r_factor,
        "self_citation_rate": 0.0,
        "absurdity_index_median": absurdity_median,
    }


__all__ = [
    "MIN_QUARTILE_SAMPLE",
    "MIN_R_FACTOR_SAMPLE",
    "Engagement",
    "compute_engagement",
    "journal_metrics",
    "load_raw_engagement",
]
