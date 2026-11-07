"""赛道（track）——历史遗留字段，已下线，仅保留荒诞指数。

历史背景：本刊曾有 serious / absurd 双赛道（正经研究 / 荒诞研究），但每篇
论文同时带有编辑部评定的荒诞指数（absurdity_index 0–10），后者已完整覆盖
"这篇有多荒诞"的信息维度，赛道成了冗余口径，现已下线。

兼容策略（不做 DB 破坏性迁移）：

- ``serious`` / ``absurd`` 两列（resources.track / submissions.track）原样
  保留，历史数据不清洗；
- 本模块把合法取值收敛为 ``"serious"``：``normalize_track`` 把任何非
  serious 输入（含旧客户端传的 ``"absurd"``）归一为 serious，保证旧客户端
  不会被 422 拒掉；
- 展示层不再呈现赛道，读者以荒诞指数（absurdityLevel）区分文章气质。

放在 core 而不是任一模块里：submission 与 catalog 都要用，且二者默认
不互相 import（见 docs/ARCHITECTURE.md「模块之间默认不互相 import」）。
"""

from __future__ import annotations

from typing import Final, Literal

Track = Literal["serious"]

# 内容赛道（P0）：由 content_category 派生，与历史 track(serious|absurd)
# 完全无关。paper = 学术研究（进 R 因子/篇均指标）；essay = 娱乐/吐槽（不进）。
ContentTrack = Literal["paper", "essay"]

DEFAULT_CONTENT_TRACK: Final[ContentTrack] = "paper"

# content_category → content_track。fun / rant 均为娱乐稿（essay）。
_CATEGORY_TO_TRACK: Final[dict[str, ContentTrack]] = {
    "academic": "paper",
    "fun": "essay",
    "rant": "essay",
}


def derive_content_track(content_category: str | None, db_value: str | None = None) -> ContentTrack:
    """按 content_category 派生 content_track（paper|essay）。

    DB 值缺失时回退到 content_category 计算；两者都缺省时按学术稿（paper）
    保守处理——本刊默认是学术刊。
    """
    if db_value in ("paper", "essay"):
        return db_value  # type: ignore[return-value]
    return _CATEGORY_TO_TRACK.get((content_category or "").lower(), DEFAULT_CONTENT_TRACK)


def is_paper_track(content_category: str | None, db_value: str | None = None) -> bool:
    """是否学术稿（paper）：R 因子/篇均指标只统计 paper。"""
    return derive_content_track(content_category, db_value) == "paper"

DEFAULT_TRACK: Final[Track] = "serious"
ALL_TRACKS: Final[tuple[Track, ...]] = ("serious",)

# 展示口径：数据库存 slug。赛道下线后仅剩 serious 一项，保留映射是为了
# 导出/邮件等历史消费方不至于 KeyError。
TRACK_LABELS: Final[dict[str, str]] = {
    "serious": "正经研究",
}

TRACK_SHORT_LABELS: Final[dict[str, str]] = {
    "serious": "正经",
}

TRACK_DESCRIPTIONS: Final[dict[str, str]] = {
    "serious": "统一评审标准：格式、引用与论证要求对全部稿件一致，"
    "文章气质由每篇论文的荒诞指数（0–10）标注。",
}


def normalize_track(value: str | None) -> Track:
    """Coerce an arbitrary string to a valid track, defaulting conservatively.

    赛道已下线：任何非 ``serious`` 的输入（含历史 ``absurd``、None、
    任意脏数据）一律归一为 ``serious``。归一而非拒绝，保证旧客户端
    传 ``absurd`` 不会被 422 拒掉，历史数据也无需清洗。
    """
    return DEFAULT_TRACK


def track_label(value: str | None, *, short: bool = False) -> str:
    table = TRACK_SHORT_LABELS if short else TRACK_LABELS
    return table.get(normalize_track(value), TRACK_LABELS[DEFAULT_TRACK])


__all__ = [
    "ALL_TRACKS",
    "DEFAULT_CONTENT_TRACK",
    "DEFAULT_TRACK",
    "TRACK_DESCRIPTIONS",
    "TRACK_LABELS",
    "TRACK_SHORT_LABELS",
    "ContentTrack",
    "Track",
    "derive_content_track",
    "is_paper_track",
    "normalize_track",
    "track_label",
]
