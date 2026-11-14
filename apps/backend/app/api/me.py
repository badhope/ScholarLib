"""个人中心接口：身份（权限轴）+ 身份内等级（激励轴）。

设计口径（v1.14）
-----------------
* 权限轴五层：visitor < user < reviewer < editor < editor_in_chief。
  ``/api/me/profile`` 只返回当前权限档位与该档位对应的能力清单。
* 等级轴按身份分轨：author L1–L5 / reviewer R1–R3 / editor E1–E3。
  **不同身份数值不混在一起**：profile 里每个身份一段独立快照；流水接口
  必须显式带 ``?identity=``，不做跨身份总榜。
* 积分只服务同身份升级，不兑换权限。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    PERMISSION_RANK,
    effective_permission_role,
    get_current_user,
)
from app.core.db import get_db
from app.domain.gamification import levels_axis
from app.domain.gamification.models import PointEvent
from app.models import User

router = APIRouter(prefix="/me", tags=["me"])

PERMISSION_LABELS = {
    "user": "用户（读者/作者）",
    "reviewer": "审稿人",
    "editor": "栏目编辑",
    "editor_in_chief": "主编",
}

# 每个权限档位对应的能力清单（与 require_role 一一对应）。
_PERMISSIONS = {
    "user": [
        "阅读全部已发表文章",
        "下载 PDF / Markdown",
        "收藏到阅读列表、关注作者",
        "发表评论与论坛讨论",
        "提交稿件（需先确认投稿规范）",
    ],
    "reviewer": [
        "接收审稿邀请",
        "阅读匿名稿并提交评审意见与评分",
        "查看自己完成的审稿历史",
    ],
    "editor": [
        "初审稿件、分配与撤销审稿人",
        "编排卷期、管理目录",
        "查看编辑工作台",
    ],
    "editor_in_chief": [
        "作出录用 / 修回 / 拒稿最终决定",
        "审批角色申请与作者认领",
        "站点设置与审计日志",
    ],
}


async def _has_author_activity(db: AsyncSession, user: User) -> bool:
    """该账号是否真的有作者产出（投稿 / 被认领稿）。

    没有产出就不展示「作者」等级轨——避免一个只读过文章的账号在个人中心
    看到一枚无意义的 L1。
    """
    from app.domain.submission.models import Submission

    submitted = (
        await db.execute(
            select(func.count(Submission.id)).where(
                Submission.tenant_id == user.tenant_id,
                Submission.submitted_by == user.id,
            )
        )
    ).scalar_one()
    if int(submitted or 0) > 0:
        return True
    # 认领通过（claim.approve）会写 author 轨 point_event，也算作者活动。
    authored = (
        await db.execute(
            select(func.count(PointEvent.id)).where(
                PointEvent.tenant_id == user.tenant_id,
                PointEvent.user_id == user.id,
                PointEvent.identity == "author",
                PointEvent.delta > 0,
            )
        )
    ).scalar_one()
    return int(authored or 0) > 0


async def _identities_for_role(db: AsyncSession, user: User, permission_role: str) -> list[str]:
    """按账号**实际持有身份**决定展示哪几条等级轨。

    口径（v1.14 定稿）：
    - editor_in_chief → 只显示「主编」，不挂任何 L/R/E 等级轨；
    - editor         → 只显示「编辑」轨；
    - reviewer       → 只显示「审稿人」轨；若同时有作者产出，再额外加「作者」轨；
    - user           → 有作者产出才显示「作者」轨，否则不展示等级轨。
    """
    if permission_role == "editor_in_chief":
        return []
    if permission_role == "editor":
        return ["editor"]
    if permission_role == "reviewer":
        out = ["reviewer"]
        if await _has_author_activity(db, user):
            out.append("author")
        return out
    # user：仅在确有作者产出时展示作者轨。
    return ["author"] if await _has_author_activity(db, user) else []


@router.get("/profile")
async def my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """当前身份 + 各身份轨等级 + 权限清单。

    只返回当前账号实际具备的身份轨；A 身份的等级数值不会混进 B 身份段。
    主编不挂任何等级轨。
    """
    permission_role = await effective_permission_role(db, current_user)
    identities = await _identities_for_role(db, current_user, permission_role)

    level_sections: dict[str, dict[str, object]] = {}
    for ident in identities:
        level_sections[ident] = await levels_axis.level_snapshot(db, current_user, ident)

    # 能力清单：取到最高档位为止（大身份包含小身份能力）。
    perms: list[str] = []
    for role in ("user", "reviewer", "editor", "editor_in_chief"):
        if PERMISSION_RANK[role] <= PERMISSION_RANK[permission_role]:
            perms.extend(_PERMISSIONS[role])

    return {
        "user_id": current_user.id,
        "username": current_user.username,
        # 权限轴（单一档位）。
        "permission_role": permission_role,
        "permission_label": PERMISSION_LABELS[permission_role],
        "permissions": perms,
        # 等级轴：分轨快照，键为 identity（author/reviewer/editor）。
        # 主编为空列表（不设等级）。
        "identities": identities,
        "levels": level_sections,
        "rules_accepted": current_user.rules_ack_version is not None,
    }


@router.get("/points")
async def my_points(
    identity: str = Query(pattern="^(author|reviewer|editor)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """某一身份轨的积分流水（只显示该身份，不跨身份合并）。"""
    permission_role = await effective_permission_role(db, current_user)
    allowed = await _identities_for_role(db, current_user, permission_role)
    if identity not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"当前账号不具备 {identity} 身份轨",
        )
    snap = await levels_axis.level_snapshot(db, current_user, identity)
    events = await levels_axis.recent_events(db, current_user, identity)
    return {
        "identity": identity,
        "identity_name": levels_axis.IDENTITY_NAMES[identity],
        "snapshot": snap,
        "events": events,
    }
