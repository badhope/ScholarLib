"""Tests for the metadata fetchers (Crossref / arXiv / PubMed / OpenAlex / S2).

All five fetchers share the same contract, and that contract is what we
pin down here:

- transport failure (timeout / connection error) → ``UpstreamError`` (502)
- upstream says "unknown id" (404 or empty record) → ``ResourceNotFoundError``
- upstream says "broken" (5xx / non-JSON / invalid XML) → ``UpstreamError``
- a record without a title or without authors is unusable →
  ``ResourceNotFoundError``, not a half-filled ``IngestResource``

HTTP is faked at ``httpx.AsyncClient``; nothing leaves the process.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.domain.ingest import fetchers


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: Any = None,
        text: str = "",
        json_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self._json_error = json_error

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def patch_http(
    monkeypatch: pytest.MonkeyPatch,
    response: FakeResponse | None = None,
    error: Exception | None = None,
) -> list[str]:
    """Swap ``httpx.AsyncClient`` for a stub; return the list of requested URLs."""
    urls: list[str] = []

    class StubClient:
        async def __aenter__(self) -> StubClient:
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

        async def get(self, url: str, **_kw: Any) -> FakeResponse:
            urls.append(url)
            if error is not None:
                raise error
            assert response is not None
            return response

    monkeypatch.setattr(fetchers.httpx, "AsyncClient", lambda *_a, **_kw: StubClient())
    return urls


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_crossref_authors_handles_partial_names() -> None:
    message = {
        "author": [
            {"given": "Alice", "family": "Smith"},
            {"family": "Bob"},
            {"given": "Carol"},
            {},
        ]
    }

    assert fetchers._crossref_authors(message) == ["Alice Smith", "Bob", "Carol"]


def test_crossref_authors_empty_when_no_author_field() -> None:
    assert fetchers._crossref_authors({}) == []


def test_crossref_year_falls_back_through_date_keys() -> None:
    # published-print 缺失时应继续找 published-online / issued / created
    assert fetchers._crossref_year({"published-online": {"date-parts": [[2021]]}}) == 2021
    assert fetchers._crossref_year({"issued": {"date-parts": [[2020]]}}) == 2020
    assert fetchers._crossref_year({"created": {"date-parts": [[2019, 5]]}}) == 2019


def test_crossref_year_tolerates_garbage() -> None:
    assert fetchers._crossref_year({"issued": {"date-parts": [["nope"]]}}) is None
    assert fetchers._crossref_year({"issued": {"date-parts": [[]]}}) is None
    assert fetchers._crossref_year({}) is None


def test_invert_abstract_rebuilds_word_order() -> None:
    inverted = {"hello": [0], "world": [1], "again": [2]}

    assert fetchers._invert_abstract(inverted) == "hello world again"
    assert fetchers._invert_abstract(None) == ""


def test_safe_parse_year() -> None:
    assert fetchers._safe_parse_year("2024") == 2024
    assert fetchers._safe_parse_year("abcd") is None


# ---------------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------------

_CROSSREF_OK = FakeResponse(
    200,
    {
        "message": {
            "title": ["  A Crossref Paper  "],
            "author": [{"given": "Ada", "family": "Lovelace"}],
            "published-print": {"date-parts": [[1843]]},
            "container-title": ["Journal of Testing"],
            "short-container-title": ["J. Test"],
            "publisher": " Test Publisher ",
            "volume": " 3 ",
            "issue": " 4 ",
            "page": " 10-20 ",
            "ISSN": ["1234-5678"],
            "abstract": "An abstract.",
        }
    },
)


async def test_fetch_crossref_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = patch_http(monkeypatch, _CROSSREF_OK)

    resource = await fetchers.fetch_crossref("10.1000/xyz")

    assert resource.title == "A Crossref Paper"
    assert resource.authors == ["Ada Lovelace"]
    assert resource.year == 1843
    assert resource.venue == "Journal of Testing"
    assert resource.short_container_title == "J. Test"
    assert resource.publisher == "Test Publisher"
    assert (resource.volume, resource.issue, resource.pages) == ("3", "4", "10-20")
    assert resource.issn == "1234-5678"
    assert resource.doi == "10.1000/xyz"
    assert urls == [f"{fetchers.CROSSREF_BASE_URL}/10.1000/xyz"]


async def test_fetch_crossref_url_encodes_doi(monkeypatch: pytest.MonkeyPatch) -> None:
    """DOI 里的 ? / & 不能被当成查询参数注入。"""
    urls = patch_http(monkeypatch, _CROSSREF_OK)

    await fetchers.fetch_crossref("10.1000/a?b&c")

    assert "?b&c" not in urls[0]
    assert "%3F" in urls[0]


async def test_fetch_crossref_404_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(404))

    with pytest.raises(fetchers.ResourceNotFoundError):
        await fetchers.fetch_crossref("10.1000/missing")


async def test_fetch_crossref_5xx_is_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(503))

    with pytest.raises(fetchers.UpstreamError):
        await fetchers.fetch_crossref("10.1000/xyz")


async def test_fetch_crossref_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, error=httpx.TimeoutException("slow"))

    with pytest.raises(fetchers.UpstreamError, match="timeout"):
        await fetchers.fetch_crossref("10.1000/xyz")


async def test_fetch_crossref_request_error(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, error=httpx.ConnectError("dns"))

    with pytest.raises(fetchers.UpstreamError, match="request failed"):
        await fetchers.fetch_crossref("10.1000/xyz")


async def test_fetch_crossref_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(200, json_error=ValueError("not json")))

    with pytest.raises(fetchers.UpstreamError, match="non-JSON"):
        await fetchers.fetch_crossref("10.1000/xyz")


async def test_fetch_crossref_missing_message(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(200, {}))

    with pytest.raises(fetchers.UpstreamError, match="missing 'message'"):
        await fetchers.fetch_crossref("10.1000/xyz")


async def test_fetch_crossref_without_title_or_authors(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(200, {"message": {"title": []}}))

    with pytest.raises(fetchers.ResourceNotFoundError, match="no title"):
        await fetchers.fetch_crossref("10.1000/xyz")

    patch_http(monkeypatch, FakeResponse(200, {"message": {"title": ["T"], "author": []}}))

    with pytest.raises(fetchers.ResourceNotFoundError, match="no authors"):
        await fetchers.fetch_crossref("10.1000/xyz")


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------


def _arxiv_feed(
    *,
    title: str = "An arXiv Preprint",
    authors: list[str] | None = None,
    published: str = "2024-01-15T00:00:00Z",
    journal_ref: str | None = "J. Ref 2024",
    doi: str | None = "10.1000/arxiv",
    summary: str = "Preprint abstract.",
) -> FakeResponse:
    # 注意用 `is not None`：`authors=[]` 是合法输入（无作者），不能回退成默认作者
    names = "".join(
        f"<author><name>{n}</name></author>"
        for n in (authors if authors is not None else ["Alice A"])
    )
    journal = f"<arxiv:journal_ref>{journal_ref}</arxiv:journal_ref>" if journal_ref else ""
    doi_tag = f"<arxiv:doi>{doi}</arxiv:doi>" if doi else ""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <title>{title}</title>
        <summary>{summary}</summary>
        <published>{published}</published>
        {names}
        {journal}
        {doi_tag}
      </entry>
    </feed>"""
    return FakeResponse(200, text=xml)


async def test_fetch_arxiv_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = patch_http(monkeypatch, _arxiv_feed(authors=["Alice A", "Bob B"]))

    resource = await fetchers.fetch_arxiv("2401.12345")

    assert resource.title == "An arXiv Preprint"
    assert resource.authors == ["Alice A", "Bob B"]
    assert resource.year == 2024
    assert resource.venue == "J. Ref 2024"
    assert resource.doi == "10.1000/arxiv"
    assert resource.type == "preprint"
    assert resource.abstract == "Preprint abstract."
    assert urls == [f"{fetchers.ARXIV_BASE_URL}?id_list=2401.12345"]


async def test_fetch_arxiv_url_encodes_id(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = patch_http(monkeypatch, _arxiv_feed())

    await fetchers.fetch_arxiv("2401.1&evil=1")

    assert "&evil=1" not in urls[0]
    assert "%26" in urls[0]


async def test_fetch_arxiv_empty_feed_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = FakeResponse(
        200,
        text='<feed xmlns="http://www.w3.org/2005/Atom"></feed>',
    )
    patch_http(monkeypatch, empty)

    with pytest.raises(fetchers.ResourceNotFoundError):
        await fetchers.fetch_arxiv("9999.99999")


async def test_fetch_arxiv_invalid_xml_is_upstream_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_http(monkeypatch, FakeResponse(200, text="<feed><<<"))

    with pytest.raises(fetchers.UpstreamError, match="invalid XML"):
        await fetchers.fetch_arxiv("2401.12345")


async def test_fetch_arxiv_5xx_and_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(500))
    with pytest.raises(fetchers.UpstreamError):
        await fetchers.fetch_arxiv("2401.12345")

    patch_http(monkeypatch, error=httpx.TimeoutException("slow"))
    with pytest.raises(fetchers.UpstreamError, match="timeout"):
        await fetchers.fetch_arxiv("2401.12345")

    patch_http(monkeypatch, error=httpx.ConnectError("dns"))
    with pytest.raises(fetchers.UpstreamError, match="request failed"):
        await fetchers.fetch_arxiv("2401.12345")


async def test_fetch_arxiv_without_title_or_authors(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, _arxiv_feed(title="   "))

    with pytest.raises(fetchers.ResourceNotFoundError, match="no title"):
        await fetchers.fetch_arxiv("2401.12345")

    patch_http(monkeypatch, _arxiv_feed(authors=[]))

    with pytest.raises(fetchers.ResourceNotFoundError, match="no authors"):
        await fetchers.fetch_arxiv("2401.12345")


async def test_fetch_arxiv_optional_fields_default_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_http(monkeypatch, _arxiv_feed(journal_ref=None, doi=None, published=""))

    resource = await fetchers.fetch_arxiv("2401.12345")

    assert resource.venue is None
    assert resource.doi is None
    assert resource.year is None


# ---------------------------------------------------------------------------
# PubMed
# ---------------------------------------------------------------------------

_PUBMED_OK = FakeResponse(
    200,
    {
        "result": {
            "12345": {
                "title": " A PubMed Paper ",
                "authors": [{"name": "Alice A"}, {"name": ""}],
                "pubdate": "2022 Mar",
                "source": " Nature ",
                "volume": " 7 ",
                "issue": " 8 ",
                "pages": " 1-9 ",
                "issn": " 0000-0001 ",
                "elocationid": "doi: 10.1000/pubmed",
            }
        }
    },
)


async def test_fetch_pubmed_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = patch_http(monkeypatch, _PUBMED_OK)

    resource = await fetchers.fetch_pubmed("12345")

    assert resource.title == "A PubMed Paper"
    assert resource.authors == ["Alice A"]  # 空姓名被过滤
    assert resource.year == 2022
    assert resource.venue == "Nature"
    assert (resource.volume, resource.issue, resource.pages) == ("7", "8", "1-9")
    assert resource.issn == "0000-0001"
    assert resource.doi == "10.1000/pubmed"
    assert urls[0].startswith(fetchers.PUBMED_BASE_URL)


async def test_fetch_pubmed_missing_record(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(200, {"result": {}}))

    with pytest.raises(fetchers.ResourceNotFoundError):
        await fetchers.fetch_pubmed("12345")


async def test_fetch_pubmed_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(502))
    with pytest.raises(fetchers.UpstreamError):
        await fetchers.fetch_pubmed("12345")

    patch_http(monkeypatch, FakeResponse(200, json_error=ValueError("bad")))
    with pytest.raises(fetchers.UpstreamError, match="non-JSON"):
        await fetchers.fetch_pubmed("12345")

    patch_http(monkeypatch, error=httpx.TimeoutException("slow"))
    with pytest.raises(fetchers.UpstreamError, match="timeout"):
        await fetchers.fetch_pubmed("12345")


async def test_fetch_pubmed_without_title_or_authors(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(200, {"result": {"1": {"title": "  "}}}))
    with pytest.raises(fetchers.ResourceNotFoundError, match="no title"):
        await fetchers.fetch_pubmed("1")

    patch_http(monkeypatch, FakeResponse(200, {"result": {"1": {"title": "T", "authors": []}}}))
    with pytest.raises(fetchers.ResourceNotFoundError, match="no authors"):
        await fetchers.fetch_pubmed("1")


async def test_fetch_pubmed_elocationid_without_doi_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(
        monkeypatch,
        FakeResponse(
            200,
            {"result": {"1": {"title": "T", "authors": [{"name": "A"}], "elocationid": "e12345"}}},
        ),
    )

    resource = await fetchers.fetch_pubmed("1")

    assert resource.doi is None


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------

_OPENALEX_OK = FakeResponse(
    200,
    {
        "title": " An OpenAlex Paper ",
        "authorships": [{"author": {"display_name": "Alice A"}}, {"author": None}],
        "publication_year": "2023",
        "primary_location": {
            "source": {
                "display_name": "Journal of OpenAlex",
                "host_organization_name": " OpenAlex Press ",
            }
        },
        "biblio": {"volume": " 1 ", "issue": " 2 ", "pages": " 3-4 "},
        "doi": "https://doi.org/10.1000/openalex",
        "abstract_inverted_index": {"an": [0], "abstract": [1]},
    },
)


async def test_fetch_openalex_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = patch_http(monkeypatch, _OPENALEX_OK)

    resource = await fetchers.fetch_openalex("10.1000/openalex")

    assert resource.title == "An OpenAlex Paper"
    assert resource.authors == ["Alice A"]
    assert resource.year == 2023
    assert resource.venue == "Journal of OpenAlex"
    assert resource.publisher == "OpenAlex Press"
    assert (resource.volume, resource.issue, resource.pages) == ("1", "2", "3-4")
    # OpenAlex 返回完整 URL，必须剥掉前缀
    assert resource.doi == "10.1000/openalex"
    assert resource.abstract == "an abstract"
    # DOI 里的 "/" 保留（OpenAlex 的 doi: 前缀路径就长这样）：
    # 编码成 %2F 会被上游当成未知 ID，等于每次 DOI 抓取都 404。
    assert urls == [f"{fetchers.OPENALEX_BASE_URL}/doi:10.1000/openalex"]


async def test_fetch_openalex_accepts_bare_work_id(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = patch_http(monkeypatch, _OPENALEX_OK)

    await fetchers.fetch_openalex("W123456789")

    assert urls == [f"{fetchers.OPENALEX_BASE_URL}/W123456789"]


async def test_fetch_openalex_publisher_falls_back_to_top_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "title": "T",
        "authorships": [{"author": {"display_name": "A"}}],
        "publisher": " Top Level ",
    }
    patch_http(monkeypatch, FakeResponse(200, payload))

    resource = await fetchers.fetch_openalex("W1")

    assert resource.publisher == "Top Level"
    assert resource.venue is None


async def test_fetch_openalex_bad_year_becomes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "title": "T",
        "authorships": [{"author": {"display_name": "A"}}],
        "publication_year": "not-a-year",
    }
    patch_http(monkeypatch, FakeResponse(200, payload))

    assert (await fetchers.fetch_openalex("W1")).year is None


async def test_fetch_openalex_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(404))
    with pytest.raises(fetchers.ResourceNotFoundError):
        await fetchers.fetch_openalex("W1")

    patch_http(monkeypatch, FakeResponse(500))
    with pytest.raises(fetchers.UpstreamError):
        await fetchers.fetch_openalex("W1")

    patch_http(monkeypatch, FakeResponse(200, json_error=ValueError("bad")))
    with pytest.raises(fetchers.UpstreamError, match="non-JSON"):
        await fetchers.fetch_openalex("W1")

    patch_http(monkeypatch, error=httpx.ConnectError("dns"))
    with pytest.raises(fetchers.UpstreamError, match="request failed"):
        await fetchers.fetch_openalex("W1")


async def test_fetch_openalex_without_title_or_authors(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(200, {"title": "  "}))
    with pytest.raises(fetchers.ResourceNotFoundError, match="no title"):
        await fetchers.fetch_openalex("W1")

    patch_http(monkeypatch, FakeResponse(200, {"title": "T", "authorships": []}))
    with pytest.raises(fetchers.ResourceNotFoundError, match="no authors"):
        await fetchers.fetch_openalex("W1")


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------

_S2_OK = FakeResponse(
    200,
    {
        "title": " An S2 Paper ",
        "authors": [{"name": "Alice A"}, {"name": "Bob B"}],
        "year": "2021",
        "venue": " S2 Venue ",
        "abstract": "S2 abstract.",
        "externalIds": {"DOI": " 10.1000/s2 "},
    },
)


async def test_fetch_semantic_scholar_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = patch_http(monkeypatch, _S2_OK)

    resource = await fetchers.fetch_semantic_scholar("DOI:10.1000/s2")

    assert resource.title == "An S2 Paper"
    assert resource.authors == ["Alice A", "Bob B"]
    assert resource.year == 2021
    assert resource.venue == "S2 Venue"
    assert resource.doi == "10.1000/s2"
    assert resource.abstract == "S2 abstract."
    assert urls[0].startswith(fetchers.SEMANTIC_SCHOLAR_BASE_URL)
    assert "fields=title,authors" in urls[0]


async def test_fetch_semantic_scholar_bad_year_becomes_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"title": "T", "authors": [{"name": "A"}], "year": "xx"}
    patch_http(monkeypatch, FakeResponse(200, payload))

    assert (await fetchers.fetch_semantic_scholar("abc")).year is None


async def test_fetch_semantic_scholar_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, FakeResponse(404))
    with pytest.raises(fetchers.ResourceNotFoundError):
        await fetchers.fetch_semantic_scholar("abc")

    patch_http(monkeypatch, FakeResponse(429))
    with pytest.raises(fetchers.UpstreamError):
        await fetchers.fetch_semantic_scholar("abc")

    patch_http(monkeypatch, FakeResponse(200, json_error=ValueError("bad")))
    with pytest.raises(fetchers.UpstreamError, match="non-JSON"):
        await fetchers.fetch_semantic_scholar("abc")

    patch_http(monkeypatch, error=httpx.TimeoutException("slow"))
    with pytest.raises(fetchers.UpstreamError, match="timeout"):
        await fetchers.fetch_semantic_scholar("abc")


async def test_fetch_semantic_scholar_without_title_or_authors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_http(monkeypatch, FakeResponse(200, {"title": "  "}))
    with pytest.raises(fetchers.ResourceNotFoundError, match="no title"):
        await fetchers.fetch_semantic_scholar("abc")

    patch_http(monkeypatch, FakeResponse(200, {"title": "T", "authors": []}))
    with pytest.raises(fetchers.ResourceNotFoundError, match="no authors"):
        await fetchers.fetch_semantic_scholar("abc")
