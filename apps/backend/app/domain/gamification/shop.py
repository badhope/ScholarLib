"""R 币商城 — 货品目录、购买、主编管理口径。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.gamification.currency import COIN_IDENTITY
from app.domain.gamification.models import CoinPurchase, CoinShopItem, PointEvent
from app.models import User


class ShopError(Exception):
    pass


async def list_items(
    db: AsyncSession, tenant_id: Any, *, include_inactive: bool = False
) -> list[CoinShopItem]:
    stmt = select(CoinShopItem).where(CoinShopItem.tenant_id == tenant_id)
    if not include_inactive:
        stmt = stmt.where(CoinShopItem.is_active.is_(True))
    return list(
        (await db.execute(stmt.order_by(CoinShopItem.sort_order.asc(), CoinShopItem.id.asc())))
        .scalars()
        .all()
    )


async def create_item(
    db: AsyncSession,
    *,
    tenant_id: Any,
    created_by: int,
    name: str,
    description: str,
    price_coin: int,
    stock: int | None,
    effect: str,
    cover_url: str | None,
    sort_order: int,
) -> CoinShopItem:
    item = CoinShopItem(
        tenant_id=tenant_id,
        name=name.strip(),
        description=description.strip(),
        price_coin=price_coin,
        stock=stock,
        effect=effect,
        cover_url=cover_url,
        sort_order=sort_order,
        created_by=created_by,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def update_item(
    db: AsyncSession,
    item: CoinShopItem,
    *,
    name: str | None = None,
    description: str | None = None,
    price_coin: int | None = None,
    stock: int | None = None,
    is_active: bool | None = None,
    effect: str | None = None,
    cover_url: str | None = None,
    sort_order: int | None = None,
) -> CoinShopItem:
    if name is not None:
        item.name = name.strip()
    if description is not None:
        item.description = description.strip()
    if price_coin is not None:
        item.price_coin = price_coin
    if stock is not None:
        item.stock = stock
    if is_active is not None:
        item.is_active = is_active
    if effect is not None:
        item.effect = effect
    if cover_url is not None:
        item.cover_url = cover_url
    if sort_order is not None:
        item.sort_order = sort_order
    await db.commit()
    await db.refresh(item)
    return item


async def purchase(db: AsyncSession, user: User, item_id: int) -> dict[str, Any]:
    item = (
        await db.execute(
            select(CoinShopItem).where(
                CoinShopItem.tenant_id == user.tenant_id,
                CoinShopItem.id == item_id,
                CoinShopItem.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise ShopError("货品不存在或已下架")
    if item.stock is not None and item.stock <= 0:
        raise ShopError("货品已售罄")
    if item.effect == "accent_unlock" and user.accent_unlocked:
        raise ShopError("你已经解锁过自定义主题色")
    if int(user.coin_balance or 0) < item.price_coin:
        raise ShopError(f"R 币不足，还差 {item.price_coin - int(user.coin_balance or 0)} R")

    import uuid

    ref_id = f"{item.id}:{uuid.uuid4().hex}"
    db.add(
        PointEvent(
            tenant_id=user.tenant_id,
            user_id=user.id,
            identity=COIN_IDENTITY,
            delta=-item.price_coin,
            reason="shop.item",
            ref_type="shop_item",
            ref_id=ref_id,
            note=item.name,
        )
    )
    user.coin_balance = int(user.coin_balance or 0) - item.price_coin
    if item.stock is not None:
        item.stock = max(0, item.stock - 1)
    status = "paid"
    note = "待主编人工发货"
    if item.effect == "accent_unlock":
        user.accent_unlocked = True
        status = "fulfilled"
        note = "已自动解锁自定义主题色"
    purchase = CoinPurchase(
        tenant_id=user.tenant_id,
        user_id=user.id,
        item_id=item.id,
        item_name=item.name,
        price_coin=item.price_coin,
        status=status,
        note=note,
    )
    db.add(purchase)
    await db.commit()
    await db.refresh(user)
    await db.refresh(purchase)
    return {
        "purchase_id": purchase.id,
        "item": item.name,
        "price_coin": item.price_coin,
        "balance": int(user.coin_balance or 0),
        "status": status,
        "note": note,
    }
