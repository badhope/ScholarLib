"""Application configuration via pydantic-settings v2.

All settings are read from environment variables prefixed ``RUBBISH_`` or
from a ``.env`` file at the backend root. Secrets (``secret_key``,
``admin_password``) have no defaults and must be provided in every non-test
environment; the ``validate_secrets`` model validator enforces this.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Test-only secrets. Never used outside the test environment; exist solely so
# the test suite can run without manual .env configuration. Both values are
# also members of the weak-secret blocklists below, so any non-test config
# that inherits them is rejected at startup.
_TEST_SECRET_KEY = "TEST_ONLY_DO_NOT_USE_IN_PRODUCTION_0123456789abcdef"  # nosec B105
_TEST_ADMIN_PASSWORD = "test_admin_password_12345"  # nosec B105

# Placeholder values that must never appear in a real environment.
_WEAK_SECRET_KEYS = frozenset(
    {
        "",
        "change-me-in-production-use-openssl-rand-hex-32",
        "<generate-with-openssl-rand-hex-32>",
        "REPLACE_ME_WITH_OPENSSL_RAND_HEX_32",
        _TEST_SECRET_KEY,
    }
)
_WEAK_ADMIN_PASSWORDS = frozenset(
    {
        "",
        "changeme",
        "change-me",
        "<change-me-at-least-12-chars>",
        "REPLACE_ME_WITH_STRONG_PASSWORD",
        "admin",
        "password",
        "admin123",
        _TEST_ADMIN_PASSWORD,
    }
)


class Settings(BaseSettings):
    """Strongly-typed application settings.

    All env vars are prefixed ``RUBBISH_`` (e.g. ``RUBBISH_DATABASE_URL``).
    Nested fields use ``__`` separator (e.g. ``RUBBISH_DB__POOL_SIZE``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RUBBISH_",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application identity ---
    app_name: str = "Rubbish API"
    environment: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = False

    # --- Tenancy ---
    # single = one tenant per deployment (typical self-hosted)
    # multi  = many tenants resolved from host header (SaaS)
    tenancy_mode: Literal["single", "multi"] = "single"
    # In single mode, this is the slug of the bootstrap tenant created on
    # first startup. Leave as default unless you want a custom slug.
    bootstrap_tenant_slug: str = "default"

    # --- Database (PostgreSQL only �?RLS requires PG) ---
    database_url: str = "postgresql+asyncpg://rubbish:rubbish@localhost:5432/rubbish"
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=20, ge=0)
    db_pool_recycle: int = Field(default=1800, ge=0, description="0 = never recycle")
    db_pool_pre_ping: bool = True
    db_pool_timeout: int = Field(default=30, ge=1)
    db_startup_retries: int = Field(default=5, ge=0)
    db_startup_retry_delay: float = Field(default=2.0, ge=0.1)

    # --- Redis (cache + rate limit, planned �?currently unused) ---
    redis_url: str = ""

    # --- JWT / Auth ---
    secret_key: str = Field(default="")
    # M3 hardening: comma-separated list of *previous* signing keys (newest
    # first). Tokens minted before a rotation verify against this list so
    # existing sessions keep working until they expire. Set via
    # ``RUBBISH_PREVIOUS_SECRET_KEYS``. Empty string is fine when no
    # rotation is in flight.
    previous_secret_keys: str = Field(default="")
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    # M3 加固：JWT 签名算法收窄为枚举。项目签名/验签全部经由
    # app.core.tokens / app.core.key_rotation / app.api.oidc，实际只支持
    # HMAC（HS*，配合 secret_key）与 RS256/ES256（非对称密钥部署）。
    # pydantic Literal 校验在启动时生效：配置了枚举之外的算法（如
    # "none" 或拼写错误）直接拒绝启动，而不是带病运行到运行时才炸。
    algorithm: Literal["HS256", "HS384", "HS512", "RS256", "ES256"] = "HS256"
    refresh_token_cookie_name: str = "rubbish_refresh"
    # Symmetric key for at-rest encryption of secrets we cannot hash (i.e.
    # TOTP seeds, where we need to recover the cleartext to compute the
    # expected code at verify time). 32-byte url-safe base64 (Fernet format).
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Rotate by setting the new key as primary and the old key as fallback
    # in fernet_keys (comma separated, NEWEST FIRST).
    fernet_key: str = Field(default="")
    fernet_keys: str = Field(default="")  # comma-separated for rotation
    refresh_token_cookie_secure: bool | None = None
    refresh_token_cookie_samesite: str = "strict"

    # --- CSRF ---
    # Double-submit-cookie protection for state-changing requests on
    # cookie-authenticated endpoints. Off by default for backward
    # compatibility; flip on once the SPA echoes ``X-CSRF-Token``.
    csrf_enabled: bool = False

    # --- WebAuthn / Passkeys ---
    # Relying Party identifier — typically the domain serving the app
    # (e.g. "rubbish.example.com" or "localhost" for dev).
    webauthn_rp_id: str = "localhost"
    # Human-readable RP name, e.g. "Rubbish".
    webauthn_rp_name: str = "Rubbish"
    # Expected origin for WebAuthn ceremonies. Must match the origin
    # the browser sends — typically the SPA base URL (e.g. "http://localhost:5173").
    webauthn_origin: str = "http://localhost:5173"

    # --- Admin 2FA policy ---
    # When True, callers reaching /api/admin/* must have TOTP enabled
    # on their account. Off by default so existing admin accounts do
    # not get locked out at deploy time; flip on once the operator
    # has rolled out 2FA to all admins.
    require_2fa_for_admin: bool = False

    # --- CAPTCHA policy ---
    # When True, /api/auth/register demands a captcha_token field and
    # runs it through the verifier at ``captcha_verifier``. Default
    # off so dev / CI / unit tests do not need an external provider.
    captcha_required_for_registration: bool = False
    # Dotted path to a verifier. Empty -> a dev passthrough that
    # accepts everything (with a single warning log).
    # 默认使用自建算术题，不依赖第三方 SaaS、不产生费用。
    captcha_verifier: str = "app.core.captcha.SelfHostedCaptchaVerifier"

    # --- Email ---
    # ``console`` logs to stdout (dev/test). ``smtp`` uses the relay below.
    # Mailgun / SendGrid / SES / Postmark all expose an SMTP relay, so this
    # one backend covers every mainstream transactional provider.
    email_backend: Literal["console", "smtp"] = "console"
    # 外发总闸（开发阶段护栏）：默认 **关闭**。即便误填了真实的组邮箱
    # SMTP 授权码，也只把邮件写进日志，绝不投递到真实收件人。
    # 只有运维显式设置 RUBBISH_EMAIL_OUTBOUND_ENABLED=true 才允许真实发信；
    # 上线前请确认收件人范围、并取得负责人同意后再打开。
    email_outbound_enabled: bool = False
    # 恭喜邮件独立开关：录用/接收后的作者祝贺邮件不受总闸约束，由主编
    # 单独授权（2026-11-06 主编指令：发布成功要发恭喜邮件）。其余类型
    # （验证码/催审/裁决/补审）仍受 email_outbound_enabled 管控。
    email_congrat_enabled: bool = False
    # 审稿工作流邮件摘要（指派/催审/裁决/认领结果）独立开关。
    # 即便打开，也只有在 SMTP 已配置且 email_outbound_enabled=true 时才真正投递；
    # 未配置时仍会把摘要落库（email_digest_records.status='skipped_no_smtp'），
    # 便于运维核对"本该发什么"，而不是假装已发。
    email_review_digest_enabled: bool = True
    email_from_address: str = "no-reply@rubbish.local"
    email_from_name: str = "Rubbish"
    email_smtp_host: str = ""
    email_smtp_port: int = Field(default=587, ge=1, le=65535)
    email_smtp_username: str = ""
    email_smtp_password: str = ""
    email_smtp_use_tls: bool = False
    email_smtp_starttls: bool = True
    # 发信超时（秒）：SMTP 握手/发送的网络超时，避免请求被挂死。
    email_smtp_timeout: int = Field(default=15, ge=3, le=120)
    # 失败重试次数（不含首次）：网络抖动时自动重试，全部失败才静默降级。
    email_smtp_retries: int = Field(default=2, ge=0, le=5)
    # 多账号发信池（JSON 数组）。每项字段：
    # {"host","port","username","password","from_address","from_name",
    #  "use_tls","starttls"}。配置后优先于上面的单账号字段，按轮询分发；
    # 某个账号连续失败会被暂时摘除（熔断），其余账号继续发信，
    # 因此单个邮箱被服务商限流不会让全站邮件停摆。
    email_smtp_accounts: str = ""
    # 账号熔断冷却（秒）：连续失败达到 email_smtp_breaker_threshold 次后
    # 暂停使用该账号这么久。取值偏短，避免一次网络抖动把账号长期摘除。
    email_smtp_breaker_cooldown: int = Field(default=180, ge=10, le=3600)
    email_smtp_breaker_threshold: int = Field(default=2, ge=1, le=10)
    # 同一收件地址的发信冷却（秒）：验证邮件 / 重置邮件共用。
    # 超限时仍然返回 200（不泄露账号是否存在），只是不再真正发信。
    # 0 = 关闭冷却（仅测试用）。默认 45 秒：够挡住连点与脚本，
    # 又不至于让「没收到，再点一次」的正常用户白等。
    email_per_address_cooldown: int = Field(default=45, ge=0, le=3600)
    email_per_address_window_minutes: int = Field(default=30, ge=1, le=1440)
    email_per_address_limit: int = Field(default=6, ge=1, le=100)
    email_verification_expire_hours: int = Field(default=24, ge=1)
    password_reset_expire_minutes: int = Field(default=60, ge=1)
    # 站内信/邮件共用的站点名，出现在邮件标题与正文。
    site_name: str = "Rubbish"
    # 进程内定时任务（审稿催办等）。单节点部署默认开启；多节点部署时
    # 应只在一个实例上开启，或用外部调度器触发 admin 端点。
    scheduler_enabled: bool = True
    # 首次运行延迟（秒）。线上曾用 10**9 直接把催办永久挂起，这是事故补丁
    # 而不是配置；现在改成可配，默认 5 分钟，避开启动迁移窗口。
    scheduler_startup_delay_seconds: int = Field(default=300, ge=0, le=86400)
    # 两轮之间的间隔（秒）。催办最小窗口是 3 天，6 小时足够。
    scheduler_interval_seconds: int = Field(default=6 * 60 * 60, ge=60, le=7 * 24 * 60 * 60)

    # --- Frontend base URL ---
    # Used to build deep-link URLs in transactional emails (verify-email,
    # password-reset). If unset, links use a relative path so the SPA can
    # route them client-side �?but most deployments should set this so
    # links work in any email client.
    frontend_base_url: str = ""

    # --- OIDC SSO ---
    # ``oidc_enabled`` flips the /api/auth/oidc/* routes on. Provider
    # configuration is per-provider (Google / GitHub / generic), loaded
    # from the env vars below. If multiple providers are needed, repeat
    # the vars with the provider slug in the field name.
    # See docs/integrations.md for the per-provider setup walkthrough.
    oidc_enabled: bool = False
    oidc_provider: str = ""  # e.g. "google" / "github" / "keycloak"
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_authorize_url: str = ""
    oidc_token_url: str = ""
    oidc_userinfo_url: str = ""
    oidc_scopes: str = "openid email profile"
    # After OIDC callback, where to redirect the browser. We append
    # ``?access_token=...&refresh_token=...`` (refresh also set as cookie).
    oidc_redirect_url: str = ""  # e.g. https://app.example.com/auth/oidc/callback
    # PKCE (RFC 7636) is REQUIRED on every deployment by default. The
    # one-shot code_verifier is stored in an httpOnly cookie and
    # exchanged for the auth code in /callback. Disabling this setting
    # is only for legacy IdPs that don't implement S256; do not turn
    # it off in production.
    oidc_pkce_required: bool = True
    # Human-readable label shown on the login button (e.g. "Google" /
    # "GitHub" / "University SSO"). Empty string falls back to the
    # provider slug capitalized at the API boundary, so the SPA never
    # has to guess at a label.
    oidc_provider_label: str = ""

    # --- Bibliographic metadata ---
    # Used by the ingest module to identify itself to Crossref (their API
    # policy asks callers to include a mailto in the User-Agent header).
    # Optional �?falls back to a placeholder if not set.
    crossref_mailto: str = ""

    # --- DataCite DOI registration ---
    # Empty URL = DataCite disabled; the DOI module returns 501 Not
    # Implemented. At minimum, ``datacite_api_url``, ``datacite_prefix``
    # and ``datacite_api_key`` must be set for DOI minting to work.
    datacite_api_url: str = ""
    # DOI prefix issued by DataCite (e.g. "10.12345").
    datacite_prefix: str = ""
    # Base64-encoded "<username>:<password>" for HTTP Basic Auth against
    # the DataCite MDS API. Generate with:
    #   echo -n "username:password" | base64
    datacite_api_key: str = ""

    # --- 本站刊号 ---
    # 六位刊物代码：站内编号 R-<code>-<YYYYMMDD>-<四位流水>。
    # 这不是 DOI；官方 DOI 仍由作者决定是否另行注册。
    publication_code: str = "000001"

    # --- CORS / Trusted hosts ---
    cors_origins: str = "http://localhost:5173,http://localhost"
    allowed_hosts: str = "localhost,127.0.0.1"
    trusted_proxies_count: int = Field(default=0, ge=0)

    # --- Rate limiting ---
    rate_limit_per_minute: int = Field(default=120, ge=1)

    # --- Public surface ---
    # Canonical public origin used to build absolute URLs in the sitemap,
    # robots.txt and per-page metadata. Empty = infer from the request
    # (behind a TLS-terminating proxy that yields http://app:8080, so
    # production deployments should set this explicitly).
    public_base_url: str = ""
    # Prometheus /metrics is unauthenticated and exposes route-level
    # traffic shapes. Off by default; flip on only on a private network.
    metrics_public: bool = False

    # --- Logging ---
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    json_logs: bool = False

    # --- Error monitoring (Sentry, optional) ---
    # Empty DSN = monitoring disabled; the SDK is never imported in that
    # case, so self-hosters pay nothing for a feature they don't use.
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    sentry_profiles_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    # Scrub PII by default — submissions can carry unpublished manuscripts
    # and reviewer identities, which must not leak to a third party.
    sentry_send_default_pii: bool = False

    # --- Full-text search (Meilisearch, optional) ---
    # Empty URL = Meilisearch disabled; catalog search falls back to the
    # built-in DB ILIKE search. Same fail-open philosophy as Sentry above:
    # the SDK is never imported when unconfigured.
    meilisearch_url: str = ""
    meilisearch_api_key: str = ""
    meilisearch_index_prefix: str = "rubbish"

    # --- Admin bootstrap ---
    admin_email: str = "admin@rubbish.local"
    admin_username: str = "admin"
    admin_password: str = Field(default="")

    # --- File storage ---
    # local = 文件系统（默认，零依赖）；s3 = S3 兼容对象存储
    # （AWS S3 / MinIO / R2 / OSS），需要 uv sync --extra s3。
    storage_backend: str = Field(default="local", pattern=r"^(local|s3)$")
    storage_path: str = "/data/uploads"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""  # MinIO/R2 等自建端点；AWS 官方留空
    s3_region: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> str:
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        if isinstance(value, str):
            import json

            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return ",".join(str(item) for item in parsed)
            except json.JSONDecodeError:
                pass
        return str(value)

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, value: object) -> str:
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return str(value)

    @model_validator(mode="after")
    def validate_secrets(self) -> "Settings":
        """Enforce strong secrets in every non-test environment."""
        # Test environment: auto-fill test secrets if not provided.
        if self.environment == "test":
            if not self.secret_key:
                self.secret_key = _TEST_SECRET_KEY
            if not self.admin_password:
                self.admin_password = _TEST_ADMIN_PASSWORD
            if not self.fernet_key:
                # Deterministic test key (DO NOT use in production).
                # Pinned to a value generated by Fernet.generate_key() so the
                # test suite can encrypt/decrypt deterministically across runs.
                # Must be a valid 32-byte url-safe base64 string.
                self.fernet_key = "88Q2Rl3-2UqzRfG_3tyKUPUDp9CP81YuJp2dLSkQa_0="
            return self

        # Non-test environments: reject weak/missing secrets.
        if self.secret_key in _WEAK_SECRET_KEYS:
            raise ValueError(
                "RUBBISH_SECRET_KEY is missing or uses a known-weak value. "
                "Generate a strong key with: openssl rand -hex 32"
            )
        if len(self.secret_key) < 32:
            raise ValueError(
                "RUBBISH_SECRET_KEY must be at least 32 characters long. "
                "Generate with: openssl rand -hex 32"
            )

        # M3 rotation: every entry in previous_secret_keys must be a real,
        # non-weak key. We reject weak values and enforce length so a typo
        # in the rotation env var cannot silently disable the verification
        # fallback.
        for raw in self.previous_secret_keys.split(","):
            chunk = raw.strip()
            if not chunk:
                continue
            if chunk in _WEAK_SECRET_KEYS:
                raise ValueError(
                    "RUBBISH_PREVIOUS_SECRET_KEYS contains a weak value. "
                    "Rotate only with real keys generated via: openssl rand -hex 32"
                )
            if len(chunk) < 32:
                raise ValueError(
                    "Every entry in RUBBISH_PREVIOUS_SECRET_KEYS must be at least 32 characters."
                )

        if self.admin_password in _WEAK_ADMIN_PASSWORDS:
            raise ValueError(
                "RUBBISH_ADMIN_PASSWORD is missing or uses a common weak value. "
                "Provide a strong password of at least 12 characters."
            )
        if len(self.admin_password) < 12:
            raise ValueError("RUBBISH_ADMIN_PASSWORD must be at least 12 characters long.")

        # Fernet key is required in non-test environments because TOTP 2FA
        # (M2 hardening) encrypts user secrets at rest with it. Tests get a
        # deterministic key above; production must provide one via env.
        if not self.fernet_key:
            raise ValueError(
                "RUBBISH_FERNET_KEY is missing. Generate with: "
                "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        # Validate the actual Fernet format. An ill-formed key would only
        # fail at first encrypt/decrypt, which is much harder to diagnose.
        try:
            from cryptography.fernet import (
                Fernet,
            )

            Fernet(
                self.fernet_key.encode() if isinstance(self.fernet_key, str) else self.fernet_key
            )
        except Exception as exc:  # InvalidToken / ValueError
            raise ValueError(
                "RUBBISH_FERNET_KEY is not a valid Fernet key (must be 32 url-safe base64 bytes)."
            ) from exc

        # Production-specific checks.
        if self.is_production:
            hosts = self.allowed_hosts_list
            if not hosts or hosts == ["*"]:
                raise ValueError("RUBBISH_ALLOWED_HOSTS must be explicitly set in production")
            if "*" in self.cors_origins_list:
                raise ValueError("CORS wildcard '*' is not allowed in production")

        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_test(self) -> bool:
        return self.environment == "test"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def cors_methods(self) -> list[str]:
        if self.is_production:
            return ["GET", "POST", "PUT", "DELETE", "PATCH"]
        return ["*"]

    @property
    def cors_headers(self) -> list[str]:
        if self.is_production:
            # X-CSRF-Token must be allowed so enabling CSRF protection in
            # production does not break the browser's preflight (CORS) request.
            return ["Authorization", "Content-Type", "X-Tenant-ID", "X-CSRF-Token"]
        return ["*"]

    @property
    def cookie_secure(self) -> bool:
        if self.refresh_token_cookie_secure is not None:
            return self.refresh_token_cookie_secure
        return self.is_production

    @property
    def cookie_samesite(self) -> Literal["lax", "strict", "none"]:
        mode = self.refresh_token_cookie_samesite.lower()
        if mode == "strict":
            return "strict"
        if mode == "lax":
            return "lax"
        if mode == "none":
            return "none"
        return "strict" if self.is_production else "lax"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
