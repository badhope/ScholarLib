"""等级轴：身份内等级 + 幂等计分。

设计要点
--------
* **只在同一身份内比较**：author L1–L5、reviewer R1–R3、editor E1–E3。
  不同身份之间不比较、不并列展示、不进同一榜单。
* **积分不换权限**：积分只服务同身份升级；权限走 users.role（五层轴）。
* **幂等**：同一业务 ref（同一认领/同一稿件/同一审稿 assignment）只加一次分，
  靠 point_events 的唯一约束兜底。
* **娱乐/吐槽轨不计分**：essay 轨录用写 delta=0 的流水（记活跃度），不推进等级。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.models import User
from app.modules.gamification.models import PointEvent, UserLevel

Identity = Literal["author", "reviewer", "editor"]

# 计分规则（reason → delta）。娱乐/吐槽轨在调用处传 delta=0。
POINT_RULES: dict[str, dict[str, object]] = {
    "claim.approve": {"identity": "author", "delta": 20, "label": "认领审核通过"},
    "submission.accepted": {"identity": "author", "delta": 60, "label": "正式论文录用"},
    "submission.accepted.essay": {
        "identity": "author",
        "delta": 0,
        "label": "娱乐/吐槽稿录用（仅记活跃度）",
    },
    "review.completed": {"identity": "reviewer", "delta": 1, "label": "完成审稿报告"},
    "editor.decision": {"identity": "editor", "delta": 8, "label": "编辑裁决"},
}


@dataclass(frozen=True)
class LevelBand:
    level: int
    # 该等级积分下限（含）。上限 = 下一档下限 - 1。
    floor: int
    prefix: str  # L / R / E


# 阈值写死在配置里（任务要求说明口径）：
#   author  L1 0–49 / L2 50–149 / L3 150–299 / L4 300–499 / L5 500+
#   reviewer R1 0–2 份 / R2 3–7 / R3 8+
#   editor  E1 0–19 / E2 20–59 / E3 60+
LEVEL_BANDS: dict[str, tuple[LevelBand, ...]] = {
    "author": (
        LevelBand(1, 0, "L"),
        LevelBand(2, 50, "L"),
        LevelBand(3, 150, "L"),
        LevelBand(4, 300, "L"),
        LevelBand(5, 500, "L"),
    ),
    "reviewer": (
        LevelBand(1, 0, "R"),
        LevelBand(2, 3, "R"),
        LevelBand(3, 8, "R"),
    ),
    "editor": (
        LevelBand(1, 0, "E"),
        LevelBand(2, 20, "E"),
        LevelBand(3, 60, "E"),
    ),
}

IDENTITY_NAMES = {"author": "作者", "reviewer": "审稿人", "editor": "编辑"}


def level_for_points(identity: str, points: int) -> tuple[int, str]:
    """根据累计积分推算 (等级序号, 等级文案如 L3/R2/E1)。"""
    bands = LEVEL_BANDS[identity]
    chosen = bands[0]
    for band in bands:
        if points >= band.floor:
            chosen = band
        else:
            break
    return chosen.level, f"{chosen.prefix}{chosen.level}"


def next_threshold(identity: str, points: int) -> tuple[int | None, int]:
    """返回 (下一档积分下限, 距下一档还差多少分)。满级时下限为 None。"""
    bands = LEVEL_BANDS[identity]
    for band in bands:
        if points < band.floor:
            return band.floor, band.floor - points
    return None, 0


async def _get_level_row(db: AsyncSession, user: User, identity: str) -> UserLevel:
    row = (
        await db.execute(
            select(UserLevel).where(
                UserLevel.tenant_id == user.tenant_id,
                UserLevel.user_id == user.id,
                UserLevel.identity == identity,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = UserLevel(
            tenant_id=user.tenant_id,
            user_id=user.id,
            identity=identity,
            level=1,
            points=0,
        )
        db.add(row)
        await db.flush()
    return row


async def award_points(
    db: AsyncSession,
    user: User,
    reason: str,
    *,
    ref_type: str,
    ref_id: str,
    identity: str | None = None,
    delta: int | None = None,
    note: str | None = None,
) -> bool:
    """幂等给某身份加积分。返回 True 表示新加分，False 表示重复触发已拦截。

    - ``identity`` / ``delta`` 缺省时从 POINT_RULES 查。
    - 同一 (user, identity, reason, ref_type, ref_id) 只写一次 point_events；
      重复调用直接返回 False，不重复推进 level。
    - delta=0（娱乐/吐槽轨）也写一条流水记活跃度，但不动 user_levels。
    """
    rule = POINT_RULES.get(reason, {})
    ident = identity or str(rule.get("identity") or "author")
    d = int(str(rule.get("delta", 0) if delta is None else delta))

    exists = (
        await db.execute(
            select(PointEvent.id).where(
                PointEvent.tenant_id == user.tenant_id,
                PointEvent.user_id == user.id,
                PointEvent.identity == ident,
                PointEvent.reason == reason,
                PointEvent.ref_type == ref_type,
                PointEvent.ref_id == ref_id,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return False

    db.add(
        PointEvent(
            tenant_id=user.tenant_id,
            user_id=user.id,
            identity=ident,
            delta=d,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
            note=note,
        )
    )
    # 同一业务动作顺带发 R 币（独立 identity，不影响身份等级）。
    from app.modules.gamification import currency

    await currency.award_for_reason(db, user, reason, ref_type=ref_type, ref_id=ref_id)
    if d != 0:
        row = await _get_level_row(db, user, ident)
        row.points = (row.points or 0) + d
        level, _ = level_for_points(ident, row.points)
        row.level = level
        row.updated_at = utcnow()
    return True


async def level_snapshot(db: AsyncSession, user: User, identity: str) -> dict[str, object]:
    """某身份的等级快照：level/文案/points/下一档/距下一档。"""
    row = (
        await db.execute(
            select(UserLevel).where(
                UserLevel.tenant_id == user.tenant_id,
                UserLevel.user_id == user.id,
                UserLevel.identity == identity,
            )
        )
    ).scalar_one_or_none()
    points = int(row.points) if row else 0
    level, label = level_for_points(identity, points)
    nxt, to_next = next_threshold(identity, points)
    floor = LEVEL_BANDS[identity][level - 1].floor
    # 当前档区间，用于前端进度条。
    if level < len(LEVEL_BANDS[identity]):
        ceiling = LEVEL_BANDS[identity][level].floor - 1
    else:
        ceiling = points  # 满级：进度 100%
    return {
        "identity": identity,
        "identity_name": IDENTITY_NAMES[identity],
        "level": level,
        "level_label": label,
        "points": points,
        "current_floor": floor,
        "current_ceiling": ceiling,
        "next_threshold": nxt,
        "to_next": to_next,
        # 进度条：当前档内已走过的比例（满级=1）。
        "progress": (1.0 if nxt is None else (points - floor) / max(1, (ceiling - floor) + 1)),
    }


async def recent_events(
    db: AsyncSession, user: User, identity: str, limit: int = 20
) -> list[dict[str, object]]:
    rows = (
        (
            await db.execute(
                select(PointEvent)
                .where(
                    PointEvent.tenant_id == user.tenant_id,
                    PointEvent.user_id == user.id,
                    PointEvent.identity == identity,
                )
                .order_by(PointEvent.created_at.desc(), PointEvent.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "reason": e.reason,
            "label": POINT_RULES.get(e.reason, {}).get("label", e.reason),
            "delta": e.delta,
            "note": e.note,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]


async def total_points(db: AsyncSession, user: User, identity: str) -> int:
    """聚合校验用：point_events 中 delta 之和（应等于 user_levels.points）。"""
    return int(
        (
            await db.execute(
                select(func.coalesce(func.sum(PointEvent.delta), 0)).where(
                    PointEvent.tenant_id == user.tenant_id,
                    PointEvent.user_id == user.id,
                    PointEvent.identity == identity,
                )
            )
        ).scalar_one()
        or 0
    )
