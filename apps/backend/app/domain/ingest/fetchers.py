"""Metadata fetchers — Crossref (DOI) and arXiv (arXiv ID) → IngestResource.

Both fetchers are stateless async functions. They raise:

- ``ResourceNotFoundError`` when the upstream reports the id is unknown
  (maps to 404 in the route layer).
- ``UpstreamError`` when the upstream times out, returns a 5xx, or any
  other transport error occurs (maps to 502).

Each fetcher builds a fresh ``httpx.AsyncClient`` with a 10s timeout.
Tests monkeypatch these functions (or the underlying ``httpx`` call) so
no real network request is ever made in the suite.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx
from defusedxml import ElementTree as ET  # type: ignore[attr-defined]

from app.core.config import settings
from app.domain.ingest.types import IngestResource

# Crossref politely asks callers to identify themselves with a mailto.
# Read from settings; falls back to a placeholder if not configured.
CROSSREF_MAILTO = settings.crossref_mailto or "rubbish-operator@example.com"
CROSSREF_BASE_URL = "https://api.crossref.org/works"
# Use HTTPS for arXiv (same host/path as the plaintext endpoint) to prevent
# in-transit tampering by a man-in-the-middle.
ARXIV_BASE_URL = "https://export.arxiv.org/api/query"
HTTP_TIMEOUT = 10.0

# Atom namespace used by the arXiv API response.
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"


class ResourceNotFoundError(Exception):
    """Upstream reports the DOI/arXiv ID does not exist."""


class UpstreamError(Exception):
    """Upstream timed out or returned an error status."""


def _crossref_authors(message: Mapping[str, Any]) -> list[str]:
    """Crossref authors are ``{given, family}`` dicts → ``"given family"``."""
    out: list[str] = []
    for author in message.get("author") or []:
        given = (author.get("given") or "").strip()
        family = (author.get("family") or "").strip()
        if given and family:
            out.append(f"{given} {family}")
        elif family:
            out.append(family)
        elif given:
            out.append(given)
    return out


def _crossref_year(message: Mapping[str, Any]) -> int | None:
    """Crossref dates nest under ``date-parts`` as a list of lists."""
    for key in ("published-print", "published-online", "issued", "created"):
        block = message.get(key)
        if not block:
            continue
        parts = block.get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                continue
    return None


async def fetch_crossref(doi: str) -> IngestResource:
    """Fetch a single work by DOI from the Crossref REST API."""
    # URL-encode the DOI so a '?' inside it cannot inject extra query params.
    url = f"{CROSSREF_BASE_URL}/{quote(doi, safe='/')}"
    headers = {
        "User-Agent": f"Rubbish/0.1 (mailto:{CROSSREF_MAILTO})",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise UpstreamError(f"Crossref timeout: {exc}") from exc
    except httpx.RequestError as exc:
        raise UpstreamError(f"Crossref request failed: {exc}") from exc

    if response.status_code == 404:
        raise ResourceNotFoundError(f"DOI not found: {doi}")
    if response.status_code >= 400:
        raise UpstreamError(f"Crossref returned status {response.status_code} for {doi}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamError(f"Crossref returned non-JSON body: {exc}") from exc

    message = payload.get("message")
    if not message:
        raise UpstreamError("Crossref response missing 'message' field")

    title_list = message.get("title") or []
    title = title_list[0].strip() if title_list else ""
    if not title:
        raise ResourceNotFoundError(f"Crossref record for {doi} has no title")

    authors = _crossref_authors(message)
    if not authors:
        raise ResourceNotFoundError(f"Crossref record for {doi} has no authors")

    container = message.get("container-title") or []
    venue = container[0].strip() if container else None

    publisher = (message.get("publisher") or "").strip() or None
    volume = (message.get("volume") or "").strip() or None
    issue = (message.get("issue") or "").strip() or None
    pages = (message.get("page") or "").strip() or None
    issn_list = message.get("ISSN") or []
    issn = issn_list[0] if issn_list else None
    short_container_title = None
    short_container_list = message.get("short-container-title") or []
    if short_container_list:
        short_container_title = short_container_list[0].strip() or None

    return IngestResource(
        title=title,
        type="paper",
        authors=authors,
        year=_crossref_year(message),
        venue=venue,
        discipline="",
        tags=[],
        abstract=(message.get("abstract") or "").strip(),
        doi=doi,
        publisher=publisher,
        volume=volume,
        issue=issue,
        pages=pages,
        issn=issn,
        short_container_title=short_container_title,
    )


def _arxiv_text(entry: ET.Element, tag: str) -> str:
    """Read a namespaced Atom child's text, or empty string if absent."""
    node = entry.find(f"{_ATOM_NS}{tag}")
    return (node.text or "").strip() if node is not None and node.text else ""


def _arxiv_authors(entry: ET.Element) -> list[str]:
    out: list[str] = []
    for author_node in entry.findall(f"{_ATOM_NS}author"):
        name_node = author_node.find(f"{_ATOM_NS}name")
        if name_node is not None and name_node.text:
            name = name_node.text.strip()
            if name:
                out.append(name)
    return out


async def fetch_arxiv(arxiv_id: str) -> IngestResource:
    """Fetch a single paper by arXiv ID from the arXiv Atom API."""
    # URL-encode the arXiv id so an '&' inside it cannot inject extra query params.
    url = f"{ARXIV_BASE_URL}?id_list={quote(arxiv_id, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        raise UpstreamError(f"arXiv timeout: {exc}") from exc
    except httpx.RequestError as exc:
        raise UpstreamError(f"arXiv request failed: {exc}") from exc

    if response.status_code == 404:
        raise ResourceNotFoundError(f"arXiv ID not found: {arxiv_id}")
    if response.status_code >= 400:
        raise UpstreamError(f"arXiv returned status {response.status_code} for {arxiv_id}")

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        raise UpstreamError(f"arXiv returned invalid XML: {exc}") from exc

    # Atom feed entries live directly under the root <feed> element.
    entries = [child for child in root if child.tag == f"{_ATOM_NS}entry"]
    if not entries:
        # arXiv returns an empty feed when the id is unknown.
        raise ResourceNotFoundError(f"arXiv ID not found: {arxiv_id}")

    entry = entries[0]
    title = _arxiv_text(entry, "title")
    if not title:
        raise ResourceNotFoundError(f"arXiv record for {arxiv_id} has no title")

    authors = _arxiv_authors(entry)
    if not authors:
        raise ResourceNotFoundError(f"arXiv record for {arxiv_id} has no authors")

    year = None
    published = _arxiv_text(entry, "published")
    if published:
        # arXiv timestamps look like "2024-01-15T00:00:00Z".
        year = _safe_parse_year(published[:4])

    venue_node = entry.find(f"{_ARXIV_NS}journal_ref")
    venue = venue_node.text.strip() if venue_node is not None and venue_node.text else None

    doi_node = entry.find(f"{_ARXIV_NS}doi")
    doi = doi_node.text.strip() if doi_node is not None and doi_node.text else None

    abstract = _arxiv_text(entry, "summary")

    return IngestResource(
        title=title,
        type="preprint",
        authors=authors,
        year=year,
        venue=venue,
        discipline="",
        tags=[],
        abstract=abstract,
        doi=doi,
    )


# ---------------------------------------------------------------------------
# PubMed
# ---------------------------------------------------------------------------

PUBMED_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


async def fetch_pubmed(pubmed_id: str) -> IngestResource:
    """Fetch a single paper by PubMed ID from the NCBI E-utilities API."""
    url = f"{PUBMED_BASE_URL}?db=pubmed&id={quote(pubmed_id, safe='')}&retmode=json"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        raise UpstreamError(f"PubMed timeout: {exc}") from exc
    except httpx.RequestError as exc:
        raise UpstreamError(f"PubMed request failed: {exc}") from exc

    if response.status_code == 404:
        raise ResourceNotFoundError(f"PubMed ID not found: {pubmed_id}")
    if response.status_code >= 400:
        raise UpstreamError(f"PubMed returned status {response.status_code} for {pubmed_id}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamError(f"PubMed returned non-JSON body: {exc}") from exc

    result = payload.get("result", {})
    record = result.get(pubmed_id)
    if not record:
        raise ResourceNotFoundError(f"PubMed ID not found: {pubmed_id}")

    title = (record.get("title") or "").strip()
    if not title:
        raise ResourceNotFoundError(f"PubMed record for {pubmed_id} has no title")

    authors_raw = record.get("authors") or []
    authors = [a["name"].strip() for a in authors_raw if a.get("name")]
    if not authors:
        raise ResourceNotFoundError(f"PubMed record for {pubmed_id} has no authors")

    pubdate = (record.get("pubdate") or "").strip()
    year = _safe_parse_year(pubdate[:4]) if pubdate else None

    venue = (record.get("source") or "").strip() or None
    volume = (record.get("volume") or "").strip() or None
    issue = (record.get("issue") or "").strip() or None
    pages = (record.get("pages") or "").strip() or None
    issn = (record.get("issn") or "").strip() or None

    # elocationid may contain a DOI (e.g. "doi: 10.1000/xyz123").
    doi = None
    elocationid = (record.get("elocationid") or "").strip()
    if elocationid.lower().startswith("doi:"):
        doi = elocationid[4:].strip()

    return IngestResource(
        title=title,
        type="paper",
        authors=authors,
        year=year,
        venue=venue,
        discipline="",
        tags=[],
        abstract="",
        doi=doi,
        volume=volume,
        issue=issue,
        pages=pages,
        issn=issn,
    )


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------

OPENALEX_BASE_URL = "https://api.openalex.org/works"


def _invert_abstract(inverted: dict[str, list[int]] | None) -> str:
    """Convert OpenAlex inverted-index abstract back to plain text."""
    if not inverted:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join(word for _, word in word_positions)


async def fetch_openalex(doi_or_id: str) -> IngestResource:
    """Fetch a single work by DOI or OpenAlex ID from the OpenAlex API.

    When *doi_or_id* looks like a DOI (contains ``/``), it is sent as
    ``doi:<doi>``; otherwise it is treated as an OpenAlex ID (e.g.
    ``W123456789``).
    """
    if "/" in doi_or_id:
        url = f"{OPENALEX_BASE_URL}/doi:{quote(doi_or_id, safe='/')}"
    else:
        url = f"{OPENALEX_BASE_URL}/{quote(doi_or_id, safe='')}"

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        raise UpstreamError(f"OpenAlex timeout: {exc}") from exc
    except httpx.RequestError as exc:
        raise UpstreamError(f"OpenAlex request failed: {exc}") from exc

    if response.status_code == 404:
        raise ResourceNotFoundError(f"OpenAlex work not found: {doi_or_id}")
    if response.status_code >= 400:
        raise UpstreamError(f"OpenAlex returned status {response.status_code} for {doi_or_id}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamError(f"OpenAlex returned non-JSON body: {exc}") from exc

    title = (payload.get("title") or "").strip()
    if not title:
        raise ResourceNotFoundError(f"OpenAlex record for {doi_or_id} has no title")

    authorships = payload.get("authorships") or []
    authors = [
        a["author"]["display_name"].strip()
        for a in authorships
        if a.get("author") and a["author"].get("display_name")
    ]
    if not authors:
        raise ResourceNotFoundError(f"OpenAlex record for {doi_or_id} has no authors")

    year = payload.get("publication_year")
    if year is not None:
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None

    # primary_location → source → display_name as venue.
    venue = None
    primary_location = payload.get("primary_location") or {}
    source = primary_location.get("source") or {}
    if source.get("display_name"):
        venue = source["display_name"].strip()

    # publisher from primary_location or top-level publisher field.
    publisher = None
    if source.get("host_organization_name"):
        publisher = source["host_organization_name"].strip()
    if not publisher:
        publisher = (payload.get("publisher") or "").strip() or None

    biblio = payload.get("biblio") or {}
    volume = (biblio.get("volume") or "").strip() or None
    issue = (biblio.get("issue") or "").strip() or None
    pages = (biblio.get("pages") or "").strip() or None

    doi = (payload.get("doi") or "").strip() or None
    # OpenAlex returns DOIs as full URLs (https://doi.org/10.xxx).
    if doi and doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/") :]

    # short_container_title from primary_location → source → display_name
    short_container_title = None
    if source.get("display_name"):
        short_container_title = source["display_name"].strip() or None

    abstract = _invert_abstract(payload.get("abstract_inverted_index"))

    return IngestResource(
        title=title,
        type="paper",
        authors=authors,
        year=year,
        venue=venue,
        discipline="",
        tags=[],
        abstract=abstract,
        doi=doi,
        publisher=publisher,
        volume=volume,
        issue=issue,
        pages=pages,
        short_container_title=short_container_title,
    )


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------

SEMANTIC_SCHOLAR_BASE_URL = "https://api.semanticscholar.org/graph/v1/paper"


async def fetch_semantic_scholar(paper_id: str) -> IngestResource:
    """Fetch a single paper from the Semantic Scholar Graph API.

    *paper_id* can be a Semantic Scholar ID (e.g. ``abc123def``), a DOI
    prefixed with ``DOI:`` (e.g. ``DOI:10.1000/xyz123``), or an arXiv ID
    prefixed with ``arXiv:``.
    """
    url = (
        f"{SEMANTIC_SCHOLAR_BASE_URL}/{quote(paper_id, safe=':')}"
        "?fields=title,authors,year,venue,abstract,externalIds"
    )
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        raise UpstreamError(f"Semantic Scholar timeout: {exc}") from exc
    except httpx.RequestError as exc:
        raise UpstreamError(f"Semantic Scholar request failed: {exc}") from exc

    if response.status_code == 404:
        raise ResourceNotFoundError(f"Semantic Scholar paper not found: {paper_id}")
    if response.status_code >= 400:
        raise UpstreamError(
            f"Semantic Scholar returned status {response.status_code} for {paper_id}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamError(f"Semantic Scholar returned non-JSON body: {exc}") from exc

    title = (payload.get("title") or "").strip()
    if not title:
        raise ResourceNotFoundError(f"Semantic Scholar record for {paper_id} has no title")

    authors_raw = payload.get("authors") or []
    authors = [a["name"].strip() for a in authors_raw if a.get("name")]
    if not authors:
        raise ResourceNotFoundError(f"Semantic Scholar record for {paper_id} has no authors")

    year = payload.get("year")
    if year is not None:
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None

    venue = (payload.get("venue") or "").strip() or None

    external_ids = payload.get("externalIds") or {}
    doi = None
    if external_ids.get("DOI"):
        doi = external_ids["DOI"].strip()

    abstract = (payload.get("abstract") or "").strip()

    return IngestResource(
        title=title,
        type="paper",
        authors=authors,
        year=year,
        venue=venue,
        discipline="",
        tags=[],
        abstract=abstract,
        doi=doi,
    )


def _safe_parse_year(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


__all__ = [
    "ARXIV_BASE_URL",
    "CROSSREF_BASE_URL",
    "CROSSREF_MAILTO",
    "HTTP_TIMEOUT",
    "OPENALEX_BASE_URL",
    "PUBMED_BASE_URL",
    "SEMANTIC_SCHOLAR_BASE_URL",
    "ResourceNotFoundError",
    "UpstreamError",
    "fetch_arxiv",
    "fetch_crossref",
    "fetch_openalex",
    "fetch_pubmed",
    "fetch_semantic_scholar",
]
