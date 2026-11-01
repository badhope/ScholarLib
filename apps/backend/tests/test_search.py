"""Tests for the optional Meilisearch full-text search integration.

Contract (mirrors the Sentry monitoring tests): search is opt-in and
fail-open. Every failure mode — no URL / SDK missing / server error —
must degrade to the built-in DB search without raising, and index-sync
failures must never block the write path.
"""

from __future__ import annotations

import builtins
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import auth_headers
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import search as fulltext
from app.core.config import settings
from app.models import Tenant
from app.modules.catalog.models import Resource


@pytest.fixture(autouse=True)
def _reset_search_state() -> Any:
    fulltext.reset_for_tests()
    yield
    fulltext.reset_for_tests()


# ---------------------------------------------------------------------------
# Unit: enable/disable + degradation
# ---------------------------------------------------------------------------


async def test_disabled_when_url_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """No URL configured → feature off, all calls are silent no-ops."""
    monkeypatch.setattr(settings, "meilisearch_url", "", raising=False)
    assert fulltext.search_enabled() is False
    assert await fulltext.search_resource_ids(tenant_id=1, q="x") is None
    # index/unindex must be harmless no-ops
    await fulltext.index_resource(SimpleNamespace(id=1))
    await fulltext.unindex_resource(1)


async def test_sdk_missing_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """URL set but SDK not installed → warn once, then permanent fallback."""
    monkeypatch.setattr(settings, "meilisearch_url", "http://localhost:7700", raising=False)
    monkeypatch.delitem(sys.modules, "meilisearch_python_sdk", raising=False)

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "meilisearch_python_sdk":
            raise ImportError("No module named 'meilisearch_python_sdk'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert await fulltext.search_resource_ids(tenant_id=1, q="x") is None
    # 第二次调用不应再尝试 import（_init_failed 缓存）
    assert await fulltext.search_resource_ids(tenant_id=1, q="x") is None


async def test_search_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A server-side search failure → None (caller falls back to DB)."""
    monkeypatch.setattr(settings, "meilisearch_url", "http://localhost:7700", raising=False)

    class FakeIndex:
        async def search(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("meilisearch down")

    async def fake_get_client() -> Any:
        return SimpleNamespace(index=lambda _n: FakeIndex())

    monkeypatch.setattr(fulltext, "_get_client", fake_get_client)
    assert await fulltext.search_resource_ids(tenant_id=1, q="x") is None


async def test_index_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Index-sync failure must not break the resource write path."""
    monkeypatch.setattr(settings, "meilisearch_url", "http://localhost:7700", raising=False)

    class FakeIndex:
        async def add_documents(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("boom")

        async def delete_document(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("boom")

    async def fake_get_client() -> Any:
        return SimpleNamespace(index=lambda _n: FakeIndex())

    monkeypatch.setattr(fulltext, "_get_client", fake_get_client)
    await fulltext.index_resource(
        SimpleNamespace(
            id=1,
            tenant_id=1,
            title="t",
            abstract=None,
            authors=None,
            keywords=None,
            tags=None,
            type="paper",
            discipline="cs",
            year=2024,
        )
    )
    await fulltext.unindex_resource(1)


async def test_search_builds_tenant_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: tenant/type filters are forwarded; ranked ids returned."""
    monkeypatch.setattr(settings, "meilisearch_url", "http://localhost:7700", raising=False)
    captured: dict[str, Any] = {}

    class FakeIndex:
        async def search(self, q: str, **kwargs: Any) -> Any:
            captured["q"] = q
            captured.update(kwargs)
            return SimpleNamespace(hits=[{"id": 7}, {"id": 3}], estimated_total_hits=2)

    async def fake_get_client() -> Any:
        return SimpleNamespace(index=lambda _n: FakeIndex())

    monkeypatch.setattr(fulltext, "_get_client", fake_get_client)
    result = await fulltext.search_resource_ids(
        tenant_id=42, q="graph", type_="paper", page=2, page_size=10
    )
    assert result == ([7, 3], 2)
    assert captured["q"] == "graph"
    # UUID/数字租户都要按字面量加引号，否则 Meilisearch 解析失败会静默
    # 退化成 DB ILIKE（全文搜索功能形同虚设）。
    assert 'tenant_id = "42"' in captured["filter"]
    assert 'type = "paper"' in captured["filter"]
    assert captured["offset"] == 10  # (page-1) * page_size
    assert captured["limit"] == 10


# ---------------------------------------------------------------------------
# Integration: catalog route uses ranked ids and preserves relevance order
# ---------------------------------------------------------------------------


async def test_catalog_route_uses_search_ranking(
    client: AsyncClient, admin_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When search returns ranked ids, the route re-fetches rows from the
    DB in that order and drops ghost ids that no longer exist."""
    created: list[int] = []
    for i in range(2):
        resp = await client.post(
            "/api/catalog",
            json={
                "title": f"Search Ranking Test {i}",
                "type": "paper",
                "authors": ["A"],
                "year": 2024,
                "discipline": "computer science",
                "tags": [],
                "abstract": "ranking abstract",
            },
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 201
        created.append(resp.json()["id"])

    monkeypatch.setattr(settings, "meilisearch_url", "http://localhost:7700", raising=False)

    async def fake_search(**_kwargs: Any) -> tuple[list[int], int]:
        # 倒序返回 + 一个不存在的幽灵 id
        return [created[1], created[0], 999_999], 3

    monkeypatch.setattr(fulltext, "search_resource_ids", fake_search)
    resp = await client.get("/api/catalog?q=ranking")
    assert resp.status_code == 200
    body = resp.json()
    ids = [r["id"] for r in body["data"]]
    assert ids == [created[1], created[0]]  # 相关性顺序保留，幽灵 id 被丢弃
    assert body["meta"]["total"] == 3


async def test_catalog_route_falls_back_to_db(
    client: AsyncClient, admin_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Search unavailable (returns None) → the DB ILIKE path still works."""
    resp = await client.post(
        "/api/catalog",
        json={
            "title": "Fallback Unique Zebra",
            "type": "paper",
            "authors": ["A"],
            "year": 2024,
            "discipline": "computer science",
            "tags": [],
            "abstract": "abstract",
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201

    monkeypatch.setattr(settings, "meilisearch_url", "http://localhost:7700", raising=False)

    async def fake_search(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(fulltext, "search_resource_ids", fake_search)
    resp = await client.get("/api/catalog?q=Zebra")
    assert resp.status_code == 200
    titles = [r["title"] for r in resp.json()["data"]]
    assert "Fallback Unique Zebra" in titles


@pytest.mark.parametrize("search_unavailable", [False, True])
async def test_db_author_search_respects_visibility_and_tenant(
    client: AsyncClient,
    admin_user: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    search_unavailable: bool,
) -> None:
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()
    other = Tenant(slug="other", name="Other")
    db_session.add(other)
    await db_session.flush()
    resources = []
    for tenant_id, state, publish_at in (
        (tenant.id, "published", None),
        (tenant.id, "draft", None),
        (tenant.id, "published", datetime.now(UTC) + timedelta(days=1)),
        (other.id, "published", None),
    ):
        resource = Resource(
            tenant_id=tenant_id,
            title="Unrelated title",
            authors=["Someone Else", "Alice Wonderland"],
            type="paper",
            year=2024,
            discipline="physics",
            tags=[],
            abstract="Unrelated abstract",
            preview="",
            publication_status=state,
            publish_at=publish_at,
        )
        db_session.add(resource)
        resources.append(resource)
    await db_session.commit()

    monkeypatch.setattr(
        settings, "meilisearch_url", "http://localhost:7700" if search_unavailable else ""
    )

    async def fake_search(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(fulltext, "search_resource_ids", fake_search)
    response = await client.get("/api/catalog", params={"q": "wonder"})
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["data"]] == [resources[0].id]
    assert response.json()["meta"]["total"] == 1
    sorted_response = await client.get("/api/catalog", params={"q": "wonder", "sort": "issue"})
    assert sorted_response.status_code == 200
    assert [row["id"] for row in sorted_response.json()["data"]] == [resources[0].id]

    response = await client.get(
        "/api/catalog", params={"q": "wonder"}, headers=auth_headers(admin_user)
    )
    assert response.status_code == 200
    assert {row["id"] for row in response.json()["data"]} == {r.id for r in resources[:3]}
    assert response.json()["meta"]["total"] == 3
