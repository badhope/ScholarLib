"""Tests for the DOI module (DataCite adapter + routes).

Covers two layers:

1. ``doi.registration`` — the DataCite HTTP adapter. Every failure mode
   (4xx / timeout / connection error) must degrade to ``"failed"`` and
   never raise, because DOI registration sits on the write path and a
   DataCite outage must not block cataloguing.
2. ``doi.routes`` — the 501 / 404 / 409 / success branches and the
   append-only audit row.

HTTP is faked at the ``httpx.AsyncClient`` level so no real request
ever leaves the test process.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.catalog.models import Resource
from app.domain.doi import registration
from app.domain.doi.models import DOIRegistration

_SAMPLE = {
    "type": "paper",
    "title": "DOI Test Paper",
    "authors": ["Alice Author"],
    "year": 2024,
    "discipline": "computer-science",
    "abstract": "Abstract used for DataCite metadata.",
    "tags": ["doi", "test"],
}


class FakeResponse:
    """Minimal stand-in for ``httpx.Response``."""

    def __init__(self, status_code: int = 201, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or str(self._payload)

    def json(self) -> Any:
        return self._payload


class FakeAsyncClient:
    """Records calls and replays a scripted list of responses / exceptions."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def _next(self, method: str, url: str) -> FakeResponse:
        self.calls.append((method, url))
        item = self.script.pop(0) if self.script else FakeResponse(201)
        if isinstance(item, BaseException):
            raise item
        return item

    async def post(self, url: str, **_kw: Any) -> FakeResponse:
        return await self._next("POST", url)

    async def put(self, url: str, **_kw: Any) -> FakeResponse:
        return await self._next("PUT", url)

    async def get(self, url: str, **_kw: Any) -> FakeResponse:
        return await self._next("GET", url)


def patch_http(monkeypatch: pytest.MonkeyPatch, script: list[Any]) -> list[FakeAsyncClient]:
    """Swap ``httpx.AsyncClient`` for a scripted fake; return the created clients."""
    created: list[FakeAsyncClient] = []

    def factory(*_args: Any, **_kwargs: Any) -> FakeAsyncClient:
        client = FakeAsyncClient(script)
        created.append(client)
        return client

    monkeypatch.setattr(registration.httpx, "AsyncClient", factory)
    return created


def enable_datacite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "datacite_api_url", "https://api.test.datacite.org")
    monkeypatch.setattr(settings, "datacite_prefix", "10.5072")
    monkeypatch.setattr(settings, "datacite_api_key", "dXNlcjpwYXNz")


class FakeResource:
    """Duck-typed stand-in for the ``Resource`` ORM object."""

    def __init__(self, **kwargs: Any) -> None:
        self.id = kwargs.get("id", 1)
        self.title = kwargs.get("title", "A Title")
        self.authors = kwargs.get("authors", ["Alice Author"])
        self.publisher = kwargs.get("publisher", None)
        self.year = kwargs.get("year", 2024)
        self.type = kwargs.get("type", "paper")
        self.abstract = kwargs.get("abstract", "An abstract.")
        self.tags = kwargs.get("tags", ["one", "two"])


# ---------------------------------------------------------------------------
# registration: pure helpers
# ---------------------------------------------------------------------------


def test_datacite_enabled_requires_both_url_and_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "datacite_api_url", "")
    monkeypatch.setattr(settings, "datacite_prefix", "10.5072")
    assert registration.datacite_enabled() is False

    monkeypatch.setattr(settings, "datacite_api_url", "https://api.test.datacite.org")
    monkeypatch.setattr(settings, "datacite_prefix", "")
    assert registration.datacite_enabled() is False

    monkeypatch.setattr(settings, "datacite_prefix", "10.5072")
    assert registration.datacite_enabled() is True


def test_build_doi_joins_prefix_and_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    enable_datacite(monkeypatch)
    assert registration._build_doi("abc-123") == "10.5072/abc-123"


def test_build_datacite_metadata_handles_dict_and_string_authors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_datacite(monkeypatch)
    resource = FakeResource(
        authors=[{"name": "Alice A", "given_name": "Alice", "family_name": "A"}, "Bob B"]
    )

    payload = registration._build_datacite_metadata(resource, "10.5072/1")
    attrs = payload["data"]["attributes"]

    assert attrs["creators"][0] == {
        "name": "Alice A",
        "nameType": "Personal",
        "givenName": "Alice",
        "familyName": "A",
    }
    # 字符串作者没有 given/family，只保留 name
    assert attrs["creators"][1] == {"name": "Bob B", "nameType": "Personal"}
    assert attrs["titles"] == [{"title": "A Title"}]
    assert attrs["url"] == "https://doi.org/10.5072/1"


def test_build_datacite_metadata_defaults_and_omits_missing_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_datacite(monkeypatch)
    resource = FakeResource(publisher=None, year=None, type=None, abstract=None, tags=None)

    attrs = registration._build_datacite_metadata(resource, "10.5072/1")["data"]["attributes"]

    assert attrs["publisher"] == "Rubbish"
    assert attrs["publicationYear"] == "2026"
    assert attrs["types"]["resourceType"] == "JournalArticle"
    assert attrs["descriptions"] == []
    assert attrs["subjects"] == []


def test_build_datacite_metadata_caps_subjects_at_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    enable_datacite(monkeypatch)
    resource = FakeResource(tags=[f"t{i}" for i in range(25)])

    attrs = registration._build_datacite_metadata(resource, "10.5072/1")["data"]["attributes"]

    assert len(attrs["subjects"]) == 10


# ---------------------------------------------------------------------------
# registration: mint_doi
# ---------------------------------------------------------------------------


async def test_mint_doi_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "datacite_api_url", "")
    monkeypatch.setattr(settings, "datacite_prefix", "")
    clients = patch_http(monkeypatch, [])

    doi, state = await registration.mint_doi(FakeResource())

    assert (doi, state) == ("", "failed")
    assert clients == []  # 连 HTTP 客户端都不该创建


async def test_mint_doi_success(monkeypatch: pytest.MonkeyPatch) -> None:
    enable_datacite(monkeypatch)
    clients = patch_http(monkeypatch, [FakeResponse(201), FakeResponse(200)])

    doi, state = await registration.mint_doi(FakeResource(id=42))

    assert doi == "10.5072/42"
    assert state == "completed"
    assert [c for c in clients[0].calls] == [
        ("POST", f"{registration.DATACITE_API_URL}/dois"),
        ("PUT", f"{registration.DATACITE_API_URL}/dois/10.5072/42"),
    ]


async def test_mint_doi_uses_explicit_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    enable_datacite(monkeypatch)
    clients = patch_http(monkeypatch, [FakeResponse(201), FakeResponse(200)])

    doi, _state = await registration.mint_doi(FakeResource(id=42), suffix="custom-slug")

    assert doi == "10.5072/custom-slug"
    assert clients[0].calls[1] == (
        "PUT",
        f"{registration.DATACITE_API_URL}/dois/10.5072/custom-slug",
    )


async def test_mint_doi_metadata_rejected_does_not_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_datacite(monkeypatch)
    clients = patch_http(monkeypatch, [FakeResponse(422, text="validation error")])

    doi, state = await registration.mint_doi(FakeResource(id=7))

    assert (doi, state) == ("10.5072/7", "failed")
    # 元数据都没写进去，不能继续注册 DOI
    assert [m for m, _ in clients[0].calls] == ["POST"]


async def test_mint_doi_register_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    enable_datacite(monkeypatch)
    clients = patch_http(monkeypatch, [FakeResponse(201), FakeResponse(403, text="forbidden")])

    doi, state = await registration.mint_doi(FakeResource(id=7))

    assert (doi, state) == ("10.5072/7", "failed")
    assert len(clients[0].calls) == 2


async def test_mint_doi_timeout_degrades_to_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    enable_datacite(monkeypatch)
    patch_http(monkeypatch, [httpx.TimeoutException("too slow")])

    doi, state = await registration.mint_doi(FakeResource(id=7))

    assert (doi, state) == ("10.5072/7", "failed")


async def test_mint_doi_request_error_degrades_to_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    enable_datacite(monkeypatch)
    patch_http(monkeypatch, [httpx.ConnectError("no route to host")])

    doi, state = await registration.mint_doi(FakeResource(id=7))

    assert (doi, state) == ("10.5072/7", "failed")


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


async def _create_resource(client: AsyncClient, admin_user: dict, **overrides: Any) -> dict:
    payload = {**_SAMPLE, **overrides}
    response = await client.post(
        "/api/catalog",
        json=payload,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    response.raise_for_status()
    return response.json()


async def test_register_501_when_not_configured(
    client: AsyncClient, admin_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "datacite_api_url", "")
    monkeypatch.setattr(settings, "datacite_prefix", "")
    resource = await _create_resource(client, admin_user)

    response = await client.post(
        "/api/doi/register",
        json={"resource_id": resource["id"]},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 501
    assert "not configured" in response.json()["detail"]


async def test_register_requires_admin(client: AsyncClient, test_user: dict) -> None:
    response = await client.post(
        "/api/doi/register",
        json={"resource_id": 1},
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )

    assert response.status_code == 403


async def test_register_404_for_unknown_resource(
    client: AsyncClient, admin_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_datacite(monkeypatch)

    response = await client.post(
        "/api/doi/register",
        json={"resource_id": 999_999},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 404
    assert "999999" in response.json()["detail"]


async def test_register_conflict_when_resource_already_has_doi(
    client: AsyncClient, admin_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_datacite(monkeypatch)
    resource = await _create_resource(client, admin_user, doi="10.1234/existing")

    response = await client.post(
        "/api/doi/register",
        json={"resource_id": resource["id"]},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 409
    assert "10.1234/existing" in response.json()["detail"]


async def test_register_success_updates_resource_and_writes_audit_row(
    client: AsyncClient,
    admin_user: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_datacite(monkeypatch)
    patch_http(monkeypatch, [FakeResponse(201), FakeResponse(200)])
    resource = await _create_resource(client, admin_user, doi=None)

    response = await client.post(
        "/api/doi/register",
        json={"resource_id": resource["id"], "doi_suffix": "paper-1"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["doi"] == "10.5072/paper-1"
    assert body["state"] == "completed"

    # 资源上的 doi 列必须同步更新
    stored = (
        await db_session.execute(select(Resource).where(Resource.id == resource["id"]))
    ).scalar_one()
    assert stored.doi == "10.5072/paper-1"

    # 审计表必须落一行，且记下触发人
    rows = (
        (
            await db_session.execute(
                select(DOIRegistration).where(DOIRegistration.resource_id == resource["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].state == "completed"
    assert rows[0].registered_by == admin_user["user_id"]


async def test_register_failure_keeps_resource_doi_empty_but_records_audit(
    client: AsyncClient,
    admin_user: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_datacite(monkeypatch)
    patch_http(monkeypatch, [httpx.ConnectError("datacite down")])
    resource = await _create_resource(client, admin_user, doi=None)

    response = await client.post(
        "/api/doi/register",
        json={"resource_id": resource["id"]},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "failed"

    stored = (
        await db_session.execute(select(Resource).where(Resource.id == resource["id"]))
    ).scalar_one()
    assert stored.doi is None  # 失败绝不能把 doi 写到资源上

    rows = (
        (
            await db_session.execute(
                select(DOIRegistration).where(DOIRegistration.resource_id == resource["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].state == "failed"


async def test_status_none_when_never_registered(client: AsyncClient, admin_user: dict) -> None:
    resource = await _create_resource(client, admin_user, doi=None)

    response = await client.get(
        f"/api/doi/{resource['id']}/status",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "doi": None,
        "state": "none",
        "registered_at": None,
        "message": None,
    }


async def test_status_returns_latest_registration(
    client: AsyncClient,
    admin_user: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_datacite(monkeypatch)
    patch_http(monkeypatch, [FakeResponse(201), FakeResponse(200)])
    resource = await _create_resource(client, admin_user, doi=None)
    await client.post(
        "/api/doi/register",
        json={"resource_id": resource["id"]},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    response = await client.get(
        f"/api/doi/{resource['id']}/status",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "completed"
    # 默认后缀现在带租户维度（``{resource_id}-{tenant_id 前8位}``）：
    # resources.id 是全局自增，多租户下不同租户的同 id 资源会铸出同一个 DOI，
    # 而 DOI 撞号不可撤销。见 P0-3。
    assert body["doi"].startswith(f"10.5072/{resource['id']}-")
    assert len(body["doi"]) > len(f"10.5072/{resource['id']}-")
    assert body["registered_at"] is not None


async def test_status_404_for_unknown_resource(client: AsyncClient, admin_user: dict) -> None:
    response = await client.get(
        "/api/doi/999999/status",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 404


async def test_status_requires_auth(client: AsyncClient, admin_user: dict) -> None:
    resource = await _create_resource(client, admin_user)

    response = await client.get(f"/api/doi/{resource['id']}/status")

    assert response.status_code == 401


async def test_config_reports_whether_datacite_is_enabled(
    client: AsyncClient, admin_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_datacite(monkeypatch)

    response = await client.get(
        "/api/doi/config",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    assert response.json() == {"enabled": True, "prefix": "10.5072"}


async def test_config_reports_not_configured(
    client: AsyncClient, admin_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "datacite_api_url", "")
    monkeypatch.setattr(settings, "datacite_prefix", "")

    response = await client.get(
        "/api/doi/config",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.json() == {"enabled": False, "prefix": "not configured"}


async def test_register_conflict_when_suffix_collides_with_other_resource(
    client: AsyncClient,
    admin_user: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """撞号预检：显式后缀与别的资源已铸 DOI 相同 → 409，且不打扰 DataCite。"""
    enable_datacite(monkeypatch)
    clients = patch_http(monkeypatch, [FakeResponse(201), FakeResponse(200)])

    first = await _create_resource(client, admin_user, doi=None)
    resp1 = await client.post(
        "/api/doi/register",
        json={"resource_id": first["id"], "doi_suffix": "shared-suffix"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["doi"] == "10.5072/shared-suffix"
    datacite_calls_after_first = len(clients[0].calls)

    # 第二个资源复用同一后缀：必须在本地预检阶段就被拒
    second = await _create_resource(client, admin_user, doi=None, title="Another Paper")
    resp2 = await client.post(
        "/api/doi/register",
        json={"resource_id": second["id"], "doi_suffix": "shared-suffix"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert resp2.status_code == 409
    assert "10.5072/shared-suffix" in resp2.json()["detail"]
    # 预检拦截，没有新的 DataCite 调用（避免污染永久标识元数据）
    assert len(clients[0].calls) == datacite_calls_after_first


async def test_register_conflict_when_doi_taken_concurrently(
    client: AsyncClient,
    admin_user: dict,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """并发兜底：预检漏过（如 catalog 端点直接占位）撞唯一约束 → 409 而非 500。"""
    enable_datacite(monkeypatch)
    patch_http(monkeypatch, [FakeResponse(201), FakeResponse(200)])

    # 资源 A 经 catalog 端点直接占用 DOI 10.5072/race（不走 doi_registrations，
    # 模拟预检查不到、只在 commit 时撞 resources.doi 唯一约束的场景）
    occupied = await _create_resource(client, admin_user, doi="10.5072/race")

    target = await _create_resource(client, admin_user, doi=None, title="Race Target")
    resp = await client.post(
        "/api/doi/register",
        json={"resource_id": target["id"], "doi_suffix": "race"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert resp.status_code == 409
    assert "10.5072/race" in resp.json()["detail"]

    # 目标资源的 doi 列必须保持未设置
    stored = (
        await db_session.execute(select(Resource).where(Resource.id == target["id"]))
    ).scalar_one()
    assert stored.doi is None
    assert occupied["id"] != target["id"]
