"""Citation serializers — pure functions, duck-typed on ``Exportable``.

No I/O, no DB, no ``app.*`` imports. Each function takes a list of
objects satisfying the ``Exportable`` protocol and returns a string in
the target format. Round-trip safe with the (future) ingest module's
parsers: CSV headers line up with importer aliases, BibTeX entry types
mirror the importer type map.

Self-contained: only the import paths and the ``Resource`` type
reference are module-local.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

# Resource types → BibTeX entry types.
_BIBTEX_TYPE_MAP: dict[str, str] = {
    "paper": "article",
    "book": "book",
    "tutorial": "misc",
    "dataset": "misc",
}

# Resource types → RIS type_of_reference.
_RIS_TYPE_MAP: dict[str, str] = {
    "paper": "JOUR",
    "book": "BOOK",
    "tutorial": "GEN",
    "dataset": "DATA",
}

# Canonical CSV column order. Headers align with the future ingest
# module's CSV aliases so a re-import resolves every column.
_CSV_COLUMNS: list[str] = [
    "title",
    "type",
    "authors",
    "year",
    "venue",
    "discipline",
    "tags",
    "abstract",
    "doi",
    "url",
]

_KEY_SAFE_RE = re.compile(r"[^a-zA-Z0-9_-]")


@runtime_checkable
class Exportable(Protocol):
    """Structural interface — any ORM Resource or test stub satisfies this."""

    id: int | str
    title: str
    authors: list[str]
    year: int
    venue: str | None
    type: str
    discipline: str | None
    tags: list[str]
    abstract: str
    doi: str | None
    download_url: str | None
    external_url: str | None
    volume: str | None
    issue: str | None
    pages: str | None
    keywords: list[str] | None


# --- Shared helpers ---


def _author_list(resource: Exportable) -> list[str]:
    """Authors as a de-duplicated, ordered list."""
    seen: set[str] = set()
    ordered: list[str] = []
    for author in resource.authors or []:
        name = (author or "").strip()
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _tags(resource: Exportable) -> list[str]:
    return list(resource.tags or [])


def _keywords(resource: Exportable) -> list[str]:
    """Prefer explicit ``keywords``; fall back to ``tags``."""
    if resource.keywords:
        return list(resource.keywords)
    return _tags(resource)


def _url(resource: Exportable) -> str | None:
    return resource.download_url or resource.external_url or None


def _family_name(author: str) -> str:
    """Extract surname for citation key. Accepts "Family, Given" and "Given Family"."""
    if "," in author:
        return author.split(",", 1)[0].strip()
    parts = author.strip().split()
    return parts[-1] if parts else "anon"


def _citation_key(resource: Exportable, index: int) -> str:
    """Stable, BibTeX-safe key: ``<surname><year><titleword>`` (+ disambiguator)."""
    authors = _author_list(resource)
    surname = _family_name(authors[0]).lower() if authors else "anon"
    surname = _KEY_SAFE_RE.sub("", surname) or "anon"
    first_word = ""
    for word in re.split(r"\W+", resource.title or ""):
        if word and word[0].isalpha():
            first_word = word.lower()
            break
    first_word = _KEY_SAFE_RE.sub("", first_word)
    if not first_word:
        # 中文/日文等无 ASCII 首词的标题：用资源 id 兜底。否则所有中文稿
        # 都会生成 ``author2024untitled``，只能靠 _2/_3 后缀区分，既不稳定
        # 也不可读。
        fallback = _KEY_SAFE_RE.sub("", str(resource.id))
        first_word = f"r{fallback}" if fallback else "untitled"
    key = f"{surname}{resource.year}{first_word}"
    if index:
        key += f"_{index}"
    return key


# --- BibTeX ---


# LaTeX 特殊字符 → 转义序列。花括号尤其关键：它是 BibTeX 字段的定界符，
# 标题里多一个未转义的 ``}`` 会把整个条目截断（ibliography 直接报错）。
_BIBTEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
}


def _escape_bibtex(value: str) -> str:
    """Escape LaTeX specials in free-text fields (title / author / abstract / venue / keywords).

    只用于自由文本：DOI、URL、页码这类结构化字段保持原样 —— 给 DOI 里的
    ``_`` 加反斜杠反而会让引用的 DOI 变成乱码。
    """
    return "".join(_BIBTEX_ESCAPES.get(ch, ch) for ch in value)


def to_bibtex(resources: list[Exportable]) -> str:
    """Render resources as a BibTeX bibliography string."""
    used_keys: set[str] = set()
    blocks: list[str] = []
    for resource in resources:
        key = _citation_key(resource, 0)
        suffix = 1
        while key in used_keys:
            suffix += 1
            key = _citation_key(resource, suffix)
        used_keys.add(key)
        blocks.append(_resource_to_bibtex(resource, key))
    return "\n\n".join(blocks)


def _resource_to_bibtex(resource: Exportable, key: str) -> str:
    entry_type = _BIBTEX_TYPE_MAP.get(resource.type, "misc")
    authors = _author_list(resource)
    fields: list[str] = [f"  title = {{{_escape_bibtex(resource.title)}}}"]
    if authors:
        escaped_authors = " and ".join(_escape_bibtex(author) for author in authors)
        fields.append(f"  author = {{{escaped_authors}}}")
    fields.append(f"  year = {{{resource.year}}}")
    if resource.venue:
        venue_field = "journal" if resource.type == "paper" else "booktitle"
        fields.append(f"  {venue_field} = {{{_escape_bibtex(resource.venue)}}}")
    if resource.volume:
        fields.append(f"  volume = {{{resource.volume}}}")
    if resource.issue:
        fields.append(f"  number = {{{resource.issue}}}")
    if resource.pages:
        fields.append(f"  pages = {{{resource.pages}}}")
    keywords = _keywords(resource)
    if keywords:
        escaped_keywords = ", ".join(_escape_bibtex(keyword) for keyword in keywords)
        fields.append(f"  keywords = {{{escaped_keywords}}}")
    if resource.doi:
        fields.append(f"  doi = {{{resource.doi}}}")
    url = _url(resource)
    if url:
        fields.append(f"  url = {{{url}}}")
    if resource.abstract:
        abstract = re.sub(r"\s+", " ", resource.abstract).strip()
        fields.append(f"  abstract = {{{_escape_bibtex(abstract)}}}")
    return f"@{entry_type}{{{key},\n" + ",\n".join(fields) + "\n}"


# --- RIS ---


def to_ris(resources: list[Exportable]) -> str:
    """Render resources as an RIS tagged string."""
    blocks: list[str] = []
    for resource in resources:
        blocks.append(_resource_to_ris(resource))
    return "\n\n".join(blocks)


_PAGE_RANGE_RE = re.compile(r"^\s*(\d+)\s*[-–—]\s*(\d+)\s*$")


def _ris_text(value: str) -> str:
    """RIS 每条 tag 只占一行；换行会把一条记录拆成两条。"""
    return re.sub(r"\s+", " ", value or "").strip()


def _ris_pages(pages: str) -> tuple[str, str | None]:
    """RIS 没有 ``SP - 1-20`` 这种写法：起始页/结束页必须拆成 SP/EP。"""
    raw = _ris_text(pages)
    match = _PAGE_RANGE_RE.match(raw)
    if match:
        return match.group(1), match.group(2)
    return raw, None


def _resource_to_ris(resource: Exportable) -> str:
    lines: list[str] = [f"TY  - {_RIS_TYPE_MAP.get(resource.type, 'GEN')}"]
    lines.append(f"TI  - {_ris_text(resource.title)}")
    for author in _author_list(resource):
        lines.append(f"AU  - {_ris_text(author)}")
    lines.append(f"PY  - {resource.year}")
    if resource.venue:
        lines.append(f"JO  - {_ris_text(resource.venue)}")
    if resource.volume:
        lines.append(f"VL  - {resource.volume}")
    if resource.issue:
        lines.append(f"IS  - {resource.issue}")
    if resource.pages:
        start, end = _ris_pages(resource.pages)
        lines.append(f"SP  - {start}")
        if end:
            lines.append(f"EP  - {end}")
    for keyword in _keywords(resource):
        lines.append(f"KW  - {_ris_text(keyword)}")
    if resource.doi:
        lines.append(f"DO  - {resource.doi}")
    url = _url(resource)
    if url:
        lines.append(f"UR  - {url}")
    if resource.abstract:
        lines.append(f"AB  - {_ris_text(resource.abstract)}")
    lines.append("ER  -")
    return "\n".join(lines)


# --- CSV ---


def _csv_safe(value: Any) -> Any:
    """Defuse CSV formula injection.

    If a cell string starts with ``=``, ``+``, ``-``, ``@``, ``\\t`` or
    ``\\r``, prefix it with a single quote so spreadsheet apps (Excel,
    WPS) treat it as text rather than a formula.
    """
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def to_csv(resources: list[Exportable]) -> str:
    """Render resources as CSV with canonical headers (import-round-trip safe)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for resource in resources:
        writer.writerow(
            [
                _csv_safe(resource.title),
                _csv_safe(resource.type),
                _csv_safe(" and ".join(_author_list(resource))),
                resource.year,
                _csv_safe(resource.venue or ""),
                _csv_safe(resource.discipline or ""),
                _csv_safe("; ".join(_keywords(resource))),
                _csv_safe(resource.abstract or ""),
                _csv_safe(resource.doi or ""),
                _csv_safe(_url(resource) or ""),
            ]
        )
    return buffer.getvalue()


# --- JSON ---


def to_json(resources: list[Exportable]) -> str:
    """Render resources as a JSON array of normalised records."""
    records = [_resource_to_record(r) for r in resources]
    return json.dumps(records, indent=2, ensure_ascii=False)


def _resource_to_record(resource: Exportable) -> dict[str, Any]:
    return {
        "title": resource.title,
        "type": resource.type,
        "authors": _author_list(resource),
        "year": resource.year,
        "venue": resource.venue,
        "discipline": resource.discipline,
        "tags": _tags(resource),
        "abstract": resource.abstract or None,
        "doi": resource.doi,
        "external_url": _url(resource),
        "source_id": resource.id,
        "keywords": _keywords(resource),
        "volume": resource.volume,
        "issue": resource.issue,
        "pages": resource.pages,
    }


# --- JATS (bibliographic; full-text JATS lives in ``jats.py``) ---


def to_jats(resources: list[Exportable]) -> str:
    """Render resources as a NISO JATS 1.3 ``<article>`` set (one per resource).

    书目级导出：每篇一个独立 ``<article>``，front 携带完整元数据；
    正文由 ``manuscript.jats`` 端点按全文转换，这里不重复。
    """
    from app.domain.export.jats import JatsMeta, markdown_to_jats

    articles: list[str] = []
    for resource in resources:
        meta = JatsMeta(
            title=resource.title,
            authors=_author_list(resource),
            abstract=resource.abstract or "",
            keywords=_keywords(resource),
            journal=resource.venue or "Rubbish",
            volume=resource.volume or "",
            issue=resource.issue or "",
            pages=resource.pages or "",
            doi=resource.doi or "",
            year=resource.year,
            article_id=str(resource.id),
        )
        articles.append(markdown_to_jats("", meta))
    return "\n".join(articles)


# --- Dispatch ---


EXPORTERS: dict[str, Callable[[list[Exportable]], str]] = {
    "bibtex": to_bibtex,
    "ris": to_ris,
    "csv": to_csv,
    "json": to_json,
    "jats": to_jats,
}

MIME_TYPES: dict[str, str] = {
    "bibtex": "application/x-bibtex",
    "ris": "application/x-research-info-systems",
    "csv": "text/csv",
    "json": "application/json",
    "jats": "application/xml",
}

FILE_EXTENSIONS: dict[str, str] = {
    "bibtex": "bib",
    "ris": "ris",
    "csv": "csv",
    "json": "json",
    "jats": "xml",
}


def export_resources(format_: str, resources: list[Exportable]) -> str:
    """Dispatch to the right serializer by format name (case-insensitive).

    Raises ValueError on unsupported format.
    """
    fmt = format_.strip().lower()
    exporter = EXPORTERS.get(fmt)
    if exporter is None:
        raise ValueError(f"Unsupported export format: {format_!r} (bibtex/ris/csv/json/jats)")
    return exporter(resources)


__all__ = [
    "FILE_EXTENSIONS",
    "MIME_TYPES",
    "Exportable",
    "export_resources",
    "to_bibtex",
    "to_csv",
    "to_jats",
    "to_json",
    "to_ris",
]
