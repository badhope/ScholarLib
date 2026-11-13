"""Public profile customization + R coin wallet smoke tests."""

from __future__ import annotations

import pytest
from conftest import auth_headers
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_profile_customization_defaults_and_accent_gate(
    client: AsyncClient, test_user: dict
) -> None:
    r = await client.get("/api/users/me", headers=auth_headers(test_user))
    assert r.status_code == 200
    body = r.json()
    assert body["accent_color"] == "#2f5d46"
    assert body["profile_visibility"] == "public"
    assert body["coin_balance"] == 0

    # 未解锁时不能改成非默认主题色。
    denied = await client.patch(
        "/api/users/me",
        json={"accent_color": "#24334d"},
        headers=auth_headers(test_user),
    )
    assert denied.status_code == 403

    ok = await client.patch(
        "/api/users/me",
        json={
            "avatar_url": "/api/forum/images/avatar.png",
            "contact_email": "Public@Example.com",
            "profile_visibility": "private",
        },
        headers=auth_headers(test_user),
    )
    assert ok.status_code == 200
    assert ok.json()["contact_email"] == "public@example.com"
    assert ok.json()["profile_visibility"] == "private"


@pytest.mark.asyncio
async def test_public_profile_is_private_unless_owner(client: AsyncClient, test_user: dict) -> None:
    await client.patch(
        "/api/users/me",
        json={"profile_visibility": "private", "bio": "只给朋友看"},
        headers=auth_headers(test_user),
    )
    public = await client.get("/api/users/testuser/public")
    assert public.status_code == 404

    owner = await client.get("/api/users/testuser/public", headers=auth_headers(test_user))
    assert owner.status_code == 200
    body = owner.json()
    assert body["is_owner"] is True
    assert body["user"]["bio"] == "只给朋友看"
    assert body["stats"]["works"] == 0


@pytest.mark.asyncio
async def test_wallet_checkin_is_idempotent(client: AsyncClient, test_user: dict) -> None:
    first = await client.post("/api/gamification/wallet/checkin", headers=auth_headers(test_user))
    assert first.status_code == 200
    assert first.json()["balance"] == 1
    assert first.json()["checked_in_today"] is True

    second = await client.post("/api/gamification/wallet/checkin", headers=auth_headers(test_user))
    assert second.status_code == 200
    assert second.json()["balance"] == first.json()["balance"]

    wallet = await client.get("/api/gamification/wallet", headers=auth_headers(test_user))
    assert wallet.status_code == 200
    assert wallet.json()["balance"] == first.json()["balance"]
    assert wallet.json()["coin_per_yuan"] == 100
    assert any(e["reason"] == "checkin.daily" for e in wallet.json()["recent"])


@pytest.mark.asyncio
async def test_shop_purchase_and_accent_unlock(
    client: AsyncClient, test_user: dict, admin_user: dict, db_session
) -> None:
    from sqlalchemy import update

    from app.models import User

    await db_session.execute(
        update(User).where(User.username == test_user["username"]).values(coin_balance=150)
    )
    await db_session.commit()

    created = await client.post(
        "/api/gamification/admin/shop/items",
        json={
            "name": "测试主题色",
            "description": "测试自动发货",
            "price_coin": 100,
            "stock": 2,
            "effect": "accent_unlock",
            "sort_order": 1,
        },
        headers=auth_headers(admin_user),
    )
    assert created.status_code == 200, created.text
    item_id = created.json()["id"]

    public = await client.get("/api/gamification/shop/items")
    assert public.status_code == 200
    assert any(i["id"] == item_id for i in public.json()["data"])

    bought = await client.post(
        f"/api/gamification/shop/items/{item_id}/purchase",
        headers=auth_headers(test_user),
    )
    assert bought.status_code == 200, bought.text
    body = bought.json()
    assert body["status"] == "fulfilled"
    assert body["balance"] == 50
    assert body["wallet"]["accent_unlocked"] is True

    again = await client.post(
        f"/api/gamification/shop/items/{item_id}/purchase",
        headers=auth_headers(test_user),
    )
    assert again.status_code == 400


@pytest.mark.asyncio
async def test_admin_can_set_rule_and_daily_cap(
    client: AsyncClient, test_user: dict, admin_user: dict
) -> None:
    res = await client.patch(
        "/api/gamification/admin/coin/rules/checkin.daily",
        json={"amount": 0, "daily_cap": 1, "is_active": False},
        headers=auth_headers(admin_user),
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is False

    checkin = await client.post("/api/gamification/wallet/checkin", headers=auth_headers(test_user))
    # 签到仍发 XP，但 R 币规则被停用，钱包余额不增加。
    assert checkin.status_code == 200
    assert checkin.json()["balance"] == 0
