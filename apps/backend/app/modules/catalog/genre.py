"""娱乐稿的文体细分。

``content_track`` 只回答“论文 / 娱乐”，无法回答“娱乐里到底是小说、评论还是整活”。
本模块给娱乐轨一个独立的 ``content_genre``：编辑部可在后台改，发布时按标题
给一个可用的初值，避免新稿全都落进“未分类”。

刻意不做“按摘要长度 / 关键词数量”判文体——那是把形式当内容；只按标题里的
强文体词判，判不出来统一落到 ``joke``（本刊娱乐稿的主体就是学术整活）。
"""

from __future__ import annotations

# 与前端 lib/essay-genres.ts 的 code / label 一一对应。
ESSAY_GENRES: tuple[tuple[str, str], ...] = (
    ("joke", "学术整活"),
    ("fiction", "小说故事"),
    ("review", "评论杂谈"),
    ("guide", "指南攻略"),
    ("essay", "随笔"),
    ("poetry", "诗词韵文"),
    ("rant", "吐槽"),
)

ESSAY_GENRE_CODES = {code for code, _ in ESSAY_GENRES}

# 人工兜底：标题里没有强文体词、但编辑部已经明确知道文体的少量稿件。
# 只列 id，不按标题模糊匹配，避免把同题不同稿一起改掉。
_MANUAL_GENRE_BY_ID: dict[int, str] = {
    49: "review",      # 旧瓶装新流量：陈年言情 IP 的工业复活术
    91: "essay",       # 疯狂星期四：当代中国结绳记事
    109: "fiction",    # 我的白月光，死在论文答辩前
    120: "fiction",    # 椰子水与咖啡豆
    125: "essay",      # Buffer 会记住失败吗？
    128: "fiction",    # 西川大陆
    163: "fiction",    # 一个庇护结构的版本更替史
    170: "review",     # 虚拟情感的建构与破灭
    250: "fiction",    # Regarding her evasion
    260: "fiction",    # 全球科研能力下降的一百种原因
    264: "review",     # 肉体、水与边界
    265: "fiction",    # 论谋反
    266: "essay",      # 一场“自欺欺人”的 Suno 大模型探索记
    301: "fiction",    # 形骸
    # 吐槽轨：content_category=rant 的 6 篇，即使标题像论文也归“吐槽”，
    # 否则娱乐区会看不到“吐槽”这个入口。
    32: "rant", 143: "rant", 241: "rant", 251: "rant", 255: "rant", 287: "rant",
}

_FICTION = (
    "小说", "故事", "外传", "同人", "传说", "奇谭", "物语", "前传",
    "后传", "列传", "童话", "寓言", "纪事", "叙事", "怪谈",
)
_POETRY = ("诗", "词牌", "赋", "吟", "绝句", "律诗", "韵文", "挽歌", "长歌")
_GUIDE = (
    "指南", "攻略", "教程", "手册", "入门", "技巧", "如何", "方法",
    "方法论", "怎么做", "速成",
)
_ESSAY = ("随笔", "散记", "杂记", "札记", "手记", "自述", "回忆", "纪念")
_REVIEW = (
    "评述", "评论", "书评", "影评", "乐评", "观察", "反思", "辨析",
    "解读", "考据", "考证", "小考", "为什么", "浅析", "刍议", "商榷",
    "再论", "驳",
)


def classify_essay_genre(
    title: str | None, *, category: str | None = None, resource_id: int | None = None
) -> str:
    """给娱乐稿判一个可用的文体初值；论文轨不调用本函数。"""
    if resource_id is not None and resource_id in _MANUAL_GENRE_BY_ID:
        return _MANUAL_GENRE_BY_ID[resource_id]
    t = (title or "").strip()
    if not t:
        return "joke"
    # 顺序有讲究：先判“故事/小说”，再判诗，再判指南、随笔、评论，
    # 最后才按吐槽类别兜底；判不出来统一算本刊主打的“学术整活”。
    if any(k in t for k in _FICTION):
        return "fiction"
    if any(k in t for k in _POETRY):
        return "poetry"
    if any(k in t for k in _GUIDE):
        return "guide"
    if any(k in t for k in _ESSAY):
        return "essay"
    if any(k in t for k in _REVIEW):
        return "review"
    if (category or "").lower() == "rant":
        return "rant"
    return "joke"


__all__ = ["ESSAY_GENRES", "ESSAY_GENRE_CODES", "classify_essay_genre"]
