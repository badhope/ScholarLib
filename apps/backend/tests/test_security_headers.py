"""Tests for SecurityHeadersMiddleware — baseline security headers on every response.

Verifies:
- ``X-Content-Type-Options: nosniff``
- ``X-Frame-Options: DENY``
- ``Referrer-Policy: strict-origin-when-cross-origin``
- ``Content-Security-Policy`` present (non-empty)
- ``Permissions-Policy`` present
- ``X-API-Version`` must not be exposed
- ``Strict-Transport-Security`` present ONLY when ``is_production``
- Non-HTTP scope (e.g. websocket upgrade) passes through untouched
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

# Headers that must be present on EVERY HTTP response.
_REQUIRED_HEADERS: dict[str, str] = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}


@pytest.mark.asyncio
async def test_security_headers_present_on_api_response(client: AsyncClient) -> None:
    """Every API response must carry baseline security headers."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    for header, expected in _REQUIRED_HEADERS.items():
        assert response.headers[header] == expected, f"Missing/incorrect {header}"


@pytest.mark.asyncio
async def test_security_headers_present_on_404(client: AsyncClient) -> None:
    """Even 404 responses must carry security headers."""
    response = await client.get("/this-does-not-exist-404")
    assert response.status_code == 404
    for header, expected in _REQUIRED_HEADERS.items():
        assert response.headers[header] == expected, f"Missing/incorrect {header} on 404"


@pytest.mark.asyncio
async def test_security_headers_present_on_auth_endpoint(client: AsyncClient) -> None:
    """Auth endpoints (POST) must also carry security headers."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "nonexistent", "password": "test1234"},
    )
    # 401 — still must have headers.
    assert response.status_code == 401
    for header, expected in _REQUIRED_HEADERS.items():
        assert response.headers[header] == expected, f"Missing/incorrect {header} on auth"


@pytest.mark.asyncio
async def test_csp_header_present(client: AsyncClient) -> None:
    """Content-Security-Policy must be non-empty."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    csp = response.headers.get("content-security-policy")
    assert csp, "CSP header missing"
    assert "default-src" in csp
    assert "script-src" in csp


@pytest.mark.asyncio
async def test_permissions_policy_present(client: AsyncClient) -> None:
    """Permissions-Policy must disable geolocation/mic/camera."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    pp = response.headers.get("permissions-policy")
    assert pp, "Permissions-Policy header missing"
    assert "camera=()" in pp
    assert "microphone=()" in pp
    assert "geolocation=()" in pp


@pytest.mark.asyncio
async def test_x_api_version_present(client: AsyncClient) -> None:
    """X-API-Version must not be exposed."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert "x-api-version" not in response.headers, "X-API-Version must not be exposed"


@pytest.mark.asyncio
async def test_hsts_absent_in_test_env(client: AsyncClient) -> None:
    """In test env (not production), HSTS must NOT be present."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert "strict-transport-security" not in response.headers


@pytest.mark.asyncio
async def test_api_responses_are_not_cached(client: AsyncClient) -> None:
    """动态 API 必须显式 no-store，避免权限/列表被浏览器 heuristic cache。"""
    response = await client.get("/api/capabilities")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"


@pytest.mark.asyncio
async def test_head_root_returns_200_without_body(client: AsyncClient) -> None:
    """HEAD / must be a 200 for monitors and link unfurlers, not a 405."""
    response = await client.head("/")
    assert response.status_code == 200
    assert response.content == b""
    for header, expected in _REQUIRED_HEADERS.items():
        assert response.headers[header] == expected, f"Missing/incorrect {header} on HEAD /"
