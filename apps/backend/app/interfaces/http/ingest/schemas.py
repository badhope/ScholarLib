"""Pydantic schemas for the ingest module.

The ingest module normalises external bibliographic data (BibTeX/RIS/CSV
files, Crossref/arXiv API responses) into ``IngestResource`` objects.
These objects are *not* catalog rows — the frontend takes them and
submits them via ``/api/submissions`` so the catalog keeps a single
write path.

``IngestResource`` deliberately mirrors the field shape of
``SubmissionCreate`` but is more permissive (year/abstract/discipline
optional) because parsed or fetched data may be incomplete; the user
fills gaps before submitting.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.ingest.types import (
    FetchSource,
    IngestResource,
    IngestResourceType,
    ParseError,
    ParseFormat,
)


# Broader than catalog's ResourceType: ingest can produce types the
# catalog does not yet accept (e.g. thesis, preprint) — the frontend
# either maps them or asks the user to pick before submitting.
class ParseRequest(BaseModel):
    """Body for POST /api/ingest/parse."""

    format: ParseFormat
    content: str = Field(min_length=1, max_length=2_000_000)


class FetchRequest(BaseModel):
    """Body for POST /api/ingest/fetch."""

    source: FetchSource
    id: str = Field(min_length=1, max_length=500)


class ParseResponse(BaseModel):
    """Response for POST /api/ingest/parse."""

    data: list[IngestResource]
    count: int = Field(ge=0)
    errors: list[ParseError]


__all__ = [
    "FetchRequest",
    "FetchSource",
    "IngestResource",
    "IngestResourceType",
    "ParseError",
    "ParseFormat",
    "ParseRequest",
    "ParseResponse",
]
