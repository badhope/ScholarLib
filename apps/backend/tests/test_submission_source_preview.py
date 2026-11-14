"""Auth boundary for the pre-submit source preview.

The preview PDF/PNG endpoints are capability URLs, but the capability token
must only be usable by a signed-in user. Upload/parse itself already requires
auth; the read endpoints used to be public, which leaked draft originals to
anyone who obtained a token.
"""

from __future__ import annotations

from typing import Any

import pymupdf
import pytest
from conftest import auth_headers
from httpx import AsyncClient


def _pdf_bytes() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "source preview auth test")
    data = document.tobytes()
    document.close()
    return data


@pytest.mark.asyncio
async def test_source_preview_read_endpoints_require_auth(
    client: AsyncClient, test_user: dict[str, Any]
) -> None:
    upload = await client.post(
        "/api/submissions/source-preview/pages",
        files={"file": ("preview.pdf", _pdf_bytes(), "application/pdf")},
        headers=auth_headers(test_user),
    )
    assert upload.status_code == 200
    payload = upload.json()
    token = payload["token"]
    assert payload["pages"] == 1

    png_url = f"/api/submissions/source-preview/{token}/1.png"
    pdf_url = f"/api/submissions/source-preview/{token}.pdf"

    assert (await client.get(png_url)).status_code == 401
    assert (await client.get(pdf_url)).status_code == 401

    assert (await client.get(png_url, headers=auth_headers(test_user))).status_code == 200
    assert (await client.get(pdf_url, headers=auth_headers(test_user))).status_code == 200


@pytest.mark.asyncio
async def test_source_preview_invalid_token_still_requires_auth(client: AsyncClient) -> None:
    missing = "0" * 32
    assert (await client.get(f"/api/submissions/source-preview/{missing}.pdf")).status_code == 401
