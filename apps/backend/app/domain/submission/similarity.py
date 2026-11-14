"""投稿站内相似度（不是外部查重库）。

做法：标题与摘要分别归一化，中文按单字 + 英文按词切成 token，再取 3-gram
shingle 集合，计算 Jaccard 相似度。标题权重 45%，摘要权重 55%。

边界必须说清楚：
- 只比对**本站**已发表 Resource 与其他投稿；没有接 CNKI / CrossCheck /
  Turnitin，不能对外宣称“学术查重”。
- 结果是提示编辑与作者的线索，不自动拒稿、不自动判定抄袭。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_TOKEN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")
_PUNCT = re.compile(r"[\s\u3000-\u303f\uff00-\uffef!-/:-@\[-`{-~]+")


def _tokens(text: str) -> list[str]:
    text = (text or "").lower()
    text = _PUNCT.sub(" ", text)
    return _TOKEN.findall(text)


def _shingles(text: str, n: int = 3) -> set[str]:
    tokens = _tokens(text)
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True)
class Match:
    kind: str
    id: int
    title: str
    score: float

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id, "title": self.title, "score": self.score}


def compare(title: str, abstract: str, other_title: str, other_abstract: str) -> float:
    """0–100；标题与摘要分开算，避免长摘要淹没标题重复。"""
    title_score = _jaccard(_shingles(title), _shingles(other_title))
    abstract_score = _jaccard(_shingles(abstract), _shingles(other_abstract))
    if not _shingles(abstract):
        return round(title_score * 100, 1)
    return round((0.45 * title_score + 0.55 * abstract_score) * 100, 1)


async def check_against_site(
    db: AsyncSession,
    tenant_id: Any,
    *,
    title: str,
    abstract: str,
    exclude_submission_id: int | None = None,
    limit: int = 400,
) -> tuple[float, list[dict[str, Any]]]:
    """返回 (最高相似度, Top 3 命中)。"""
    from app.domain.catalog.models import Resource
    from app.domain.submission.models import Submission

    candidates: list[Match] = []
    resources = (
        await db.execute(
            select(Resource.id, Resource.title, Resource.abstract)
            .where(Resource.tenant_id == tenant_id)
            .order_by(Resource.id.desc())
            .limit(limit)
        )
    ).all()
    for rid, rtitle, rabstract in resources:
        score = compare(title, abstract, rtitle or "", rabstract or "")
        if score > 0:
            candidates.append(Match("resource", int(rid), rtitle or "", score))

    stmt = (
        select(Submission.id, Submission.title, Submission.abstract)
        .where(
            Submission.tenant_id == tenant_id,
            Submission.status.in_(("accepted", "approved", "published")),
        )
        .order_by(Submission.id.desc())
        .limit(limit)
    )
    if exclude_submission_id is not None:
        stmt = stmt.where(Submission.id != exclude_submission_id)
    submissions = (await db.execute(stmt)).all()
    for sid, stitle, sabstract in submissions:
        score = compare(title, abstract, stitle or "", sabstract or "")
        if score > 0:
            candidates.append(Match("submission", int(sid), stitle or "", score))

    candidates.sort(key=lambda m: m.score, reverse=True)
    top = candidates[:3]
    best = top[0].score if top else 0.0
    return best, [m.as_dict() for m in top]


__all__ = ["check_against_site", "compare"]
