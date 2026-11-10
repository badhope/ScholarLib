"""赛道口径：paper 轨内部再分「学术论文 / 荒诞论文」。

历史背景：本刊曾有 serious / absurd 双赛道，后来一度被荒诞指数取代而
下线；2026-11 起重新启用为 paper 轨的子类型：serious=学术论文（正经
研究），absurd=荒诞论文（严格论文格式、一本正经地论证一个荒诞命题）。
它只描述「论文的写法与命题」，不改变 content_track=paper 的评审/计分
口径，也不影响副刊（content_track=essay）。

兼容策略：
- resources.track / submissions.track 原样保留；
- 新写入允许 serious / absurd；历史脏值仍归一为 serious；
- 副刊不展示该字段，读者只看学术论文 / 荒诞论文 / 副刊三区。
"""

from __future__ import annotations

from typing import Final, Literal

Track = Literal["serious", "absurd"]

# 内容赛道（P0，2026-11 收口为唯一权威口径）：
#   content_track（paper|essay）是唯一权威轨道字段；
#   content_category 退化为子类型标签——paper 恒为 academic，
#   essay 为 fun（娱乐向）或 rant（吐槽向）。
# 历史上 category→track 派生，已翻转：track→category 推导（见 resolve_category）。
ContentTrack = Literal["paper", "essay"]

DEFAULT_CONTENT_TRACK: Final[ContentTrack] = "paper"

# content_category → content_track。fun / rant 均为娱乐稿（essay）。
# 仅供 track 缺失时的兜底回推，不再是写入方向。
_CATEGORY_TO_TRACK: Final[dict[str, ContentTrack]] = {
    "academic": "paper",
    "fun": "essay",
    "rant": "essay",
}


def resolve_content_track(track: str | None, category: str | None = None) -> ContentTrack:
    """规范化 content_track：合法 track 权威胜出；缺失时按 category 回推。

    fun / rant → essay；academic 或两者都缺省时按学术稿（paper）保守处理——
    本刊默认是学术刊。
    """
    if track in ("paper", "essay"):
        return track  # type: ignore[return-value]
    return _CATEGORY_TO_TRACK.get((category or "").lower(), DEFAULT_CONTENT_TRACK)


def resolve_category(track: str | None, category: str | None = None) -> str:
    """由权威 content_track 推导/校正 content_category（单一权威口径）。

    - paper → 恒 academic（任何 fun/rant 输入一律覆盖，杜绝 paper+fun 漂移）；
    - essay → fun/rant 透传，缺省或非法值兜底 fun；
    - track 缺失时按 paper 保守处理（academic）。
    """
    track = resolve_content_track(track, category)
    if track == "paper":
        return "academic"
    return category if category in ("fun", "rant") else "fun"


def canonicalize_track_category(track: str | None, category: str | None = None) -> tuple[str, str]:
    """写入路径统一入口：返回 (track, category) 规范组合。

    track 合法时权威胜出；track 缺失时 category 回推赛道
    （academic→paper，fun/rant→essay）。任何写 content_track /
    content_category 的路径都必须经过本函数，禁止出现
    paper+fun、essay+academic 这类矛盾组合。
    """
    normalized_track = resolve_content_track(track, category)
    return normalized_track, resolve_category(normalized_track, category)


def derive_content_track(content_category: str | None, db_value: str | None = None) -> ContentTrack:
    """【兼容壳】按 content_category 派生 content_track。

    新口径下 content_track 才是权威；本函数保留是为了存量读路径
    （engagement.is_paper_track 等）——DB 有 track 值时 track 胜出，
    缺失才回退 category。语义等价于 resolve_content_track(db_value, category)。
    """
    return resolve_content_track(db_value, content_category)


def is_paper_track(content_category: str | None, db_value: str | None = None) -> bool:
    """是否学术稿（paper）：R 因子/篇均指标只统计 paper。"""
    return resolve_content_track(db_value, content_category) == "paper"


DEFAULT_TRACK: Final[Track] = "serious"
ALL_TRACKS: Final[tuple[Track, ...]] = ("serious", "absurd")

# 展示口径：数据库存 slug。只用于 paper 轨的子类型标签。
TRACK_LABELS: Final[dict[str, str]] = {
    "serious": "学术论文",
    "absurd": "荒诞论文",
}

TRACK_SHORT_LABELS: Final[dict[str, str]] = {
    "serious": "学术",
    "absurd": "荒诞",
}

TRACK_DESCRIPTIONS: Final[dict[str, str]] = {
    "serious": "正经研究：真实问题、可核查材料、按学术规范论证。",
    "absurd": "荒诞论文：严格论文格式，用可核查的材料一本正经地论证一个荒诞命题。",
}


def normalize_track(value: str | None) -> Track:
    """Coerce an arbitrary string to a valid paper subtype.

    只接受 ``serious`` / ``absurd``；None、空串与历史脏值保守归为 serious。
    旧客户端传 ``absurd`` 会正常保留，不再被静默改成正经研究。
    """
    return "absurd" if (value or "").strip().lower() == "absurd" else DEFAULT_TRACK


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
    "canonicalize_track_category",
    "derive_content_track",
    "is_paper_track",
    "normalize_track",
    "resolve_category",
    "resolve_content_track",
    "track_label",
]
