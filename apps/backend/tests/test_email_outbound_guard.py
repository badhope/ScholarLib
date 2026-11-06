"""外发邮件总闸：开发阶段默认关闭，任何真实投递路径都必须被挡住。

背景：生产库里有 37 个真实用户邮箱，一旦 .env 里遗留组邮箱 SMTP 授权码，
注册/审稿/裁决等业务流程就会把邮件发到真人收件箱。本测试保证：
只要没有显式 ``RUBBISH_EMAIL_OUTBOUND_ENABLED=true``，就不会有 SMTP 连接。
"""

from __future__ import annotations

import pytest

from app.core import email as email_mod
from app.core.config import settings

REAL_RECIPIENT = "real-person@example.com"


def _configure_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    """模拟「凭据齐全、backend=smtp」的最危险配置。"""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(settings, "email_smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "email_smtp_port", 25)
    monkeypatch.setattr(settings, "email_smtp_username", "group@example.com")
    monkeypatch.setattr(settings, "email_smtp_password", "an-auth-code")
    monkeypatch.setattr(settings, "email_from_address", "group@example.com")
    monkeypatch.setattr(settings, "email_smtp_use_tls", False)
    monkeypatch.setattr(settings, "email_smtp_starttls", False)


@pytest.fixture
def outbound_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "email_outbound_enabled", False)
    email_mod.reset_email_sender()
    yield
    email_mod.reset_email_sender()


class _ExplodingSMTP:
    """任何连接尝试都视为护栏失效。"""

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("外发总闸关闭时不应发生任何 SMTP 连接")


def _direct_sender() -> email_mod.SMTPEmailSender:
    return email_mod.SMTPEmailSender(
        host="smtp.example.com",
        port=25,
        username="group@example.com",
        password="an-auth-code",
        from_addr="group@example.com",
        use_tls=False,
        starttls=False,
        retries=0,
    )


def test_default_setting_is_off() -> None:
    """类级默认值必须是 False，防止有人把生产默认改回「可发信」。"""
    field = type(settings).model_fields["email_outbound_enabled"]
    assert field.default is False


def test_sender_is_console_even_with_full_smtp_config(monkeypatch, outbound_off) -> None:
    _configure_smtp(monkeypatch)
    assert isinstance(email_mod.get_email_sender(), email_mod.ConsoleEmailSender)


def test_smtp_configured_reports_false_when_guard_closed(monkeypatch, outbound_off) -> None:
    _configure_smtp(monkeypatch)
    assert email_mod.smtp_configured() is False


@pytest.mark.asyncio
async def test_direct_smtp_sender_never_connects(monkeypatch, outbound_off) -> None:
    _configure_smtp(monkeypatch)
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _ExplodingSMTP)
    monkeypatch.setattr(email_mod.smtplib, "SMTP_SSL", _ExplodingSMTP)
    await _direct_sender().send(to=REAL_RECIPIENT, subject="测试", body="正文")


@pytest.mark.asyncio
async def test_pool_sender_never_connects(monkeypatch, outbound_off) -> None:
    _configure_smtp(monkeypatch)
    monkeypatch.setattr(email_mod.smtplib, "SMTP_SSL", _ExplodingSMTP)
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _ExplodingSMTP)
    pool = email_mod.SmtpPoolEmailSender(
        [
            email_mod.SmtpAccount(
                host="smtp.example.com",
                port=465,
                username="group@example.com",
                password="an-auth-code",
                from_address="group@example.com",
            )
        ],
        retries=0,
    )
    await pool.send(to=REAL_RECIPIENT, subject="测试", body="正文")


@pytest.mark.asyncio
async def test_smtp_self_check_skips_probe(monkeypatch, outbound_off) -> None:
    _configure_smtp(monkeypatch)
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _ExplodingSMTP)
    ok, detail = await email_mod.verify_smtp_connection()
    assert ok is False
    assert "总闸" in detail


@pytest.mark.asyncio
async def test_explicit_opt_in_still_delivers(monkeypatch) -> None:
    """显式授权后业务照常可用（fake transport，不产生真实外发）。"""
    _configure_smtp(monkeypatch)
    monkeypatch.setattr(settings, "email_outbound_enabled", True)
    delivered: list[str] = []

    class _FakeSMTP:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):  # noqa: ANN002
            return False

        def starttls(self, **kwargs):  # noqa: ANN003
            pass

        def login(self, *args):  # noqa: ANN002
            pass

        def send_message(self, msg):
            delivered.append(msg["To"])

    monkeypatch.setattr(email_mod.smtplib, "SMTP", _FakeSMTP)
    await _direct_sender().send(to=REAL_RECIPIENT, subject="测试", body="正文")
    assert delivered == [REAL_RECIPIENT]
