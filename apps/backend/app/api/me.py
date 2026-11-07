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
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    PERMISSION_RANK,
    effective_permission_role,
    get_current_user,
)
from app.core.db import get_db
from app.models import User
from app.modules.gamification import levels_axis

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


def _identities_for_role(permission_role: str) -> list[str]:
    """根据权限档位列出该账号实际具备哪些身份轨（用于分轨展示）。

    大身份包含小身份：主编天然也是编辑/审稿人/作者；但等级轨各自独立，
    数值互不混排。
    """
    rank = PERMISSION_RANK[permission_role]
    out = ["author"]
    if rank >= PERMISSION_RANK["reviewer"]:
        out.append("reviewer")
    if rank >= PERMISSION_RANK["editor"]:
        out.append("editor")
    return out


@router.get("/profile")
async def my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """当前身份 + 各身份轨等级 + 权限清单。

    只返回当前账号具备的身份轨；A 身份的等级数值不会混进 B 身份段。
    """
    permission_role = await effective_permission_role(db, current_user)
    identities = _identities_for_role(permission_role)

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
    if identity not in _identities_for_role(permission_role):
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
