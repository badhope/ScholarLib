"""赛道（track）——本刊唯一的产品分野，口径唯一真源。

Rubbish 不是"一个正经期刊 + 一个玩笑栏目"，而是**两本共用同一套形式规范的
期刊合订在一处**：

- ``serious``（正经研究）：按学术惯例评审，读者预期是"这是真研究"。
- ``absurd``（荒诞研究）：选题可以离谱，但**格式、引用、论证与伦理标准
  完全相同**——荒诞靠选题本身成立，不靠放松要求。

这个区分必须进数据，而不是只活在文案里：
- 评审时编辑要据此匹配评审人（荒诞稿常需要能接住玩笑的审稿人）；
- 阅读时读者要据此选择预期（把荒诞稿当正经研究引用会闹笑话）；
- 统计时要分赛道报（合起来的接收率没有意义）。

放在 core 而不是任一模块里：submission 与 catalog 都要用，且二者默认
不互相 import（见 docs/ARCHITECTURE.md「模块之间默认不互相 import」）。
"""

from __future__ import annotations

from typing import Final, Literal

Track = Literal["serious", "absurd"]

DEFAULT_TRACK: Final[Track] = "serious"
ALL_TRACKS: Final[tuple[Track, ...]] = ("serious", "absurd")

# 展示口径：数据库存 slug，前端/邮件/导出取这里的文案。
# 刻意不叫"正经/不正经"或"严肃/搞笑"——后者暗示荒诞赛道不用认真写。
TRACK_LABELS: Final[dict[str, str]] = {
    "serious": "正经研究",
    "absurd": "荒诞研究",
}

TRACK_SHORT_LABELS: Final[dict[str, str]] = {
    "serious": "正经",
    "absurd": "荒诞",
}

TRACK_DESCRIPTIONS: Final[dict[str, str]] = {
    "serious": "提出可被反驳的研究问题，按学术惯例组织论证与引用。",
    "absurd": "选题可以离谱，但格式、引用与论证标准与正经研究完全相同。",
}


def normalize_track(value: str | None) -> Track:
    """Coerce an arbitrary string to a valid track, defaulting conservatively.

    历史数据没有 track 列时全部落到 ``serious``：把正经论文误标成荒诞的
    伤害（读者以为是玩笑、编辑按玩笑标准审）远大于反过来。
    """
    if value in ALL_TRACKS:
        return value  # type: ignore[return-value]
    return DEFAULT_TRACK


def track_label(value: str | None, *, short: bool = False) -> str:
    table = TRACK_SHORT_LABELS if short else TRACK_LABELS
    return table.get(normalize_track(value), TRACK_LABELS[DEFAULT_TRACK])


__all__ = [
    "ALL_TRACKS",
    "DEFAULT_TRACK",
    "TRACK_DESCRIPTIONS",
    "TRACK_LABELS",
    "TRACK_SHORT_LABELS",
    "Track",
    "normalize_track",
    "track_label",
]
