"""Crawler-facing endpoints: robots.txt, sitemap.xml and SPA head metadata.

The SPA serves a single index.html for every route, so without help a
crawler sees one title and one description for the whole site and cannot
discover article URLs. These routes cover the two halves of the problem:

- ``robots.txt`` / ``sitemap.xml`` tell crawlers what exists.
- ``inject_head_metadata`` rewrites the served index.html per path so
  article pages carry their own title, description, Open Graph tags and
  the Google Scholar ``citation_*`` tags that make PDFs indexable.

Only published resources are ever exposed. All interpolated values are
HTML-escaped; a title containing ``</title><script>`` must not become one.
"""

from __future__ import annotations

import html
import json
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models import Tenant
from app.modules.catalog.models import Resource
from app.modules.catalog.visibility import public_conditions

router = APIRouter(tags=["seo"])

SITE_NAME = "Rubbish"
JOURNAL_TITLE = "Rubbish — 开放获取期刊"
DEFAULT_DESCRIPTION = (
    "Rubbish 是一份开放获取学术期刊：在线投稿、同行评审、录用后全文免费开放，"
    "覆盖论文、图书、数据集与教程。"
)

# 每个公开入口都应有自己的标题与描述；共用默认 title 会让 12 个页面在
# 搜索结果里看起来像同一个页面，也无法告诉读者这一页具体能做什么。
PAGE_META: dict[str, tuple[str, str]] = {
    "": ("Rubbish — 开放获取期刊", DEFAULT_DESCRIPTION),
    "papers": (
        "论文 · 学术与荒诞分区",
        "按学科、年份与分区浏览 Rubbish 论文；学术论文与荒诞论文分轨展示，不混在一起。",
    ),
    "catalog": ("全部目录", "按类型、学科、年份筛选 Rubbish 已刊内容，支持列表与九宫格视图。"),
    "fun": (
        "副刊 · 小说、吐槽与指南",
        "Rubbish 副刊：小说、吐槽、指南与诗歌；不是论文，也不冒充论文。",
    ),
    "forum": ("讨论区", "围绕投稿、写作、审稿与学术生存的公开讨论；发帖前请先看版规。"),
    "about": ("关于 Rubbish", "Rubbish 的定位、编辑流程、开放获取政策与联系方式。"),
    "guide": ("作者指南", "投稿格式、图表规范、评审流程与常见退稿原因。"),
    "rules": ("社区规则", "讨论区与评论区的内容规则、处理方式与申诉入口。"),
    "sections": ("栏目", "按栏目浏览 Rubbish 的内容：论文、副刊、评论与更正。"),
    "journal-metrics": (
        "期刊指标",
        "Rubbish 公开指标：论文轨规模、学科构成、阅读与下载；样本不足的指标不硬凑数字。",
    ),
    "archive": ("往期目录", "按卷期浏览 Rubbish 已上线内容。"),
    "help": ("帮助中心", "投稿、审稿、账号与阅读的常见问题。"),
    "support": ("支持我们", "Rubbish 的运营方式、赞赏与志愿者入口。"),
    "policies": ("期刊政策", "开放获取、评审、数据与更正政策。"),
}


def _root(request: Request) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return str(request.base_url).rstrip("/")


async def _published_resources(db: AsyncSession, limit: int = 5000) -> list[Resource]:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.slug == settings.bootstrap_tenant_slug))
    ).scalar_one_or_none()
    if tenant is None:
        return []
    rows = (
        (
            await db.execute(
                select(Resource)
                .where(
                    Resource.tenant_id == tenant.id,
                    *public_conditions(),
                )
                .order_by(Resource.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/robots.txt", response_class=Response, include_in_schema=False)
async def robots(request: Request) -> Response:
    body = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Allow: /api/catalog/*/export",
            "Allow: /api/catalog/*/img/",
            "Disallow: /api/",
            "Disallow: /admin",
            "Disallow: /dashboard",
            "Disallow: /submissions",
            "Disallow: /review",
            "Disallow: /settings",
            "Disallow: /notifications",
            "Disallow: /library",
            f"Sitemap: {_root(request)}/sitemap.xml",
            "",
        ]
    )
    return Response(
        content=body.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )


@router.get("/sitemap.xml", response_class=Response, include_in_schema=False)
async def sitemap(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    root = _root(request)
    urls = [
        (f"{root}/", "weekly", "1.0"),
        (f"{root}/papers", "daily", "0.9"),
        (f"{root}/catalog", "daily", "0.9"),
        (f"{root}/fun", "daily", "0.8"),
        (f"{root}/forum", "daily", "0.7"),
        (f"{root}/archive", "weekly", "0.7"),
        (f"{root}/sections", "weekly", "0.6"),
        (f"{root}/about", "monthly", "0.6"),
        (f"{root}/guide", "monthly", "0.6"),
        (f"{root}/rules", "monthly", "0.5"),
        (f"{root}/journal-metrics", "monthly", "0.6"),
        (f"{root}/help", "monthly", "0.5"),
        (f"{root}/support", "monthly", "0.4"),
        (f"{root}/policies", "monthly", "0.4"),
        (f"{root}/privacy", "yearly", "0.3"),
    ]
    rows = await _published_resources(db)
    for r in rows:
        urls.append((f"{root}/catalog/{r.id}", "monthly", "0.8"))

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, changefreq, priority in urls:
        lines.append(
            "  <url>"
            f"<loc>{html.escape(loc)}</loc>"
            f"<changefreq>{changefreq}</changefreq>"
            f"<priority>{priority}</priority>"
            "</url>"
        )
    lines.append("</urlset>")
    return Response(content="\n".join(lines), media_type="application/xml")


@router.get("/feed.xml", response_class=Response, include_in_schema=False)
@router.get("/rss.xml", response_class=Response, include_in_schema=False)
async def rss_feed(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    """RSS 2.0 feed of the latest published records.

    期刊站标配：读者可用任意 RSS 阅读器订阅新刊，聚合器与索引服务也可直接
    收割。仅含已刊出内容；摘要截断 500 字；全部字段 HTML 转义。
    """
    from email.utils import format_datetime

    root = _root(request)
    site = html.escape(settings.site_name)
    rows = await _published_resources(db, limit=50)
    items: list[str] = []
    for r in rows:
        link = f"{root}/catalog/{r.id}"
        summary = html.escape((r.abstract or "")[:500])
        pub_line = f"<pubDate>{format_datetime(r.created_at)}</pubDate>" if r.created_at else ""
        items.append(
            "<item>"
            f"<title>{html.escape(r.title)}</title>"
            f"<link>{html.escape(link)}</link>"
            f'<guid isPermaLink="true">{html.escape(link)}</guid>'
            f"<description>{summary}</description>"
            f"<author>{html.escape(', '.join(r.authors or []))}</author>"
            f"<category>{html.escape(r.discipline or '')}</category>"
            f"{pub_line}"
            "</item>"
        )
    latest = rows[0].created_at if rows else None
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
        f"<title>{site}</title>"
        f"<link>{html.escape(root)}</link>"
        f"<description>{site} · 开放获取学术期刊 · 最新发表</description>"
        "<language>zh-cn</language>"
        f'<atom:link href="{html.escape(root)}/feed.xml" rel="self" type="application/rss+xml"/>'
        + (f"<lastBuildDate>{format_datetime(latest)}</lastBuildDate>" if latest else "")
        + "".join(items)
        + "</channel></rss>"
    )
    # 显式以 UTF-8 字节输出：Starlette 对 str 内容默认按 latin-1 编码，
    # 中文会变成乱码（线上实测 "开放获取" → "寮€鏀捐幏"）。
    return Response(
        content=body.encode("utf-8"),
        media_type="application/rss+xml; charset=utf-8",
        headers={"Content-Type": "application/rss+xml; charset=utf-8"},
    )


def _meta_tags(
    title: str,
    description: str,
    canonical: str,
    extra: str = "",
    *,
    root: str,
    og_type: str = "website",
) -> str:
    t = html.escape(title, quote=True)
    d = html.escape(description, quote=True)
    c = html.escape(canonical, quote=True)
    image = html.escape(f"{root.rstrip('/')}/og-cover.png", quote=True)
    return (
        f'<meta name="description" content="{d}" />\n'
        f'<link rel="canonical" href="{c}" />\n'
        f'<meta property="og:type" content="{og_type}" />\n'
        f'<meta property="og:site_name" content="{SITE_NAME}" />\n'
        f'<meta property="og:title" content="{t}" />\n'
        f'<meta property="og:description" content="{d}" />\n'
        f'<meta property="og:url" content="{c}" />\n'
        f'<meta property="og:image" content="{image}" />\n'
        '<meta property="og:image:width" content="1200" />\n'
        '<meta property="og:image:height" content="630" />\n'
        '<meta name="twitter:card" content="summary_large_image" />\n'
        f'<meta name="twitter:image" content="{image}" />\n'
        f"{extra}"
    )


def _publication_date(r: Resource) -> str:
    """Prefer the real publication date; fall back to the year only."""
    if r.publish_at is not None:
        return r.publish_at.date().isoformat()
    return str(int(r.year))


def _citation_tags(r: Resource, root: str) -> str:
    """Google Scholar / Highwire ``citation_*`` tags for one article."""
    parts = [
        f'<meta name="citation_title" content="{html.escape(r.title, quote=True)}" />',
    ]
    for author in r.authors or []:
        parts.append(
            f'<meta name="citation_author" content="{html.escape(str(author), quote=True)}" />'
        )
    parts.append(f'<meta name="citation_publication_date" content="{_publication_date(r)}" />')
    parts.append(f'<meta name="citation_journal_title" content="{JOURNAL_TITLE}" />')
    if r.volume:
        parts.append(
            f'<meta name="citation_volume" content="{html.escape(str(r.volume), quote=True)}" />'
        )
    if r.issue:
        parts.append(
            f'<meta name="citation_issue" content="{html.escape(str(r.issue), quote=True)}" />'
        )
    if r.pages:
        parts.append(
            f'<meta name="citation_firstpage" content="{html.escape(str(r.pages).split("-")[0], quote=True)}" />'
        )
    if r.doi:
        parts.append(f'<meta name="citation_doi" content="{html.escape(r.doi, quote=True)}" />')
    if r.abstract:
        parts.append(
            f'<meta name="citation_abstract" content="{html.escape(r.abstract[:2000], quote=True)}" />'
        )
    parts.append(
        f'<meta name="citation_pdf_url" content="{html.escape(root, quote=True)}/api/catalog/{r.id}/export?format=pdf" />'
    )
    parts.append(
        f'<meta name="citation_language" content="{html.escape(r.language, quote=True)}" />'
    )
    return "\n".join(parts)


async def build_index_html(
    index_html: str,
    full_path: str,
    request: Request,
    db: AsyncSession,
) -> tuple[str, str]:
    """Return ``(html, status)`` for a SPA route.

    Only ``/`` and ``/catalog/{id}`` get route-specific metadata; every
    other SPA path keeps the default title (crawlers reach the rest
    through the sitemap anyway).
    """
    root = _root(request)
    path = full_path.strip("/")
    title, description = PAGE_META.get(path, (JOURNAL_TITLE, DEFAULT_DESCRIPTION))
    extra = ""
    status = "200"
    og_type = "website"
    if path.startswith("catalog/") and path.split("/", 1)[1].isdigit():
        tenant = (
            await db.execute(select(Tenant).where(Tenant.slug == settings.bootstrap_tenant_slug))
        ).scalar_one_or_none()
        resource: Resource | None = None
        if tenant is not None:
            resource = (
                await db.execute(
                    select(Resource).where(
                        Resource.id == int(path.split("/", 1)[1]),
                        Resource.tenant_id == tenant.id,
                        *public_conditions(),
                    )
                )
            ).scalar_one_or_none()
        if resource is None:
            # Unpublished or absent: do not leak existence, and do not let
            # the page be indexed under the wrong title.
            title = f"未找到该文章 — {SITE_NAME}"
            description = DEFAULT_DESCRIPTION
            extra = '<meta name="robots" content="noindex" />\n'
            status = "404"
        else:
            title = f"{resource.title} — {SITE_NAME}"
            description = (resource.abstract or DEFAULT_DESCRIPTION)[:300]
            extra = _citation_tags(resource, root)
            og_type = "article"
            payload: dict[str, Any] = {
                "@context": "https://schema.org",
                "@type": "ScholarlyArticle",
                "headline": resource.title,
                "author": [{"@type": "Person", "name": str(a)} for a in resource.authors or []],
                "datePublished": _publication_date(resource),
                "abstract": (resource.abstract or "")[:2000],
                "url": f"{root}/catalog/{resource.id}",
                "isPartOf": {"@type": "Periodical", "name": JOURNAL_TITLE},
            }
            if resource.doi:
                payload["identifier"] = f"https://doi.org/{resource.doi}"
            json_ld = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
            extra += f'\n<script type="application/ld+json">{json_ld}</script>'

    block = _meta_tags(
        title,
        description,
        f"{root}/{path}" if path else f"{root}/",
        extra,
        root=root,
        og_type=og_type,
    )
    out = index_html.replace(
        f"<title>{JOURNAL_TITLE}</title>", f"<title>{html.escape(title)}</title>"
    )
    if "</head>" in out:
        out = out.replace("</head>", f"    {block}\n  </head>", 1)
    return out, status


__all__: list[Any] = ["build_index_html", "router"]
