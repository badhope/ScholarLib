"""Gamification API — level ladder, onboarding, profile, badge wall, admin grants,
role applications (L5/L6)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    require_admin,
    require_tenant_id,
    user_has_role,
)
from app.api.levels import CURRENT_RULES_VERSION
from app.core.db import get_db, paginate
from app.core.schemas import PaginationMeta
from app.core.time import utcnow
from app.models import AuditLog, User, UserRole
from app.modules.gamification import applications, currency, service, shop
from app.modules.gamification.ladder import (
    SCORING_VERSION,
    identities_payload,
    identity_payload,
)
from app.modules.gamification.models import CoinPolicy, CoinRule, CoinShopItem, RoleApplication

router = APIRouter(prefix="/gamification", tags=["gamification"])


async def require_shop_manager(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """商城后台专用：主编/副主编，或被单独授予 shop_manager 的账号。"""
    if current_user.is_admin:
        return current_user
    if await user_has_role(db, current_user, "editor_in_chief") or await user_has_role(
        db, current_user, "shop_manager"
    ):
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "insufficient_permission",
            "required_role": "shop_manager",
            "message": "需要商城主编权限。",
        },
    )


class LevelGrantRequest(BaseModel):
    points: int = Field(ge=1, le=10000)
    note: str = Field(min_length=1, max_length=200)


class AuthorOnboardingRequest(BaseModel):
    accept_rules: bool = Field(description="必须为 true：表示已读完并接受投稿规范")


class RoleApplicationCreate(BaseModel):
    target_role: Literal["reviewer", "senior_reviewer"]
    statement: str = Field(min_length=20, max_length=2000)


class RoleApplicationResponse(BaseModel):
    id: int
    user_id: int
    username: str | None = None
    target_role: str
    status: str
    statement: str
    decision_note: str | None = None
    decided_by: int | None = None
    # 用 datetime 而非 object：object 会让 OpenAPI 生成字符串类型，
    # 前端拿到的实际是 ISO 串但契约失真。
    decided_at: datetime | None = None
    created_at: datetime


class RoleApplicationListResponse(BaseModel):
    data: list[RoleApplicationResponse]
    meta: PaginationMeta


class RoleDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)


class PublicUserLevel(BaseModel):
    user_id: int
    username: str
    level: dict[str, object]


@router.get("/ladder")
async def get_ladder() -> dict[str, object]:
    """四种身份与获取方式。公开：任何访客都该知道"怎么成为审稿人"。

    路径保留 ``/ladder``（前端与外部脚本都在读），返回体从"九级阶梯"
    变成"四层身份"，字段 ``levels`` 保留一版以兼容旧调用方。
    """
    identities = identities_payload()
    return {"version": SCORING_VERSION, "identities": identities, "levels": identities}


@router.get("/me")
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Full profile for the signed-in user.

    Lazy badge evaluation: the profile read is where new unlocks surface, so
    one read never has to trust a fan-out write path to have fired.
    """
    await service.evaluate_badges(db, current_user)
    await db.commit()
    include_secret = bool(current_user.is_admin)
    payload = await service.profile(db, current_user, include_secret=include_secret)
    if not include_secret:
        # Progressive reveal: keep unlocked badges + the next three locked
        # ones, so the wall grows instead of showing 25 empty slots.
        unlocked = [b for b in payload["badges"] if b["unlocked"]]
        locked = [b for b in payload["badges"] if not b["unlocked"]][:3]
        payload["badges"] = unlocked + locked
    payload["rules_version"] = CURRENT_RULES_VERSION
    payload["rules_accepted"] = current_user.rules_ack_version == CURRENT_RULES_VERSION
    return payload


@router.post("/onboarding/community")
async def onboarding_community(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Step 1: acknowledge the community rules and unlock L2 (comments etc.)."""
    await service.award(
        db, current_user, "onboarding.ack_rules", ref_type="rules", ref_id=CURRENT_RULES_VERSION
    )
    await service.evaluate_badges(db, current_user)
    await db.commit()
    roles = await service._user_role_names(db, current_user)
    return {"level": await service.level_snapshot(db, current_user, roles)}


@router.post("/onboarding/author")
async def onboarding_author(
    body: AuthorOnboardingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Step 2: accept the editorial standards and unlock L3 (submission)."""
    if not body.accept_rules:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="accept_rules must be true to unlock author rights",
        )
    # 记录确认版本——投稿门禁（require_rules_ack）读同一字段。
    await service.award(
        db, current_user, "onboarding.ack_rules", ref_type="rules", ref_id=CURRENT_RULES_VERSION
    )
    current_user.rules_ack_version = CURRENT_RULES_VERSION
    current_user.rules_ack_at = utcnow()
    await service.award(
        db, current_user, "onboarding.author", ref_type="rules", ref_id=CURRENT_RULES_VERSION
    )
    await service.evaluate_badges(db, current_user)
    db.add(
        AuditLog(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            action="gamification.author_onboarding",
            target_type="user",
            target_id=str(current_user.id),
            payload={"rules_version": CURRENT_RULES_VERSION},
        )
    )
    await db.commit()
    roles = await service._user_role_names(db, current_user)
    return {
        "level": await service.level_snapshot(db, current_user, roles),
        "rules_version": CURRENT_RULES_VERSION,
    }


@router.post("/rules/ack")
async def acknowledge_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Re-confirm the current rules after a revision (idempotent, no XP)."""
    current_user.rules_ack_version = CURRENT_RULES_VERSION
    current_user.rules_ack_at = utcnow()
    await db.commit()
    return {"rules_version": CURRENT_RULES_VERSION}


@router.get("/checkin")
async def get_checkin_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """每日签到状态：今日是否已签、连续天数、累计天数与 XP 口径。"""
    return await service.checkin_status(db, current_user)


@router.get("/wallet")
async def get_wallet(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """R 币钱包：余额、签到状态、收入规则与最近流水。"""
    return await currency.wallet_summary(db, current_user)


@router.post("/wallet/checkin")
async def post_wallet_checkin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """每日签到：同时发 XP 与 R 币；重复签到幂等。"""
    await service.daily_checkin(db, current_user)
    await db.refresh(current_user)
    return await currency.wallet_summary(db, current_user)


@router.post("/wallet/unlock-accent")
async def post_unlock_accent(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """花 100 R 币解锁自定义主页主题色。"""
    try:
        return await currency.unlock_accent(db, current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/checkin")
async def post_daily_checkin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """执行每日签到（每天一次，重复签到幂等返回当前状态）。

    连续每满 7 天额外发放 weekly_bonus（见 service.daily_checkin）。
    """
    return await service.daily_checkin(db, current_user)


@router.get("/users/{user_id}/level", response_model=PublicUserLevel)
async def get_user_level(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> PublicUserLevel:
    """Public level badge (shown next to comments and on the author page)."""
    tenant_id = require_tenant_id()
    user = (
        await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    roles = await service._user_role_names(db, user)
    return PublicUserLevel(
        user_id=user.id,
        username=user.username,
        level=await service.level_snapshot(db, user, roles),
    )


@router.post("/admin/users/{user_id}/grant", response_model=LevelGrantRequest)
async def grant_points(
    user_id: int,
    body: LevelGrantRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LevelGrantRequest:
    """L9 only: manually credit XP (editorial merit, event rewards)."""
    tenant_id = require_tenant_id()
    target = (
        await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await service.grant_admin_xp(
        db, actor=current_admin, target=target, points=body.points, note=body.note
    )
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_admin.id,
            action="gamification.grant",
            target_type="user",
            target_id=str(user_id),
            payload={"points": body.points, "note": body.note},
        )
    )
    await db.commit()
    return body


@router.get("/levels/{level}")
async def get_level_detail(level: int) -> dict[str, object]:
    """单条身份详情。参数是身份序号 1–4（1=读者 … 4=编辑）。

    历史上这是 1–9 的九级阶梯。现在只认 1–4；>4 返回 404 而不是静默
    落到编辑身份，避免旧客户端以为"L7 栏目编辑"还存在。
    """
    from app.modules.gamification.ladder import IDENTITIES

    if level < 1 or level > len(IDENTITIES):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown identity")
    return identity_payload(IDENTITIES[level - 1].slug)


# ---------------------------------------------------------------------------
# 职员角色申请（L5 审稿人 / L6 资深审稿人；L7+ 仅编辑部提拔）
# ---------------------------------------------------------------------------

_ROLE_LABELS = {"reviewer": "审稿人（L5）", "senior_reviewer": "资深审稿人（L6）"}


def _application_response(row: RoleApplication, username: str | None) -> RoleApplicationResponse:
    return RoleApplicationResponse(
        id=row.id,
        user_id=row.user_id,
        username=username,
        target_role=row.target_role,
        status=row.status,
        statement=row.statement,
        decision_note=row.decision_note,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        created_at=row.created_at,
    )


@router.get("/applications/me")
async def my_applications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """我的申请历史 + 两个申请目标的资格画像（前端据此渲染可申请/差多少）。"""
    tenant_id = require_tenant_id()
    rows = (
        (
            await db.execute(
                select(RoleApplication)
                .where(
                    RoleApplication.tenant_id == tenant_id,
                    RoleApplication.user_id == current_user.id,
                )
                .order_by(RoleApplication.created_at.desc(), RoleApplication.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    reviewer = await applications.reviewer_profile(db, current_user)
    senior = await applications.senior_reviewer_profile(db, current_user)
    roles = await service._user_role_names(db, current_user)
    already_reviewer = "reviewer" in roles
    already_senior = "senior_reviewer" in roles
    return {
        "applications": [_application_response(r, current_user.username) for r in rows],
        "eligibility": {
            "reviewer": {
                **reviewer,
                "already_role": already_reviewer,
                "eligible": already_reviewer or applications.reviewer_eligible(reviewer),
                "thresholds": {
                    "accepted_papers": 1,
                    "best_rqs": applications.SENIOR_RQS_THRESHOLD,
                },
            },
            "senior_reviewer": {
                **senior,
                "already_role": already_senior,
                # L6 的前提是 L5：没有 reviewer 角色时即使审稿份数够也不可申请。
                "has_reviewer_role": already_reviewer,
                "eligible": already_senior
                or (already_reviewer and applications.senior_reviewer_eligible(senior)),
                "thresholds": {"reviews_completed": applications.SENIOR_REVIEW_COUNT},
            },
        },
    }


@router.post("/applications", status_code=status.HTTP_201_CREATED)
async def create_application(
    body: RoleApplicationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoleApplicationResponse:
    """提交申请（L5 / L6）。资格不达标 422；已有同角色待审申请 409。"""
    tenant_id = require_tenant_id()
    roles = await service._user_role_names(db, current_user)
    if body.target_role == "reviewer":
        profile = await applications.reviewer_profile(db, current_user)
        already_role = "reviewer" in roles
        eligible = applications.reviewer_eligible(profile)
    else:
        profile = await applications.senior_reviewer_profile(db, current_user)
        already_role = "senior_reviewer" in roles
        # L6 是 L5 之上的阶梯：口径要求「已是审稿人 + 完成审稿 ≥ 5 份」，
        # 只满足份数不足以申请，否则会出现「资深审稿人但从未是审稿人」的断层。
        if "reviewer" not in roles and not already_role:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "reviewer_role_required",
                    "target_role": body.target_role,
                    "profile": profile,
                    "message": "申请资深审稿人需先取得审稿人（L5）角色。",
                },
            )
        eligible = applications.senior_reviewer_eligible(profile)
    if already_role:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已拥有该角色，无需申请")
    if not eligible:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "eligibility_required",
                "target_role": body.target_role,
                "profile": profile,
                "message": (
                    "申请审稿人需至少 1 篇稿件被录用且最高质量分（RQS）≥ 60。"
                    if body.target_role == "reviewer"
                    else f"申请资深审稿人需已完成 {applications.SENIOR_REVIEW_COUNT} 份审稿。"
                ),
            },
        )
    if await applications.pending_application_exists(
        db, current_user.id, tenant_id, body.target_role
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="该角色的申请正在审核中，请耐心等待"
        )
    row = RoleApplication(
        tenant_id=tenant_id,
        user_id=current_user.id,
        target_role=body.target_role,
        status="pending",
        statement=body.statement.strip(),
    )
    db.add(row)
    # 先 flush 拿到自增 id：审计 payload 里的 application_id 否则恒为 None。
    await db.flush()
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_user.id,
            action="gamification.role_application.create",
            target_type="user",
            target_id=str(current_user.id),
            payload={"target_role": body.target_role, "application_id": row.id},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        # 并发双击时部分唯一索引 uq_role_applications_pending 兜底。
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="该角色的申请正在审核中，请耐心等待"
        ) from exc
    await db.refresh(row)
    return _application_response(row, current_user.username)


@router.get("/admin/applications", response_model=RoleApplicationListResponse)
async def list_applications(
    status_filter: str = Query(
        default=None, alias="status", pattern=r"^(pending|approved|rejected)$"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RoleApplicationListResponse:
    """管理员审批队列（默认待审在前）。"""
    tenant_id = require_tenant_id()
    base = select(RoleApplication).where(RoleApplication.tenant_id == tenant_id)
    if status_filter is not None:
        base = base.where(RoleApplication.status == status_filter)
    rows, meta = await paginate(
        db,
        base,
        page=page,
        page_size=page_size,
        order_by=(RoleApplication.created_at.desc(), RoleApplication.id.desc()),
    )
    user_ids = list({r.user_id for r in rows})
    names: dict[int, str] = {}
    if user_ids:
        result = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        names = {uid: uname for uid, uname in result.all()}
    return RoleApplicationListResponse(
        data=[_application_response(r, names.get(r.user_id)) for r in rows],
        meta=meta,
    )


@router.post("/admin/applications/{application_id}/decision")
async def decide_application(
    application_id: int,
    body: RoleDecisionRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """批准 / 拒绝。批准 = 授角色 + 通知 + 审计，同一事务。"""
    tenant_id = require_tenant_id()
    row = (
        await db.execute(
            select(RoleApplication)
            .where(
                RoleApplication.id == application_id,
                RoleApplication.tenant_id == tenant_id,
            )
            # 行锁：两位管理员同时点「批准」时，第二个请求必须看到终态，
            # 否则同一申请会被批准两次（重复通知/重复审计）。
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申请不存在")
    if row.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="该申请已处理（终态不可再改）"
        )
    applicant = (
        await db.execute(select(User).where(User.id == row.user_id, User.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if applicant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="申请人不存在或已注销")

    approved = body.decision == "approve"
    row.status = "approved" if approved else "rejected"
    row.decision_note = body.note
    row.decided_by = current_admin.id
    row.decided_at = utcnow()

    from app.modules.notifications import services as notifications

    role_label = _ROLE_LABELS.get(row.target_role, row.target_role)
    if approved:
        from app.api.admin import _get_or_create_role

        role = await _get_or_create_role(db, tenant_id, row.target_role)
        exists = (
            await db.execute(
                select(UserRole).where(
                    UserRole.user_id == applicant.id,
                    UserRole.role_id == role.id,
                    UserRole.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(UserRole(tenant_id=tenant_id, user_id=applicant.id, role_id=role.id))
        await notifications.create(
            db,
            tenant_id=tenant_id,
            user_id=applicant.id,
            type_="gamification.role_application",
            title=f"申请已通过：{role_label}",
            body="恭喜！编辑部已批准你的申请，对应工作台已解锁。",
            related_type="role_application",
            related_id=str(row.id),
        )
    else:
        await notifications.create(
            db,
            tenant_id=tenant_id,
            user_id=applicant.id,
            type_="gamification.role_application",
            title=f"申请未通过：{role_label}",
            body=(body.note or "本次申请未获通过。欢迎继续投稿与参与社区，未来再次申请。"),
            related_type="role_application",
            related_id=str(row.id),
        )

    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=current_admin.id,
            action="gamification.role_application.decision",
            target_type="role_application",
            target_id=str(row.id),
            payload={
                "decision": body.decision,
                "target_role": row.target_role,
                "applicant_user_id": applicant.id,
            },
        )
    )
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "status": row.status}


# --- R 币商城与发行规则（主编后台） -----------------------------------------


class ShopItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    price_coin: int = Field(ge=1, le=100000)
    stock: int | None = Field(default=None, ge=0, le=100000)
    effect: Literal["none", "accent_unlock"] = "none"
    cover_url: str | None = Field(default=None, max_length=500)
    sort_order: int = Field(default=0, ge=0, le=1000)


class ShopItemPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    price_coin: int | None = Field(default=None, ge=1, le=100000)
    stock: int | None = Field(default=None, ge=0, le=100000)
    is_active: bool | None = None
    effect: Literal["none", "accent_unlock"] | None = None
    cover_url: str | None = Field(default=None, max_length=500)
    sort_order: int | None = Field(default=None, ge=0, le=1000)


class CoinRulePatch(BaseModel):
    amount: int = Field(ge=0, le=10000)
    daily_cap: int = Field(default=0, ge=0, le=1000)
    is_active: bool = True


class CoinPolicyPatch(BaseModel):
    coin_per_yuan: int = Field(ge=1, le=10000)
    daily_earn_cap: int = Field(ge=1, le=10000)
    monthly_issue_cap: int = Field(ge=1, le=100000000)


class CoinExchangePatch(BaseModel):
    """主编自己填的 R 币兑换/收款入口；平台不自动打款。"""

    exchange_enabled: bool = False
    exchange_method: str = Field(default="", max_length=80)
    exchange_qr_url: str | None = Field(default=None, max_length=500)
    exchange_account: str | None = Field(default=None, max_length=200)
    exchange_note: str | None = Field(default=None, max_length=1000)
    exchange_min_coin: int = Field(default=100, ge=1, le=1000000)


def _exchange_out(policy: CoinPolicy) -> dict[str, object]:
    return {
        "enabled": policy.exchange_enabled,
        "method": policy.exchange_method,
        "qr_url": policy.exchange_qr_url,
        "account": policy.exchange_account,
        "note": policy.exchange_note,
        "min_coin": policy.exchange_min_coin,
        "coin_per_yuan": policy.coin_per_yuan,
    }


def _shop_item_out(item: CoinShopItem) -> dict[str, object]:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "price_coin": item.price_coin,
        "stock": item.stock,
        "is_active": item.is_active,
        "sort_order": item.sort_order,
        "effect": item.effect,
        "cover_url": item.cover_url,
    }


@router.get("/shop/items")
async def get_shop_items(
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    tenant_id = require_tenant_id()
    items = await shop.list_items(db, tenant_id)
    return {"data": [_shop_item_out(i) for i in items]}


@router.post("/shop/items/{item_id}/purchase")
async def purchase_shop_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    try:
        result = await shop.purchase(db, current_user, item_id)
    except shop.ShopError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {**result, "wallet": await currency.wallet_summary(db, current_user)}


@router.get("/shop/purchases")
async def get_my_purchases(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    from app.modules.gamification.models import CoinPurchase  # local: avoid widening top imports

    rows = (
        (
            await db.execute(
                select(CoinPurchase)
                .where(
                    CoinPurchase.tenant_id == current_user.tenant_id,
                    CoinPurchase.user_id == current_user.id,
                )
                .order_by(CoinPurchase.created_at.desc(), CoinPurchase.id.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    return {
        "data": [
            {
                "id": p.id,
                "item_name": p.item_name,
                "price_coin": p.price_coin,
                "status": p.status,
                "note": p.note,
                "created_at": p.created_at.isoformat(),
            }
            for p in rows
        ]
    }


@router.get("/admin/coin/config")
async def get_coin_config(
    current_user: User = Depends(require_shop_manager),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    policy = await currency._load_policy(db, current_user)
    rules = await currency._load_rules(db, current_user)
    return {
        "policy": {
            "coin_per_yuan": policy.coin_per_yuan,
            "daily_earn_cap": policy.daily_earn_cap,
            "monthly_issue_cap": policy.monthly_issue_cap,
        },
        "rules": [
            {
                "reason": r.reason,
                "label": r.label,
                "amount": r.amount,
                "daily_cap": r.daily_cap,
                "is_active": r.is_active,
            }
            for r in sorted(rules.values(), key=lambda x: x.id)
        ],
        "monthly_issued": await currency.monthly_issued(db, current_user.tenant_id),
        "exchange": _exchange_out(policy),
    }


@router.patch("/admin/coin/rules/{reason}")
async def patch_coin_rule(
    reason: str,
    body: CoinRulePatch,
    current_user: User = Depends(require_shop_manager),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    rule = (
        await db.execute(
            select(CoinRule).where(
                CoinRule.tenant_id == current_user.tenant_id, CoinRule.reason == reason
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        rule = CoinRule(
            tenant_id=current_user.tenant_id,
            reason=reason,
            label=currency.COIN_LABELS.get(reason, reason),
            amount=body.amount,
            daily_cap=body.daily_cap,
            is_active=body.is_active,
            updated_by=current_user.id,
        )
        db.add(rule)
    else:
        rule.amount = body.amount
        rule.daily_cap = body.daily_cap
        rule.is_active = body.is_active
        rule.updated_by = current_user.id
    await db.commit()
    await db.refresh(rule)
    return {
        "reason": rule.reason,
        "label": rule.label,
        "amount": rule.amount,
        "daily_cap": rule.daily_cap,
        "is_active": rule.is_active,
    }


@router.patch("/admin/coin/policy")
async def patch_coin_policy(
    body: CoinPolicyPatch,
    current_user: User = Depends(require_shop_manager),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    policy = (
        await db.execute(select(CoinPolicy).where(CoinPolicy.tenant_id == current_user.tenant_id))
    ).scalar_one_or_none()
    if policy is None:
        policy = CoinPolicy(tenant_id=current_user.tenant_id, updated_by=current_user.id)
        db.add(policy)
    policy.coin_per_yuan = body.coin_per_yuan
    policy.daily_earn_cap = body.daily_earn_cap
    policy.monthly_issue_cap = body.monthly_issue_cap
    policy.updated_by = current_user.id
    await db.commit()
    await db.refresh(policy)
    return {
        "coin_per_yuan": policy.coin_per_yuan,
        "daily_earn_cap": policy.daily_earn_cap,
        "monthly_issue_cap": policy.monthly_issue_cap,
    }


@router.patch("/admin/coin/exchange")
async def patch_coin_exchange(
    body: CoinExchangePatch,
    current_user: User = Depends(require_shop_manager),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    policy = (
        await db.execute(select(CoinPolicy).where(CoinPolicy.tenant_id == current_user.tenant_id))
    ).scalar_one_or_none()
    if policy is None:
        policy = CoinPolicy(tenant_id=current_user.tenant_id, updated_by=current_user.id)
        db.add(policy)
    policy.exchange_enabled = body.exchange_enabled
    policy.exchange_method = body.exchange_method.strip()
    policy.exchange_qr_url = (body.exchange_qr_url or "").strip() or None
    policy.exchange_account = (body.exchange_account or "").strip() or None
    policy.exchange_note = (body.exchange_note or "").strip() or None
    policy.exchange_min_coin = body.exchange_min_coin
    policy.updated_by = current_user.id
    await db.commit()
    await db.refresh(policy)
    return _exchange_out(policy)


@router.get("/shop/exchange")
async def get_shop_exchange(
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(require_tenant_id),
) -> dict[str, object]:
    """公开读取兑换入口；只返回主编配置，不含任何内部账号信息。"""
    policy = (
        await db.execute(select(CoinPolicy).where(CoinPolicy.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if policy is None:
        return {
            "enabled": False,
            "method": "",
            "qr_url": None,
            "account": None,
            "note": None,
            "min_coin": 100,
            "coin_per_yuan": 100,
        }
    return _exchange_out(policy)


@router.get("/admin/shop/items")
async def admin_list_shop_items(
    current_user: User = Depends(require_shop_manager),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    items = await shop.list_items(db, current_user.tenant_id, include_inactive=True)
    return {"data": [_shop_item_out(i) for i in items]}


@router.post("/admin/shop/items")
async def admin_create_shop_item(
    body: ShopItemIn,
    current_user: User = Depends(require_shop_manager),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    item = await shop.create_item(
        db,
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        name=body.name,
        description=body.description,
        price_coin=body.price_coin,
        stock=body.stock,
        effect=body.effect,
        cover_url=body.cover_url,
        sort_order=body.sort_order,
    )
    return _shop_item_out(item)


@router.patch("/admin/shop/items/{item_id}")
async def admin_update_shop_item(
    item_id: int,
    body: ShopItemPatch,
    current_user: User = Depends(require_shop_manager),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    item = (
        await db.execute(
            select(CoinShopItem).where(
                CoinShopItem.tenant_id == current_user.tenant_id,
                CoinShopItem.id == item_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="货品不存在")
    updated = await shop.update_item(
        db,
        item,
        name=body.name,
        description=body.description,
        price_coin=body.price_coin,
        stock=body.stock,
        is_active=body.is_active,
        effect=body.effect,
        cover_url=body.cover_url,
        sort_order=body.sort_order,
    )
    return _shop_item_out(updated)
