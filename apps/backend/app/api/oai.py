"""OAI-PMH 2.0 只读接口 — 让期刊资源可被 DOAJ / CNKI / 图书馆联盟等索引系统收割。

对标 OJS 3 的 OAI-PMH 插件：开放获取期刊被外部索引收录的前提是提供
标准化的元数据收割端点。本实现为最小可用子集：

- verb=Identify                仓库身份
- verb=ListMetadataFormats    支持的元数据格式（仅 oai_dc）
- verb=ListRecords            已发布资源（oai_dc 格式，支持 from/until）
- verb=GetRecord              按 identifier 取单条

不支持 resumptionToken（当前目录量级 <1 万条，一次性返回；数据量增长后
再加游标分页）。仅公开已发布资源，不暴露任何未发表内容。
"""

from __future__ import annotations

from datetime import UTC, datetime
from xml.sax.saxutils import (
    escape,  # nosec B406 -- escape() only encodes text; this module parses no XML
)

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_tenant_id
from app.core.config import settings
from app.core.db import get_db
from app.modules.catalog import models as catalog_models
from app.modules.catalog.visibility import public_conditions

router = APIRouter(prefix="/oai", tags=["oai-pmh"])

REPOSITORY_NAME = "Rubbish — 开放获取期刊"
ADMIN_EMAIL = "admin@argjiemi.cn"
BASE_IDENTIFIER_PREFIX = "oai:rubbish.argjiemi.cn"
EARLIEST_DATESTAMP = "2026-04-03T00:00:00Z"

OAI_NS = "http://www.openarchives.org/OAI/PMH/2.0/"
OAIDC_NS = "http://www.openarchives.org/OAI/PMH/2.0/oai_dc/"
DC_NS = "http://purl.org/dc/elements/1.1/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = (
    "http://www.openarchives.org/OAI/PMH/2.0/ http://www.openarchives.org/OAI/PMH/2.0/OAI-PMH.xsd"
)

_VALID_VERBS = {"Identify", "ListMetadataFormats", "ListRecords", "GetRecord"}


def _scholarly_conditions() -> list:
    """OAI 只收割学术轨的学术论文。

    荒诞论文是站内讽刺内容，不是可被 DOAJ/CNKI 收录的研究记录；副刊同样
    不进 OAI。把它们混进 oai_dc 会让外部索引把整站当成“231 篇荒诞研究”，
    这是学术信用的硬伤，不是数量问题。
    """
    return [
        catalog_models.Resource.content_track == "paper",
        or_(catalog_models.Resource.track.is_(None), catalog_models.Resource.track != "absurd"),
    ]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _public_root(request: Request) -> str:
    """Base URL for building links; honours ``RUBBISH_PUBLIC_BASE_URL``.

    Behind Caddy the app only sees ``http://app:8080``, so the configured
    public origin is the only way to emit correct absolute URLs.
    """
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return str(request.base_url).rstrip("/")


def _envelope(request: Request, body: str) -> str:
    """OAI-PMH 2.0 响应信封（含请求回显与 schema location）。"""
    qs = request.url.query
    req_attrs = f' xmlns:xsi="{XSI_NS}" xsi:schemaLocation="{SCHEMA_LOCATION}"'
    root = _public_root(request)
    if qs:  # 带参数时按规范回显纯路径
        req_line = f"<request{req_attrs}>{escape(root + request.url.path)}</request>"
    else:
        req_line = f"<request{req_attrs}>{escape(root)}/oai</request>"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<OAI-PMH xmlns="{OAI_NS}"{req_attrs}>\n'
        f"  <responseDate>{_now()}</responseDate>\n"
        f"  {req_line}\n"
        f"  {body}\n"
        f"</OAI-PMH>"
    )


def _error(code: str, message: str) -> str:
    return f'<error code="{code}">{escape(message)}</error>'


def _xml_response(content: str) -> Response:
    return Response(content=content, media_type="application/xml")


def _parse_datestamp(value: str, param: str) -> tuple[datetime | None, str | None]:
    """Parse an OAI datestamp (YYYY-MM-DD or full UTC timestamp).

    Returns ``(parsed, error_message)``; exactly one is non-None.
    """
    if not value:
        return None, None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC), None
        except ValueError:
            continue
    return None, f"Illegal {param} value: {value}"


@router.get("")
async def oai_endpoint(
    request: Request,
    verb: str = Query(default=""),
    metadataPrefix: str = Query(default=""),
    identifier: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """OAI-PMH 2.0 收割端点（只读，仅公开已发布资源）。"""
    if verb not in _VALID_VERBS:
        return _xml_response(
            _envelope(request, _error("badVerb", f"Illegal verb: {verb or '(empty)'}"))
        )

    # 参数白名单校验：不认识的参数 → badArgument（fail-closed）
    allowed_params = {"verb", "metadataPrefix", "identifier", "from", "until"}
    extra = set(request.query_params.keys()) - allowed_params
    if extra:
        return _xml_response(
            _envelope(request, _error("badArgument", f"Illegal parameter: {sorted(extra)[0]}"))
        )

    if verb == "Identify":
        body = (
            "<Identify>\n"
            f"  <repositoryName>{escape(REPOSITORY_NAME)}</repositoryName>\n"
            f"  <baseURL>{escape(_public_root(request))}/oai</baseURL>\n"
            "  <protocolVersion>2.0</protocolVersion>\n"
            f"  <adminEmail>{escape(ADMIN_EMAIL)}</adminEmail>\n"
            f"  <earliestDatestamp>{EARLIEST_DATESTAMP}</earliestDatestamp>\n"
            "  <deletedRecord>transient</deletedRecord>\n"
            "  <granularity>YYYY-MM-DDThh:mm:ssZ</granularity>\n"
            "</Identify>"
        )
        return _xml_response(_envelope(request, body))

    if verb == "ListMetadataFormats":
        body = (
            "<ListMetadataFormats>\n"
            "  <metadataFormat>\n"
            "    <metadataPrefix>oai_dc</metadataPrefix>\n"
            f"    <schema>{OAIDC_NS}oai_dc.xsd</schema>\n"
            f"    <metadataNamespace>{OAIDC_NS}</metadataNamespace>\n"
            "  </metadataFormat>\n"
            "</ListMetadataFormats>"
        )
        return _xml_response(_envelope(request, body))

    if verb == "GetRecord":
        if metadataPrefix != "oai_dc":
            return _xml_response(
                _envelope(request, _error("badArgument", "metadataPrefix must be oai_dc"))
            )
        if not identifier:
            return _xml_response(
                _envelope(request, _error("badArgument", "identifier is required"))
            )
        rid = identifier.rstrip("/").rsplit("/", 1)[-1]
        if not rid.isdigit():
            return _xml_response(
                _envelope(request, _error("idDoesNotExist", f"No matching record: {identifier}"))
            )
        tenant_id = require_tenant_id()
        row = (
            await db.execute(
                select(catalog_models.Resource).where(
                    catalog_models.Resource.id == int(rid),
                    catalog_models.Resource.tenant_id == tenant_id,
                    *public_conditions(),
                    *_scholarly_conditions(),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return _xml_response(
                _envelope(request, _error("idDoesNotExist", f"No matching record: {identifier}"))
            )
        record = _record_xml(row, request)
        body = f"<GetRecord>\n  <record>\n{record}\n  </record>\n</GetRecord>"
        return _xml_response(_envelope(request, body))

    # verb == ListRecords（前面 badVerb 分支已保证到此处的 verb 取值）
    if metadataPrefix != "oai_dc":
        return _xml_response(
            _envelope(request, _error("badArgument", "metadataPrefix must be oai_dc"))
        )
    date_from, err = _parse_datestamp(request.query_params.get("from", ""), "from")
    if err:
        return _xml_response(_envelope(request, _error("badArgument", err)))
    date_until, err = _parse_datestamp(request.query_params.get("until", ""), "until")
    if err:
        return _xml_response(_envelope(request, _error("badArgument", err)))
    if date_from and date_until and date_from > date_until:
        return _xml_response(
            _envelope(request, _error("badArgument", "from must not be later than until"))
        )

    tenant_id = require_tenant_id()
    stmt = (
        select(catalog_models.Resource)
        .where(
            catalog_models.Resource.tenant_id == tenant_id,
            *public_conditions(),
            *_scholarly_conditions(),
        )
        .order_by(catalog_models.Resource.id.asc())
    )
    if date_from:
        stmt = stmt.where(catalog_models.Resource.created_at >= date_from)
    if date_until:
        stmt = stmt.where(catalog_models.Resource.created_at <= date_until)
    rows = (await db.execute(stmt)).scalars().all()
    records = "\n".join(f"  {_record_xml(r, request, indent=2)}" for r in rows)
    body = f"<ListRecords>\n{records}\n</ListRecords>"
    return _xml_response(_envelope(request, body))


def _record_xml(r: catalog_models.Resource, request: Request, indent: int = 4) -> str:
    """单条 oai_dc 记录（Dublin Core 元数据）。"""
    pad = " " * indent
    identifier = f"{BASE_IDENTIFIER_PREFIX}:resource/{r.id}"
    lines = [
        f"{pad}<record>",
        f"{pad}  <header>",
        f"{pad}    <identifier>{escape(identifier)}</identifier>",
        f"{pad}    <datestamp>{r.created_at.strftime('%Y-%m-%dT%H:%M:%SZ')}</datestamp>",
        f"{pad}  </header>",
        f"{pad}  <metadata>",
        f'{pad}    <oai_dc:dc xmlns:oai_dc="{OAIDC_NS}" xmlns:dc="{DC_NS}" '
        f'xsi:schemaLocation="{OAIDC_NS} {OAIDC_NS}oai_dc.xsd">',
        f"{pad}      <dc:title>{escape(r.title)}</dc:title>",
    ]
    for a in r.authors or []:
        lines.append(f"{pad}      <dc:creator>{escape(str(a))}</dc:creator>")
    for kw in r.keywords or []:
        lines.append(f"{pad}      <dc:subject>{escape(str(kw))}</dc:subject>")
    if r.discipline:
        lines.append(f"{pad}      <dc:subject>{escape(r.discipline)}</dc:subject>")
    lines.append(f"{pad}      <dc:description>{escape(r.abstract)}</dc:description>")
    lines.append(f"{pad}      <dc:date>{r.year}</dc:date>")
    lines.append(f"{pad}      <dc:type>{escape(str(r.type))}</dc:type>")
    if r.language:
        lines.append(f"{pad}      <dc:language>{escape(r.language)}</dc:language>")
    base = f"{_public_root(request)}/catalog/{r.id}"
    lines.append(f"{pad}      <dc:identifier>{escape(base)}</dc:identifier>")
    if r.doi:
        lines.append(f"{pad}      <dc:identifier>doi:{escape(r.doi)}</dc:identifier>")
    lines.append(f"{pad}      <dc:rights>CC BY 4.0</dc:rights>")
    lines.append(f"{pad}    </oai_dc:dc>")
    lines.append(f"{pad}  </metadata>")
    lines.append(f"{pad}</record>")
    return "\n".join(lines)
