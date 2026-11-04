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


def test_fullwidth_space_keeps_heading_depth():
    """``2.1　演化`` 不能因为全角空格回溯成「深度 1」而把 H3 降成 H2。"""
    src = "## 1 引言\n\n### 2.1　演化博弈与分析工具\n\n#### 2.1.1 模型\n"
    out = normalize_markdown(src)
    assert "### 2.1　演化博弈与分析工具" in out
    assert "#### 2.1.1 模型" in out


def test_table_cell_gap_preserved():
    """表格单元格边界前的空格是列分隔留白，不能被中文标点空格规则清掉。"""
    src = "| 对摸鱼者 | — | +0.6（被掩护） | −1.2（被查处） |\n"
    assert normalize_markdown(src) == src


def test_broken_emdash_merged():
    assert "——谁能掌" in normalize_markdown("— —谁能掌")


def test_shredded_paragraph_rejoined():
    """行尾无句末标点 = 版心换行，必须接回；行尾有句号 = 作者断句，保持分段。"""
    src = "共纳入 412 名受访者，其中男性 198 名，\n女性 214 名。\n另一段从这里开始。\n"
    out = normalize_markdown(src)
    assert "男性 198 名，女性 214 名。" in out
    assert "另一段从这里开始。" in out


def test_blank_line_inside_sentence_ignored():
    """PDF 分栏留下的空行不该把句子切断。"""
    src = "问卷由调查员面对面发放，\n\n回收有效问卷 386 份。\n"
    out = normalize_markdown(src)
    assert "发放，回收有效问卷" in out.replace("\n", "")


def test_caption_not_swallowed_by_reflow():
    src = "结果如下所示，\n图1样本分布\n数据分布均匀。\n"
    out = normalize_markdown(src)
    assert "\n图 1 样本分布\n" in out


def test_formula_line_not_promoted_to_heading():
    """``2.1.3 limt→+oP(t)=Ao`` 是公式，不是章节标题。"""
    out = normalize_markdown("2.1.3 limt→+oP(t)=Ao\n")
    assert not out.lstrip().startswith("#")


def test_formula_heading_demoted_and_kept_on_own_line():
    src = "## limt→+oP(t)=Ao\n\n## IN=S\n\n正文。\n"
    out = normalize_markdown(src)
    assert "# limt" not in out and "# IN=S" not in out
    assert "\nIN=S\n" in out


def test_stuck_headings_split():
    out = normalize_markdown("## 2.1 模型2.1.1 核心定义\n")
    assert "### 2.1 模型" in out
    assert "#### 2.1.1 核心定义" in out


def test_fullwidth_digits_normalised():
    assert "## 4 结论" in normalize_markdown("## ４ 结论\n")


def test_cjk_bracket_widened_but_code_kept():
    out = normalize_markdown("条件(被爱解存在)成立，函数 f(x) 与 (OOD) 除外。\n")
    assert "（被爱解存在）" in out
    assert "f(x)" in out and "(OOD)" in out
