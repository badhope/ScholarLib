"""Pytest fixtures for the base spine tests.

Strategy:
- SQLite in-memory + StaticPool: all sessions share one connection so
  CREATE TABLE in one session is visible to others.
- Replace ``app.core.db.engine`` and ``async_session_factory`` with the
  test versions so the TenantContextMiddleware (which imports the
  factory lazily) also uses the test engine.
- Override ``get_db`` dependency with the test session factory.
- Trigger FastAPI lifespan via ``asgi-lifespan`` so ``load_all()`` runs.
- Reset ``TenantContextMiddleware._single_mode_tenant_id`` between
  tests so the bootstrap tenant is re-created against the fresh table.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator

# Must run before any `app.*` import so Settings() reads test env.
os.environ.setdefault("RUBBISH_ENVIRONMENT", "test")
os.environ.setdefault("RUBBISH_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
# 收件护栏默认关闭：多个用例会用同一个 example.com 地址连续触发注册与
# 重发邮件，60 秒冷却会让第二个请求静默跳过发送。护栏本身的行为由
# tests/test_email_pool.py 显式设置阈值来覆盖。
os.environ.setdefault("RUBBISH_EMAIL_PER_ADDRESS_COOLDOWN", "0")
os.environ.setdefault("RUBBISH_EMAIL_PER_ADDRESS_LIMIT", "100")
# 注册验证码在测试里关闭：真实环境默认开启，测试不依赖交互式答题。
os.environ.setdefault("RUBBISH_CAPTCHA_REQUIRED_FOR_REGISTRATION", "false")
# Uploads must go to a writable location in ANY environment (CI runners
# have no permission to create /data). tmpdir is per-OS writable.
os.environ.setdefault(
    "RUBBISH_STORAGE_PATH",
    os.path.join(tempfile.gettempdir(), "rubbish-test-uploads"),
)

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core import db as db_module
from app.core.db import get_db
from app.core.tenant import TenantContextMiddleware
from app.main import app
from app.models import Base

# All sessions share one underlying connection so the schema created in
# `fresh_database` is visible to every session opened afterwards.
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
test_async_session_factory = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Replace the production engine + factory so middleware (which lazily
# imports ``async_session_factory``) also targets the in-memory DB.
db_module.engine = test_engine
db_module.async_session_factory = test_async_session_factory


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with test_async_session_factory() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


def _reset_tenant_middleware_cache() -> None:
    """Reset ``TenantContextMiddleware._single_mode_tenant_id`` so the
    next request re-creates the bootstrap tenant against the fresh table.
    """
    current = app.middleware_stack
    while current is not None:
        if isinstance(current, TenantContextMiddleware):
            current._single_mode_tenant_id = None  # type: ignore[attr-defined]
            return
        current = getattr(current, "app", None)


@pytest.fixture(autouse=True)
def _authorise_outbound_in_tests(monkeypatch: pytest.MonkeyPatch):
    """测试环境显式授权投递路径（SMTP 全为 fake，不会外发）。

    生产/开发默认关闭外发（settings.email_outbound_enabled=False）；这里
    打开，是为了让既有的 SMTP 行为测试继续覆盖真实代码路径。护栏本身的
    默认行为由 test_email_outbound_guard.py 单独验证。
    """
    from app.core import email as email_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_outbound_enabled", True, raising=False)
    email_module.reset_email_sender()
    yield
    email_module.reset_email_sender()


@pytest_asyncio.fixture(autouse=True)
async def fresh_database() -> AsyncGenerator[None, None]:
    """Drop + recreate tables for every test to guarantee isolation.

    ``Base.metadata`` is the shared core metadata; importing catalog
    models at app import time registered ``resources`` + ``resource_stats``
    on the same metadata, so a single create_all covers both.
    """
    # 收件护栏是进程级状态：不清空的话，前一个用例发过 user@example.com，
    # 后一个用同一地址的用例会被 60s 冷却挡掉，断言「邮件已发送」直接失败。
    from app.core.mail_guard import reset_mail_guard

    reset_mail_guard()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    reset_mail_guard()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI client with lifespan started (so ``load_all()`` runs)."""
    async with LifespanManager(app) as manager:
        _reset_tenant_middleware_cache()
        async with AsyncClient(
            transport=ASGITransport(app=manager.app),
            base_url="http://test",
        ) as ac:
            yield ac


async def register_reviewer(
    client: AsyncClient, admin: dict, username: str, email: str
) -> dict[str, str | int | bool]:
    """Register a user and grant the ``reviewer`` role (via admin API)."""
    user = await register_user(client, email=email, username=username)
    grant = await client.post(
        f"/api/admin/users/{user['user_id']}/roles",
        json={"role": "reviewer"},
        headers={"Authorization": f"Bearer {admin['token']}"},
    )
    grant.raise_for_status()
    return user


async def complete_one_review(
    client: AsyncClient, admin: dict, submission_id: int, *, reviewer_name: str = "reviewer"
) -> None:
    """Drive a submission through one full review so it becomes decidable.

    录用现在要求至少一份已完成的审稿意见（见
    ``routes_editor.decide_submission`` 的 no_completed_reviews 分支）。
    此前测试都用"投稿→直接 accept"两步走，靠的正是那个缺陷；现在需要
    真正走一遍分配→接受→提交报告。

    审稿人按 ``reviewer_name`` 区分，避免同一测试里多次调用撞
    (submission_id, reviewer_id) 唯一约束。
    """
    # 发表闸门要求至少 2 名不同审稿人给出 accept；helper 名字保留历史，
    # 但实际跑满两份独立意见，避免测试继续依赖“单人录用”的旧漏洞。
    for i in range(2):
        reviewer = await register_reviewer(
            client,
            admin,
            f"{reviewer_name}_{submission_id}_{i}",
            f"{reviewer_name}{submission_id}_{i}@example.com",
        )
        assign = await client.post(
            f"/api/submissions/{submission_id}/assignments",
            json={"reviewer_id": reviewer["user_id"]},
            headers={"Authorization": f"Bearer {admin['token']}"},
        )
        assign.raise_for_status()
        assignment_id = assign.json()["id"]
        hdr = {"Authorization": f"Bearer {reviewer['token']}"}
        accept = await client.post(f"/api/review/assignments/{assignment_id}/accept", headers=hdr)
        accept.raise_for_status()
        report = await client.post(
            f"/api/review/assignments/{assignment_id}/submit",
            json={
                "recommendation": "accept",
                "scores": review_scores(88),
                "comments_to_author": "Sound work, ready for publication.",
            },
            headers=hdr,
        )
        report.raise_for_status()


async def register_user(
    client: AsyncClient,
    *,
    email: str,
    username: str,
    password: str = "password123",
) -> dict[str, str | int | bool]:
    """Create a user through the public API and return authenticated creds.

    ``POST /api/auth/register`` intentionally issues no tokens (success and
    duplicate responses must be indistinguishable), so tests that need a
    session complete the normal login step — the same flow the SPA uses.
    """
    register = await client.post(
        "/api/auth/register",
        json={"email": email, "username": username, "password": password},
    )
    register.raise_for_status()
    login = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    login.raise_for_status()
    data = login.json()
    return {
        "email": email,
        "username": username,
        "password": password,
        "token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "user_id": data["user_id"],
        "is_admin": data["is_admin"],
    }


@pytest_asyncio.fixture
async def test_user(client: AsyncClient) -> dict[str, str | int | bool]:
    """Register a normal user via the API and return login credentials."""
    user = await register_user(client, email="user@example.com", username="testuser")
    # 等级体系上线后，新用户是 L1；投稿/评论/阅读列表分别要求 L3/L2/L2。
    # 测试主体默认代表"已完成引导的作者"，因此在这里走一次作者引导，
    # 让 L1→L3 的规则不被每个用例重复实现。
    onboard = await client.post(
        "/api/gamification/onboarding/author",
        json={"accept_rules": True},
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    onboard.raise_for_status()
    return user


@pytest_asyncio.fixture
async def admin_user(client: AsyncClient, db_session: AsyncSession) -> dict[str, str | int | bool]:
    """Create an admin user directly in the DB and login via the API."""
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.models import Tenant, User

    # Trigger middleware to create the bootstrap tenant. admin_user
    # does not depend on test_user, so we must warm the tenant cache
    # ourselves with any request.
    warmup = await client.get("/api/health")
    warmup.raise_for_status()

    result = await db_session.execute(select(Tenant).where(Tenant.slug == "default"))
    tenant = result.scalar_one()
    db_session.add(
        User(
            tenant_id=tenant.id,
            email="admin@example.com",
            username="adminuser",
            hashed_password=hash_password("adminpass123"),
            is_active=True,
            is_admin=True,
        )
    )
    await db_session.commit()

    response = await client.post(
        "/api/auth/login",
        json={"username": "adminuser", "password": "adminpass123"},
    )
    response.raise_for_status()
    data = response.json()
    return {
        "email": "admin@example.com",
        "username": "adminuser",
        "password": "adminpass123",
        "token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "user_id": data["user_id"],
        "is_admin": data["is_admin"],
    }


def review_scores(score: int = 82) -> dict[str, object]:
    """v5.0 合法审稿评分：五维 + 理由 + 正文证据。"""
    # 90+ 的顶刊级分数在接口层有更长的理由/证据门槛，fixture 也要给出
    # 与该档位匹配的证据，而不是用同一句短话骗过校验。
    high = score >= 90
    dimensions = {
        key: {
            "score": score,
            "reason": (
                f"{key} 维度逐条核对：问题边界清楚，论证链条从假设到结论完整，"
                "反例与替代解释有交代，方法可复现，证据与结论之间没有跳步。"
                if high
                else f"{key} 维度按检查项逐条核对后给分"
            ),
            "evidence": (
                f"证据：正文 §3 第 2 段给出主论证；§4 表 1 列出全部样本与对照；"
                f"§5 第 3 段讨论反例；参考文献[4][7]支撑方法来源（{key}）。"
                if high
                else f"证据：正文 §3 第 2 段与表 1（{key}）"
            ),
        }
        for key in ("question", "argument", "method", "evidence", "integrity")
    }
    return {"rubric_version": "5.0", "track": "academic", "dimensions": dimensions}


def auth_headers(user: dict[str, str | int | bool]) -> dict[str, str]:
    """Return ``Authorization`` header for a fixture user dict."""
    token = user["token"]
    assert isinstance(token, str), "user['token'] must be a str"
    return {"Authorization": f"Bearer {token}"}


class FakeEmailSender:
    """Test email sender — captures every message in ``outbox`` so tests
    can assert subject / recipient / extract the verification token.

    Drop-in replacement for ``app.core.email.ConsoleEmailSender`` via the
    ``EmailSender`` Protocol — no inheritance needed.
    """

    def __init__(self) -> None:
        self.outbox: list[dict[str, str]] = []

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        html: str | None = None,
    ) -> None:
        self.outbox.append({"to": to, "subject": subject, "body": body, "html": html or ""})

    def reset(self) -> None:
        self.outbox.clear()

    def last(self) -> dict[str, str]:
        assert self.outbox, "no email was sent"
        return self.outbox[-1]


@pytest_asyncio.fixture
async def fake_email_sender() -> AsyncGenerator[FakeEmailSender, None]:
    """Patch ``app.core.email.get_email_sender`` to return a fake.

    Tests that need to inspect sent mail depend on this fixture, then
    call ``fake_email_sender.last()``. Tests that don't care about email
    keep the default console sender.
    """
    from app.core import email as email_module

    fake = FakeEmailSender()
    email_module._sender = fake
    yield fake
    email_module.reset_email_sender()


async def complete_two_reviews(client: AsyncClient, admin: dict, submission_id: int) -> None:
    """两位不同审稿人都给出录用意见：发表闸门的正常路径。"""
    await complete_one_review(client, admin, submission_id, reviewer_name="reviewer_a")
    await complete_one_review(client, admin, submission_id, reviewer_name="reviewer_b")
