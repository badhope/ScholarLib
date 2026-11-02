"""身份阶梯（identity ladder）——从"九级游戏等级"回到"四种真实身份"。

为什么重写
----------
旧实现是九级、双轨、XP 门槛、每日签到、27 枚徽章的一套完整手游化体系。
它对**读者**是噪音：一个来读论文的人打开个人中心，看到的是"距 L3 还差
86 XP"和"连续签到 4 天"，而不是"我读过什么、我投的稿走到哪一步了"。

对**编辑部**更是负担：九级里 L5–L9 全部由角色授予、XP 门槛恒为 0，
所以"等级"在这五级上退化成"角色名的另一种写法"；而 L2/L3 的 XP 门槛
（30 / 150）拦的是"关注作者""建阅读列表"这类无害的社交动作——给一个
学术期刊制造了"读完几篇才能收藏"这种既拦不住灌水、又劝退真实读者的
摩擦。

现在保留的
----------
四层身份，全部对应**真实的责任边界**，而不是参与度：

- ``reader``   读者：能读、能评论。注册即得，无门槛。
- ``author``   作者：能投稿。确认投稿规范即得（合规动作，不是升级）。
- ``reviewer`` 审稿人：能接审稿邀请。由编辑部授予（申请或提名）。
- ``editor``   编辑：能送审、能裁决。由编辑部授予。

这四层的边界与后端 ``require_*`` 依赖一一对应，不存在"等级到了但权限
没有"或"权限有了但等级没到"的错位——旧体系的 L2/L3 恰好有这个问题。

XP 仍然保留，但**只作为荣誉与统计**，不再是任何权限的闸门。它回答
"这个人参与了多少"，不回答"这个人能做什么"。两者混在一起是旧体系
最根本的设计错误。

积分不删的理由：它是编辑部识别活跃贡献者的信号（谁在持续写、持续审），
也是个人页的成就感来源。删掉是过度矫正；让它决定权限才是错的。
"""

from __future__ import annotations

from dataclasses import dataclass

# 口径版本：身份定义变更时 +1。前端据此提示"身份说明已更新"。
SCORING_VERSION = "3.0"


@dataclass(frozen=True)
class IdentitySpec:
    """一种身份：名称、slug、如何获得、能做什么。"""

    slug: str
    name: str
    title: str
    # 获得方式的一句话说明（前端原样展示，不写成营销话术）
    granted_by: str
    # 对应的后端角色 slug（空元组 = 无需角色，注册即得）
    roles: tuple[str, ...]
    # 这个身份实际能做的事（与 require_* 依赖一一对应）
    capabilities: tuple[str, ...]
    description: str


IDENTITIES: tuple[IdentitySpec, ...] = (
    IdentitySpec(
        slug="reader",
        name="读者",
        title="Reader",
        granted_by="注册即得",
        roles=(),
        capabilities=(
            "阅读全部已发表文章（无需登录）",
            "下载 PDF / Markdown",
            "收藏到阅读列表、关注作者",
            "发表评论",
            "保存跨设备阅读进度",
        ),
        description="站点的默认身份。任何人不登录也能读全文——开放获取不是口号。",
    ),
    IdentitySpec(
        slug="author",
        name="作者",
        title="Author",
        granted_by="确认当版《投稿与编辑规范》",
        roles=(),
        capabilities=(
            "读者的全部能力",
            "提交稿件（可附 PDF / Word / Markdown）",
            "查看自己的稿件状态、审稿意见与版本历史",
            "按审稿意见修改并重投",
            "关联 ORCID 与作品集",
        ),
        description="确认规范即可投稿——投稿前必须读过规范，这是合规要求，不是门槛。",
    ),
    IdentitySpec(
        slug="reviewer",
        name="审稿人",
        title="Reviewer",
        granted_by="编辑部授予（申请或提名）",
        roles=("reviewer", "senior_reviewer"),
        capabilities=(
            "作者的全部能力",
            "接收审稿邀请",
            "阅读匿名稿并提交评审意见与评分",
            "在评审历史中查看自己完成的每一份意见",
        ),
        description=(
            "审稿权来自编辑部的信任，不能靠攒积分购买。"
            "申请条件：至少 1 篇稿件被本刊录用，且最高 RQS ≥ 60。"
        ),
    ),
    IdentitySpec(
        slug="editor",
        name="编辑",
        title="Editor",
        granted_by="编辑部提拔",
        roles=("section_editor", "editor"),
        capabilities=(
            "审稿人的全部能力",
            "初审稿件、分配与撤销审稿人",
            "栏目编辑：推荐录用（无最终裁决权）",
            "执行编辑：作出录用 / 修回 / 拒稿决定",
            "编排卷期、管理目录",
        ),
        description="对稿件的去留有实际责任，因此只能由编辑部内部提拔，不开放申请。",
    ),
)

IDENTITY_BY_SLUG = {spec.slug: spec for spec in IDENTITIES}

# 角色 slug → 身份 slug。多个角色映射到同一身份（senior_reviewer 与
# reviewer 都是"审稿人"；section_editor 与 editor 都是"编辑"）。
ROLE_TO_IDENTITY: dict[str, str] = {
    "reviewer": "reviewer",
    "senior_reviewer": "reviewer",
    "section_editor": "editor",
    "editor": "editor",
}

# 身份排序：数值越大权限越高。用于"该用户最高身份是哪个"。
IDENTITY_RANK: dict[str, int] = {spec.slug: i for i, spec in enumerate(IDENTITIES)}


def identity_for_roles(roles: list[str], *, is_admin: bool = False) -> str:
    """Resolve a user's highest identity from their role slugs.

    admin 视为编辑身份（站点管理员天然拥有全部编辑权限）。没有任何角色
    的用户是读者——作者身份需要显式确认规范，但那是状态而非角色，
    所以这里只回答"基于角色能到哪一层"；作者判定见 ``is_author_eligible``。
    """
    if is_admin:
        return "editor"
    best = "reader"
    best_rank = IDENTITY_RANK["reader"]
    for role in roles:
        slug = ROLE_TO_IDENTITY.get(role)
        if slug is None:
            continue
        rank = IDENTITY_RANK[slug]
        if rank > best_rank:
            best = slug
            best_rank = rank
    return best


def is_author_eligible(rules_ack_version: str | None, current_version: str) -> bool:
    """作者身份 = 已确认当前版投稿规范。

    这不是"等级"，是一个合规状态：规范改版后旧确认自动失效，作者必须
    重读一遍才能再投。用状态而不是积分来表达，才是这件事的真实形状。
    """
    return bool(rules_ack_version) and rules_ack_version == current_version


def identity_payload(slug: str) -> dict[str, object]:
    spec = IDENTITY_BY_SLUG[slug]
    return {
        "slug": spec.slug,
        "name": spec.name,
        "title": spec.title,
        "granted_by": spec.granted_by,
        "roles": list(spec.roles),
        "capabilities": list(spec.capabilities),
        "description": spec.description,
    }


def identities_payload() -> list[dict[str, object]]:
    return [identity_payload(spec.slug) for spec in IDENTITIES]


__all__ = [
    "IDENTITIES",
    "IDENTITY_BY_SLUG",
    "IDENTITY_RANK",
    "ROLE_TO_IDENTITY",
    "SCORING_VERSION",
    "IdentitySpec",
    "identities_payload",
    "identity_for_roles",
    "identity_payload",
    "is_author_eligible",
]
