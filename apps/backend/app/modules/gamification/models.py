"""Gamification models — XP ledger + unlocked achievements.

Design notes
------------
- ``user_xp_events`` is an append-only ledger. The users table carries the
  running total (``users.xp``) so level lookups never aggregate the ledger
  on the hot path; the ledger exists for auditability and for the
  "where did these points come from" panel in the profile page.
- One event per (tenant, user, action, ref_type, ref_id) — the unique
  constraint makes awarding idempotent, so a retried request can never
  double-credit the same action.
- ``user_achievements`` stores only unlocked badges. Badge definitions live
  in code (``badges.py``) and are frozen; unlocking is evaluated lazily on
  profile reads and writes a row the first time the criterion holds.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models import Base, TenantScopedMixin


class UserXpEvent(Base, TenantScopedMixin):
    """Append-only XP ledger row."""

    __tablename__ = "user_xp_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    ref_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    # __table_args__ 必须放在 created_at 声明之后（类体自上而下求值）。
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "action",
            "ref_type",
            "ref_id",
            name="uq_user_xp_event_identity",
        ),
        Index("ix_user_xp_events_tenant_user_created", "tenant_id", "user_id", created_at.desc()),
    )


class UserAchievement(Base, TenantScopedMixin):
    """A badge a user has unlocked. Appearance order follows ``unlocked_at``."""

    __tablename__ = "user_achievements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "badge_key", name="uq_user_achievement_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    badge_key: Mapped[str] = mapped_column(String(64), nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class RoleApplication(Base, TenantScopedMixin):
    """职员角色申请（L5 审稿人 / L6 资深审稿人；L7+ 仅编辑部提拔）。

    状态机 pending → approved / rejected（终态；重申需新开一行）。
    批准动作由 API 层完成：授角色 + 站内通知 + 审计，同一事务。
    """

    __tablename__ = "role_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 仅允许 reviewer / senior_reviewer（schema 层 Literal 校验）。
    target_role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        Index(
            "ix_role_applications_tenant_status_created",
            "tenant_id",
            "status",
            created_at.desc(),
        ),
        # 同一用户同一角色最多一条待审申请：应用层的「先查后写」挡不住
        # 双击/并发提交，这里用部分唯一索引兜底（终态可并列多条历史）。
        Index(
            "uq_role_applications_pending",
            "tenant_id",
            "user_id",
            "target_role",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )


__all__ = ["PointEvent", "RoleApplication", "UserAchievement", "UserLevel", "UserXpEvent"]


# ---------------------------------------------------------------------------
# 等级轴（v1.14）：身份内等级，跨身份不比较、不并列、不进同一榜单。
#   author  L1–L5（按累计积分）
#   reviewer R1–R3（按完成审稿份数）
#   editor  E1–E3（按累计积分）
# 娱乐/吐槽轨（essay）可写 point_events 但 delta=0，不推进 user_levels。
# ---------------------------------------------------------------------------


class UserLevel(Base, TenantScopedMixin):
    """某用户在某一身份内的等级快照（热路径读）。

    事实源是 ``point_events``；这里存累计 points 与推算出的 level，
    避免每次 /me 都聚合流水。
    """

    __tablename__ = "user_levels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "identity", name="uq_user_level_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # author / reviewer / editor
    identity: Mapped[str] = mapped_column(String(16), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class PointEvent(Base, TenantScopedMixin):
    """某身份积分流水（append-only）。

    唯一约束 (tenant, user, identity, reason, ref_type, ref_id) 让同一
    业务动作（同一 ref）幂等：重复触发不会重复加分。
    娱乐/吐槽轨写 delta=0 仅记活跃度，不影响 level。
    """

    __tablename__ = "point_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identity: Mapped[str] = mapped_column(String(16), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "identity",
            "reason",
            "ref_type",
            "ref_id",
            name="uq_point_event_identity",
        ),
        Index("ix_point_events_tenant_user_created", "tenant_id", "user_id", created_at.desc()),
    )


class CoinRule(Base, TenantScopedMixin):
    """R 币发放规则（主编可在后台调整金额与每日上限）。"""

    __tablename__ = "coin_rules"
    __table_args__ = (UniqueConstraint("tenant_id", "reason", name="uq_coin_rule_tenant_reason"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    daily_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CoinPolicy(Base, TenantScopedMixin):
    """R 币发行口径：汇率锚、单用户日上限、全站月度发行上限。"""

    __tablename__ = "coin_policy"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_coin_policy_tenant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin_per_yuan: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    daily_earn_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    monthly_issue_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CoinShopItem(Base, TenantScopedMixin):
    """商城货品。stock 为 NULL 表示不限量；0 表示售罄。"""

    __tablename__ = "coin_shop_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price_coin: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 目前支持 none（人工发货） / accent_unlock（自动解锁主题色）
    effect: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    cover_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CoinPurchase(Base, TenantScopedMixin):
    """R 币消费流水（事实源仍是 point_events，这里记录订单履约状态）。"""

    __tablename__ = "coin_purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    price_coin: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="paid")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
