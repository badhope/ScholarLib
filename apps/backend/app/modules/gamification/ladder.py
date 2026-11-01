"""Level ladder — the frozen 9-tier permission ladder.

The ladder is intentionally code, not a database table: every level carries
capabilities that are enforced elsewhere (require_editor, require_reviewer,
admin gates). A configurable table would drift away from the enforcement
points and produce "level 8 user who cannot edit" ghosts.

Two tracks combine into one effective level:

- **Merit track** (L1–L4): earned automatically from XP.
- **Staff track** (L5–L9): granted by role. A staff role sets a *floor*;
  XP never promotes into a staff tier on its own, because review and
  editorial power are accountability, not a participation reward.

Effective level = max(merit level from XP, role floor, admin=9).
"""

from __future__ import annotations

from dataclasses import dataclass

SCORING_VERSION = "2.0"


@dataclass(frozen=True)
class LevelSpec:
    level: int
    code: str
    name: str
    title: str
    track: str
    xp_floor: int
    roles: tuple[str, ...]
    capabilities: tuple[str, ...]
    description: str
    # 2.0 起 merit 轨 L4 增加投稿指标：XP 满只是必要条件，指标不达成不升级。
    # None = 纯 XP 阈值（L2/L3）；"accepted_papers" = 另需录用稿件 >= 1。
    metric: str | None = None


LEVELS: tuple[LevelSpec, ...] = (
    LevelSpec(
        level=1,
        code="novice",
        name="L1 小白读者",
        title="路人",
        track="merit",
        xp_floor=0,
        roles=(),
        capabilities=(
            "浏览目录与全文",
            "下载 PDF / Markdown",
            "本地阅读进度",
            "发表评论",
            "提交稿件（确认投稿规范后）",
        ),
        description="刚注册的读者。可阅读、评论和投稿；投稿前必须确认《投稿规范》。",
    ),
    LevelSpec(
        level=2,
        code="reader",
        name="L2 注册读者",
        title="读者",
        track="merit",
        xp_floor=30,
        roles=(),
        capabilities=(
            "L1 全部权限",
            "关注作者 / 订阅学科",
            "建立阅读列表",
            "跨设备阅读进度",
            "社区规范徽章",
        ),
        description="完成初始阅读量后解锁社交与收藏能力：关注、阅读列表、跨设备进度。评论与投稿自 L1 起即可用。",
    ),
    LevelSpec(
        level=3,
        code="author",
        name="L3 作者",
        title="投稿人",
        track="merit",
        xp_floor=150,
        roles=(),
        capabilities=(
            "L2 全部权限",
            "查看审稿意见与版本历史",
            "申请 ORCID 关联",
            "作者署名页与作品集",
        ),
        description="完成投稿规范确认后的正式作者身份：作品集、审稿意见可见、ORCID 关联。投稿自 L1 起即可用。",
    ),
    LevelSpec(
        level=4,
        code="senior-author",
        name="L4 常驻作者",
        title="常驻作者",
        track="merit",
        xp_floor=400,
        roles=(),
        capabilities=(
            "L3 全部权限",
            "稿件优先进入排版队列",
            "个人主页展示已刊作品",
        ),
        description="有稿件被本刊录用的作者：投稿并录用才是升级的重磅，积分满也不再自动升级。",
        metric="accepted_papers",
    ),
    LevelSpec(
        level=5,
        code="reviewer",
        name="L5 审稿人",
        title="同行评审",
        track="staff",
        xp_floor=0,
        roles=("reviewer",),
        capabilities=(
            "L4 全部读者侧权限",
            "接收审稿邀请",
            "提交审稿意见与评分",
            "查看匿名稿",
        ),
        description="由编辑部授予 reviewer 角色。审稿权限不靠积分购买。",
    ),
    LevelSpec(
        level=6,
        code="senior-reviewer",
        name="L6 资深审稿人",
        title="资深评审",
        track="staff",
        xp_floor=0,
        roles=("senior_reviewer",),
        capabilities=(
            "L5 全部权限",
            "审稿质量进入编辑参考榜",
            "可被指定为争议稿第三审",
        ),
        description="累计完成足量高质量审稿后由编辑提名，进入资深评审池。",
    ),
    LevelSpec(
        level=7,
        code="section-editor",
        name="L7 栏目编辑",
        title="栏目编辑",
        track="staff",
        xp_floor=0,
        roles=("section_editor",),
        capabilities=(
            "L6 全部权限",
            "初审与送审（分配/撤销审稿人）",
            "推荐录用名单（无最终裁决权）",
        ),
        description="编辑部初审岗位：送审与推荐，录用/修回/拒稿由 L8 执行编辑裁决。",
    ),
    LevelSpec(
        level=8,
        code="editor",
        name="L8 执行编辑",
        title="执行编辑",
        track="staff",
        xp_floor=0,
        roles=("editor",),
        capabilities=(
            "L7 全部权限",
            "全学科分配审稿人",
            "作出录用 / 修回 / 拒稿决定",
            "编排卷期",
        ),
        description="对全刊稿件有裁决权，决定进入公开目录的最终形态。",
    ),
    LevelSpec(
        level=9,
        code="editor-in-chief",
        name="L9 主编 / 管理员",
        title="主编",
        track="staff",
        xp_floor=0,
        roles=("admin",),
        capabilities=(
            "L8 全部权限",
            "用户与角色管理",
            "期刊设置、评分模型与公告",
            "审计日志与全站数据",
        ),
        description="站点最高权限。仅主编可查看全部等级与全部隐藏成就。",
    ),
)

LEVEL_BY_NUMBER = {spec.level: spec for spec in LEVELS}
MERIT_MAX_LEVEL = 4
STAFF_ROLE_TO_LEVEL = {
    "reviewer": 5,
    "senior_reviewer": 6,
    "section_editor": 7,
    "editor": 8,
}


# XP 单独能买到的最高等级：L2/L3 仍是确认动作的积分反馈；
# L4 起由投稿指标（录用 + RQS / 审稿）驱动，XP 满不再是充分条件。
XP_ONLY_MAX_LEVEL = 3


def merit_level_for_xp(xp: int) -> int:
    """Highest merit tier whose XP floor is met (XP 单独封顶 L3)。"""
    level = 1
    for spec in LEVELS:
        if spec.track != "merit":
            continue
        if spec.level > XP_ONLY_MAX_LEVEL:
            break
        if xp >= spec.xp_floor:
            level = spec.level
    return min(level, XP_ONLY_MAX_LEVEL)


def effective_level(xp: int, roles: list[str], is_admin: bool, accepted_papers: int = 0) -> int:
    """max(merit, metric, role floor), with admin pinned to 9.

    2.0 口径：L4 需要 XP 满 400 **且** 录用稿件 >= 1——XP 只是必要条件，
    投稿录用才是升级的闸门；两个条件都满足才升 L4。L5+ 仍走角色授予。
    """
    if is_admin:
        return 9
    level = merit_level_for_xp(xp)
    if level >= XP_ONLY_MAX_LEVEL:
        for spec in LEVELS:
            if spec.track != "merit" or spec.metric is None:
                continue
            if spec.level <= level:
                continue
            if xp >= spec.xp_floor and accepted_papers >= 1:
                level = spec.level
    for role in roles:
        level = max(level, STAFF_ROLE_TO_LEVEL.get(role, 0))
    return level


def level_payload(level: int) -> dict[str, object]:
    spec = LEVEL_BY_NUMBER[level]
    return {
        "level": spec.level,
        "code": spec.code,
        "name": spec.name,
        "title": spec.title,
        "track": spec.track,
        "capabilities": list(spec.capabilities),
        "description": spec.description,
    }


def ladder_payload() -> list[dict[str, object]]:
    return [
        {
            "level": spec.level,
            "metric": spec.metric,
            "code": spec.code,
            "name": spec.name,
            "title": spec.title,
            "track": spec.track,
            "xp_floor": spec.xp_floor,
            "roles": list(spec.roles),
            "capabilities": list(spec.capabilities),
            "description": spec.description,
        }
        for spec in LEVELS
    ]


__all__ = [
    "LEVELS",
    "LEVEL_BY_NUMBER",
    "SCORING_VERSION",
    "STAFF_ROLE_TO_LEVEL",
    "XP_ONLY_MAX_LEVEL",
    "effective_level",
    "ladder_payload",
    "level_payload",
    "merit_level_for_xp",
]
