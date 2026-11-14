from __future__ import annotations

from httpx import AsyncClient

_PNG = b"\x89PNG\r\n\x1a\n" + b"test"


async def test_upload_media_image_and_read_it_back(client: AsyncClient, admin_user: dict) -> None:
    response = await client.post(
        "/api/media/images?purpose=submission",
        files={"file": ("figure.png", _PNG, "image/png")},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert response.status_code == 201
    url = response.json()["url"]
    assert url.startswith("/api/media/images/")

    read = await client.get(url)
    assert read.status_code == 200
    assert read.headers["content-type"] == "image/png"
    assert read.content == _PNG


async def test_upload_media_image_rejects_wrong_magic(
    client: AsyncClient, admin_user: dict
) -> None:
    response = await client.post(
        "/api/media/images",
        files={"file": ("figure.png", b"not-a-png", "image/png")},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert response.status_code == 400


async def test_upload_media_image_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/media/images",
        files={"file": ("figure.png", _PNG, "image/png")},
    )
    assert response.status_code == 401


async def test_upload_media_image_rejects_unknown_purpose(
    client: AsyncClient, admin_user: dict
) -> None:
    response = await client.post(
        "/api/media/images?purpose=avatar",
        files={"file": ("figure.png", _PNG, "image/png")},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert response.status_code == 422
