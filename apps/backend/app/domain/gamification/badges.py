"""Achievement catalog — frozen badge definitions.

Badges are defined in code so that the criteria and the copy can be
reviewed as one unit. ``metric`` names refer to the aggregate dict built
by ``service.collect_metrics``; ``threshold`` is the value that unlocks.

Tiers: bronze / silver / gold / special. ``secret`` badges are hidden from
everyone except L9 (see the profile payload), which keeps a few surprises
without turning the profile into a wall of locked slots.
"""

from __future__ import annotations

from dataclasses import dataclass

TIER_ORDER = ("bronze", "silver", "gold", "special")


@dataclass(frozen=True)
class BadgeSpec:
    key: str
    name: str
    tier: str
    category: str
    description: str
    metric: str
    threshold: int
    secret: bool = False


BADGES: tuple[BadgeSpec, ...] = (
    # --- 阅读 ---
    BadgeSpec("read.first", "开卷", "bronze", "阅读", "读完第一篇文章。", "completed_reads", 1),
    BadgeSpec("read.10", "博览", "bronze", "阅读", "读完 10 篇文章。", "completed_reads", 10),
    BadgeSpec("read.50", "蠹鱼", "silver", "阅读", "读完 50 篇文章。", "completed_reads", 50),
    BadgeSpec("read.150", "藏书楼", "gold", "阅读", "读完 150 篇文章。", "completed_reads", 150),
    BadgeSpec(
        "read.allday",
        "通宵读者",
        "special",
        "阅读",
        "单日阅读时长超过 3 小时。",
        "max_daily_minutes",
        180,
        True,
    ),
    # --- 评论 ---
    BadgeSpec("comment.first", "首次发声", "bronze", "讨论", "发布第一条评论。", "comments", 1),
    BadgeSpec("comment.25", "常驻评审席", "silver", "讨论", "发布 25 条评论。", "comments", 25),
    BadgeSpec("comment.100", "公共领域", "gold", "讨论", "发布 100 条评论。", "comments", 100),
    # --- 收藏与关注 ---
    BadgeSpec(
        "library.first", "第一格书架", "bronze", "收藏", "建立第一个阅读列表。", "reading_lists", 1
    ),
    BadgeSpec("library.50", "目录学家", "silver", "收藏", "收藏 50 条条目。", "saved_items", 50),
    BadgeSpec("follow.5", "学术雷达", "bronze", "关注", "关注 5 位作者。", "followed_authors", 5),
    BadgeSpec(
        "subscribe.3", "学科地图", "silver", "关注", "订阅 3 个学科。", "subscribed_disciplines", 3
    ),
    # --- 投稿 ---
    BadgeSpec("submit.first", "初次投稿", "bronze", "投稿", "提交第一篇稿件。", "submissions", 1),
    BadgeSpec(
        "submit.accepted",
        "见刊",
        "gold",
        "投稿",
        "第一篇稿件被录用并刊出。",
        "accepted_submissions",
        1,
    ),
    BadgeSpec(
        "submit.5", "多产作者", "gold", "投稿", "累计 5 篇稿件被录用。", "accepted_submissions", 5
    ),
    BadgeSpec(
        "submit.rejected",
        "退稿不死",
        "special",
        "投稿",
        "收到第一封拒稿信后仍继续投稿。",
        "rejections_then_resubmit",
        1,
        True,
    ),
    # --- 审稿 ---
    BadgeSpec(
        "review.first",
        "第一份审稿意见",
        "silver",
        "审稿",
        "完成第一次同行评审。",
        "reviews_completed",
        1,
    ),
    BadgeSpec(
        "review.10", "同行之锚", "gold", "审稿", "完成 10 次同行评审。", "reviews_completed", 10
    ),
    BadgeSpec(
        "review.30", "守门人", "special", "审稿", "完成 30 次同行评审。", "reviews_completed", 30
    ),
    # --- 编辑 ---
    BadgeSpec(
        "editor.first", "第一次裁决", "silver", "编辑", "作出第一个编辑决定。", "decisions_made", 1
    ),
    BadgeSpec(
        "editor.50", "版面之手", "gold", "编辑", "作出 50 个编辑决定。", "decisions_made", 50
    ),
    # --- 习惯 ---
    BadgeSpec(
        "streak.7", "七日不辍", "bronze", "习惯", "连续 7 天有阅读记录。", "best_streak_days", 7
    ),
    BadgeSpec(
        "streak.30", "月度常客", "silver", "习惯", "连续 30 天有阅读记录。", "best_streak_days", 30
    ),
    BadgeSpec(
        "streak.100", "百日", "gold", "习惯", "连续 100 天有阅读记录。", "best_streak_days", 100
    ),
    # --- 探索 ---
    BadgeSpec(
        "explore.all-disciplines",
        "全学科漫游",
        "gold",
        "探索",
        "在全部学科栏目中至少各读完 1 篇。",
        "distinct_disciplines_read",
        5,
    ),
    BadgeSpec(
        "explore.night",
        "凌晨三点的引用",
        "special",
        "探索",
        "在 02:00–05:00 之间读完一篇文章。",
        "night_reads",
        1,
        True,
    ),
    BadgeSpec(
        "explore.early",
        "早八前的图书馆",
        "special",
        "探索",
        "在 05:00–07:00 之间读完一篇文章。",
        "early_reads",
        1,
        True,
    ),
)

BADGE_BY_KEY = {b.key: b for b in BADGES}


def badge_payload(spec: BadgeSpec) -> dict[str, object]:
    return {
        "key": spec.key,
        "name": spec.name,
        "tier": spec.tier,
        "category": spec.category,
        "description": spec.description,
        "threshold": spec.threshold,
        "secret": spec.secret,
    }


__all__ = ["BADGES", "BADGE_BY_KEY", "TIER_ORDER", "BadgeSpec", "badge_payload"]
