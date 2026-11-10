"""Integration tests for TOTP two-factor authentication (Phase 3.1).

Covers the full enrolment + login chain and the ways it can be abused:

- setup issues a secret but does NOT activate 2FA;
- enable requires a genuine code and returns one-time recovery codes;
- once enabled, /auth/login stops handing out tokens;
- the pending token is short-lived, type-checked, and tied to
  token_version (password change kills it);
- recovery codes work exactly once;
- disabling requires the account password.
"""

from __future__ import annotations

import time

import pyotp
import pytest
from conftest import auth_headers
from httpx import AsyncClient

from app.core.totp import (
    create_two_factor_pending_token,
    decode_two_factor_pending_token,
)


def _code(secret: str) -> str:
    return pyotp.TOTP(secret).now()


async def _setup(client: AsyncClient, user: dict) -> str:
    """Run setup and return the pending TOTP secret."""
    resp = await client.post("/api/auth/2fa/setup", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert "Rubbish" in body["otpauth_uri"]
    return body["secret"]


async def _enable(client: AsyncClient, user: dict) -> tuple[str, list[str]]:
    """Full enrolment; returns (secret, backup_codes).

    恢复码只在 /auth/2fa/setup 的响应里出现一次（verify-setup 不再返回），
    所以在 setup 阶段取出来。
    """
    resp = await client.post("/api/auth/2fa/setup", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    secret = body["secret"]
    codes = body["backup_codes"]
    assert len(codes) == 10
    verify = await client.post(
        "/api/auth/2fa/verify-setup",
        json={"code": _code(secret)},
        headers=auth_headers(user),
    )
    assert verify.status_code == 200, verify.text
    return secret, codes


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------


async def test_status_is_disabled_by_default(client: AsyncClient, test_user: dict) -> None:
    """2FA 是 opt-in：新账号默认关闭，且没有恢复码。"""
    resp = await client.get("/api/auth/2fa/status", headers=auth_headers(test_user))
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False, "backup_codes_remaining": 0}


async def test_setup_does_not_activate_two_factor(client: AsyncClient, test_user: dict) -> None:
    """只跑 setup 不算启用——否则用户扫码失败就把自己锁在门外了。"""
    await _setup(client, test_user)

    status_resp = await client.get("/api/auth/2fa/status", headers=auth_headers(test_user))
    assert status_resp.json()["enabled"] is False

    # 登录仍然直接发 token
    login = await client.post(
        "/api/auth/login",
        json={"username": test_user["username"], "password": test_user["password"]},
    )
    assert login.status_code == 200
    assert "access_token" in login.json()


async def test_enable_requires_valid_code(client: AsyncClient, test_user: dict) -> None:
    """错误的验证码不能启用 2FA。"""
    await _setup(client, test_user)
    resp = await client.post(
        "/api/auth/2fa/verify-setup",
        json={"code": "000000"},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 400
    assert "Invalid TOTP code" in resp.json()["detail"]


async def test_enable_without_setup_is_rejected(client: AsyncClient, test_user: dict) -> None:
    """没跑 setup 就 enable → 400，而不是 500。"""
    resp = await client.post(
        "/api/auth/2fa/verify-setup",
        json={"code": "123456"},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 400
    assert "setup" in resp.json()["detail"].lower()


async def test_enable_returns_recovery_codes_and_flips_status(
    client: AsyncClient, test_user: dict
) -> None:
    """启用成功返回一次性恢复码；服务端只存哈希。"""
    _, codes = await _enable(client, test_user)
    assert len(codes) == 10
    assert all("-" in c for c in codes)
    assert len(set(codes)) == 10  # 不重复

    status_resp = await client.get("/api/auth/2fa/status", headers=auth_headers(test_user))
    assert status_resp.json() == {"enabled": True, "backup_codes_remaining": 10}


async def test_setup_again_after_enabled_is_conflict(client: AsyncClient, test_user: dict) -> None:
    """已启用后再 setup → 409，避免误把现有 secret 冲掉。"""
    await _enable(client, test_user)
    resp = await client.post("/api/auth/2fa/setup", headers=auth_headers(test_user))
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Login flow
# ---------------------------------------------------------------------------


async def test_login_returns_pending_token_when_enabled(
    client: AsyncClient, test_user: dict
) -> None:
    """启用后，密码正确也拿不到 access token，只有 pending token。"""
    await _enable(client, test_user)
    resp = await client.post(
        "/api/auth/login",
        json={"username": test_user["username"], "password": test_user["password"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["two_factor_required"] is True
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert body["pending_token"]


async def test_wrong_password_still_401_when_2fa_enabled(
    client: AsyncClient, test_user: dict
) -> None:
    """2FA 不能变成密码错误的遮羞布：密码错依然 401，不发 pending token。"""
    await _enable(client, test_user)
    resp = await client.post(
        "/api/auth/login",
        json={"username": test_user["username"], "password": "wrong-password"},
    )
    assert resp.status_code == 401


async def test_full_two_factor_login_chain(
    client: AsyncClient, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """完整链路：密码 → pending token → TOTP → 真正的 access token。

    verify-setup 会消耗当前窗口的码（TOTP 重放防线，H-1 修复），而
    verify_totp 只接受 T / T-1 两个窗口（明确拒绝 T+1），所以登录必须
    发生在下一个窗口：把服务器时钟前移 35s，提交 +30s（下一窗口 N+1）
    生成的码。服务器 current ∈ {N+1, N+2} 时 N+1 恒在候选集内，且恒
    大于已消耗的 N——对 30s 窗口边界完全确定，无闪挂。
    """
    secret, _ = await _enable(client, test_user)
    real_time = time.time()

    login = await client.post(
        "/api/auth/login",
        json={"username": test_user["username"], "password": test_user["password"]},
    )
    pending = login.json()["pending_token"]

    monkeypatch.setattr(time, "time", lambda: real_time + 35)
    resp = await client.post(
        "/api/auth/login/2fa",
        json={
            "pending_token": pending,
            "code": pyotp.TOTP(secret).at(real_time + 30),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["user_id"] == test_user["user_id"]

    # 换来的 token 真的能用
    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200


async def test_wrong_totp_code_is_rejected(client: AsyncClient, test_user: dict) -> None:
    await _enable(client, test_user)
    login = await client.post(
        "/api/auth/login",
        json={"username": test_user["username"], "password": test_user["password"]},
    )
    resp = await client.post(
        "/api/auth/login/2fa",
        json={"pending_token": login.json()["pending_token"], "code": "000000"},
    )
    assert resp.status_code == 401
    assert "Invalid two-factor code" in resp.json()["detail"]


async def test_garbage_pending_token_is_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/login/2fa",
        json={"pending_token": "not-a-jwt", "code": "123456"},
    )
    assert resp.status_code == 401


async def test_access_token_cannot_be_used_as_pending_token(
    client: AsyncClient, test_user: dict
) -> None:
    """type 校验：普通 access token 不能冒充 pending token 直接换 token。"""
    secret, _ = await _enable(client, test_user)
    resp = await client.post(
        "/api/auth/login/2fa",
        json={"pending_token": test_user["token"], "code": _code(secret)},
    )
    assert resp.status_code == 401


async def test_pending_token_dies_with_token_version(client: AsyncClient, test_user: dict) -> None:
    """改密后 token_version 变了，之前签发的 pending token 立刻失效。"""
    secret, _ = await _enable(client, test_user)
    login = await client.post(
        "/api/auth/login",
        json={"username": test_user["username"], "password": test_user["password"]},
    )
    pending = login.json()["pending_token"]

    change = await client.post(
        "/api/users/me/password",
        json={"old_password": test_user["password"], "new_password": "newpassword456"},
        headers=auth_headers(test_user),
    )
    assert change.status_code == 204

    resp = await client.post(
        "/api/auth/login/2fa",
        json={"pending_token": pending, "code": _code(secret)},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------


async def test_recovery_code_works_once(client: AsyncClient, test_user: dict) -> None:
    """恢复码可以顶替 TOTP 登录，但只能用一次。"""
    _, codes = await _enable(client, test_user)
    recovery = codes[0]

    async def _login_with(code: str) -> int:
        login = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": test_user["password"],
            },
        )
        resp = await client.post(
            "/api/auth/login/2fa",
            json={"pending_token": login.json()["pending_token"], "code": code},
        )
        return resp.status_code

    assert await _login_with(recovery) == 200
    # 第二次同一个码必须失败
    assert await _login_with(recovery) == 401

    status_resp = await client.get("/api/auth/2fa/status", headers=auth_headers(test_user))
    assert status_resp.json()["backup_codes_remaining"] == 9


async def test_recovery_code_is_case_insensitive(client: AsyncClient, test_user: dict) -> None:
    """恢复码是人手抄的，大小写/空格不该成为障碍。"""
    _, codes = await _enable(client, test_user)
    login = await client.post(
        "/api/auth/login",
        json={"username": test_user["username"], "password": test_user["password"]},
    )
    resp = await client.post(
        "/api/auth/login/2fa",
        json={
            "pending_token": login.json()["pending_token"],
            "code": f"  {codes[0].upper()}  ",
        },
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Disable
# ---------------------------------------------------------------------------


async def test_disable_requires_password(client: AsyncClient, test_user: dict) -> None:
    """被劫持的会话不能光凭 cookie 就把第二因子摘掉。"""
    await _enable(client, test_user)
    resp = await client.post(
        "/api/auth/2fa/disable",
        json={"password": "wrong-password"},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 401

    status_resp = await client.get("/api/auth/2fa/status", headers=auth_headers(test_user))
    assert status_resp.json()["enabled"] is True


async def test_disable_with_password_restores_plain_login(
    client: AsyncClient, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关闭 2FA 后登录回到一步式，且恢复码被清空。"""
    secret, _ = await _enable(client, test_user)
    # disable 端点同样带重放保护（verify-setup 已消费当前 time-step 的码）。
    # 与 login/2fa 测试同口径：把服务端时间拨到下一个窗口，用该窗口的码。
    real_time = time.time()
    monkeypatch.setattr(time, "time", lambda: real_time + 35)
    resp = await client.post(
        "/api/auth/2fa/disable",
        json={"password": test_user["password"], "code": pyotp.TOTP(secret).at(real_time + 30)},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 200
    monkeypatch.undo()

    # 关闭 2FA 会吊销既有会话（token_version 提升），所以先重新登录：
    # 关掉之后登录回到一步式，直接发 access_token。
    login = await client.post(
        "/api/auth/login",
        json={"username": test_user["username"], "password": test_user["password"]},
    )
    assert "access_token" in login.json()

    status_resp = await client.get(
        "/api/auth/2fa/status",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert status_resp.json() == {"enabled": False, "backup_codes_remaining": 0}


async def test_disable_when_not_enabled_is_400(client: AsyncClient, test_user: dict) -> None:
    resp = await client.post(
        "/api/auth/2fa/disable",
        json={"password": test_user["password"]},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 400


async def test_disable_rejects_replayed_totp_code(
    client: AsyncClient, test_user: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M2 加固回归：disable 与 authenticate 同样拒绝重放已消费的 time-step。

    verify-setup 已消耗当前窗口 N 的码（last_counter=N）。同窗口重发该码
    关 2FA 必须被拒（防止被钓鱼/截获的验证码在 30 秒内既登录又关 2FA）；
    拨到下一窗口后用新码则能正常关闭——证明拒绝来自重放保护而非别处。
    """
    secret, _ = await _enable(client, test_user)
    real_time = time.time()

    # 同窗口重放 verify-setup 消费过的码 → 401，且 2FA 保持开启
    replay = await client.post(
        "/api/auth/2fa/disable",
        json={"password": test_user["password"], "code": _code(secret)},
        headers=auth_headers(test_user),
    )
    assert replay.status_code == 401, replay.text
    status_resp = await client.get("/api/auth/2fa/status", headers=auth_headers(test_user))
    assert status_resp.json()["enabled"] is True

    # 下一窗口的新码 → 正常关闭
    monkeypatch.setattr(time, "time", lambda: real_time + 35)
    resp = await client.post(
        "/api/auth/2fa/disable",
        json={"password": test_user["password"], "code": pyotp.TOTP(secret).at(real_time + 30)},
        headers=auth_headers(test_user),
    )
    assert resp.status_code == 200, resp.text
    status_resp = await client.get("/api/auth/2fa/status", headers=auth_headers(test_user))
    # 关闭动作会吊销会话，此请求用的是被吊销的旧 token；401 即视为已吊销
    assert status_resp.status_code in (200, 401)


async def test_two_factor_endpoints_require_auth(client: AsyncClient) -> None:
    """未登录不能碰任何 2FA 自管理端点。"""
    for method, path, body in (
        ("get", "/api/auth/2fa/status", None),
        ("post", "/api/auth/2fa/setup", None),
        ("post", "/api/auth/2fa/verify-setup", {"code": "123456"}),
        ("post", "/api/auth/2fa/disable", {"password": "whatever"}),
    ):
        resp = (
            await getattr(client, method)(path, json=body)
            if body
            else await getattr(client, method)(path)
        )
        assert resp.status_code == 401, f"{method} {path} → {resp.status_code}"


# ---------------------------------------------------------------------------
# Pending token unit-level guards
# ---------------------------------------------------------------------------


def test_pending_token_roundtrip_carries_claims() -> None:
    token = create_two_factor_pending_token(user_id=42, token_version=7)
    claims = decode_two_factor_pending_token(token)
    assert claims is not None
    assert claims["sub"] == "42"
    assert claims["token_version"] == 7
    assert claims["type"] == "2fa_pending"


def test_decode_rejects_tampered_token() -> None:
    token = create_two_factor_pending_token(user_id=1, token_version=0)
    assert decode_two_factor_pending_token(token + "x") is None


def test_pending_token_survives_hot_key_rotation(monkeypatch) -> None:
    """A pending token minted before a key rotation still verifies.

    The token is issued at the password step and redeemed at the code
    step, so a rotation landing in between must not break the
    half-finished login. Before M4 these functions signed and verified
    with the current key only — a rotated-out key made every in-flight
    pending token undecryptable until the TTL elapsed.
    """
    from dataclasses import dataclass

    from app.core import key_rotation

    @dataclass
    class _FakeSettings:
        secret_key: str = ""
        previous_secret_keys: str = ""
        algorithm: str = "HS256"

    holder: dict[str, _FakeSettings] = {
        "s": _FakeSettings(secret_key="a" * 64),
        "previous": None,
    }
    monkeypatch.setattr(key_rotation, "get_settings", lambda: holder["s"])

    token = create_two_factor_pending_token(user_id=42, token_version=7)

    # Rotate the signing key while the token is in flight.
    holder["s"] = _FakeSettings(secret_key="b" * 64, previous_secret_keys="a" * 64)

    claims = decode_two_factor_pending_token(token)
    assert claims is not None
    assert claims["sub"] == "42"
    assert claims["token_version"] == 7
    assert claims["type"] == "2fa_pending"
