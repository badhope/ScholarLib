"""Content-based recommendation engine.

Builds a user interest profile from reading history (tags + disciplines
+ subdisciplines of read resources) and scores unread catalog resources
by tag overlap + discipline / subdiscipline matches. Falls back to the
latest catalog resources when the user has no reading history yet.

Scoring weights sum to 1.0 so the score stays in [0, 1]:

- tag overlap:    0.6  (precision: overlap / candidate tag count)
- discipline:     0.3  (1.0 if the candidate's discipline is in the profile)
- subdiscipline:  0.1  (1.0 if the candidate's subdiscipline is in the profile)

Cross-module reads: imports ``Resource`` (catalog) and ``ReadingHistory``
(reader) models only — no routes or schemas — per the module boundary
rules in ARCHITECTURE.md. All queries are scoped by ``tenant_id`` so
recommendations never leak across tenants (defense-in-depth with RLS).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.catalog.models import Resource
from app.domain.catalog.visibility import public_conditions
from app.domain.reader.models import ReadingHistory

TAG_WEIGHT = 0.6
DISCIPLINE_WEIGHT = 0.3
SUBDISCIPLINE_WEIGHT = 0.1
# Cap the candidate set scanned for ranking. Beyond this the user has
# read so little of a very large catalog that scanning the rest in one
# pass is wasteful; falling back to "latest" is cheaper and still useful.
_MAX_CANDIDATE_SCAN = 5000


@dataclass
class _Candidate:
    """Lightweight scoring row.

    Only the columns the content-based score needs are fetched — no
    ``abstract``/``preview``/JSON payloads — so a large catalog does not
    drag heavy BLOB-like data into Python just to rank it.
    """

    id: int
    tags: list[str]
    discipline: str
    subdiscipline: str | None
    content_category: str | None = None


@dataclass
class UserProfile:
    """Aggregated interests extracted from the user's read resources."""

    tags: Counter[str] = field(default_factory=Counter)
    disciplines: Counter[str] = field(default_factory=Counter)
    subdisciplines: Counter[str] = field(default_factory=Counter)
    # 内容类别偏好计数（v1.11）：同类别才可比对。
    categories: Counter[str] = field(default_factory=Counter)


@dataclass
class ScoredResource:
    """A candidate resource paired with its computed score and reason."""

    resource: Resource
    score: float
    reason: str


async def _load_read_resources(db: AsyncSession, user_id: int, tenant_id: UUID) -> list[Resource]:
    """Return the resources the user has reading history for (tenant-scoped).

    Read-history is bounded by the user's own activity and is used to
    build the profile + the ``read_ids`` set, so the full row is fetched
    here. The heavy candidate scan (which can span the whole catalog)
    is what's pruned to lightweight columns in :func:`recommend`.
    """
    rows = (
        (
            await db.execute(
                select(Resource)
                .join(ReadingHistory, ReadingHistory.resource_id == Resource.id)
                .where(
                    ReadingHistory.user_id == user_id,
                    ReadingHistory.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _build_profile(read_resources: list[Resource]) -> UserProfile:
    """Aggregate the user's interest profile from read resources.

    Only ``tags`` / ``discipline`` / ``subdiscipline`` are consulted —
    the heavy ``abstract`` / ``preview`` / JSON columns stay out of the
    Python heap even when the user has read many items.
    """
    profile = UserProfile()
    for r in read_resources:
        # 内容类别分域（v1.11 铁律三）：读者偏好按类别累计，推荐只在
        # 读者最常读的那一类里做同类别比对，避免「学术稿推荐吐槽稿」。
        cat = getattr(r, "content_category", None)
        if cat:
            profile.categories[cat] = profile.categories.get(cat, 0) + 1
        for tag in r.tags or []:
            profile.tags[tag] += 1
        if r.discipline:
            profile.disciplines[r.discipline] += 1
        if r.subdiscipline:
            profile.subdisciplines[r.subdiscipline] += 1
    return profile


def _score_candidate(
    candidate: _Candidate,
    profile: UserProfile,
) -> tuple[float, str]:
    """Compute the content-based score + reason for one lightweight candidate.

    Only the scoring columns are needed (tags, discipline, subdiscipline);
    no full ``Resource`` row is materialized during the ranking pass. The
    returned ``(score, reason)`` pair is attached to the full ORM row
    after the top-N selection is known.
    """
    candidate_tags = candidate.tags or []
    overlap = [t for t in candidate_tags if t in profile.tags]
    # Precision: fraction of the candidate's tags the user cares about.
    # max(..., 1) avoids division by zero for tagless candidates.
    tag_part = (len(overlap) / max(len(candidate_tags), 1)) * TAG_WEIGHT

    discipline_match = 1.0 if candidate.discipline in profile.disciplines else 0.0
    subdiscipline_match = (
        1.0
        if candidate.subdiscipline and candidate.subdiscipline in profile.subdisciplines
        else 0.0
    )
    score = (
        tag_part + discipline_match * DISCIPLINE_WEIGHT + subdiscipline_match * SUBDISCIPLINE_WEIGHT
    )
    score = max(0.0, min(1.0, score))

    parts: list[str] = []
    if overlap:
        parts.append(f"matches {len(overlap)} tags: {overlap}")
    if discipline_match:
        parts.append(f"discipline '{candidate.discipline}'")
    if subdiscipline_match:
        parts.append(f"subdiscipline '{candidate.subdiscipline}'")
    reason = "; ".join(parts) if parts else "no direct match"
    return score, reason


async def _fallback_latest(
    db: AsyncSession,
    limit: int,
    tenant_id: UUID,
    reason: str = "no reading history; showing latest",
) -> list[ScoredResource]:
    """Return the most recently created resources as a last resort.

    Used both for brand-new readers (no history yet) and for readers who
    have already read everything in the catalog — an empty page would be
    a dead end either way, while "latest" keeps the page actionable.
    ``score`` stays 0.0 so the UI can label these as "latest" rather than
    pretending a real match exists.
    """
    rows = (
        (
            await db.execute(
                select(Resource)
                .where(Resource.tenant_id == tenant_id, *public_conditions())
                # id 决胜（desc）：「最新优先」= 后创建的在前；同批插入的
                # 行 created_at 相同，纯时间戳排序不稳定。
                .order_by(desc(Resource.created_at), Resource.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        ScoredResource(
            resource=r,
            score=0.0,
            reason=reason,
        )
        for r in rows
    ]


async def recommend(
    db: AsyncSession, user_id: int, tenant_id: UUID, limit: int
) -> list[ScoredResource]:
    """Compute top-N recommendations for the user.

    No reading history → latest ``limit`` catalog resources (score 0).
    Otherwise → unread resources ranked by content-based score, truncated
    to ``limit``. Ties break by resource id for deterministic ordering.

    Two degenerate cases still return content instead of an empty page:
    no history at all, and a reader who has already read every resource
    (no unread candidates left).

    All queries are scoped by ``tenant_id`` so recommendations never
    leak across tenants even when RLS is not active (e.g. SQLite tests).
    """
    read_resources = await _load_read_resources(db, user_id, tenant_id)
    if not read_resources:
        return await _fallback_latest(db, limit, tenant_id)

    profile = _build_profile(read_resources)
    read_ids = {r.id for r in read_resources}
    # Phase 1: score on lightweight columns only (id, tags, discipline,
    # subdiscipline) so a large catalog never drags abstract/preview/JSON
    # payloads into Python just to rank it.
    candidate_rows = (
        await db.execute(
            select(
                Resource.id,
                Resource.tags,
                Resource.discipline,
                Resource.subdiscipline,
                Resource.content_category,
            )
            .where(
                ~Resource.id.in_(read_ids),
                Resource.tenant_id == tenant_id,
                # 推荐是公开面：排期中的期号不得出现在推荐结果里
                # （falls back to _fallback_latest which already filters）。
                *public_conditions(),
            )
            # id 决胜：同一批次插入的行 created_at 可能完全相同，
            # 纯时间戳排序不稳定（测试中 Latest Paper A/B 顺序抖动）。
            .order_by(desc(Resource.created_at), Resource.id.desc())
            .limit(_MAX_CANDIDATE_SCAN)
        )
    ).all()
    if not candidate_rows:
        # 已读完全部资源：回退到最新收录，避免推荐页变成死胡同。
        return await _fallback_latest(
            db, limit, tenant_id, reason="you have read everything; showing latest"
        )

    # 候选排序：(score, id, reason)，稳定排序用 (-score, id)。
    ranked: list[tuple[float, int, str]] = []
    for row in candidate_rows:
        candidate = _Candidate(
            id=row[0],
            tags=row[1] or [],
            discipline=row[2],
            subdiscipline=row[3],
            content_category=row[4],
        )
        # 类别分域（铁律三）：读者有明确类别偏好时，只在该类别内比对。
        # 无偏好（未读过任何带类别的内容）时不设限，保证冷启动可用。
        preferred = profile.categories.most_common(1)
        if preferred and candidate.content_category:
            if candidate.content_category != preferred[0][0]:
                continue
        score, reason = _score_candidate(candidate, profile)
        ranked.append((score, candidate.id, reason))
    ranked.sort(key=lambda r: (-r[0], r[1]))

    top_ids = [r[1] for r in ranked[: max(limit, 1)]]
    # Phase 2: hydrate full rows only for the survivors.
    top_resources = (
        (
            await db.execute(
                select(Resource).where(Resource.id.in_(top_ids), Resource.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    # SQLAlchemy does not guarantee IN-list ordering, so rebuild by id.
    by_id = {r.id: r for r in top_resources}
    result: list[ScoredResource] = []
    for score, rid, reason in ranked[: max(limit, 1)]:
        if rid in by_id:
            result.append(ScoredResource(resource=by_id[rid], score=score, reason=reason))
    return result
