"""D4 captcha hook tests."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.core.captcha import _load_verifier
from app.core.config import settings


def _payload(email: str = "captcha1@example.com", username: str = "captcha1") -> dict[str, Any]:
    return {
        "email": email,
        "username": username,
        "password": "Sup3rSecret!",
        "captcha_token": "any-token",
    }


def _payload_no_token(
    email: str = "captcha1@example.com", username: str = "captcha1"
) -> dict[str, Any]:
    return {
        "email": email,
        "username": username,
        "password": "Sup3rSecret!",
    }


@pytest.mark.asyncio
async def test_register_works_without_captcha_when_policy_off(
    client: AsyncClient,
) -> None:
    """Baseline: captcha_required_for_registration is off -> no captcha needed."""
    assert settings.captcha_required_for_registration is False
    r = await client.post("/api/auth/register", json=_payload())
    assert r.status_code in (201, 200)
    body = r.json()
    # Registration never issues tokens: success and duplicate look the same.
    assert set(body) == {"message"}


@pytest.mark.asyncio
async def test_register_requires_captcha_token_when_policy_on(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the policy is on, missing token -> 400."""
    monkeypatch.setattr(settings, "captcha_required_for_registration", True)
    p = _payload_no_token(email="captcha2@example.com", username="captcha2")
    r = await client.post("/api/auth/register", json=p)
    assert r.status_code == 400
    assert "captcha" in r.text.lower()


@pytest.mark.asyncio
async def test_register_accepts_captcha_token_when_policy_on(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the policy is on and token is present, dev passthrough accepts."""
    monkeypatch.setattr(settings, "captcha_required_for_registration", True)
    # 自建算术验证码：先取题，算出答案后连同 token 一起回传。
    challenge = (await client.get("/api/auth/captcha")).json()
    a, b = challenge["question"].replace("= ?", "").split("+")
    answer = str(int(a.strip()) + int(b.strip()))
    r = await client.post(
        "/api/auth/register",
        json={
            **_payload(email="captcha3@example.com", username="captcha3"),
            "captcha_token": challenge["token"],
            "captcha_answer": answer,
        },
    )
    assert r.status_code in (201, 200)


def test_default_verifier_is_self_hosted() -> None:
    assert settings.captcha_verifier.endswith("SelfHostedCaptchaVerifier")
    v = _load_verifier()
    assert hasattr(v, "verify")


def test_load_verifier_rejects_bad_path() -> None:
    """A dotted path that doesn't resolve should fail loud at call time."""
    import pytest

    from app.core import captcha

    original = captcha.settings.captcha_verifier
    try:
        captcha.settings.captcha_verifier = "no.such.module.Foo"
        with pytest.raises(RuntimeError):
            captcha._load_verifier()
    finally:
        captcha.settings.captcha_verifier = original
