"""Email delivery layer.

Design goals (0.8.0):

- **Fill-in-the-code ready**: with SMTP credentials present in the env, mail
  works with no code change; without them, everything degrades silently to
  the console sender so registration/login flows never break.
- **Non-blocking**: ``smtplib`` is synchronous, so every send is offloaded to
  a worker thread (``asyncio.to_thread``). A slow relay can never stall the
  request that triggered it.
- **Retry with backoff**: transient network errors are retried
  ``email_smtp_retries`` times (default 2) with exponential backoff.
- **HTML + text**: every message carries both parts; the HTML shell is the
  same editorial card used on the site (no external assets, inline CSS).
- **Testable**: ``EmailSender`` is a Protocol; tests swap in a fake via
  ``app.core.email._sender`` or ``reset_email_sender()``.

Providers: Mailgun / SendGrid / SES / Postmark / QQ 邮箱 / 163 / 腾讯企业邮 all
speak SMTP, so one backend covers them. Ports: 465 = implicit TLS
(``email_smtp_use_tls=true``), 587 = STARTTLS (``use_tls=false`` +
``starttls=true``), 25 = plain (not recommended).
"""

from __future__ import annotations

import asyncio
import json
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("rubbish.email")

# 只接收、不发送的联系邮箱。它没有 SMTP 授权，不能作为 From/登录身份。
# 这里硬性拦住，避免以后有人把页脚联系邮箱误填进 SMTP_FROM。
CONTACT_ONLY_ADDRESSES: frozenset[str] = frozenset({"rubbish_eb@qun.mail.163.com"})


@runtime_checkable
class EmailSender(Protocol):
    """Send a transactional email to one recipient."""

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        html: str | None = None,
    ) -> None: ...


class ConsoleEmailSender:
    """Dev / test sender — writes the message to the log stream."""

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        html: str | None = None,
    ) -> None:
        logger.info(
            "email_sent_console",
            to=to,
            subject=subject,
            body_preview=body[:200],
        )


class SMTPEmailSender:
    _bypass_outbound_guard: bool = False
    """SMTP relay sender with timeout, retry and thread offloading."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_addr: str,
        from_name: str = "Rubbish",
        use_tls: bool = True,
        starttls: bool = False,
        timeout: int = 15,
        retries: int = 2,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_addr = from_addr
        self._from_name = from_name
        self._use_tls = use_tls
        self._starttls = starttls
        self._timeout = timeout
        self._retries = retries

    def _build_message(self, to: str, subject: str, body: str, html: str | None) -> EmailMessage:
        if self._from_addr.strip().lower() in CONTACT_ONLY_ADDRESSES:
            logger.error(
                "email_from_address_is_receive_only",
                from_address=self._from_addr,
                reason="contact mailbox cannot be used as SMTP sender",
            )
            raise RuntimeError("Contact mailbox is receive-only and cannot send mail")
        msg = EmailMessage()
        msg["From"] = (
            f"{self._from_name} <{self._from_addr}>" if self._from_name else self._from_addr
        )
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        if html is not None:
            msg.add_alternative(html, subtype="html")
        return msg

    def _send_sync(self, msg: EmailMessage) -> None:
        """Blocking SMTP round-trip (runs inside a worker thread)."""
        if self._use_tls:
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                self._host,
                self._port,
                timeout=self._timeout,
                context=ssl.create_default_context(),
            )
        else:
            client = smtplib.SMTP(self._host, self._port, timeout=self._timeout)
        with client:
            if not self._use_tls and self._starttls:
                client.starttls(context=ssl.create_default_context())
            if self._username and self._password:
                client.login(self._username, self._password)
            client.send_message(msg)

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        html: str | None = None,
    ) -> None:
        # 外发总闸：默认拦截一切真实投递。实例可携带 _bypass_outbound_guard
        # （仅恭喜邮件通道由主编显式授权使用），其余路径一律受闸。
        if not settings.email_outbound_enabled and not getattr(
            self, "_bypass_outbound_guard", False
        ):
            logger.warning(
                "email_outbound_blocked",
                to=to,
                subject=subject,
                reason="RUBBISH_EMAIL_OUTBOUND_ENABLED=false",
            )
            return
        msg = self._build_message(to, subject, body, html)
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                await asyncio.to_thread(self._send_sync, msg)
                logger.info("email_sent_smtp", to=to, subject=subject, attempt=attempt + 1)
                return
            except (OSError, smtplib.SMTPException) as exc:
                last_error = exc
                logger.warning(
                    "email_smtp_attempt_failed",
                    to=to,
                    attempt=attempt + 1,
                    retries=self._retries,
                    error=str(exc)[:200],
                )
                if attempt < self._retries:
                    await asyncio.sleep(2**attempt)
        logger.error("email_smtp_gave_up", to=to, subject=subject, error=str(last_error)[:200])
        raise last_error if last_error else RuntimeError("smtp send failed")


_sender: EmailSender | None = None
_congrat_sender: EmailSender | None = None


@dataclass(frozen=True)
class SmtpAccount:
    """One sender identity in the outbound pool."""

    host: str
    port: int
    username: str
    password: str
    from_address: str
    from_name: str = "Rubbish"
    use_tls: bool = True
    starttls: bool = False

    @property
    def key(self) -> str:
        return f"{self.username}@{self.host}"


def _account_from_settings() -> SmtpAccount:
    return SmtpAccount(
        host=settings.email_smtp_host,
        port=settings.email_smtp_port,
        username=settings.email_smtp_username,
        password=settings.email_smtp_password,
        from_address=settings.email_from_address,
        from_name=settings.email_from_name,
        use_tls=settings.email_smtp_use_tls,
        starttls=settings.email_smtp_starttls,
    )


def parse_smtp_accounts(raw: str) -> list[SmtpAccount]:
    """Parse ``email_smtp_accounts`` (JSON array) into account objects.

    Malformed input is logged and ignored rather than raised: a typo in one
    optional env var must not take the whole mail subsystem down.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except ValueError:
        logger.warning("email_smtp_accounts_invalid_json", length=len(raw))
        return []
    if not isinstance(items, list):
        logger.warning("email_smtp_accounts_not_a_list")
        return []
    accounts: list[SmtpAccount] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        host = str(item.get("host") or "").strip()
        username = str(item.get("username") or "").strip()
        from_address = str(item.get("from_address") or username).strip()
        if not host or not from_address:
            continue
        try:
            port = int(item.get("port") or 465)
        except (TypeError, ValueError):
            port = 465
        accounts.append(
            SmtpAccount(
                host=host,
                port=port,
                username=username,
                password=str(item.get("password") or ""),
                from_address=from_address,
                from_name=str(item.get("from_name") or settings.email_from_name),
                use_tls=bool(item.get("use_tls", True)),
                starttls=bool(item.get("starttls", False)),
            )
        )
    return accounts


def configured_accounts() -> list[SmtpAccount]:
    """Accounts available for delivery, pool first, single account as fallback."""
    pool = parse_smtp_accounts(settings.email_smtp_accounts)
    if pool:
        return pool
    if settings.email_smtp_host and settings.email_from_address:
        return [_account_from_settings()]
    return []


class SmtpPoolEmailSender:
    _bypass_outbound_guard: bool = False
    """Round-robin SMTP sender with per-account circuit breaking.

    Why a pool: a single free mailbox (QQ/126) throttles aggressively and
    sometimes rejects connections outright. Rotating between two identities
    spreads the load and keeps verification / reset mail flowing when one
    provider has a bad minute. Failures are counted per account; after
    ``breaker_threshold`` consecutive failures the account is parked for
    ``breaker_cooldown`` seconds and the next account takes over.

    The rotation is deliberately *sticky-fair*: every send advances the
    cursor, so two accounts get roughly half the traffic each.
    """

    def __init__(
        self,
        accounts: list[SmtpAccount],
        *,
        timeout: int = 15,
        retries: int = 1,
        breaker_threshold: int = 2,
        breaker_cooldown: int = 180,
    ) -> None:
        if not accounts:
            raise ValueError("SmtpPoolEmailSender needs at least one account")
        self._accounts = accounts
        self._timeout = timeout
        self._retries = retries
        self._breaker_threshold = breaker_threshold
        self._breaker_cooldown = breaker_cooldown
        self._cursor = 0
        self._failures: dict[str, int] = {a.key: 0 for a in accounts}
        self._cooldown_until: dict[str, float] = {a.key: 0.0 for a in accounts}

    @property
    def account_count(self) -> int:
        return len(self._accounts)

    def _available(self, now: float) -> list[SmtpAccount]:
        live = [a for a in self._accounts if self._cooldown_until[a.key] <= now]
        # All accounts parked (total provider outage): try them all anyway
        # rather than fail fast — better one slow success than none.
        return live or list(self._accounts)

    def _order(self, now: float) -> list[SmtpAccount]:
        live = self._available(now)
        n = len(live)
        start = self._cursor % n
        self._cursor = (self._cursor + 1) % max(1, len(self._accounts))
        return live[start:] + live[:start]

    def _record_success(self, account: SmtpAccount) -> None:
        self._failures[account.key] = 0
        self._cooldown_until[account.key] = 0.0

    def _record_failure(self, account: SmtpAccount) -> None:
        self._failures[account.key] = self._failures[account.key] + 1
        if self._failures[account.key] >= self._breaker_threshold:
            self._cooldown_until[account.key] = time.monotonic() + self._breaker_cooldown
            logger.warning(
                "email_account_parked",
                account=account.key,
                failures=self._failures[account.key],
                cooldown=self._breaker_cooldown,
            )

    def _send_sync(self, account: SmtpAccount, msg: EmailMessage) -> None:
        if account.use_tls:
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                account.host,
                account.port,
                timeout=self._timeout,
                context=ssl.create_default_context(),
            )
        else:
            client = smtplib.SMTP(account.host, account.port, timeout=self._timeout)
        with client:
            if not account.use_tls and account.starttls:
                client.starttls(context=ssl.create_default_context())
            if account.username and account.password:
                client.login(account.username, account.password)
            client.send_message(msg)

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        html: str | None = None,
    ) -> None:
        if not settings.email_outbound_enabled and not getattr(
            self, "_bypass_outbound_guard", False
        ):
            logger.warning(
                "email_outbound_blocked",
                to=to,
                subject=subject,
                reason="RUBBISH_EMAIL_OUTBOUND_ENABLED=false",
            )
            return
        last_error: Exception | None = None
        order = self._order(time.monotonic())
        for account in order:
            sender = SMTPEmailSender(
                host=account.host,
                port=account.port,
                username=account.username,
                password=account.password,
                from_addr=account.from_address,
                from_name=account.from_name,
                use_tls=account.use_tls,
                starttls=account.starttls,
                timeout=self._timeout,
                retries=self._retries,
            )
            # 内层实例必须继承外层的外发许可：否则恭喜通道（外层 bypass）
            # 会被内层 guard 静默拦截，且 guard 静默 return 会让 pool 误记成功。
            if getattr(self, "_bypass_outbound_guard", False):
                sender._bypass_outbound_guard = True
            try:
                await sender.send(to=to, subject=subject, body=body, html=html)
                self._record_success(account)
                logger.info("email_sent_pool", to=to, account=account.key)
                return
            except Exception as exc:
                last_error = exc
                self._record_failure(account)
                logger.warning(
                    "email_account_failed",
                    account=account.key,
                    error=str(exc)[:200],
                )
        logger.error(
            "email_pool_gave_up",
            to=to,
            subject=subject,
            accounts=len(order),
            error=str(last_error)[:200],
        )
        raise last_error if last_error else RuntimeError("smtp pool send failed")


def smtp_configured() -> bool:
    """True only when real delivery is both configured **and** authorised."""
    return bool(
        settings.email_outbound_enabled
        and settings.email_backend == "smtp"
        and configured_accounts()
    )


def get_email_sender() -> EmailSender:
    """Return the configured sender (lazily constructed, test-swappable).

    Hard guard: outbound delivery is OFF unless the operator explicitly
    enables it. A stray group-mailbox SMTP credential in .env must never
    turn a development box into a mass-mailer.
    """
    global _sender
    if not settings.email_outbound_enabled:
        if not isinstance(_sender, ConsoleEmailSender):
            logger.warning(
                "email_outbound_disabled",
                reason="RUBBISH_EMAIL_OUTBOUND_ENABLED=false",
            )
            _sender = ConsoleEmailSender()
        return _sender
    if _sender is not None:
        return _sender

    if settings.email_backend == "console" or settings.environment == "test":
        _sender = ConsoleEmailSender()
        return _sender

    if settings.email_backend == "smtp":
        accounts = configured_accounts()
        if not accounts:
            logger.warning(
                "email_smtp_misconfigured_fallback_to_console",
                reason="missing host or from_address",
            )
            _sender = ConsoleEmailSender()
            return _sender

        if len(accounts) > 1:
            _sender = SmtpPoolEmailSender(
                accounts,
                timeout=settings.email_smtp_timeout,
                retries=min(settings.email_smtp_retries, 1),
                breaker_threshold=settings.email_smtp_breaker_threshold,
                breaker_cooldown=settings.email_smtp_breaker_cooldown,
            )
            logger.info("email_sender_pool", accounts=len(accounts))
            return _sender

        account = accounts[0]
        _sender = SMTPEmailSender(
            host=account.host,
            port=account.port,
            username=account.username,
            password=account.password,
            from_addr=account.from_address,
            from_name=account.from_name,
            use_tls=settings.email_smtp_use_tls,
            starttls=settings.email_smtp_starttls,
            timeout=settings.email_smtp_timeout,
            retries=settings.email_smtp_retries,
        )
        return _sender

    logger.warning("email_unknown_backend_fallback_to_console", backend=settings.email_backend)
    _sender = ConsoleEmailSender()
    return _sender


def reset_email_sender() -> None:
    """Test helper: clear the cached sender so the next call re-reads settings."""
    global _sender
    _sender = None


def get_congrat_sender() -> EmailSender:
    """录用祝贺专用通道（主编单独授权，不受外发总闸约束）。

    ``RUBBISH_EMAIL_CONGRAT_ENABLED=true`` 且 SMTP 配置完整时走真实投递；
    否则降级 console——与 get_email_sender 的护栏语义一致，只是开关独立。
    """
    global _congrat_sender
    if not settings.email_congrat_enabled:
        if not isinstance(_congrat_sender, ConsoleEmailSender):
            logger.warning(
                "congrat_email_disabled",
                reason="RUBBISH_EMAIL_CONGRAT_ENABLED=false",
            )
            _congrat_sender = ConsoleEmailSender()
        return _congrat_sender
    if _congrat_sender is not None and not isinstance(_congrat_sender, ConsoleEmailSender):
        return _congrat_sender
    accounts = configured_accounts()
    if not accounts:
        logger.warning("congrat_email_no_smtp_fallback_console")
        _congrat_sender = ConsoleEmailSender()
        return _congrat_sender
    if len(accounts) > 1:
        _congrat_sender = SmtpPoolEmailSender(
            accounts,
            timeout=settings.email_smtp_timeout,
            retries=min(settings.email_smtp_retries, 1),
            breaker_threshold=settings.email_smtp_breaker_threshold,
            breaker_cooldown=settings.email_smtp_breaker_cooldown,
        )
    else:
        account = accounts[0]
        _congrat_sender = SMTPEmailSender(
            host=account.host,
            port=account.port,
            username=account.username,
            password=account.password,
            from_addr=account.from_address,
            from_name=account.from_name,
            use_tls=settings.email_smtp_use_tls,
            starttls=settings.email_smtp_starttls,
            timeout=settings.email_smtp_timeout,
            retries=settings.email_smtp_retries,
        )
    # 主编已通过 CONGRAT 开显式授权录用祝贺邮件：该实例旁路外发总闸。
    _congrat_sender._bypass_outbound_guard = True
    logger.info("congrat_sender_ready", accounts=len(accounts))
    return _congrat_sender


def reset_congrat_sender() -> None:
    """Test helper: clear the cached congrat sender."""
    global _congrat_sender
    _congrat_sender = None


async def verify_smtp_connection() -> tuple[bool, str]:
    """Startup/ops self-check: probe every configured account.

    Returns ``(ok, detail)``. ``ok`` is True when at least one account
    answers, so a single throttled mailbox does not read as "mail is down".
    Never raises — callers log the result.
    """
    if not settings.email_outbound_enabled:
        return False, "外发总闸已关闭（RUBBISH_EMAIL_OUTBOUND_ENABLED=false），不探测 SMTP"
    accounts = configured_accounts()
    if not accounts:
        return False, "SMTP 未配置（email_backend=console 或缺少 host/from）"
    results: list[str] = []
    any_ok = False
    for account in accounts:
        try:
            await asyncio.to_thread(_probe_account, account)
            any_ok = True
            results.append(f"{account.key} 连接成功")
        except Exception as exc:
            results.append(f"{account.key} 失败：{str(exc)[:120]}")
    return any_ok, "；".join(results)


def _probe_account(account: SmtpAccount) -> None:
    if account.use_tls:
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            account.host,
            account.port,
            timeout=settings.email_smtp_timeout,
            context=ssl.create_default_context(),
        )
    else:
        client = smtplib.SMTP(account.host, account.port, timeout=settings.email_smtp_timeout)
    with client:
        if not account.use_tls and account.starttls:
            client.starttls(context=ssl.create_default_context())
        if account.username and account.password:
            client.login(account.username, account.password)
        client.noop()


def _probe_smtp() -> None:
    _probe_account(_account_from_settings())
