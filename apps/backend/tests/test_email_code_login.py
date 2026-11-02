"""邮箱验证码登录（email-code login）集成测试。

覆盖：console 后端 503、反枚举（未注册邮箱同响应）、一次性消费、
错误码 5 次作废、过期码、未注册邮箱校验、发送节流。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

import pytest

from app.core.email_code import hash_code
from app.models import EmailLoginCode, User
from app.core.time import utcnow


async def _seed_code(
    db_session, tenant_id, email: str, code: str, *, minutes: int = 10
) -> EmailLoginCode:
    """直接在库里种一条已知哈希的码（绕开 SMTP 依赖，专注校验逻辑）。"""
    now = utcnow()
    row = EmailLoginCode(
        tenant_id=tenant_id,
        email=email,
        code_hash=hash_code(email, code),
        expires_at=now + timedelta(minutes=minutes),
    )
    db_session.add(row)
    await db_session.commit()
    return row


async def _user_tenant(db_session, email: str):
    row = (
        await db_session.execute(select(User).where(func_lower_email(email)))
    ).scalar_one()
    return row.tenant_id


def func_lower_email(email: str):
    from sqlalchemy import func

    return func.lower(User.email) == email.lower()


@pytest.mark.asyncio
async def test_request_rejected_when_backend_is_console(client: AsyncClient) -> None:
    """console 后端（测试默认）应 503，而不是假装发送成功。"""
    r = await client.post("/api/auth/email-code/request", json={"email": "someone@example.com"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_verify_rejects_bad_and_expired_codes(
    client: AsyncClient, test_user: dict, db_session
) -> None:
    """错码 / 无码 / 过期码一律 401，同一文案不泄露原因。"""
    email = test_user["email"]
    tenant_id = await _user_tenant(db_session, email)

    # 无码
    r = await client.post("/api/auth/email-code/verify", json={"email": email, "code": "123456"})
    assert r.status_code == 401

    # 错码
    await _seed_code(db_session, tenant_id, email.lower(), "999999")
    r = await client.post("/api/auth/email-code/verify", json={"email": email, "code": "123456"})
    assert r.status_code == 401

    # 过期码
    row = await _seed_code(db_session, tenant_id, email.lower(), "888888", minutes=-1)
    r = await client.post("/api/auth/email-code/verify", json={"email": email, "code": "888888"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_verify_success_issues_tokens_once(
    client: AsyncClient, test_user: dict, db_session
) -> None:
    email = test_user["email"]
    tenant_id = await _user_tenant(db_session, email)
    await _seed_code(db_session, tenant_id, email.lower(), "012345")

    r = await client.post("/api/auth/email-code/verify", json={"email": email, "code": "012345"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["user_id"] == test_user["user_id"]

    # 一次性：同一码第二次必须失败
    r2 = await client.post("/api/auth/email-code/verify", json={"email": email, "code": "012345"})
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_verify_killed_after_five_bad_attempts(
    client: AsyncClient, test_user: dict, db_session
) -> None:
    """5 次错误后码作废：即使第 6 次输入的是正确码也 401。"""
    email = test_user["email"]
    tenant_id = await _user_tenant(db_session, email)
    await _seed_code(db_session, tenant_id, email.lower(), "111111")

    for _ in range(5):
        r = await client.post(
            "/api/auth/email-code/verify", json={"email": email, "code": "000000"}
        )
        assert r.status_code == 401

    r = await client.post("/api/auth/email-code/verify", json={"email": email, "code": "111111"})
    assert r.status_code == 401, "超过 5 次尝试后正确码也应作废"


@pytest.mark.asyncio
async def test_verify_unknown_email_401(client: AsyncClient) -> None:
    """未注册邮箱（自然无码）401；不向攻击者提供更多信息。"""
    r = await client.post(
        "/api/auth/email-code/verify", json={"email": "ghost@example.com", "code": "123456"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_request_throttles_second_call_within_window(
    client: AsyncClient, db_session, monkeypatch
) -> None:
    """SMTP 开启时：首次 200（反枚举文案），60 秒内第二次 429。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_backend", "smtp")

    async def fake_send(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    class FakeSender:
        async def send(self, **kwargs):  # noqa: ANN003
            return None

    from app.core import email as email_mod

    monkeypatch.setattr(email_mod, "get_email_sender", lambda: FakeSender())

    r1 = await client.post("/api/auth/email-code/request", json={"email": "throttle@example.com"})
    assert r1.status_code == 200
    r2 = await client.post("/api/auth/email-code/request", json={"email": "throttle@example.com"})
    assert r2.status_code == 429
