"""Integration tests for the library module.

Two groups:

- List CRUD (owner-only):
  POST /reading-lists, GET /reading-lists, GET /reading-lists/{id},
  PATCH /reading-lists/{id}, DELETE /reading-lists/{id}
- Item lifecycle (idempotent add/remove):
  POST /reading-lists/{id}/items, DELETE /reading-lists/{id}/items/{rid}

Cross-tenant / cross-user isolation: a list is only visible to its
owner; another user gets 404 on every operation.
"""

from __future__ import annotations

from conftest import auth_headers, register_user
from httpx import AsyncClient

_RESOURCE_PAYLOAD = {
    "type": "paper",
    "title": "Reading-list test resource",
    "authors": ["Alice Author"],
    "year": 2024,
    "discipline": "physics",
    "tags": ["test"],
    "abstract": "An abstract for the test resource.",
    "preview": "A preview for the test resource.",
}


async def _create_resource(client: AsyncClient, admin: dict) -> int:
    """Helper: create a catalog Resource (admin only) and return its id."""
    response = await client.post(
        "/api/catalog", json=_RESOURCE_PAYLOAD, headers=auth_headers(admin)
    )
    response.raise_for_status()
    return response.json()["id"]


async def _create_list(
    client: AsyncClient,
    user: dict,
    name: str = "My Reading List",
    description: str | None = "A test list",
) -> dict:
    response = await client.post(
        "/api/reading-lists",
        json={"name": name, "description": description},
        headers=auth_headers(user),
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def test_list_endpoint_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/reading-lists")
    assert response.status_code == 401


async def test_create_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/api/reading-lists", json={"name": "x"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# List CRUD
# ---------------------------------------------------------------------------


async def test_create_list_defaults(client: AsyncClient, test_user: dict) -> None:
    """POST returns 201 with the new list and empty items."""
    response = await client.post(
        "/api/reading-lists",
        json={"name": "Papers", "description": "For later"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["name"] == "Papers"
    assert body["description"] == "For later"
    assert body["items"] == []
    assert body["created_at"]
    assert body["updated_at"]


async def test_create_rejects_empty_name(client: AsyncClient, test_user: dict) -> None:
    response = await client.post(
        "/api/reading-lists",
        json={"name": ""},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 422


async def test_create_duplicate_name_409(client: AsyncClient, test_user: dict) -> None:
    await _create_list(client, test_user, name="Dup")
    response = await client.post(
        "/api/reading-lists",
        json={"name": "Dup"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


async def test_list_my_lists_empty(client: AsyncClient, test_user: dict) -> None:
    response = await client.get("/api/reading-lists", headers=auth_headers(test_user))
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


async def test_list_my_lists_pagination(client: AsyncClient, test_user: dict) -> None:
    """Lists are returned newest first; pagination meta reflects total."""
    for i in range(3):
        await _create_list(client, test_user, name=f"L{i}")
    response = await client.get(
        "/api/reading-lists?page=1&page_size=2", headers=auth_headers(test_user)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 3
    assert body["meta"]["page_size"] == 2
    assert body["meta"]["total_pages"] == 2
    assert len(body["data"]) == 2
    # List view excludes items; item_count is computed
    assert "items" not in body["data"][0]
    assert body["data"][0]["item_count"] == 0


async def test_get_list_owner(client: AsyncClient, test_user: dict) -> None:
    created = await _create_list(client, test_user)
    response = await client.get(
        f"/api/reading-lists/{created['id']}", headers=auth_headers(test_user)
    )
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_get_list_other_user_404(client: AsyncClient, test_user: dict) -> None:
    """Another registered user cannot see someone else's list."""
    created = await _create_list(client, test_user)
    # Register a second user
    second = await register_user(client, email="other@example.com", username="otheruser")
    response = await client.get(
        f"/api/reading-lists/{created['id']}",
        headers={"Authorization": f"Bearer {second['token']}"},
    )
    assert response.status_code == 404


async def test_get_list_404(client: AsyncClient, test_user: dict) -> None:
    response = await client.get("/api/reading-lists/99999", headers=auth_headers(test_user))
    assert response.status_code == 404


async def test_update_list(client: AsyncClient, test_user: dict) -> None:
    created = await _create_list(client, test_user, name="Old", description="old desc")
    response = await client.patch(
        f"/api/reading-lists/{created['id']}",
        json={"name": "New", "description": "new desc"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New"
    assert body["description"] == "new desc"


async def test_update_partial(client: AsyncClient, test_user: dict) -> None:
    """Partial update leaves other fields untouched."""
    created = await _create_list(client, test_user, name="Keep", description="keep desc")
    response = await client.patch(
        f"/api/reading-lists/{created['id']}",
        json={"description": "new desc"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Keep"
    assert body["description"] == "new desc"


async def test_update_to_duplicate_name_409(client: AsyncClient, test_user: dict) -> None:
    await _create_list(client, test_user, name="A")
    b = await _create_list(client, test_user, name="B")
    response = await client.patch(
        f"/api/reading-lists/{b['id']}",
        json={"name": "A"},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 409


async def test_delete_list(client: AsyncClient, test_user: dict) -> None:
    created = await _create_list(client, test_user)
    response = await client.delete(
        f"/api/reading-lists/{created['id']}", headers=auth_headers(test_user)
    )
    assert response.status_code == 200
    # Subsequent GET → 404
    assert (
        await client.get(f"/api/reading-lists/{created['id']}", headers=auth_headers(test_user))
    ).status_code == 404


async def test_delete_other_user_404(client: AsyncClient, test_user: dict) -> None:
    created = await _create_list(client, test_user)
    second = await register_user(client, email="other2@example.com", username="other2user")
    response = await client.delete(
        f"/api/reading-lists/{created['id']}",
        headers={"Authorization": f"Bearer {second['token']}"},
    )
    assert response.status_code == 404
    # Owner can still see the list (delete didn't happen)
    assert (
        await client.get(f"/api/reading-lists/{created['id']}", headers=auth_headers(test_user))
    ).status_code == 200


# ---------------------------------------------------------------------------
# Item lifecycle
# ---------------------------------------------------------------------------


async def test_add_item(client: AsyncClient, test_user: dict, admin_user: dict) -> None:
    rid = await _create_resource(client, admin_user)
    created = await _create_list(client, test_user)
    response = await client.post(
        f"/api/reading-lists/{created['id']}/items",
        json={"resource_id": rid},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["resource_id"] == rid
    assert item["resource"]["id"] == rid
    assert item["resource"]["title"] == _RESOURCE_PAYLOAD["title"]
    assert item["added_at"]


async def test_add_item_idempotent(client: AsyncClient, test_user: dict, admin_user: dict) -> None:
    """Re-adding the same resource returns 201 with one item (no dup)."""
    rid = await _create_resource(client, admin_user)
    created = await _create_list(client, test_user)
    first = await client.post(
        f"/api/reading-lists/{created['id']}/items",
        json={"resource_id": rid},
        headers=auth_headers(test_user),
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/reading-lists/{created['id']}/items",
        json={"resource_id": rid},
        headers=auth_headers(test_user),
    )
    assert second.status_code == 201
    body = second.json()
    assert len(body["items"]) == 1


async def test_add_item_unknown_resource_404(client: AsyncClient, test_user: dict) -> None:
    created = await _create_list(client, test_user)
    response = await client.post(
        f"/api/reading-lists/{created['id']}/items",
        json={"resource_id": 99999},
        headers=auth_headers(test_user),
    )
    assert response.status_code == 404
    assert "Resource" in response.json()["detail"]


async def test_add_item_to_other_user_list_404(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    rid = await _create_resource(client, admin_user)
    created = await _create_list(client, test_user)
    second = await register_user(client, email="other3@example.com", username="other3user")
    response = await client.post(
        f"/api/reading-lists/{created['id']}/items",
        json={"resource_id": rid},
        headers={"Authorization": f"Bearer {second['token']}"},
    )
    assert response.status_code == 404


async def test_remove_item(client: AsyncClient, test_user: dict, admin_user: dict) -> None:
    rid = await _create_resource(client, admin_user)
    created = await _create_list(client, test_user)
    await client.post(
        f"/api/reading-lists/{created['id']}/items",
        json={"resource_id": rid},
        headers=auth_headers(test_user),
    )
    response = await client.delete(
        f"/api/reading-lists/{created['id']}/items/{rid}",
        headers=auth_headers(test_user),
    )
    assert response.status_code == 204
    # Subsequent list GET shows zero items
    detail = await client.get(
        f"/api/reading-lists/{created['id']}", headers=auth_headers(test_user)
    )
    assert detail.json()["items"] == []


async def test_remove_item_idempotent(client: AsyncClient, test_user: dict) -> None:
    """Removing an item that isn't in the list is a 204 no-op."""
    rid = 12345  # doesn't need to exist for remove (no resource lookup)
    created = await _create_list(client, test_user)
    response = await client.delete(
        f"/api/reading-lists/{created['id']}/items/{rid}",
        headers=auth_headers(test_user),
    )
    assert response.status_code == 204


async def test_remove_item_other_user_404(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    rid = await _create_resource(client, admin_user)
    created = await _create_list(client, test_user)
    await client.post(
        f"/api/reading-lists/{created['id']}/items",
        json={"resource_id": rid},
        headers=auth_headers(test_user),
    )
    second = await register_user(client, email="other4@example.com", username="other4user")
    response = await client.delete(
        f"/api/reading-lists/{created['id']}/items/{rid}",
        headers={"Authorization": f"Bearer {second['token']}"},
    )
    assert response.status_code == 404


async def test_delete_list_cascades_items(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """Deleting a list removes all its items (cascade)."""
    rid = await _create_resource(client, admin_user)
    created = await _create_list(client, test_user)
    await client.post(
        f"/api/reading-lists/{created['id']}/items",
        json={"resource_id": rid},
        headers=auth_headers(test_user),
    )
    delete = await client.delete(
        f"/api/reading-lists/{created['id']}", headers=auth_headers(test_user)
    )
    assert delete.status_code == 200
    assert (
        await client.get(f"/api/reading-lists/{created['id']}", headers=auth_headers(test_user))
    ).status_code == 404


async def test_item_count_in_list_view(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    """The list view's item_count reflects added items."""
    rid = await _create_resource(client, admin_user)
    created = await _create_list(client, test_user)
    await client.post(
        f"/api/reading-lists/{created['id']}/items",
        json={"resource_id": rid},
        headers=auth_headers(test_user),
    )
    response = await client.get("/api/reading-lists", headers=auth_headers(test_user))
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["item_count"] == 1
    # items should NOT be in the list view (excluded)
    assert "items" not in body["data"][0]
