"""Release gate: deterministic checks for one issue.

The gate is intentionally boring: it reads the actual resource rows and the
actual uploaded files, produces a flat list of checks, and hashes the
snapshot.  A release manifest is only usable while that hash still matches.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time import utcnow
from app.modules.catalog.models import Resource
from app.modules.submission.models import Submission

GATE_VERSION = "1.0"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _safe_upload_path(relative: str | None) -> Path | None:
    if not relative:
        return None
    base = Path(settings.storage_path).resolve()
    candidate = (base / relative).resolve()
    if base != candidate and base not in candidate.parents:
        return None
    return candidate


def _file_meta(relative: str | None) -> dict[str, Any]:
    path = _safe_upload_path(relative)
    if path is None:
        return {"path": relative, "exists": False, "size": 0, "sha256": None}
    if not path.is_file():
        return {"path": relative, "exists": False, "size": 0, "sha256": None}
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            sha.update(chunk)
    return {
        "path": relative,
        "exists": True,
        "size": path.stat().st_size,
        "sha256": sha.hexdigest(),
    }


def _check(code: str, level: str, message: str, resource_id: int | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "level": level,  # error | warning | info
        "message": message,
        "resource_id": resource_id,
    }


def _resource_snapshot(resource: Resource, submission: Submission | None) -> dict[str, Any]:
    file_meta = _file_meta(submission.file_path if submission else None)
    markdown_meta = _file_meta(submission.markdown_path if submission else None)
    return {
        "id": resource.id,
        "slug": resource.slug,
        "type": resource.type,
        "title": resource.title,
        "authors": resource.authors or [],
        "year": resource.year,
        "volume": resource.volume,
        "issue": resource.issue,
        "publication_status": resource.publication_status,
        "publish_at": _iso(resource.publish_at),
        "content_category": resource.content_category,
        "discipline": resource.discipline,
        "updated_at": _iso(resource.updated_at),
        "pdf": file_meta,
        "markdown": markdown_meta,
    }


def _content_hash(resources: list[dict[str, Any]]) -> str:
    canonical = json.dumps(resources, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def check_issue(db: AsyncSession, tenant_id: UUID, volume: str, issue: str) -> dict[str, Any]:
    """Return a full gate result for one issue.

    The caller persists it as a manifest.  This function does not commit.
    """
    rows = (
        (
            await db.execute(
                select(Resource)
                .where(
                    Resource.tenant_id == tenant_id,
                    Resource.volume == volume,
                    Resource.issue == issue,
                )
                .order_by(Resource.id.asc())
            )
        )
        .scalars()
        .all()
    )

    submission_rows: list[Submission] = []
    if rows:
        result = await db.execute(
            select(Submission)
            .where(
                Submission.tenant_id == tenant_id,
                Submission.resource_id.in_([r.id for r in rows]),
            )
            .order_by(Submission.id.asc())
        )
        submission_rows = list(result.scalars().all())
    # Latest submission wins when an issue was re-uploaded.
    submissions = {s.resource_id: s for s in submission_rows if s.resource_id is not None}

    checks: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    seen_titles: dict[str, int] = {}
    seen_slugs: dict[str, int] = {}

    if not rows:
        checks.append(_check("issue_empty", "error", f"Vol. {volume} Issue {issue} 没有任何资源"))

    for resource in rows:
        snapshot = _resource_snapshot(resource, submissions.get(resource.id))
        snapshots.append(snapshot)
        rid = resource.id

        if resource.publication_status != "published":
            checks.append(
                _check(
                    "resource_not_published",
                    "error",
                    f"资源 #{rid} 仍是 {resource.publication_status}，不能随整期发布",
                    rid,
                )
            )
        if not (resource.title or "").strip():
            checks.append(_check("metadata_title", "error", f"资源 #{rid} 缺少标题", rid))
        if not (resource.abstract or "").strip():
            checks.append(_check("metadata_abstract", "error", f"资源 #{rid} 缺少摘要", rid))
        elif resource.type == "paper" and len(resource.abstract.strip()) < 40:
            checks.append(
                _check("metadata_abstract_short", "warning", f"资源 #{rid} 摘要少于 40 字", rid)
            )
        if not resource.authors:
            checks.append(_check("metadata_authors", "error", f"资源 #{rid} 缺少作者", rid))
        if not (resource.discipline or "").strip():
            checks.append(_check("metadata_discipline", "warning", f"资源 #{rid} 缺少学科", rid))
        if not (resource.content_category or "").strip():
            checks.append(_check("metadata_category", "error", f"资源 #{rid} 缺少内容类别", rid))

        title_key = (resource.title or "").strip().lower()
        if title_key:
            if title_key in seen_titles:
                checks.append(
                    _check(
                        "duplicate_title",
                        "error",
                        f"资源 #{rid} 与 #{seen_titles[title_key]} 标题重复",
                        rid,
                    )
                )
            else:
                seen_titles[title_key] = rid
        slug_key = (resource.slug or "").strip().lower()
        if slug_key:
            if slug_key in seen_slugs:
                checks.append(
                    _check(
                        "duplicate_slug",
                        "error",
                        f"资源 #{rid} 与 #{seen_slugs[slug_key]} slug 重复",
                        rid,
                    )
                )
            else:
                seen_slugs[slug_key] = rid

        file_meta = snapshot["pdf"]
        markdown_exists = snapshot["markdown"]["exists"]
        # The journal's canonical source is Markdown; PDFs are often rendered
        # on demand from it (and original uploads may be purged).  A missing
        # PDF is therefore only a hard error when there is no Markdown and no
        # external link to fall back to.
        if file_meta["exists"] and file_meta["size"] < 1024:
            checks.append(
                _check("file_pdf_too_small", "warning", f"资源 #{rid} 的 PDF 小于 1KB", rid)
            )
        elif file_meta["path"] and not file_meta["exists"] and not markdown_exists:
            checks.append(
                _check(
                    "file_pdf_not_found",
                    "error",
                    f"资源 #{rid} 的 PDF 不存在，且没有 Markdown 源",
                    rid,
                )
            )
        elif file_meta["path"] and not file_meta["exists"] and markdown_exists:
            checks.append(
                _check(
                    "file_pdf_fallback_markdown",
                    "warning",
                    f"资源 #{rid} 的 PDF 已清理，将用 Markdown 渲染",
                    rid,
                )
            )
        elif (
            not file_meta["path"]
            and not markdown_exists
            and not (resource.external_url or "").strip()
        ):
            checks.append(
                _check(
                    "file_source_missing",
                    "error",
                    f"资源 #{rid} 没有 PDF、Markdown 或外部链接",
                    rid,
                )
            )
        elif not file_meta["path"] and markdown_exists:
            checks.append(
                _check("file_markdown_source", "info", f"资源 #{rid} 使用 Markdown 作为正文源", rid)
            )
        if not markdown_exists:
            checks.append(
                _check("file_markdown_missing", "info", f"资源 #{rid} 没有 Markdown 源", rid)
            )
        if not (resource.cover_image or "").strip():
            checks.append(_check("cover_missing", "info", f"资源 #{rid} 使用生成的默认封面", rid))
        if resource.publish_at is not None and resource.publish_at > utcnow():
            checks.append(
                _check(
                    "publish_scheduled",
                    "info",
                    f"资源 #{rid} 已排期到 {_iso(resource.publish_at)}",
                    rid,
                )
            )

    error_count = sum(1 for c in checks if c["level"] == "error")
    warning_count = sum(1 for c in checks if c["level"] == "warning")
    status = "blocked" if error_count else "ready"
    return {
        "gate_version": GATE_VERSION,
        "volume": volume,
        "issue": issue,
        "status": status,
        "content_hash": _content_hash(snapshots),
        "resource_count": len(snapshots),
        "error_count": error_count,
        "warning_count": warning_count,
        "checks": checks,
        "resources": snapshots,
    }
