"""Release gate: ready -> publish, stale hash refusal, draft blocking."""

from __future__ import annotations

import pytest
from conftest import auth_headers
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Tenant
from app.modules.catalog.models import Resource


async def _tenant(db: AsyncSession) -> Tenant:
    return (await db.execute(select(Tenant).where(Tenant.slug == "default"))).scalar_one()


def _resource(tenant_id, **overrides) -> Resource:
    data = {
        "tenant_id": tenant_id,
        "slug": "release-test-a",
        "type": "paper",
        "title": "A release gate test paper",
        "authors": ["Alice"],
        "year": 2026,
        "discipline": "计算机科学",
        "tags": ["test"],
        "abstract": "This abstract is deliberately longer than forty characters for the release gate.",
        "preview": "preview",
        "external_url": "https://example.com/paper.pdf",
        "volume": "12",
        "issue": "9",
        "publication_status": "published",
        "content_category": "academic",
        "content_track": "paper",
    }
    data.update(overrides)
    return Resource(**data)


@pytest.mark.asyncio
async def test_release_check_publish_and_audit(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    tenant = await _tenant(db_session)
    db_session.add_all(
        [_resource(tenant.id), _resource(tenant.id, slug="release-test-b", title="Second paper")]
    )
    await db_session.commit()

    check = await client.post(
        "/api/admin/releases/check",
        json={"volume": "12", "issue": "9"},
        headers=auth_headers(admin_user),
    )
    assert check.status_code == 200, check.text
    manifest = check.json()
    assert manifest["status"] == "ready"
    assert manifest["resource_count"] == 2
    assert manifest["error_count"] == 0

    publish_without_approval = await client.post(
        "/api/admin/releases/publish",
        json={"volume": "12", "issue": "9", "manifest_id": manifest["id"]},
        headers=auth_headers(admin_user),
    )
    assert publish_without_approval.status_code == 409
    assert publish_without_approval.json()["detail"]["code"] == "not_approved"

    approve = await client.post(
        "/api/admin/releases/approve",
        json={"manifest_id": manifest["id"], "note": "editorial sign-off"},
        headers=auth_headers(admin_user),
    )
    assert approve.status_code == 200, approve.text
    approved = approve.json()
    assert approved["approved_by"] is not None
    assert len(approved["approval_signature"]) == 64

    publish = await client.post(
        "/api/admin/releases/publish",
        json={"volume": "12", "issue": "9", "manifest_id": manifest["id"]},
        headers=auth_headers(admin_user),
    )
    assert publish.status_code == 200, publish.text
    assert publish.json()["status"] == "published"

    rows = (
        (
            await db_session.execute(
                select(Resource).where(Resource.tenant_id == tenant.id, Resource.issue == "9")
            )
        )
        .scalars()
        .all()
    )
    assert all(r.publish_at is not None for r in rows)
    audit = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "release.publish")))
        .scalars()
        .first()
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_release_refuses_stale_manifest(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    tenant = await _tenant(db_session)
    db_session.add(_resource(tenant.id, volume="13", issue="1", slug="stale-a"))
    await db_session.commit()

    check = await client.post(
        "/api/admin/releases/check",
        json={"volume": "13", "issue": "1"},
        headers=auth_headers(admin_user),
    )
    manifest = check.json()
    assert manifest["status"] == "ready"
    approve = await client.post(
        "/api/admin/releases/approve",
        json={"manifest_id": manifest["id"]},
        headers=auth_headers(admin_user),
    )
    assert approve.status_code == 200, approve.text

    row = (
        await db_session.execute(
            select(Resource).where(Resource.tenant_id == tenant.id, Resource.slug == "stale-a")
        )
    ).scalar_one()
    row.title = "Changed after gate"
    await db_session.commit()

    publish = await client.post(
        "/api/admin/releases/publish",
        json={"volume": "13", "issue": "1", "manifest_id": manifest["id"]},
        headers=auth_headers(admin_user),
    )
    assert publish.status_code == 409
    assert publish.json()["detail"]["code"] == "manifest_stale"


@pytest.mark.asyncio
async def test_release_blocks_draft_resource(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    tenant = await _tenant(db_session)
    db_session.add(
        _resource(tenant.id, volume="14", issue="2", slug="draft-a", publication_status="draft")
    )
    await db_session.commit()

    check = await client.post(
        "/api/admin/releases/check",
        json={"volume": "14", "issue": "2"},
        headers=auth_headers(admin_user),
    )
    assert check.status_code == 200
    body = check.json()
    assert body["status"] == "blocked"
    assert body["error_count"] >= 1

    publish = await client.post(
        "/api/admin/releases/publish",
        json={"volume": "14", "issue": "2", "manifest_id": body["id"]},
        headers=auth_headers(admin_user),
    )
    assert publish.status_code == 409


@pytest.mark.asyncio
async def test_release_rollback_restores_published_snapshot(
    client: AsyncClient, admin_user: dict, db_session: AsyncSession
) -> None:
    tenant = await _tenant(db_session)
    db_session.add(_resource(tenant.id, volume="15", issue="3", slug="rollback-a"))
    await db_session.commit()

    check = await client.post(
        "/api/admin/releases/check",
        json={"volume": "15", "issue": "3"},
        headers=auth_headers(admin_user),
    )
    manifest = check.json()
    await client.post(
        "/api/admin/releases/approve",
        json={"manifest_id": manifest["id"]},
        headers=auth_headers(admin_user),
    )
    publish = await client.post(
        "/api/admin/releases/publish",
        json={"volume": "15", "issue": "3", "manifest_id": manifest["id"]},
        headers=auth_headers(admin_user),
    )
    assert publish.status_code == 200, publish.text
    published = publish.json()

    row = (
        await db_session.execute(
            select(Resource).where(Resource.tenant_id == tenant.id, Resource.slug == "rollback-a")
        )
    ).scalar_one()
    row.publish_at = None
    await db_session.commit()

    rollback = await client.post(
        "/api/admin/releases/rollback",
        json={
            "volume": "15",
            "issue": "3",
            "manifest_id": published["id"],
            "reason": "restore issue timeline",
        },
        headers=auth_headers(admin_user),
    )
    assert rollback.status_code == 200, rollback.text
    body = rollback.json()
    assert body["status"] == "published"
    assert body["rollback_of"] == published["id"]
    assert body["restored"] == 1
