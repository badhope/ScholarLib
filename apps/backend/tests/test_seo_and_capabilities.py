"""Crawler surface (robots/sitemap/head metadata) + capability probe tests."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from httpx import AsyncClient

from app.api.seo import build_index_html
from app.core import email as email_module
from app.core.config import settings

_SAMPLE = {
    "type": "paper",
    "title": "SEO 可见论文 <script>alert(1)</script>",
    "authors": ["张三", "Li Si"],
    "year": 2026,
    "venue": "Rubbish",
    "discipline": "computer-science",
    "tags": ["seo"],
    "abstract": "一篇用于验证 sitemap 与 citation 标签的摘要。",
    "language": "zh",
    "publication_status": "published",
}


async def _create(client: AsyncClient, admin_user: dict, **overrides: object) -> int:
    payload = {**_SAMPLE, **overrides}
    r = await client.post(
        "/api/catalog", json=payload, headers={"Authorization": f"Bearer {admin_user['token']}"}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_robots_advertises_sitemap(client: AsyncClient) -> None:
    r = await client.get("/robots.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "Sitemap:" in r.text
    assert "/sitemap.xml" in r.text
    assert "Disallow: /api/" in r.text


async def test_sitemap_lists_only_published(client: AsyncClient, admin_user: dict) -> None:
    published = await _create(client, admin_user)
    draft = await _create(client, admin_user, title="草稿不可见", publication_status="draft")

    r = await client.get("/sitemap.xml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    root = ET.fromstring(r.text)
    locs = [e.text for e in root.iter() if e.tag.endswith("loc")]
    assert any(str(published) in loc for loc in locs)
    assert not any(str(draft) in loc for loc in locs)


async def test_head_metadata_carries_citation_tags(
    client: AsyncClient, admin_user: dict, db_session
) -> None:
    rid = await _create(client, admin_user)
    index_html = "<html><head><title>Rubbish — 开放获取期刊</title></head><body></body></html>"
    request = _FakeRequest()

    body, status = await build_index_html(index_html, f"catalog/{rid}", request, db_session)
    assert status == "200"
    assert 'name="citation_title"' in body
    assert 'name="citation_author"' in body
    assert 'name="citation_pdf_url"' in body
    assert "<title>SEO 可见论文 &lt;script&gt;alert(1)&lt;/script&gt; — Rubbish</title>" in body
    # Escaped, never raw: a title must not be able to close the tag.
    assert "<script>alert(1)</script>" not in body


async def test_head_metadata_noindex_for_draft(
    client: AsyncClient, admin_user: dict, db_session
) -> None:
    rid = await _create(client, admin_user, title="草稿标题", publication_status="draft")
    index_html = "<html><head><title>Rubbish — 开放获取期刊</title></head><body></body></html>"
    body, _ = await build_index_html(index_html, f"catalog/{rid}", _FakeRequest(), db_session)
    assert 'name="robots" content="noindex"' in body
    assert 'name="citation_title"' not in body


async def test_capabilities_reports_console_email(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "email_backend", "console")
    email_module.reset_email_sender()
    r = await client.get("/api/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["email_delivery"] is False
    assert body["email_backend"] == "console"
    assert body["registration_open"] is True


async def test_capabilities_reports_smtp_email(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(settings, "email_smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "email_from_address", "no-reply@example.com")
    email_module.reset_email_sender()
    monkeypatch.setattr(
        email_module,
        "_sender",
        email_module.SMTPEmailSender(
            host="smtp.example.com",
            port=587,
            username="",
            password="",
            from_addr="no-reply@example.com",
        ),
    )
    body = (await client.get("/api/capabilities")).json()
    assert body["email_delivery"] is True
    email_module.reset_email_sender()


class _FakeRequest:
    """Minimal Request stand-in: only base_url is consulted by the builder."""

    base_url = "https://rubbish.argjiemi.cn/"

    @property
    def url(self):  # type: ignore[no-untyped-def]
        class _Url:
            path = "/"
            query = ""

        return _Url()


async def test_robots_allows_ai_crawlers(client: AsyncClient) -> None:
    r = await client.get("/robots.txt")
    assert r.status_code == 200
    for bot in ("GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended"):
        assert f"User-agent: {bot}" in r.text
    assert "/llms.txt" in r.text


async def test_sitemap_has_lastmod(client: AsyncClient, admin_user: dict) -> None:
    await _create(client, admin_user)
    root = ET.fromstring((await client.get("/sitemap.xml")).text)
    assert any(e.tag.endswith("lastmod") for e in root.iter())


async def test_llms_txt_lists_public_entries(client: AsyncClient, admin_user: dict) -> None:
    rid = await _create(client, admin_user)
    r = await client.get("/llms.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert f"/catalog/{rid}" in r.text
