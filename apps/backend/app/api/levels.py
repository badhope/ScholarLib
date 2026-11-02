"""身份门禁（identity enforcement）。

身份体系定义在 ``app.modules.gamification.ladder``；本模块把它变成
FastAPI 依赖，让规则只有一处。

与旧版本的关键差别：**不再有积分门槛**。

旧实现提供 ``require_level(n)``，按 XP 阶梯拦人（如"评论需要 L2 = 30 XP"）。
这套门槛的问题不是数值定得高低，而是**方向错了**：它用参与度当权限。
一个刚注册的读者读完一篇文章想留个言，被告知"再攒 28 积分"——这不是
在筛选质量，是在惩罚真实使用。而真正需要把关的动作（审稿、裁决）从来
就不是 XP 能换到的，是角色授予的。

现在只保留三种门禁，全部对应真实的责任边界：

- ``require_reader``   — 登录即可（评论、收藏、关注）
- ``require_author``   — 已确认当版投稿规范（投稿）
- ``require_reviewer`` / ``require_editor`` / ``require_chief_editor``
                        — 见 ``app.api.deps``，由角色授予

XP 仍是荣誉统计，但不参与任何一处权限判定。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import User

# 投稿规范版本：与 docs/editorial-standards.md 的「版本 1.1」一致。
# 规范改版时同步 +1，所有作者需重新确认。
CURRENT_RULES_VERSION = "1.1"


async def _role_names(db: AsyncSession, user: User) -> list[str]:
    from app.modules.gamification import service as gamification

    return await gamification._user_role_names(db, user)


async def level_of(db: AsyncSession, user: User) -> int:
    """当前用户的身份层级（1=读者 2=作者 3=审稿人 4=编辑）。

    保留这个函数名与返回类型，是为了让外部调用方（admin 用户列表、
    认证响应）不用改动；语义已从"九级 XP 等级"变成"四层身份序号"。
    """
    from app.modules.gamification.ladder import (
        IDENTITY_RANK,
        identity_for_roles,
        is_author_eligible,
    )

    roles = await _role_names(db, user)
    slug = identity_for_roles(roles, is_admin=bool(user.is_admin))
    if slug == "reader" and is_author_eligible(user.rules_ack_version, CURRENT_RULES_VERSION):
        return IDENTITY_RANK["author"] + 1
    return IDENTITY_RANK[slug] + 1


async def require_reader(current_user: User = Depends(get_current_user)) -> User:
    """登录即可的写动作（评论、阅读列表、关注）。

    历史上这些动作要求 L2（30 XP）。门槛已移除：登录本身就是"这是个
    真实用户"的足够证据，攒积分换发言权只会劝退真实读者。
    """
    return current_user


async def require_author(
    current_user: User = Depends(get_current_user),
) -> User:
    """作者身份：必须已确认当版《投稿与编辑规范》。

    这是合规要求而非等级：投稿前读过规范，是作者对"不编造数据、不编造
    引用、不伤人"这三条承诺的知情确认。规范改版后旧确认自动失效。
    """
    if current_user.rules_ack_version != CURRENT_RULES_VERSION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "rules_ack_required",
                "version": CURRENT_RULES_VERSION,
                "message": "投稿前请先阅读并确认《Rubbish 投稿与编辑规范》。",
            },
        )
    return current_user


# 向后兼容别名：旧调用点写的是 require_rules_ack，语义完全相同。
require_rules_ack = require_author


def require_level(minimum: int) -> Callable[..., Any]:
    """已废弃：按 XP 门槛拦人的依赖工厂。

    保留签名只为让遗留代码在 import 时不炸；任何新代码都不应该用它。
    若被调用，返回的守卫按**身份**判定（1=读者 2=作者 3=审稿人 4=编辑），
    而不是 XP——这样即便有遗漏的调用点，行为也是"权限模型"而非"积分模型"。
    """

    async def _guard(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        current = await level_of(db, current_user)
        if current < minimum:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "identity_required",
                    "required_identity": minimum,
                    "current_identity": current,
                    "message": f"需要身份层级 {minimum}，当前为 {current}。",
                },
            )
        return current_user

    return _guard


__all__ = [
    "CURRENT_RULES_VERSION",
    "level_of",
    "require_author",
    "require_level",
    "require_reader",
    "require_rules_ack",
]
