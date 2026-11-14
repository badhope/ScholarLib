"""Integration tests for the ingest module.

Two endpoint groups:

- ``POST /api/ingest/parse`` — parses BibTeX/RIS/CSV strings into a
  list of normalised ``IngestResource`` objects. Per-entry parse errors
  are returned in ``errors`` (the whole request still returns 200).
- ``POST /api/ingest/fetch`` — fetches a single DOI (Crossref) or arXiv
  ID (arXiv) and returns one ``IngestResource``.

The fetcher tests monkeypatch ``httpx.AsyncClient`` inside the fetchers
module so no real network request is ever made. The stub returns a
canned ``httpx.Response`` for every ``get()`` call.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from conftest import auth_headers
from httpx import AsyncClient

from app.domain.ingest.fetchers import ResourceNotFoundError, UpstreamError
from app.interfaces.http.ingest.schemas import IngestResource

_BIBTEX_OK = """\
@article{Cesar2013,
  author = {Jean Cesar and Bob Author},
  title = {An amazing title},
  year = {2013},
  volume = {12},
  pages = {12--23},
  journal = {Nice Journal},
  doi = {10.1234/test.001},
  keywords = {machine-learning, python}
}
@book{Book2020,
  author = {Author Name},
  title = {Book Title},
  year = {2020},
  publisher = {Publisher},
  doi = {10.1234/book.001}
}
"""

# Second entry has no ``author`` field — should land in ``errors``.
_BIBTEX_WITH_BAD = """\
@article{Good2024,
  author = {Good Author},
  title = {Good Title},
  year = {2024}
}
@article{Bad2024,
  title = {Bad Title},
  year = {2024}
}
"""

_RIS_OK = """\
TY  - JOUR
TI  - RIS Test Title
AU  - Alice Author
AU  - Bob Coauthor
PY  - 2024
JO  - Journal of Testing
DO  - 10.1234/ris.001
ER  -
"""

_CSV_OK = (
    "title,type,authors,year,venue,discipline,tags,abstract,doi\n"
    "CSV Paper,paper,Alice Author and Bob Coauthor,2024,Journal of Testing,"
    'physics,ml; python,"A short abstract.",10.1234/csv.001\n'
    "CSV Book,book,Carol Author,2020,Publisher,math,,Another abstract.,\n"
)


def _stub_httpx_response(monkeypatch: pytest.MonkeyPatch, response: Any) -> None:
    """Patch ``fetchers.httpx.AsyncClient`` to return ``response`` from get().

    The existing ``client`` fixture instance (created before this patch)
    keeps using the real ``httpx.AsyncClient``; only new ``AsyncClient``
    instantiations inside the fetchers module are intercepted.
    """

    class _StubAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _StubAsyncClient:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def get(self, url: str, headers: Any = None) -> Any:
            return response

    monkeypatch.setattr(
        "app.domain.ingest.fetchers.httpx.AsyncClient",
        _StubAsyncClient,
    )


def _stub_httpx_exception(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    """Patch ``fetchers.httpx.AsyncClient.get`` to raise ``exc``."""

    class _StubAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _StubAsyncClient:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def get(self, url: str, headers: Any = None) -> Any:
            raise exc

    monkeypatch.setattr(
        "app.domain.ingest.fetchers.httpx.AsyncClient",
        _StubAsyncClient,
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def test_parse_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/ingest/parse",
        json={"format": "bibtex", "content": "@article{x, title={T}, author={A}, year={2024}}"},
    )
    assert response.status_code == 401


async def test_fetch_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/ingest/fetch",
        json={"source": "crossref", "id": "10.1234/test"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Parse: BibTeX
# ---------------------------------------------------------------------------


async def test_parse_bibtex_success(client: AsyncClient, test_user: dict[str, Any]) -> None:
    response = await client.post(
        "/api/ingest/parse",
        json={"format": "bibtex", "content": _BIBTEX_OK},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["errors"] == []

    paper = body["data"][0]
    assert paper["title"] == "An amazing title"
    assert paper["type"] == "paper"
    assert paper["authors"] == ["Jean Cesar", "Bob Author"]
    assert paper["year"] == 2013
    assert paper["venue"] == "Nice Journal"
    assert paper["doi"] == "10.1234/test.001"
    assert "machine-learning" in paper["tags"]

    book = body["data"][1]
    assert book["type"] == "book"
    assert book["title"] == "Book Title"


async def test_parse_bibtex_records_per_entry_errors(
    client: AsyncClient, test_user: dict[str, Any]
) -> None:
    """An entry missing required fields lands in ``errors`` instead of raising."""
    response = await client.post(
        "/api/ingest/parse",
        json={"format": "bibtex", "content": _BIBTEX_WITH_BAD},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["line"] == 2
    assert "authors" in body["errors"][0]["error"]


# ---------------------------------------------------------------------------
# Parse: RIS
# ---------------------------------------------------------------------------


async def test_parse_ris_success(client: AsyncClient, test_user: dict[str, Any]) -> None:
    response = await client.post(
        "/api/ingest/parse",
        json={"format": "ris", "content": _RIS_OK},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["errors"] == []

    entry = body["data"][0]
    assert entry["title"] == "RIS Test Title"
    assert entry["type"] == "paper"
    assert entry["authors"] == ["Alice Author", "Bob Coauthor"]
    assert entry["year"] == 2024
    assert entry["venue"] == "Journal of Testing"
    assert entry["doi"] == "10.1234/ris.001"


# ---------------------------------------------------------------------------
# Parse: CSV
# ---------------------------------------------------------------------------


async def test_parse_csv_success(client: AsyncClient, test_user: dict[str, Any]) -> None:
    response = await client.post(
        "/api/ingest/parse",
        json={"format": "csv", "content": _CSV_OK},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["errors"] == []

    paper = body["data"][0]
    assert paper["title"] == "CSV Paper"
    assert paper["type"] == "paper"
    assert paper["authors"] == ["Alice Author", "Bob Coauthor"]
    assert paper["year"] == 2024
    assert paper["venue"] == "Journal of Testing"
    assert paper["doi"] == "10.1234/csv.001"
    assert "ml" in paper["tags"]
    assert "python" in paper["tags"]

    book = body["data"][1]
    assert book["type"] == "book"
    assert book["authors"] == ["Carol Author"]


async def test_parse_csv_records_line_number_in_errors(
    client: AsyncClient, test_user: dict[str, Any]
) -> None:
    """CSV errors carry the actual file line number (header is line 1)."""
    bad_csv = (
        "title,type,authors,year,venue,discipline,tags,abstract,doi\n"
        "Bad Row,not-a-type,Alice Author,2024,Venue,physics,,abs,\n"
    )
    response = await client.post(
        "/api/ingest/parse",
        json={"format": "csv", "content": bad_csv},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert len(body["errors"]) == 1
    assert body["errors"][0]["line"] == 2
    assert "type" in body["errors"][0]["error"]


# ---------------------------------------------------------------------------
# Parse: JSON (round-trips the export format)
# ---------------------------------------------------------------------------


async def test_parse_json_accepts_exported_array(
    client: AsyncClient, test_user: dict[str, Any]
) -> None:
    payload = [
        {
            "title": "JSON Paper",
            "type": "paper",
            "authors": ["Alice Author", "Bob Coauthor"],
            "year": 2024,
            "venue": "Journal of JSON",
            "tags": ["json", "import"],
            "abstract": "A short abstract.",
            "doi": "10.1234/json.001",
            "source_id": 9,
            "external_url": "https://example.org/paper",
        }
    ]
    response = await client.post(
        "/api/ingest/parse",
        json={"format": "json", "content": json.dumps(payload, ensure_ascii=False)},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["errors"] == []
    entry = body["data"][0]
    assert entry["title"] == "JSON Paper"
    assert entry["authors"] == ["Alice Author", "Bob Coauthor"]
    assert entry["tags"] == ["json", "import"]
    assert entry["doi"] == "10.1234/json.001"


async def test_parse_json_reports_bad_entry_and_bad_document(
    client: AsyncClient, test_user: dict[str, Any]
) -> None:
    response = await client.post(
        "/api/ingest/parse",
        json={
            "format": "json",
            "content": json.dumps([{"title": "No authors", "type": "paper"}]),
        },
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["errors"][0]["line"] == 1
    assert "authors" in body["errors"][0]["error"]

    response = await client.post(
        "/api/ingest/parse",
        json={"format": "json", "content": "{not json"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    assert response.json()["errors"][0]["error"].startswith("JSON parse failed")


# ---------------------------------------------------------------------------
# Parse: format validation
# ---------------------------------------------------------------------------


async def test_parse_rejects_unsupported_format(
    client: AsyncClient, test_user: dict[str, Any]
) -> None:
    response = await client.post(
        "/api/ingest/parse",
        json={"format": "yaml", "content": "title: x"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Fetch: Crossref
# ---------------------------------------------------------------------------


_CROSSREF_PAYLOAD: dict[str, Any] = {
    "message": {
        "title": ["Crossref Test Paper"],
        "author": [
            {"given": "Alice", "family": "Author"},
            {"given": "Bob", "family": "Coauthor"},
        ],
        "published-print": {"date-parts": [[2024]]},
        "container-title": ["Journal of Testing"],
        "abstract": "A test abstract from Crossref.",
        "DOI": "10.1234/test",
        "publisher": "Society of Testing",
        "volume": "45",
        "issue": "3",
        "page": "100-120",
        "ISSN": ["1234-5678"],
        "short-container-title": ["J. Test."],
    }
}


async def test_fetch_crossref_success(
    client: AsyncClient, test_user: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_httpx_response(monkeypatch, httpx.Response(200, json=_CROSSREF_PAYLOAD))

    response = await client.post(
        "/api/ingest/fetch",
        json={"source": "crossref", "id": "10.1234/test"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Crossref Test Paper"
    assert body["type"] == "paper"
    assert body["authors"] == ["Alice Author", "Bob Coauthor"]
    assert body["year"] == 2024
    assert body["venue"] == "Journal of Testing"
    assert body["doi"] == "10.1234/test"
    assert body["abstract"] == "A test abstract from Crossref."
    assert body["publisher"] == "Society of Testing"
    assert body["volume"] == "45"
    assert body["issue"] == "3"
    assert body["pages"] == "100-120"
    assert body["issn"] == "1234-5678"
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."
    assert body["short_container_title"] == "J. Test."


async def test_fetch_crossref_not_found_404(
    client: AsyncClient, test_user: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_httpx_response(monkeypatch, httpx.Response(404))

    response = await client.post(
        "/api/ingest/fetch",
        json={"source": "crossref", "id": "10.9999/does-not-exist"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 404
    # Error detail must not echo the user-supplied id back; assert on the fixed text.
    assert "not found" in response.json()["detail"].lower()


async def test_fetch_crossref_upstream_error_502(
    client: AsyncClient, test_user: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_httpx_exception(monkeypatch, httpx.TimeoutException("simulated timeout"))

    response = await client.post(
        "/api/ingest/fetch",
        json={"source": "crossref", "id": "10.1234/test"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 502
    # Error detail must not leak the underlying exception message.
    assert "upstream service error" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Fetch: arXiv
# ---------------------------------------------------------------------------


_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.01234v1</id>
    <title>arXiv Test Paper</title>
    <author>
      <name>Alice Author</name>
    </author>
    <author>
      <name>Bob Coauthor</name>
    </author>
    <published>2024-01-15T00:00:00Z</published>
    <summary>A test abstract from arXiv.</summary>
  </entry>
</feed>
"""


async def test_fetch_arxiv_success(
    client: AsyncClient, test_user: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_httpx_response(monkeypatch, httpx.Response(200, text=_ARXIV_XML))

    response = await client.post(
        "/api/ingest/fetch",
        json={"source": "arxiv", "id": "2401.01234"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "arXiv Test Paper"
    assert body["type"] == "preprint"
    assert body["authors"] == ["Alice Author", "Bob Coauthor"]
    assert body["year"] == 2024
    assert body["abstract"] == "A test abstract from arXiv."


_ARXIV_EMPTY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>
"""


async def test_fetch_arxiv_not_found_404(
    client: AsyncClient, test_user: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_httpx_response(monkeypatch, httpx.Response(200, text=_ARXIV_EMPTY_XML))

    response = await client.post(
        "/api/ingest/fetch",
        json={"source": "arxiv", "id": "9999.99999"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 404
    # Error detail must not echo the user-supplied id back.
    assert "not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Fetch: error-class direct unit-style checks (no HTTP layer)
# ---------------------------------------------------------------------------


async def test_fetch_unknown_source_rejected(
    client: AsyncClient, test_user: dict[str, Any]
) -> None:
    """Pydantic Literal on ``FetchRequest.source`` rejects unknown values."""
    response = await client.post(
        "/api/ingest/fetch",
        json={"source": "invalid_source", "id": "12345"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 422


async def test_fetcher_exceptions_map_to_status_codes(
    client: AsyncClient,
    test_user: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ResourceNotFoundError → 404, UpstreamError → 502, verified end-to-end."""

    async def raise_not_found(_doi: str) -> IngestResource:
        raise ResourceNotFoundError("not found")

    monkeypatch.setattr("app.interfaces.http.ingest.routes.fetch_crossref", raise_not_found)
    response = await client.post(
        "/api/ingest/fetch",
        json={"source": "crossref", "id": "10.9999/x"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 404

    async def raise_upstream(_arxiv_id: str) -> IngestResource:
        raise UpstreamError("upstream down")

    monkeypatch.setattr("app.interfaces.http.ingest.routes.fetch_arxiv", raise_upstream)
    response = await client.post(
        "/api/ingest/fetch",
        json={"source": "arxiv", "id": "2401.01234"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 502
