"""Integration tests for the notifications module.

Endpoints are all auth-required and user-scoped (the recipient sees only
their own notifications). The tests use the internal ``create()`` helper
to seed rows directly, then exercise the HTTP surface to verify the
endpoints behave correctly against the seeded data.

Test groups:
- Auth / scoping: missing token, another user's notifications are invisible.
- Listing: paginated, ordered newest-first.
- Unread count.
- Mark one read / mark all read.
- Delete one.
"""

from __future__ import annotations

from conftest import auth_headers
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.notifications.models import Notification
from app.domain.notifications.services import create as create_notification
from app.models import Tenant, User


async def _resolve_tenant(db: AsyncSession) -> Tenant:
    """Look up the bootstrap 'default' tenant; raise if absent."""
    result = await db.execute(select(Tenant).where(Tenant.slug == "default"))
    return result.scalar_one()


async def _seed(
    db: AsyncSession,
    *,
    user_id: int,
    type_: str = "system",
    title: str = "Hello",
    body: str | None = "World",
    related_type: str | None = None,
    related_id: str | None = None,
    is_read: bool = False,
) -> Notification:
    """Insert a notification row and commit; return it.

    Tenant is auto-resolved from the bootstrap 'default' tenant so test
    code does not need to thread tenant_id through every call site.
    """
    tenant = await _resolve_tenant(db)
    n = await create_notification(
        db,
        tenant_id=tenant.id,
        user_id=user_id,
        type_=type_,
        title=title,
        body=body,
        related_type=related_type,
        related_id=related_id,
    )
    # Force the requested is_read state (the helper always inserts
    # unread, which is the canonical flow; tests sometimes want to seed
    # an already-read row to verify filtering).
    n.is_read = is_read
    await db.commit()
    await db.refresh(n)
    return n


# ---------------------------------------------------------------------------
# Auth / scoping
# ---------------------------------------------------------------------------


async def test_list_requiresauth_headers(client: AsyncClient) -> None:
    response = await client.get("/api/notifications")
    assert response.status_code == 401


async def test_list_empty(client: AsyncClient, test_user: dict) -> None:
    response = await client.get("/api/notifications", headers=auth_headers(test_user))
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


async def test_other_users_notifications_invisible(
    client: AsyncClient, test_user: dict, db_session: AsyncSession
) -> None:
    """A user cannot see another user's notifications (filtered by user_id)."""
    # Seed a notification addressed to a different user_id.
    # test_user is the only user in the fixture; pick an arbitrary
    # non-existent recipient id — the row will be inserted but the
    # current user will not see it.
    result = await db_session.execute(select(Tenant).where(Tenant.slug == "default"))
    tenant = result.scalar_one()
    other_user = User(
        tenant_id=tenant.id,
        email="other@example.com",
        username="otheruser",
        hashed_password="x",
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)

    await _seed(
        db_session,
        user_id=other_user.id,
        title="Private to other user",
    )

    response = await client.get("/api/notifications", headers=auth_headers(test_user))
    body = response.json()
    assert body["meta"]["total"] == 0
    assert body["data"] == []


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


async def test_list_returns_user_notifications(
    client: AsyncClient, test_user: dict, db_session: AsyncSession
) -> None:
    await _seed(
        db_session,
        user_id=test_user["user_id"],
        title="First",
    )
    await _seed(
        db_session,
        user_id=test_user["user_id"],
        title="Second",
    )
    response = await client.get("/api/notifications", headers=auth_headers(test_user))
    body = response.json()
    assert body["meta"]["total"] == 2
    # Newest first — "Second" was inserted last.
    assert body["data"][0]["title"] == "Second"
    assert body["data"][1]["title"] == "First"


async def test_list_paginates(
    client: AsyncClient, test_user: dict, db_session: AsyncSession
) -> None:
    for i in range(5):
        await _seed(
            db_session,
            user_id=test_user["user_id"],
            title=f"N{i}",
        )
    # page_size=2 — page 2 should return 2 items.
    response = await client.get(
        "/api/notifications?page=2&page_size=2", headers=auth_headers(test_user)
    )
    body = response.json()
    assert body["meta"]["total"] == 5
    assert body["meta"]["page"] == 2
    assert body["meta"]["page_size"] == 2
    assert body["meta"]["total_pages"] == 3
    assert len(body["data"]) == 2


# ---------------------------------------------------------------------------
# Unread count
# ---------------------------------------------------------------------------


async def test_unread_count_zero_when_empty(client: AsyncClient, test_user: dict) -> None:
    response = await client.get("/api/notifications/unread-count", headers=auth_headers(test_user))
    assert response.status_code == 200
    assert response.json()["unread"] == 0


async def test_unread_count_excludes_read(
    client: AsyncClient, test_user: dict, db_session: AsyncSession
) -> None:
    await _seed(
        db_session,
        user_id=test_user["user_id"],
        title="Unread 1",
        is_read=False,
    )
    await _seed(
        db_session,
        user_id=test_user["user_id"],
        title="Unread 2",
        is_read=False,
    )
    await _seed(
        db_session,
        user_id=test_user["user_id"],
        title="Already read",
        is_read=True,
    )
    response = await client.get("/api/notifications/unread-count", headers=auth_headers(test_user))
    assert response.json()["unread"] == 2


# ---------------------------------------------------------------------------
# Mark one read
# ---------------------------------------------------------------------------


async def test_mark_read_404_when_not_owned(client: AsyncClient, test_user: dict) -> None:
    response = await client.patch("/api/notifications/99999/read", headers=auth_headers(test_user))
    assert response.status_code == 404


async def test_mark_read(client: AsyncClient, test_user: dict, db_session: AsyncSession) -> None:
    n = await _seed(
        db_session,
        user_id=test_user["user_id"],
        title="To be read",
    )
    assert n.is_read is False
    response = await client.patch(
        f"/api/notifications/{n.id}/read", headers=auth_headers(test_user)
    )
    assert response.status_code == 200
    assert response.json()["is_read"] is True

    # Unread count drops to 0.
    count = await client.get("/api/notifications/unread-count", headers=auth_headers(test_user))
    assert count.json()["unread"] == 0


# ---------------------------------------------------------------------------
# Mark all read
# ---------------------------------------------------------------------------


async def test_mark_all_read(
    client: AsyncClient, test_user: dict, db_session: AsyncSession
) -> None:
    for i in range(3):
        await _seed(
            db_session,
            user_id=test_user["user_id"],
            title=f"Unread {i}",
        )
    # Plus one already-read row, which should NOT count as "updated".
    await _seed(
        db_session,
        user_id=test_user["user_id"],
        title="Already read",
        is_read=True,
    )

    response = await client.patch("/api/notifications/read-all", headers=auth_headers(test_user))
    assert response.status_code == 200
    assert response.json()["updated"] == 3

    # Unread count is now 0.
    count = await client.get("/api/notifications/unread-count", headers=auth_headers(test_user))
    assert count.json()["unread"] == 0


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def test_delete_404_when_not_owned(client: AsyncClient, test_user: dict) -> None:
    response = await client.delete("/api/notifications/99999", headers=auth_headers(test_user))
    assert response.status_code == 404


async def test_delete(client: AsyncClient, test_user: dict, db_session: AsyncSession) -> None:
    n = await _seed(
        db_session,
        user_id=test_user["user_id"],
        title="To be deleted",
    )
    response = await client.delete(f"/api/notifications/{n.id}", headers=auth_headers(test_user))
    assert response.status_code == 200
    # Subsequent list shows 0.
    listed = await client.get("/api/notifications", headers=auth_headers(test_user))
    assert listed.json()["meta"]["total"] == 0


async def test_long_title_is_truncated_to_column_limit(
    test_user: dict, db_session: AsyncSession
) -> None:
    """Long submission titles must not break the assignment transaction."""
    n = await _seed(db_session, user_id=test_user["user_id"], title="长" * 260)
    assert len(n.title) == 200
    assert n.title.endswith("…")
