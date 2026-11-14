"""Markdown reader cleanup tests — the noise readers complained about."""

from __future__ import annotations

from app.domain.submission.markdown_clean import clean
from app.domain.submission.markdown_clean import reflow_paragraphs as _reflow

SAMPLE = """Rubbish - 于荒诞处见同路人

Open Access
Research Article
Received 17th April 2026,
Accepted 28th April 2026
https://mts-rubbish.github.io/

RUBBISH

AI 能否取代导师
Rui Tang<sup>1,*</sup>，Ying Cai<sup>2</sup>

### 摘要

本文讨论 AI 能否取代导师。<sup>1</sup>

关键词 **:** 人工智能；导师

### **1** 引言

正文第一段。

**Rubbish -** 于荒诞处见同路人

#### Rubbish - 于荒诞处见同路人

正文第二段。
"""


def test_drops_boilerplate_before_abstract() -> None:
    out = clean(SAMPLE)
    assert out.startswith("## 摘要")
    assert "mts-rubbish" not in out
    assert "Received 17th April" not in out
    assert "Open Access" not in out


def test_drops_html_tags() -> None:
    out = clean(SAMPLE)
    assert "<sup>" not in out
    assert "</sup>" not in out
    # 作者行在摘要之前，被 drop_prefix 一并裁掉（页面头部已有作者）
    assert "Rui Tang" not in out


def test_drops_running_heads_everywhere() -> None:
    out = clean(SAMPLE)
    assert "于荒诞处见同路人" not in out


def test_normalises_keyword_label() -> None:
    out = clean(SAMPLE)
    # 唯一保留的粗体：关键词标签（阅读器里作为字段名，视觉上需要区分）
    assert "**关键词**：" in out
    assert "**:**" not in out


def test_heading_bold_removed_and_space_added() -> None:
    out = clean(SAMPLE)
    assert "### 1 引言" in out
    assert "**1**" not in out


def test_abstract_promoted_to_h2() -> None:
    out = clean(SAMPLE)
    assert out.splitlines()[0] == "## 摘要"


def test_cjk_gaps_collapsed() -> None:
    md = "本文 讨论 中文 排版\n"
    assert clean(md).strip() == "本文讨论中文排版"


def test_drops_volume_footer_variants() -> None:
    for line in (
        "RUBBISH | Volume XX | February 2026 | XXXX",
        "> RUBBISH | Volume XX | March 2026 | XXXX",
        "**1** Rubbish | Volume XX | February 2026 | XXXX",
        "_Rubbish_ | Volume 9 | October 2026 | 2609",
    ):
        assert clean(line) == "", line


def test_drops_footer_merged_into_paragraph() -> None:
    md = "正文结束居民区的 _Rubbish_ | Volume 9 | October 2026 | 2609\n下一段"
    out = clean(md)
    assert "Volume" not in out
    assert "正文结束居民区的" in out
    assert "下一段" in out


def test_drops_english_tagline() -> None:
    md = "**Where the absurd dwells, fellow wayfarers meet.**"
    assert clean(md) == ""


# --- 1.6.0 段落重组（reflow_paragraphs） -------------------------------


def test_reflow_joins_cjk_lines_without_space() -> None:
    """中文段落续行拼接不插空格：修复「数字工 具」式断词。"""
    md = "近年来人工智能尤其是大模型技术快速进入知识生\n产与科学发现等领域。"
    assert _reflow(md) == "近年来人工智能尤其是大模型技术快速进入知识生产与科学发现等领域。"


def test_reflow_joins_latin_lines_with_space() -> None:
    md = "the quick brown fox\njumps over the lazy dog"
    assert _reflow(md) == "the quick brown fox jumps over the lazy dog"


def test_reflow_keeps_headings_and_lists_separate() -> None:
    md = "### 1 引言\n近年来 AI 发展迅速。\n- 第一项\n- 第二项\n正文继续。"
    out = _reflow(md)
    lines = out.split("\n")
    assert "### 1 引言" in lines
    assert "- 第一项" in lines
    assert "- 第二项" in lines
    assert "正文继续。" in lines


def test_reflow_preserves_code_fence() -> None:
    md = "```\ndef f():\n    return 1\n```\n后文。"
    assert "def f():" in _reflow(md)
    assert "    return 1" in _reflow(md)


def test_reflow_collapses_blank_runs_and_adds_spacing() -> None:
    md = "段落一结束。\n\n\n\n### 标题\n紧跟标题的正文。"
    out = _reflow(md)
    assert "\n\n\n" not in out
    assert "### 标题\n紧跟标题的正文。" in out


def test_reflow_table_lines_untouched() -> None:
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    out = _reflow(md)
    # 表格三行各自独立成行（不并入段落）
    assert out.split("\n") == ["| a | b |", "|---|---|", "| 1 | 2 |"]
