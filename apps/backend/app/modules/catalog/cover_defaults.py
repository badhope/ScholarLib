"""默认封面回填：发布闭环的最后一块。

设定（v1.11 生态规范）：已发布内容必须有封面。历史上有 275 篇录用即刊
的稿件没走封面环节就直接上线了。本模块把「无封面」变成不可能态：
- 学科 → 封面主题的映射表（覆盖 106 个一级学科的 13 个门类）；
- 每个主题 3 张候选图（public/covers/，与前端 covers.json 同源）；
- 按资源 id 确定性选图（同一资源永远同一张默认封面，避免刷新跳变）。
"""

from __future__ import annotations

# 门类关键词 → covers.json 主题 slug。匹配顺序即优先级，取第一个命中。
_CATEGORY_SLUGS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("计算机", "软件", "网络空间", "电子信", "人工智能"), "computer-science"),
    (("图书情报", "信息资源", "新闻传播"), "information-science"),
    (("管理", "工商", "公共管理", "会计", "图书"), "management"),
    (("心理",), "psychology"),
    (("医", "药", "生物", "农", "林", "食品"), "life-science"),
    (("物理", "天文", "力学", "光学", "材料"), "physics"),
    (("数学", "统计"), "mathematics"),
    (("文学", "历史", "哲学", "艺术", "语言", "音乐", "美术"), "humanities"),
    (("生态", "环境", "地理", "地质", "气象", "海洋"), "ecology"),
    (("经济", "法", "政治", "社会", "教育", "体育", "民族", "马理"), "social-science"),
)
FALLBACK_SLUG = "social-science"


def cover_slug_for_discipline(discipline: str | None) -> str:
    """把（可能是中文的）学科名映射到封面主题 slug。"""
    if not discipline:
        return FALLBACK_SLUG
    for keywords, slug in _CATEGORY_SLUGS:
        if any(k in discipline for k in keywords):
            return slug
    return FALLBACK_SLUG


def default_cover_for(discipline: str | None, *, seed: int) -> str:
    """按学科给一个确定性默认封面路径（1–3 号图轮转）。"""
    slug = cover_slug_for_discipline(discipline)
    n = (seed % 3) + 1
    return f"/covers/{slug}-{n}.jpg"
