"""Domain record types produced by ingest parsers/fetchers.

These are business records, not HTTP DTOs: they can be consumed by CLI,
MCP or scheduled jobs without importing the web layer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import Authors

IngestResourceType = Literal[
    "paper",
    "book",
    "journal",
    "preprint",
    "thesis",
    "dataset",
    "tutorial",
]

ParseFormat = Literal["bibtex", "ris", "csv", "json"]
FetchSource = Literal["crossref", "arxiv", "pubmed", "openalex", "semantic_scholar"]


class IngestResource(BaseModel):
    """Normalised record produced by parsers and fetchers.

    Field shape mirrors ``SubmissionCreate`` so the frontend can forward
    an object verbatim to ``POST /api/submissions`` after the user fills
    any missing required fields (year, abstract, discipline).
    """

    title: str = Field(min_length=1, max_length=1000)
    type: IngestResourceType
    authors: Authors = Field(min_length=1, max_length=200)
    year: int | None = Field(default=None, ge=-3000, le=2100)
    venue: str | None = Field(default=None, max_length=500)
    discipline: str = Field(default="unknown", max_length=100)
    subdiscipline: str | None = Field(default=None, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=50)
    abstract: str = Field(default="", max_length=20000)
    doi: str | None = Field(default=None, max_length=200)
    publisher: str | None = Field(default=None, max_length=500)
    volume: str | None = Field(default=None, max_length=50)
    issue: str | None = Field(default=None, max_length=50)
    pages: str | None = Field(default=None, max_length=50)
    issn: str | None = Field(default=None, max_length=20)
    short_container_title: str | None = Field(default=None, max_length=200)


class ParseError(BaseModel):
    """Per-entry parse error; line is 1-based."""

    line: int = Field(ge=1)
    error: str = Field(min_length=1, max_length=500)
