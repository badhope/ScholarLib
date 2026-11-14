"""Bibliographic parsers — BibTeX / RIS / CSV → list[IngestResource].

Each parser returns ``(resources, errors)`` where ``errors`` carries
per-entry failures with a 1-based line/index number. A parser only
raises when the whole input is unparseable (the route layer maps that
to 422); per-entry problems never raise.

Author / tag separators are aligned with the export module
(``" and "`` for authors, ``"; "`` for tags) so a CSV produced by
``GET /api/export?format=csv`` round-trips through ``POST /api/ingest/parse``.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from typing import Any

import bibtexparser
import rispy
from bibtexparser.bparser import BibTexParser
from pydantic import ValidationError

from app.domain.ingest.types import IngestResource, ParseError

# BibTeX entry type → IngestResourceType. Anything unmapped falls back
# to ``DEFAULT_TYPE`` so an exotic ``@misc{...}`` still imports cleanly.
BIBTEX_TYPE_MAP: dict[str, str] = {
    "article": "paper",
    "inproceedings": "paper",
    "conference": "paper",
    "incollection": "paper",
    "techreport": "paper",
    "unpublished": "preprint",
    "book": "book",
    "booklet": "book",
    "proceedings": "book",
    "manual": "book",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
}

# RIS ``type_of_reference`` → IngestResourceType.
RIS_TYPE_MAP: dict[str, str] = {
    "JOUR": "paper",
    "CHAP": "paper",
    "CONF": "paper",
    "RPRT": "paper",
    "GEN": "paper",
    "BOOK": "book",
    "THES": "thesis",
    "UNPB": "preprint",
    "ELEC": "preprint",
    "DATA": "dataset",
}

DEFAULT_TYPE = "paper"
AUTHOR_SEP = " and "
TAG_SEP = "; "


def _parse_year(raw: Any) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        # Some BibTeX entries use "to appear" or similar; treat as unknown.
        return None


def _split_authors(raw: Any) -> list[str]:
    if not raw:
        return []
    return [a.strip() for a in str(raw).split(AUTHOR_SEP) if a.strip()]


def _split_tags(raw: Any) -> list[str]:
    if not raw:
        return []
    # BibTeX ``keywords`` field is comma- or semicolon-separated.
    text = str(raw).replace(",", ";")
    return [t.strip() for t in text.split(";") if t.strip()]


def _format_validation_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "validation error"
    first = errors[0]
    field = ".".join(str(p) for p in first.get("loc", ()))
    msg = first.get("msg", "invalid value")
    return f"{field}: {msg}" if field else msg


def parse_bibtex(content: str) -> tuple[list[IngestResource], list[ParseError]]:
    """Parse a BibTeX string into resources + per-entry errors."""
    parser = BibTexParser()
    parser.ignore_nonstandard_types = False
    try:
        db = bibtexparser.loads(content, parser=parser)
    except Exception as exc:
        return [], [ParseError(line=1, error=f"BibTeX parse failed: {exc}")]

    resources: list[IngestResource] = []
    errors: list[ParseError] = []
    for idx, entry in enumerate(db.entries, start=1):
        try:
            resources.append(_bibtex_entry_to_resource(entry))
        except ValidationError as exc:
            errors.append(ParseError(line=idx, error=_format_validation_error(exc)))
        except ValueError as exc:
            errors.append(ParseError(line=idx, error=str(exc)))
    return resources, errors


def _bibtex_entry_to_resource(entry: Mapping[str, str]) -> IngestResource:
    title = (entry.get("title") or "").strip()
    if not title:
        raise ValueError("missing title")

    authors = _split_authors(entry.get("author"))
    if not authors:
        raise ValueError("missing authors")

    entry_type = (entry.get("ENTRYTYPE") or "").lower().strip()
    resource_type = BIBTEX_TYPE_MAP.get(entry_type, DEFAULT_TYPE)

    venue = entry.get("journal") or entry.get("booktitle")
    return IngestResource(
        title=title,
        type=resource_type,
        authors=authors,
        year=_parse_year(entry.get("year")),
        venue=venue.strip() if venue else None,
        discipline="unknown",
        tags=_split_tags(entry.get("keywords")),
        abstract=(entry.get("abstract") or "").strip(),
        doi=(entry.get("doi") or "").strip() or None,
    )


def parse_ris(content: str) -> tuple[list[IngestResource], list[ParseError]]:
    """Parse an RIS string into resources + per-entry errors."""
    try:
        entries = rispy.loads(content)
    except Exception as exc:
        return [], [ParseError(line=1, error=f"RIS parse failed: {exc}")]

    resources: list[IngestResource] = []
    errors: list[ParseError] = []
    for idx, entry in enumerate(entries, start=1):
        try:
            resources.append(_ris_entry_to_resource(entry))
        except ValidationError as exc:
            errors.append(ParseError(line=idx, error=_format_validation_error(exc)))
        except ValueError as exc:
            errors.append(ParseError(line=idx, error=str(exc)))
    return resources, errors


def _ris_entry_to_resource(entry: Mapping[str, Any]) -> IngestResource:
    title = (entry.get("title") or "").strip()
    if not title:
        raise ValueError("missing title")

    raw_authors = entry.get("authors") or []
    authors = [a.strip() for a in raw_authors if a and a.strip()]
    if not authors:
        raise ValueError("missing authors")

    ris_type = (entry.get("type_of_reference") or "GEN").strip().upper()
    resource_type = RIS_TYPE_MAP.get(ris_type, DEFAULT_TYPE)

    venue = entry.get("journal_name") or entry.get("secondary_title") or entry.get("publisher")
    return IngestResource(
        title=title,
        type=resource_type,
        authors=authors,
        year=_parse_year(entry.get("year")),
        venue=venue.strip() if isinstance(venue, str) else None,
        discipline="unknown",
        tags=list(entry.get("keywords") or []),
        abstract=(entry.get("abstract") or "").strip(),
        doi=(entry.get("doi") or "").strip() or None,
    )


# CSV column aliases. Aligned with the export module's ``_CSV_COLUMNS``
# so a CSV produced by ``GET /api/export?format=csv`` re-imports cleanly.
# We accept any subset; missing optional columns fall back to defaults.
_CSV_ALLOWED_TYPES = {
    "paper",
    "book",
    "journal",
    "preprint",
    "thesis",
    "dataset",
    "tutorial",
}


def parse_csv(content: str) -> tuple[list[IngestResource], list[ParseError]]:
    """Parse a CSV string (header row + one entry per row)."""
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        return [], [ParseError(line=1, error="empty CSV: no header row")]

    resources: list[IngestResource] = []
    errors: list[ParseError] = []
    # Header is line 1, so the first data row is line 2.
    for line_no, row in enumerate(reader, start=2):
        try:
            resources.append(_csv_row_to_resource(row))
        except ValidationError as exc:
            errors.append(ParseError(line=line_no, error=_format_validation_error(exc)))
        except ValueError as exc:
            errors.append(ParseError(line=line_no, error=str(exc)))
    return resources, errors


def _csv_row_to_resource(row: Mapping[str, str | None]) -> IngestResource:
    def get(name: str) -> str:
        return (row.get(name) or "").strip()

    title = get("title")
    if not title:
        raise ValueError("missing title")

    authors = _split_authors(get("authors"))
    if not authors:
        raise ValueError("missing authors")

    type_str = get("type") or DEFAULT_TYPE
    if type_str not in _CSV_ALLOWED_TYPES:
        raise ValueError(f"invalid type: {type_str}")

    tag_text = get("tags")
    tags = [t.strip() for t in tag_text.split(TAG_SEP) if t.strip()] if tag_text else []

    discipline = get("discipline") or "unknown"
    subdiscipline = get("subdiscipline") or None

    return IngestResource(
        title=title,
        type=type_str,
        authors=authors,
        year=_parse_year(get("year")),
        venue=get("venue") or None,
        discipline=discipline,
        subdiscipline=subdiscipline,
        tags=tags,
        abstract=get("abstract"),
        doi=get("doi") or None,
    )


__all__ = [
    "AUTHOR_SEP",
    "BIBTEX_TYPE_MAP",
    "DEFAULT_TYPE",
    "RIS_TYPE_MAP",
    "TAG_SEP",
    "parse_bibtex",
    "parse_csv",
    "parse_ris",
]
