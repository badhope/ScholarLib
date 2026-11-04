"""排印规范化的回归测试。

这些规则会直接改写作者稿件，因此每条都必须有「改对了」和「不该动的没动」
两个方向：过度清洗比不清洗更危险（会把正文改出语义偏差）。
"""

from __future__ import annotations

from app.modules.submission.normalize import audit_style, normalize_markdown


def test_heading_number_gets_space():
    # 编号 2.1 是二级章节，按刊物骨架应为 H3（H2 留给一级章节）
    out = normalize_markdown("# 标题\n\n##2.1方法\n")
    assert "### 2.1 方法" in out


def test_heading_keeps_year_like_number():
    # ``## 2024`` 是标题内容本身，不能被拆成 ``## 2024`` 的编号 + 空标题
    out = normalize_markdown("## 2024年度报告\n")
    assert "2024年度报告" in out


def test_caption_number_gets_space():
    out = normalize_markdown("图1系统架构\n")
    assert out.strip() == "图 1 系统架构"


def test_caption_rule_only_at_line_start():
    # 正文里的「如图1所示」不该被当成题注
    out = normalize_markdown("实验结果如图1所示，详见正文。\n")
    assert "图1" in out or "图 1" in out


def test_blank_line_between_paragraphs_survives():
    # 曾经的事故：句号后的空白用 \s+ 匹配，把空行吃掉，两段粘成一段
    out = normalize_markdown("第一段结束。\n\n**图1 说明**\n")
    assert "第一段结束。\n\n" in out


def test_table_broken_row_gets_pipe_not_merged():
    out = normalize_markdown("| a | b\n| c | d |\n")
    assert "| a | b |" in out
    assert "| c | d |" in out


def test_cjk_latin_spacing():
    out = normalize_markdown("使用Python实现\n")
    assert "使用 Python 实现" in out


def test_image_data_uri_untouched():
    uri = "![](data:image/png;base64,iVBORw0KGgoAAAANSUhEUg)"
    out = normalize_markdown(uri + "\n")
    assert uri in out


def test_link_untouched():
    out = normalize_markdown("参见[官方文档](https://example.com/a b)\n")
    assert "](https://example.com/a b)" in out


def test_idempotent():
    src = "##2.1方法\n使用Python实现。\n\n图1架构\n\n| a | b\n| c | d |\n"
    once = normalize_markdown(src)
    assert normalize_markdown(once) == once


def test_audit_flags_missing_structure():
    report = audit_style("## 引言\n本文讨论方法。\n")
    keys = {i["key"] for i in report["issues"]}
    assert "no_abstract" in keys
    assert "no_references" in keys
