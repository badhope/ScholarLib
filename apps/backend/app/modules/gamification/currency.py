"""R 币（可消费社区货币） — 稀缺锚定 + 钱包快照 + 台账。

发行锚：**100 R = 1 元人民币的站内购买力**（不充值、不提现、不转账）。
发放规则和上限都可被主编在后台调整；默认值刻意压低，避免超发：

- 每日签到 1 R（100 天 = 1 元）
- 连续 7 天额外 2 R
- 论坛发主题 1 R / 天，回帖默认 0
- 认领 10 R、审稿 5 R、录用 20 R、裁决 3 R
- 单用户每日最多 5 R；全站每月最多 5000 R

事实源是 ``point_events.identity='coin'`` 的 append-only 流水；余额在
``users.coin_balance`` 做快照。所有发放都先过规则、每日上限、月度发行上限
和幂等唯一约束，四道闸门任一不过就不发。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.modules.gamification.models import CoinPolicy, CoinRule, PointEvent
from app.modules.gamification.service import _checkin_dates, _current_streak, _today_str

COIN_IDENTITY = "coin"
COIN_PER_YUAN_DEFAULT = 100
DAILY_EARN_CAP_DEFAULT = 5
MONTHLY_ISSUE_CAP_DEFAULT = 5000
ACCENT_PRICE = 100

# 代码内兜底；生产以 coin_rules 表为准（主编可改）。
COIN_RULES: dict[str, int] = {
    "checkin.daily": 1,
    "checkin.weekly_bonus": 2,
    "forum.topic": 1,
    "forum.reply": 0,
    "claim.approve": 10,
    "review.completed": 5,
    "submission.accepted": 20,
    "editor.decision": 3,
}

COIN_LABELS: dict[str, str] = {
    "checkin.daily": "每日签到",
    "checkin.weekly_bonus": "连续签到 7 天奖励",
    "forum.topic": "发布论坛主题",
    "forum.reply": "论坛回复",
    "claim.approve": "作者认领通过",
    "review.completed": "完成审稿",
    "submission.accepted": "论文录用",
    "editor.decision": "编辑裁决",
    "shop.accent": "解锁自定义主题色",
    "shop.item": "商城消费",
}


def _month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _coin_event_exists(
    db: AsyncSession, user: User, reason: str, ref_type: str, ref_id: str
) -> bool:
    return (
        await db.execute(
            select(PointEvent.id).where(
                PointEvent.tenant_id == user.tenant_id,
                PointEvent.user_id == user.id,
                PointEvent.identity == COIN_IDENTITY,
                PointEvent.reason == reason,
                PointEvent.ref_type == ref_type,
                PointEvent.ref_id == ref_id,
            )
        )
    ).scalar_one_or_none() is not None


async def _load_rules(db: AsyncSession, user: User) -> dict[str, CoinRule]:
    rows = (
        (
            await db.execute(
                select(CoinRule).where(
                    CoinRule.tenant_id == user.tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return {}
    return {r.reason: r for r in rows}


async def _load_policy(db: AsyncSession, user: User) -> CoinPolicy:
    policy = (
        await db.execute(select(CoinPolicy).where(CoinPolicy.tenant_id == user.tenant_id))
    ).scalar_one_or_none()
    if policy is not None:
        return policy
    # 迁移前的老租户没有 policy 行：返回临时默认值，不写库。
    return CoinPolicy(
        tenant_id=user.tenant_id,
        coin_per_yuan=COIN_PER_YUAN_DEFAULT,
        daily_earn_cap=DAILY_EARN_CAP_DEFAULT,
        monthly_issue_cap=MONTHLY_ISSUE_CAP_DEFAULT,
    )


async def _daily_earned(db: AsyncSession, user: User) -> int:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        (
            await db.execute(
                select(func.coalesce(func.sum(PointEvent.delta), 0)).where(
                    PointEvent.tenant_id == user.tenant_id,
                    PointEvent.user_id == user.id,
                    PointEvent.identity == COIN_IDENTITY,
                    PointEvent.delta > 0,
                    PointEvent.created_at >= start,
                )
            )
        ).scalar_one()
    )


async def monthly_issued(db: AsyncSession, tenant_id: Any) -> int:
    return int(
        (
            await db.execute(
                select(func.coalesce(func.sum(PointEvent.delta), 0)).where(
                    PointEvent.tenant_id == tenant_id,
                    PointEvent.identity == COIN_IDENTITY,
                    PointEvent.delta > 0,
                    PointEvent.created_at >= _month_start(),
                )
            )
        ).scalar_one()
    )


async def award(
    db: AsyncSession,
    user: User,
    reason: str,
    *,
    ref_type: str,
    ref_id: str,
    amount: int | None = None,
    note: str | None = None,
    commit: bool = False,
) -> bool:
    """给用户发 R 币；规则、日上限、月上限、幂等四道闸门全过才发。"""
    rule = (await _load_rules(db, user)).get(reason)
    if rule is not None and not rule.is_active:
        return False
    value = (
        (rule.amount if rule is not None else COIN_RULES.get(reason, 0))
        if amount is None
        else amount
    )
    if value <= 0:
        return False
    if await _coin_event_exists(db, user, reason, ref_type, ref_id):
        return False

    policy = await _load_policy(db, user)
    if await _daily_earned(db, user) + value > policy.daily_earn_cap:
        return False
    if await monthly_issued(db, user.tenant_id) + value > policy.monthly_issue_cap:
        return False
    if rule is not None and rule.daily_cap > 0:
        # 单规则日上限（例如发主题每天只算 1 次，防止灌水）。
        rule_daily = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(PointEvent.delta), 0)).where(
                        PointEvent.tenant_id == user.tenant_id,
                        PointEvent.user_id == user.id,
                        PointEvent.identity == COIN_IDENTITY,
                        PointEvent.reason == reason,
                        PointEvent.delta > 0,
                        PointEvent.created_at
                        >= datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0),
                    )
                )
            ).scalar_one()
        )
        if rule_daily + value > rule.daily_cap:
            return False

    db.add(
        PointEvent(
            tenant_id=user.tenant_id,
            user_id=user.id,
            identity=COIN_IDENTITY,
            delta=value,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
            note=note,
        )
    )
    user.coin_balance = int(user.coin_balance or 0) + value
    if commit:
        await db.commit()
        await db.refresh(user)
    return True


async def award_for_reason(
    db: AsyncSession, user: User, reason: str, *, ref_type: str, ref_id: str
) -> bool:
    """把已有的身份积分动作映射成 R 币收入（金额读后台规则）。"""
    return await award(db, user, reason, ref_type=ref_type, ref_id=ref_id)


async def wallet_summary(db: AsyncSession, user: User) -> dict[str, Any]:
    dates = await _checkin_dates(db, user)
    today = _today_str()
    recent = (
        (
            await db.execute(
                select(PointEvent)
                .where(
                    PointEvent.tenant_id == user.tenant_id,
                    PointEvent.user_id == user.id,
                    PointEvent.identity == COIN_IDENTITY,
                )
                .order_by(PointEvent.created_at.desc(), PointEvent.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    total_earned = (
        await db.execute(
            select(func.coalesce(func.sum(PointEvent.delta), 0)).where(
                PointEvent.tenant_id == user.tenant_id,
                PointEvent.user_id == user.id,
                PointEvent.identity == COIN_IDENTITY,
                PointEvent.delta > 0,
            )
        )
    ).scalar_one()
    policy = await _load_policy(db, user)
    rules = await _load_rules(db, user)
    rule_payload = [
        {
            "reason": r.reason,
            "label": r.label,
            "amount": r.amount,
            "daily_cap": r.daily_cap,
            "is_active": r.is_active,
        }
        for r in sorted(rules.values(), key=lambda x: x.id)
    ]
    if not rule_payload:
        rule_payload = [
            {
                "reason": k,
                "label": COIN_LABELS.get(k, k),
                "amount": v,
                "daily_cap": 1 if k == "checkin.daily" else 0,
                "is_active": v > 0,
            }
            for k, v in COIN_RULES.items()
        ]
    return {
        "balance": int(user.coin_balance or 0),
        "balance_yuan": round(int(user.coin_balance or 0) / policy.coin_per_yuan, 2),
        "coin_per_yuan": policy.coin_per_yuan,
        "daily_earn_cap": policy.daily_earn_cap,
        "monthly_issue_cap": policy.monthly_issue_cap,
        "monthly_issued": await monthly_issued(db, user.tenant_id),
        "checked_in_today": today in dates,
        "streak": _current_streak(dates, today),
        "total_checkins": len(dates),
        "total_earned": int(total_earned or 0),
        "accent_unlocked": bool(user.accent_unlocked),
        "accent_cost": ACCENT_PRICE,
        "rules": rule_payload,
        "recent": [
            {
                "reason": e.reason,
                "label": COIN_LABELS.get(e.reason, e.reason),
                "delta": e.delta,
                "note": e.note,
                "created_at": e.created_at.isoformat(),
            }
            for e in recent
        ],
    }


async def unlock_accent(db: AsyncSession, user: User) -> dict[str, Any]:
    if user.accent_unlocked:
        return {"unlocked": True, "balance": int(user.coin_balance or 0)}
    if int(user.coin_balance or 0) < ACCENT_PRICE:
        raise ValueError(f"R 币不足，解锁自定义主题色需要 {ACCENT_PRICE} R 币")
    stamp = _today_str()
    db.add(
        PointEvent(
            tenant_id=user.tenant_id,
            user_id=user.id,
            identity=COIN_IDENTITY,
            delta=-ACCENT_PRICE,
            reason="shop.accent",
            ref_type="shop",
            ref_id=f"accent:{stamp}",
            note="解锁自定义主题色",
        )
    )
    user.coin_balance = int(user.coin_balance or 0) - ACCENT_PRICE
    user.accent_unlocked = True
    await db.commit()
    await db.refresh(user)
    return {"unlocked": True, "balance": int(user.coin_balance or 0)}
