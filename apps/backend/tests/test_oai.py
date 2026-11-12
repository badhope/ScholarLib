"""OAI-PMH 端点测试：Identify / ListMetadataFormats / ListRecords / GetRecord / 错误分支。

资源通过管理 API 创建（与 test_catalog.py 同一集成路径），
确保租户上下文与应用侧完全一致。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from httpx import AsyncClient

OAI_NS = "{http://www.openarchives.org/OAI/PMH/2.0/}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"

_SAMPLE = {
    "title": "OAI 收割测试论文：同行评审自动化",
    "type": "paper",
    "authors": ["测试作者"],
    "year": 2026,
    "discipline": "computer-science",
    "tags": [],
    "abstract": "用于验证 OAI-PMH 收割端点的测试资源摘要。",
    "keywords": ["OAI-PMH"],
    "language": "zh",
    "publication_status": "published",
    "doi": None,
}


def _error_codes(xml: str) -> list[str]:
    return [e.get("code") for e in ET.fromstring(xml).iter(f"{OAI_NS}error")]


async def _seed_resource_via_api(client: AsyncClient, admin_user: dict) -> int:
    r = await client.post(
        "/api/catalog",
        json=_SAMPLE,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_identify(client: AsyncClient):
    r = await client.get("/oai", params={"verb": "Identify"})
    assert r.status_code == 200
    assert "application/xml" in r.headers["content-type"]
    root = ET.fromstring(r.text)
    assert root.find(f"{OAI_NS}Identify") is not None
    name = root.find(f"{OAI_NS}Identify/{OAI_NS}repositoryName")
    assert name is not None and "Rubbish" in name.text


async def test_list_metadata_formats(client: AsyncClient):
    r = await client.get("/oai", params={"verb": "ListMetadataFormats"})
    assert r.status_code == 200
    root = ET.fromstring(r.text)
    prefixes = [e.text for e in root.iter(f"{OAI_NS}metadataPrefix")]
    assert prefixes == ["oai_dc"]


async def test_list_records_returns_published_resources(client: AsyncClient, admin_user: dict):
    rid = await _seed_resource_via_api(client, admin_user)
    r = await client.get("/oai", params={"verb": "ListRecords", "metadataPrefix": "oai_dc"})
    assert r.status_code == 200
    root = ET.fromstring(r.text)
    records = list(root.iter(f"{OAI_NS}record"))
    assert len(records) >= 1
    identifiers = [e.text for e in root.iter(f"{OAI_NS}identifier")]
    assert f"oai:rubbish.argjiemi.cn:resource/{rid}" in identifiers
    titles = [e.text for e in root.iter(f"{DC_NS}title")]
    assert any(t and "OAI 收割测试" in t for t in titles)


async def test_get_record_existing(client: AsyncClient, admin_user: dict):
    rid = await _seed_resource_via_api(client, admin_user)
    r = await client.get(
        "/oai",
        params={
            "verb": "GetRecord",
            "metadataPrefix": "oai_dc",
            "identifier": f"oai:rubbish.argjiemi.cn:resource/{rid}",
        },
    )
    assert r.status_code == 200
    root = ET.fromstring(r.text)
    assert root.find(f"{OAI_NS}GetRecord/{OAI_NS}record") is not None


async def test_get_record_missing_id(client: AsyncClient):
    r = await client.get(
        "/oai",
        params={
            "verb": "GetRecord",
            "metadataPrefix": "oai_dc",
            "identifier": "oai:rubbish.argjiemi.cn:resource/999999",
        },
    )
    assert r.status_code == 200  # OAI 错误也是 200 + error 元素
    assert _error_codes(r.text) == ["idDoesNotExist"]


async def test_bad_verb(client: AsyncClient):
    r = await client.get("/oai", params={"verb": "Hack"})
    assert _error_codes(r.text) == ["badVerb"]


async def test_illegal_extra_argument(client: AsyncClient):
    r = await client.get("/oai", params={"verb": "Identify", "evil": "1"})
    assert _error_codes(r.text) == ["badArgument"]


async def test_list_records_requires_oai_dc(client: AsyncClient):
    r = await client.get("/oai", params={"verb": "ListRecords", "metadataPrefix": "marc"})
    assert _error_codes(r.text) == ["badArgument"]


async def test_list_records_excludes_drafts(client: AsyncClient, admin_user: dict):
    """收割端点是公开面，未发表记录不得流出。"""
    published = await _seed_resource_via_api(client, admin_user)
    draft_payload = {
        **_SAMPLE,
        "title": "OAI 草稿不应被收割",
        "publication_status": "draft",
    }
    r = await client.post(
        "/api/catalog",
        json=draft_payload,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert r.status_code == 201, r.text
    draft = r.json()["id"]

    listing = await client.get("/oai", params={"verb": "ListRecords", "metadataPrefix": "oai_dc"})
    identifiers = [e.text for e in ET.fromstring(listing.text).iter(f"{OAI_NS}identifier")]
    assert f"oai:rubbish.argjiemi.cn:resource/{published}" in identifiers
    assert f"oai:rubbish.argjiemi.cn:resource/{draft}" not in identifiers

    single = await client.get(
        "/oai",
        params={
            "verb": "GetRecord",
            "metadataPrefix": "oai_dc",
            "identifier": f"oai:rubbish.argjiemi.cn:resource/{draft}",
        },
    )
    assert _error_codes(single.text) == ["idDoesNotExist"]


async def test_list_records_rejects_bad_dates(client: AsyncClient):
    r = await client.get(
        "/oai",
        params={"verb": "ListRecords", "metadataPrefix": "oai_dc", "from": "2026-13-45"},
    )
    assert _error_codes(r.text) == ["badArgument"]


async def test_list_records_from_until_window(client: AsyncClient, admin_user: dict):
    rid = await _seed_resource_via_api(client, admin_user)
    # Window that starts in the future excludes everything.
    future = await client.get(
        "/oai",
        params={
            "verb": "ListRecords",
            "metadataPrefix": "oai_dc",
            "from": "2099-01-01",
        },
    )
    ids = [e.text for e in ET.fromstring(future.text).iter(f"{OAI_NS}identifier")]
    assert f"oai:rubbish.argjiemi.cn:resource/{rid}" not in ids

    # Wide window includes it.
    wide = await client.get(
        "/oai",
        params={
            "verb": "ListRecords",
            "metadataPrefix": "oai_dc",
            "from": "2026-01-01",
            "until": "2099-12-31",
        },
    )
    ids = [e.text for e in ET.fromstring(wide.text).iter(f"{OAI_NS}identifier")]
    assert f"oai:rubbish.argjiemi.cn:resource/{rid}" in ids


async def test_record_includes_language_and_rights(client: AsyncClient, admin_user: dict):
    rid = await _seed_resource_via_api(client, admin_user)
    r = await client.get(
        "/oai",
        params={
            "verb": "GetRecord",
            "metadataPrefix": "oai_dc",
            "identifier": f"oai:rubbish.argjiemi.cn:resource/{rid}",
        },
    )
    languages = [e.text for e in ET.fromstring(r.text).iter(f"{DC_NS}language")]
    rights = [e.text for e in ET.fromstring(r.text).iter(f"{DC_NS}rights")]
    assert languages == ["zh"]
    assert rights == ["CC BY 4.0"]


async def test_rss_feed_serves_published_only(client: AsyncClient, admin_user: dict) -> None:
    """RSS 2.0 feed：只有已刊出内容，字段完整且转义。"""
    from conftest import auth_headers

    await client.post(
        "/api/catalog",
        json={
            "type": "paper",
            "title": "RSS 测试论文 <script>",
            "authors": ["RSS 作者"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "用于验证 RSS feed 的摘要内容。",
            "publication_status": "published",
        },
        headers=auth_headers(admin_user),
    )
    r = await client.get("/feed.xml")
    assert r.status_code == 200
    assert "application/rss+xml" in r.headers["content-type"]
    body = r.text
    assert '<rss version="2.0"' in body
    assert "RSS 测试论文" in body
    assert "<script>" not in body  # 标题已转义
    assert "&lt;script&gt;" in body
    assert "<pubDate>" in body


async def test_rss_alias_path(client: AsyncClient) -> None:
    assert (await client.get("/rss.xml")).status_code == 200


async def test_rss_excludes_drafts(client: AsyncClient, admin_user: dict) -> None:
    from conftest import auth_headers

    await client.post(
        "/api/catalog",
        json={
            "type": "paper",
            "title": "RSS 草稿不应出现",
            "authors": ["作者"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "草稿摘要。",
            "publication_status": "draft",
        },
        headers=auth_headers(admin_user),
    )
    assert "RSS 草稿不应出现" not in (await client.get("/feed.xml")).text


async def test_list_sets(client: AsyncClient):
    r = await client.get("/oai", params={"verb": "ListSets"})
    assert r.status_code == 200
    root = ET.fromstring(r.text)
    specs = [e.text for e in root.iter(f"{OAI_NS}setSpec")]
    assert specs == ["all"]


async def test_list_identifiers_returns_headers_without_metadata(
    client: AsyncClient, admin_user: dict
):
    rid = await _seed_resource_via_api(client, admin_user)
    r = await client.get("/oai", params={"verb": "ListIdentifiers", "metadataPrefix": "oai_dc"})
    assert r.status_code == 200
    root = ET.fromstring(r.text)
    identifiers = [e.text for e in root.iter(f"{OAI_NS}identifier")]
    assert f"oai:rubbish.argjiemi.cn:resource/{rid}" in identifiers
    assert root.find(f"{OAI_NS}ListIdentifiers") is not None
    assert not list(root.iter(f"{DC_NS}title"))


async def test_list_records_no_match_returns_error(client: AsyncClient):
    r = await client.get(
        "/oai",
        params={
            "verb": "ListRecords",
            "metadataPrefix": "oai_dc",
            "from": "2099-01-01",
        },
    )
    assert _error_codes(r.text) == ["noRecordsMatch"]
