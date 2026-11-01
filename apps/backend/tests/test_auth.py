"""Auth flow tests: register / login / refresh / logout / me."""

from __future__ import annotations

from httpx import AsyncClient


async def test_register_success_and_duplicates_are_observably_identical(
    client: AsyncClient, test_user: dict
) -> None:
    """成功、邮箱冲突、用户名冲突必须返回完全一致的响应。

    修复前成功分支返回 TokenResponse 并下发刷新 Cookie，冲突分支返回
    MessageResponse 且不下发 Cookie，调用方据此可直接枚举账号。
    """
    created = await client.post(
        "/api/auth/register",
        json={
            "email": "fresh-register@example.com",
            "username": "fresh_register",
            "password": "password123",
        },
    )
    duplicate_email = await client.post(
        "/api/auth/register",
        json={
            "email": "user@example.com",
            "username": "fresh_register_2",
            "password": "password123",
        },
    )
    duplicate_username = await client.post(
        "/api/auth/register",
        json={
            "email": "fresh-register-2@example.com",
            "username": "testuser",
            "password": "password123",
        },
    )

    for response in (created, duplicate_email, duplicate_username):
        assert response.status_code == 201
        assert set(response.json()) == {"message"}
        assert "access_token" not in response.json()
        assert "refresh_token" not in response.json()
        # 同 Cookie 设置行为：注册路径一律不建立会话。
        assert "rubbish_refresh" not in response.cookies
        assert "set-cookie" not in response.headers

    assert created.json() == duplicate_email.json() == duplicate_username.json()


async def test_registered_user_can_log_in_with_the_credentials(
    client: AsyncClient,
) -> None:
    """统一响应不得牺牲可用性：新账号仍能用注册凭据正常登录。"""
    register = await client.post(
        "/api/auth/register",
        json={
            "email": "login-after-register@example.com",
            "username": "login_after_register",
            "password": "password123",
        },
    )
    assert register.status_code == 201
    assert "access_token" not in register.json()

    login = await client.post(
        "/api/auth/login",
        json={"username": "login_after_register", "password": "password123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "login_after_register"


async def test_duplicate_registration_does_not_change_existing_credentials(
    client: AsyncClient, test_user: dict
) -> None:
    """冲突请求携带的新密码不得覆盖既有账号密码（防账号接管）。"""
    attempt = await client.post(
        "/api/auth/register",
        json={
            "email": "user@example.com",
            "username": "attacker_username",
            "password": "attackerpass123",
        },
    )
    assert attempt.status_code == 201

    hijack = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "attackerpass123"},
    )
    assert hijack.status_code == 401

    original = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "password123"},
    )
    assert original.status_code == 200


async def test_login_returns_valid_tokens(client: AsyncClient, test_user: dict) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["username"] == "testuser"


async def test_login_accepts_email_as_identifier(client: AsyncClient, test_user: dict) -> None:
    """登录标识支持邮箱（大小写不敏感）：读者记住的往往是注册邮箱。"""
    r = await client.post(
        "/api/auth/login",
        json={"username": "user@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    assert r.json()["username"] == "testuser"

    upper = await client.post(
        "/api/auth/login",
        json={"username": "USER@EXAMPLE.COM", "password": "password123"},
    )
    assert upper.status_code == 200

    with_spaces = await client.post(
        "/api/auth/login",
        json={"username": "  user@example.com  ", "password": "password123"},
    )
    assert with_spaces.status_code == 200


async def test_login_email_wrong_password_still_401(client: AsyncClient, test_user: dict) -> None:
    r = await client.post(
        "/api/auth/login",
        json={"username": "user@example.com", "password": "wrongpassword"},
    )
    assert r.status_code == 401


async def test_login_rejects_bad_password(client: AsyncClient, test_user: dict) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "wrongpassword"},
    )
    assert response.status_code == 401


async def test_me_requires_token(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


async def test_me_returns_current_user(client: AsyncClient, test_user: dict) -> None:
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "testuser"
    assert body["email"] == "user@example.com"
    assert body["is_admin"] is False


async def test_refresh_via_cookie_issues_new_tokens(client: AsyncClient, test_user: dict) -> None:
    # Cookie was set on the client during register/login, so we do not
    # need to pass it explicitly.
    response = await client.post("/api/auth/refresh")
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["username"] == "testuser"


async def test_refresh_rotates_old_refresh_token(client: AsyncClient, test_user: dict) -> None:
    """Refresh token rotation: a refresh token consumed once must not work again."""
    # First refresh: gets new pair, old refresh token (in cookie) is rotated out.
    first = await client.post("/api/auth/refresh")
    assert first.status_code == 200
    first_refresh_token = first.json()["refresh_token"]
    # Client cookie was updated to first_refresh_token after the call.

    # Second refresh using the NEW cookie succeeds and rotates again.
    second = await client.post("/api/auth/refresh")
    assert second.status_code == 200

    # Replay the rotated-out refresh token (first_refresh_token) via the body.
    # Clear the client cookie first so the server reads only the body —
    # otherwise the cookie (which holds the latest, still-valid token)
    # would mask the replay attempt.
    client.cookies.clear()
    replay = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": first_refresh_token},
    )
    assert replay.status_code == 401


async def test_refresh_rejects_after_logout(client: AsyncClient, test_user: dict) -> None:
    logout = await client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {test_user['token']}"},
    )
    assert logout.status_code == 204

    # Old refresh token (cookie) must be invalid because token_version bumped.
    refresh = await client.post("/api/auth/refresh")
    assert refresh.status_code == 401


async def test_logout_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/api/auth/logout")
    assert response.status_code == 401


async def test_old_access_token_invalid_after_logout(client: AsyncClient, test_user: dict) -> None:
    token = test_user["token"]
    logout = await client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout.status_code == 204

    me = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 401
