"""Word 下载件的品牌化与富文本还原回归测试。

覆盖用户明确要求的几点：logo 与绿色主题、国内可用字体（不引用 Google Fonts）、
标题一/标题二层级、加粗/斜体/删除线/行内码、书名号与中文引号、上下标与高亮。
"""

from __future__ import annotations

import io
import zipfile

from docx import Document
from docx.oxml.ns import qn

from app.domain.submission.docx_template import BODY_FONT, Meta, build

SAMPLE = """## 摘要
本文研究绿色排版。

关键词：绿色；排版

# 1 引言
这段包含《回收学报》与「绿色排版」、“中文引号”，**加粗**、*斜体*、~~删除线~~、
<u>下划线</u>、<mark>高亮</mark>、x<sup>2</sup> 与 H<sub>2</sub>O，以及 `行内码`。

## 1.1 方法
二级标题必须保留为 Heading 2。

### 1.1.1 细节
三级标题保留为 Heading 3。
"""


def _render() -> Document:
    blob = build(
        SAMPLE,
        Meta(
            title="绿色主题测试稿",
            authors=["张三"],
            abstract="本文研究绿色排版。",
            keywords=["绿色"],
        ),
    )
    assert blob.startswith(b"PK"), "生成的不是合法 docx"
    return Document(io.BytesIO(blob))


def _runs(doc: Document):
    return [r for p in doc.paragraphs for r in p.runs]


def test_brand_logo_and_green_header() -> None:
    blob = build(SAMPLE, Meta(title="绿色主题测试稿"))
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        media = [n for n in zf.namelist() if n.startswith("word/media/")]
    assert media, "页眉缺少品牌 logo 图片"

    doc = Document(io.BytesIO(blob))
    header = doc.sections[0].header.paragraphs[0]
    assert "RUBBISH" in header.text
    assert "<w:drawing>" in header._p.xml
    assert "2E5E4A" in header._p.xml, "页眉缺少品牌绿分隔线"


def test_title_and_labels_use_brand_dark() -> None:
    doc = _render()
    title_para = next(p for p in doc.paragraphs if p.text == "绿色主题测试稿")
    title_runs = [r for r in title_para.runs if r.font.color and r.font.color.rgb]
    assert title_runs
    assert str(title_runs[0].font.color.rgb) == "2E5E4A"
    labels = [r for r in _runs(doc) if r.text in {"摘要：", "关键词："}]
    assert len(labels) == 2
    assert all(str(r.font.color.rgb) == "2E5E4A" for r in labels)


def test_heading_levels_are_not_flattened() -> None:
    doc = _render()
    headings = [
        (p.style.name, p.text) for p in doc.paragraphs if p.style.name.startswith("Heading")
    ]
    assert ("Heading 1", "1 引言") in headings
    assert ("Heading 2", "1.1 方法") in headings
    assert ("Heading 3", "1.1.1 细节") in headings


def test_inline_semantics_all_rendered() -> None:
    runs = _runs(_render())
    texts = [r.text for r in runs]
    assert any(r.bold and r.text == "加粗" for r in runs)
    assert any(r.italic and r.text == "斜体" for r in runs)
    assert any(r.font.strike and r.text == "删除线" for r in runs)
    assert any(r.font.underline and r.text == "下划线" for r in runs)
    assert any(r.font.highlight_color is not None and r.text == "高亮" for r in runs)
    assert any(r.font.superscript and r.text == "2" for r in runs)
    assert any(r.font.subscript and r.text == "2" for r in runs)
    assert any(r.font.name == "DejaVu Sans Mono" and r.text == "行内码" for r in runs)
    assert "<u>" not in "".join(texts) and "<mark>" not in "".join(texts), "裸 HTML 标签泄漏到 Word"


def test_chinese_publication_marks_use_kaiti() -> None:
    runs = _runs(_render())

    def east_asia(run) -> str | None:
        rpr = run._element.rPr
        fonts = rpr.rFonts if rpr is not None else None
        return None if fonts is None else fonts.get(qn("w:eastAsia"))

    kaiti = [r.text for r in runs if east_asia(r) == "LXGW WenKai"]
    assert "《回收学报》" in kaiti
    assert "「绿色排版」" in kaiti
    assert "“中文引号”" in kaiti
    book = next(r for r in runs if r.text == "《回收学报》")
    assert str(book.font.color.rgb) == "2E5E4A"


def test_fonts_are_domestic_system_fonts() -> None:
    runs = _runs(_render())
    names = set()
    for r in runs:
        rpr = r._element.rPr
        fonts = rpr.rFonts if rpr is not None else None
        if fonts is not None:
            names.add(fonts.get(qn("w:eastAsia")))
            names.add(fonts.get(qn("w:ascii")))
    assert BODY_FONT in names
    assert not any(n and "google" in n.lower() for n in names)


def test_essayize_removes_paper_labels_and_multilevel_numbering() -> None:
    from app.domain.submission.docx_template import _essayize

    source = """## 摘要
这是导读正文。

## 关键词
测试；排版

## 1 引言
开场。

## 3.1 方法
做法。

### 10.1.4.2 结果
发现。
"""
    out = _essayize(source)
    assert "## 导读" in out
    assert "摘要" not in out
    assert "关键词" not in out
    assert "测试；排版" not in out
    assert "3.1" not in out
    assert "10.1.4.2" not in out
    assert "## 怎么玩的" in out
    assert "## 所以呢" in out
    assert "## 引言" not in out
