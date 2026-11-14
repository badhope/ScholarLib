"""Integration tests for the /api/export endpoint.

These need the catalog module (for Resource creation) plus the export
module's router. Admin creates resources via the catalog API, then we
hit /api/export?ids=...&format=... and assert the response shape.
"""

from __future__ import annotations

from httpx import AsyncClient

_SAMPLE = {
    "type": "paper",
    "title": "A Test Paper",
    "authors": ["Alice Author", "Bob Reviewer"],
    "year": 2024,
    "venue": "Journal of Testing",
    "discipline": "computer-science",
    "subdiscipline": "machine-learning",
    "tags": ["ml", "python"],
    "abstract": "This is a test abstract.",
    "preview": "Test preview.",
    "doi": "10.1234/test.1",
    "keywords": ["testing", "fixtures"],
}


async def test_export_requires_ids(client: AsyncClient) -> None:
    response = await client.get("/api/export")
    assert response.status_code == 400


async def test_export_rejects_too_many_ids(client: AsyncClient) -> None:
    ids = "&".join(f"ids={i}" for i in range(501))
    response = await client.get(f"/api/export?{ids}")
    assert response.status_code == 400
    assert "Too many" in response.json()["detail"]


async def test_export_returns_404_when_no_resources_match(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/export?ids=99999&ids=99998")
    assert response.status_code == 404


async def test_export_bibtex_format(client: AsyncClient, admin_user: dict) -> None:
    create = await client.post(
        "/api/catalog",
        json=_SAMPLE,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    rid = create.json()["id"]

    response = await client.get(f"/api/export?ids={rid}&format=bibtex")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-bibtex"
    assert 'filename="rubbish-export.bib"' in response.headers["content-disposition"]
    body = response.text
    assert "@article{" in body
    assert "Alice Author and Bob Reviewer" in body


async def test_export_ris_format(client: AsyncClient, admin_user: dict) -> None:
    create = await client.post(
        "/api/catalog",
        json=_SAMPLE,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    rid = create.json()["id"]

    response = await client.get(f"/api/export?ids={rid}&format=ris")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-research-info-systems"
    body = response.text
    assert "TY  - JOUR" in body
    assert "AU  - Alice Author" in body
    assert body.rstrip().endswith("ER  -")


async def test_export_csv_format(client: AsyncClient, admin_user: dict) -> None:
    create = await client.post(
        "/api/catalog",
        json=_SAMPLE,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    rid = create.json()["id"]

    response = await client.get(f"/api/export?ids={rid}&format=csv")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    lines = response.text.strip().split("\n")
    assert lines[0] == "title,type,authors,year,venue,discipline,tags,abstract,doi,url"


async def test_export_json_format(client: AsyncClient, admin_user: dict) -> None:
    create = await client.post(
        "/api/catalog",
        json=_SAMPLE,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    rid = create.json()["id"]

    response = await client.get(f"/api/export?ids={rid}&format=json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    import json

    records = json.loads(response.text)
    assert len(records) == 1
    assert records[0]["title"] == "A Test Paper"


async def test_export_jats_format(client: AsyncClient, admin_user: dict) -> None:
    create = await client.post(
        "/api/catalog",
        json=_SAMPLE,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    rid = create.json()["id"]

    response = await client.get(f"/api/export?ids={rid}&format=jats")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml"
    assert 'filename="rubbish-export.xml"' in response.headers["content-disposition"]
    assert "<article" in response.text
    assert "A Test Paper" in response.text


async def test_export_preserves_request_order(client: AsyncClient, admin_user: dict) -> None:
    r1 = await client.post(
        "/api/catalog",
        json={**_SAMPLE, "title": "First Paper"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    r2 = await client.post(
        "/api/catalog",
        json={**_SAMPLE, "title": "Second Paper", "doi": "10.2/second"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    id1 = r1.json()["id"]
    id2 = r2.json()["id"]

    response = await client.get(f"/api/export?ids={id2}&ids={id1}&format=json")
    import json

    records = json.loads(response.text)
    # Order preserved: id2 first
    assert records[0]["title"] == "Second Paper"
    assert records[1]["title"] == "First Paper"


async def test_export_default_format_is_json(client: AsyncClient, admin_user: dict) -> None:
    create = await client.post(
        "/api/catalog",
        json=_SAMPLE,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    rid = create.json()["id"]

    response = await client.get(f"/api/export?ids={rid}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"


async def test_export_rejects_invalid_format(client: AsyncClient, admin_user: dict) -> None:
    create = await client.post(
        "/api/catalog",
        json=_SAMPLE,
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    rid = create.json()["id"]

    response = await client.get(f"/api/export?ids={rid}&format=yaml")
    # Pattern validation rejects before reaching handler.
    assert response.status_code == 422
