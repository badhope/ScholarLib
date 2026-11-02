"""Catalog module edge paths: conflicts, filters/facets, file Range downloads."""

from __future__ import annotations

import pytest
from conftest import auth_headers
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError

from app.modules.catalog.routes import _conflict_detail


def _conflict(message: str) -> IntegrityError:
    return IntegrityError("INSERT", {}, Exception(message))


def test_conflict_detail_names_doi() -> None:
    assert "DOI" in _conflict_detail(_conflict("UNIQUE constraint failed: resources.doi"))


def test_conflict_detail_names_slug() -> None:
    assert "Slug" in _conflict_detail(_conflict("UNIQUE constraint failed: resources.slug"))


def test_conflict_detail_generic_fallback() -> None:
    assert (
        "conflicts"
        in _conflict_detail(_conflict("UNIQUE constraint failed: resources.year")).lower()
    )


def _resource_payload(slug: str, **overrides: object) -> dict:
    payload: dict = {
        "type": "paper",
        "title": "Edge Case Paper",
        "authors": ["边界作者"],
        "year": 2026,
        "discipline": "计算机科学",
        "abstract": "用于验证目录边界行为的摘要。",
        "slug": slug,
        "tags": ["边界"],
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_create_duplicate_slug_conflict(client: AsyncClient, admin_user: dict) -> None:
    headers = auth_headers(admin_user)
    first = await client.post("/api/catalog", json=_resource_payload("dup-slug"), headers=headers)
    assert first.status_code == 201

    again = await client.post(
        "/api/catalog", json=_resource_payload("dup-slug", title="Another"), headers=headers
    )
    assert again.status_code == 409
    assert "Slug" in again.json()["detail"]


@pytest.mark.asyncio
async def test_create_duplicate_doi_conflict(client: AsyncClient, admin_user: dict) -> None:
    headers = auth_headers(admin_user)
    first = await client.post(
        "/api/catalog", json=_resource_payload("doi-a", doi="10.9999/edge.1"), headers=headers
    )
    assert first.status_code == 201

    again = await client.post(
        "/api/catalog", json=_resource_payload("doi-b", doi="10.9999/edge.1"), headers=headers
    )
    assert again.status_code == 409
    assert "DOI" in again.json()["detail"]


@pytest.mark.asyncio
async def test_patch_conflict_returns_409(client: AsyncClient, admin_user: dict) -> None:
    headers = auth_headers(admin_user)
    first = await client.post(
        "/api/catalog", json=_resource_payload("patch-a", doi="10.9999/edge.2"), headers=headers
    )
    second = await client.post(
        "/api/catalog", json=_resource_payload("patch-b", doi="10.9999/edge.3"), headers=headers
    )
    assert first.status_code == 201 and second.status_code == 201

    clash = await client.patch(
        f"/api/catalog/{second.json()['id']}",
        json={"doi": "10.9999/edge.2"},
        headers=headers,
    )
    assert clash.status_code == 409


@pytest.mark.asyncio
async def test_list_filters_by_type_year_discipline_and_query(
    client: AsyncClient, admin_user: dict
) -> None:
    headers = auth_headers(admin_user)
    r1 = await client.post(
        "/api/catalog",
        json=_resource_payload("filter-1", year=2025, tags=["筛选"]),
        headers=headers,
    )
    r2 = await client.post(
        "/api/catalog",
        json=_resource_payload("filter-2", year=2026, type="dataset"),
        headers=headers,
    )
    assert r1.status_code == 201 and r2.status_code == 201

    by_year = await client.get("/api/catalog", params={"year": 2025})
    titles = [item["title"] for item in by_year.json()["data"]]
    assert any(t == "Edge Case Paper" for t in titles)

    by_type = await client.get("/api/catalog", params={"type": "dataset"})
    assert all(item["type"] == "dataset" for item in by_type.json()["data"])

    by_discipline = await client.get("/api/catalog", params={"discipline": "计算机科学"})
    assert len(by_discipline.json()["data"]) >= 1

    by_query = await client.get("/api/catalog", params={"q": "Edge Case"})
    assert len(by_query.json()["data"]) >= 1

    nothing = await client.get("/api/catalog", params={"q": "不存在的搜索词xyz"})
    assert nothing.json()["data"] == []


@pytest.mark.asyncio
async def test_facets_respect_type_and_discipline_filters(
    client: AsyncClient, admin_user: dict
) -> None:
    headers = auth_headers(admin_user)
    rows = (
        ("facet-1", 2025, "paper", ["甲"]),
        ("facet-2", 2026, "dataset", ["乙"]),
    )
    for slug, year, rtype, tags in rows:
        r = await client.post(
            "/api/catalog",
            json=_resource_payload(slug, year=year, type=rtype, tags=tags),
            headers=headers,
        )
        assert r.status_code == 201

    facets = await client.get("/api/catalog/facets", params={"type": "dataset"})
    assert facets.status_code == 200
    # Only the dataset-tagged facet-2 row falls inside the filter.
    tags = [b["value"] for b in facets.json()["tags"]]
    assert "乙" in tags and "甲" not in tags


async def _publish_paper_with_file(client: AsyncClient, test_user: dict, admin_user: dict) -> int:
    token = test_user["token"]
    created = await client.post(
        "/api/submissions",
        json={
            "title": "Range Download Paper",
            "type": "paper",
            "authors": ["下载作者"],
            "year": 2026,
            "discipline": "计算机科学",
            "abstract": "用于验证目录文件下载的 Range 行为。",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    sid = created.json()["id"]
    up = await client.post(
        f"/api/submissions/{sid}/files",
        files={"file": ("paper.pdf", b"%PDF-1.4 range test body", "application/pdf")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert up.status_code == 200
    # 录用要求至少一份已完成的审稿意见（no_completed_reviews）。
    from conftest import complete_one_review

    await complete_one_review(client, admin_user, sid)
    decision = await client.patch(
        f"/api/submissions/{sid}/decision",
        json={"decision": "accept"},
        headers=auth_headers(admin_user),
    )
    assert decision.status_code == 200
    return decision.json()["resource_id"]


@pytest.mark.asyncio
async def test_catalog_file_range_and_fallback(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    rid = await _publish_paper_with_file(client, test_user, admin_user)

    partial = await client.get(f"/api/catalog/{rid}/file", headers={"Range": "bytes=0-4"})
    assert partial.status_code == 206
    assert partial.headers["Content-Range"].startswith("bytes 0-4/")
    assert partial.content == b"%PDF-"

    invalid = await client.get(f"/api/catalog/{rid}/file", headers={"Range": "bytes=5000-6000"})
    assert invalid.status_code == 200
    assert b"range test body" in invalid.content


@pytest.mark.asyncio
async def test_catalog_file_presigned_redirect_and_missing(
    client: AsyncClient,
    test_user: dict,
    admin_user: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.storage import get_storage

    rid = await _publish_paper_with_file(client, test_user, admin_user)

    monkeypatch.setattr(
        get_storage(), "presigned_url", lambda path: f"https://s3.example.com/{path}"
    )
    redirect = await client.get(f"/api/catalog/{rid}/file")
    assert redirect.status_code == 302
    assert redirect.headers["location"].startswith("https://s3.example.com/")

    monkeypatch.undo()
    monkeypatch.setattr(
        get_storage(),
        "load",
        _raise_missing,
    )
    missing = await client.get(f"/api/catalog/{rid}/file")
    assert missing.status_code == 404


async def _raise_missing(path: str) -> bytes:
    raise FileNotFoundError(path)
