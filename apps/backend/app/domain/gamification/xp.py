"""XP rules — one table, frozen values.

Every point source names its ``action``; the ledger's unique constraint uses
(action, ref_type, ref_id) so awarding is idempotent per target. Values are
deliberately small and boring: the ladder should reward participation over
months, not a single burst.
"""

from __future__ import annotations

XP_RULES: dict[str, int] = {
    # 账号
    "register": 10,
    "verify_email": 10,
    "complete_profile": 10,
    # 新手引导：确认投稿规范 + 申请作者身份（一次性）
    # 10(注册) + 30(社区规范) + 120(投稿规范) = 160 → L3（门槛 150）。
    # 2.0 起 XP 单独封顶 L3：L4 需要 XP>=400 且录用 >= 1（投稿才是升级的重磅）。
    "onboarding.ack_rules": 30,
    "onboarding.author": 120,
    # 阅读（每篇一次）
    "read.article": 2,
    "read.complete": 3,
    # 每日签到：基础 2 XP，连续每满 7 天额外 5 XP（ref_id=UTC 日期，天然幂等）
    "checkin.daily": 2,
    "checkin.weekly_bonus": 5,
    # 讨论（每日上限由调用方控制）
    "comment.create": 2,
    "comment.received_like": 1,
    # 收藏与关注
    "library.create": 3,
    "library.save": 1,
    "follow.author": 2,
    "subscribe.discipline": 2,
    # 投稿
    "submission.create": 10,
    "submission.accepted": 60,
    "submission.rejected": 5,
    # 审稿
    "review.accepted": 5,
    "review.completed": 25,
    # 编辑
    "editor.decision": 8,
    # 系统奖励（管理员手动发放）
    "admin.grant": 0,
}

DAILY_COMMENT_XP_CAP = 10

__all__ = ["DAILY_COMMENT_XP_CAP", "XP_RULES"]
