"""按《RUBBISH 论文规范》生成 Word 稿件（官方模板）。

这份模板不是「把 Markdown 倒进 Word」，而是把规范本身写进样式里：

| 部位 | 字体 | 字号 | 其他 |
|---|---|---|---|
| 篇名 | 黑体 | 小二（18pt） | 居中，段后 0.5 行 |
| 作者 | 楷体 | 小四（12pt） | 居中 |
| 单位 | 宋体 | 小五（9pt） | 居中，含城市与邮编位 |
| 摘要 | 宋体 | 五号（10.5pt） | 「摘要：」黑体，两端对齐，首行不缩进 |
| 关键词 | 宋体 | 五号 | 「关键词：」黑体，分号分隔 |
| 一级标题 | 黑体 | 四号（14pt） | 段前 0.5 行，编号与题名间空一格 |
| 二级标题 | 黑体 | 五号加粗（10.5pt） | 段前 0.3 行 |
| 正文 | 宋体 | 五号 | 首行缩进 2 字符，1.5 倍行距，两端对齐 |
| 图题 | 宋体 | 小五（9pt） | 图下居中，「图 N　题名」 |
| 表题 | 宋体 | 小五 | 表上居中，「表 N　题名」 |
| 表格 | 宋体 | 小五 | 三线表，无竖线 |
| 参考文献 | 宋体 | 小五 | 悬挂缩进，GB/T 7714-2015 |

为什么要有它：投稿进来的是 PDF，PDF 里没有"这是图注、这是二级标题"这种
信息，只有坐标。先按这套模板把内容落进 Word，编辑在 Word 里改一遍，再回
传系统——入库的就是结构化好的稿子，阅读页自然不会再乱。

    python -m scripts.paper docx a.md -o a.docx --authors "张三、李四"
"""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# 字体全部落在国内 Office/WPS 必带的系统字体上，不引用任何 Google Fonts：
# 正文宋体、标题黑体、作者与书名号楷体、西文 Times New Roman。
BODY_FONT = "宋体"
HEAD_FONT = "黑体"
AUTHOR_FONT = "楷体"
LATIN_FONT = "Times New Roman"

# 品牌色：Rubbish = 回收与再生，绿色是身份色。深墨绿用于正文标题与表格线，
# 亮绿用于页眉刊名与强调标记（与 favicon 的 #1F7A4D 一致）。
BRAND_DARK = RGBColor(0x2E, 0x5E, 0x4A)
BRAND_GREEN = RGBColor(0x1F, 0x7A, 0x4D)
BRAND_HEX = "2E5E4A"

# 页眉左上角图形标：回收箭头 + 纸堆/瓶子的绿色单色稿。
LOGO_PATH = Path(__file__).with_name("assets") / "brand-mark.png"

BODY_PT = 10.5  # 五号
CAPTION_PT = 9.0  # 小五
TITLE_PT = 18.0  # 小二


@dataclass
class Meta:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    doi: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""


def _set_font(run, *, name: str, size: float, bold: bool = False, italic: bool = False,
              latin: str | None = None) -> None:
    latin_font = latin or LATIN_FONT
    run.font.name = latin_font if not re.search(r"[\u4e00-\u9fff]", run.text or "") else name
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.append(fonts)
    # 中西文分开指定：只设 w:ascii 时 Word 会用主题字体接管中文，宋体就丢了
    fonts.set(qn("w:eastAsia"), name)
    fonts.set(qn("w:ascii"), latin_font)
    fonts.set(qn("w:hAnsi"), latin_font)


def _para(doc, *, align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent_chars=0.0, before=0.0, after=0.0,
          line=1.5):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    p.alignment = align
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    if indent_chars:
        pf.first_line_indent = Pt(indent_chars * BODY_PT)
    return p


def _page_number_footer(section) -> None:
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    for instr in ("begin", "PAGE", "end"):
        el = OxmlElement("w:fldChar") if instr != "PAGE" else OxmlElement("w:instrText")
        if instr == "PAGE":
            el.set(qn("xml:space"), "preserve")
            el.text = " PAGE "
        else:
            el.set(qn("w:fldCharType"), instr)
        run._element.append(el)
    _set_font(run, name=BODY_FONT, size=CAPTION_PT)


def _green_rule(paragraph, *, size: str = "8") -> None:
    """给段落加一条回收绿下边线（页眉、篇名用）。"""
    ppr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), BRAND_HEX)
    borders.append(bottom)
    ppr.append(borders)


def _brand_header(section, title: str) -> None:
    """页眉：绿色回收标 + 绿色刊名 + 篇名，下方一条品牌细线。

    logo 缺失时静默退化为纯文字刊头，绝不让下载接口因素材问题 500。
    """
    p = section.header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if LOGO_PATH.exists():
        try:
            p.add_run().add_picture(str(LOGO_PATH), width=Cm(0.72))
        except Exception:
            pass
    hr = p.add_run("　RUBBISH")
    _set_font(hr, name=HEAD_FONT, size=9, bold=True)
    hr.font.color.rgb = BRAND_GREEN
    hr2 = p.add_run("　" + (title or "")[:40])
    _set_font(hr2, name=BODY_FONT, size=9)
    hr2.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    _green_rule(p)


def _three_line_table(table) -> None:
    """三线表：顶线与底线 1.5pt，表头下 0.75pt，其余不画。"""
    tbl = table._tbl
    tblPr = tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge, sz in (("top", 12), ("bottom", 12)):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:color"), BRAND_HEX)
        borders.append(el)
    for edge in ("left", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        borders.append(el)
    tblPr.append(borders)

    # 表头行下加一条细线
    if table.rows:
        for cell in table.rows[0].cells:
            tcPr = cell._tc.get_or_add_tcPr()
            tcBorders = OxmlElement("w:tcBorders")
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"), "single")
            bottom.set(qn("w:sz"), "6")
            bottom.set(qn("w:color"), BRAND_HEX)
            tcBorders.append(bottom)
            tcPr.append(tcBorders)


_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\((data:image/[a-z+]+;base64,[^)]+|[^)\s]+)\)")
# 行内标记：加粗 / 斜体 / 行内码 / 删除线，以及中文出版物特有的书名号、
# 中文引号，与 PDF 转换残留的 u / mark / sup / sub 语义标签。
_INLINE = re.compile(
    r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|~~[^~]+~~"
    r"|《[^》]{1,80}》|「[^」]{1,80}」|“[^”]{1,80}”"
    r"|<(?:u|mark|sup|sub)>.*?</(?:u|mark|sup|sub)>)",
    re.I | re.S,
)
# PDF/Word 转换会在正文里留下裸 HTML，Word 里不该印出标签；
# 但 u/mark/sup/sub 承载真实排版语义，保留给 _INLINE 解析。
_HTML_TAG = re.compile(r"</?(mark|u|em|i|b|strong|span|sub|sup|div|p|font)[^>]*>", re.I)
_SEMANTIC_TAGS = frozenset({"u", "mark", "sup", "sub"})
_BR = re.compile(r"<br\s*/?>", re.I)
_MATH_DOLLAR = re.compile(r"(?<!\\)\$([^$]{1,200})\$")
_TAG_INNER = re.compile(r"^<([a-z]+)>(.*)</\1>$", re.I | re.S)


def _clean_inline(text: str) -> str:
    text = _BR.sub(" ", text)

    def _strip_or_keep(m: re.Match[str]) -> str:
        return m.group(0) if m.group(1).lower() in _SEMANTIC_TAGS else ""

    text = _HTML_TAG.sub(_strip_or_keep, text)
    return _MATH_DOLLAR.sub(r"\1", text)


def _add_inline(p, text: str, *, size: float = BODY_PT, name: str = BODY_FONT) -> None:
    for part in _INLINE.split(_clean_inline(text)):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            r = p.add_run(part[2:-2]); _set_font(r, name=name, size=size, bold=True)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            r = p.add_run(part[1:-1]); _set_font(r, name=name, size=size, italic=True)
        elif part.startswith("~~") and part.endswith("~~"):
            r = p.add_run(part[2:-2]); _set_font(r, name=name, size=size); r.font.strike = True
        elif part.startswith("`") and part.endswith("`"):
            # 行内码：西文也要等宽，不能被 _set_font 的 Times New Roman 回退吃掉。
            r = p.add_run(part[1:-1]); _set_font(r, name="Consolas", size=size, latin="Consolas")
        elif part.startswith(("《", "「", "“")):
            # 书名号/中文引号：按国内出版惯例走楷体，不用西文斜体硬套中文；
            # 书名额外用品牌墨绿点出，与页面上的「书名」语义一致。
            r = p.add_run(part); _set_font(r, name=AUTHOR_FONT, size=size)
            if part.startswith("《"):
                r.font.color.rgb = BRAND_DARK
        elif (tag := _TAG_INNER.match(part)):
            kind, inner = tag.group(1).lower(), tag.group(2)
            r = p.add_run(inner); _set_font(r, name=name, size=size)
            if kind == "u":
                r.font.underline = True
            elif kind == "mark":
                r.font.highlight_color = WD_COLOR_INDEX.YELLOW
            elif kind == "sup":
                r.font.superscript = True
            elif kind == "sub":
                r.font.subscript = True
        else:
            r = p.add_run(part); _set_font(r, name=name, size=size)


def _add_picture(doc, src: str, base_dir: Path | None) -> bool:
    try:
        if src.startswith("data:"):
            raw = base64.b64decode(src.split("base64,", 1)[1])
            doc.add_picture(io.BytesIO(raw), width=Cm(14.0))
        else:
            path = Path(src) if Path(src).is_absolute() else (base_dir or Path(".")) / src
            if not path.exists():
                return False
            doc.add_picture(str(path), width=Cm(14.0))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        return True
    except Exception:
        return False


def _caption(doc, text: str, *, above: bool = False) -> None:
    p = _para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, before=0 if above else 3, after=6 if above else 10, line=1.0)
    _add_inline(p, text, size=CAPTION_PT)


def build(md: str, meta: Meta, *, base_dir: Path | None = None) -> bytes:
    doc = Document()

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.8)
    sec.left_margin = sec.right_margin = Cm(3.0)
    sec.different_first_page_header_footer = False
    _page_number_footer(sec)

    _brand_header(sec, meta.title)

    # --- 篇名 / 作者 / 单位 ---
    if meta.title:
        p = _para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, before=12, after=10, line=1.2)
        r = p.add_run(meta.title)
        _set_font(r, name=HEAD_FONT, size=TITLE_PT, bold=True)
        r.font.color.rgb = BRAND_DARK
        _green_rule(p, size="12")

    if meta.authors:
        p = _para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, before=0, after=2, line=1.2)
        _add_inline(p, "　".join(meta.authors), size=12, name=AUTHOR_FONT)

    if meta.affiliations:
        p = _para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, before=0, after=10, line=1.2)
        _add_inline(p, "；".join(meta.affiliations), size=CAPTION_PT)

    # --- 摘要 / 关键词 ---
    if meta.abstract:
        p = _para(doc, indent_chars=0, before=4, after=2, line=1.4)
        r = p.add_run("摘要：")
        _set_font(r, name=HEAD_FONT, size=BODY_PT, bold=True)
        r.font.color.rgb = BRAND_DARK
        _add_inline(p, meta.abstract.replace("\n", " "), size=BODY_PT)

    if meta.keywords:
        p = _para(doc, indent_chars=0, before=0, after=10, line=1.4)
        r = p.add_run("关键词：")
        _set_font(r, name=HEAD_FONT, size=BODY_PT, bold=True)
        r.font.color.rgb = BRAND_DARK
        _add_inline(p, "；".join(meta.keywords), size=BODY_PT)

    # --- 正文 ---
    lines = md.splitlines()
    i = 0
    # 摘要/关键词已经在刊头排过一遍，正文里遇到同名节直接跳过，
    # 否则 Word 里会印两遍摘要（这正是阅读页上看到的重复）。
    skip_abstract = False
    while i < len(lines):
        raw = lines[i]
        t = raw.strip()
        if not t:
            i += 1
            continue
        if re.match(r"^#{1,6}\s*(摘\s*要|abstract)\s*$", t, re.I):
            skip_abstract = True
            i += 1
            continue
        if skip_abstract:
            if t.startswith("#") or re.match(r"^\**\s*关键词", t):
                skip_abstract = False
                if re.match(r"^\**\s*关键词", t):
                    i += 1
                    continue
            else:
                i += 1
                continue

        # 图片（单独一行）
        m = _MD_IMAGE.fullmatch(t)
        if m:
            ok = _add_picture(doc, m.group(2), base_dir)
            if not ok:
                p = _para(doc)
                _add_inline(p, f"[图片缺失] {m.group(1) or m.group(2)[:60]}", size=CAPTION_PT)
            i += 1
            continue

        # 表格
        if t.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            rows: list[list[str]] = []
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                line = lines[j].strip()
                if not re.match(r"^\|[\s:|-]+\|$", line):
                    rows.append([c.strip() for c in line.strip("|").split("|")])
                j += 1
            if rows:
                ncol = max(len(r) for r in rows)
                table = doc.add_table(rows=len(rows), cols=ncol)
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                _three_line_table(table)
                for ri, row in enumerate(rows):
                    for ci in range(ncol):
                        cell = table.cell(ri, ci)
                        cell.text = ""
                        p = cell.paragraphs[0]
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        p.paragraph_format.line_spacing = 1.15
                        _add_inline(p, row[ci] if ci < len(row) else "", size=CAPTION_PT)
                _para(doc, after=6, line=1.0)
            i = j
            continue

        # 标题
        hm = re.match(r"^(#{1,6})\s+(.*)$", t)
        if hm:
            level = len(hm.group(1))
            text = hm.group(2).strip()
            # 必须用 Word 内置的 Heading 样式，不能只是「把字设成黑体加粗」：
            # 编辑部改完要回传系统，入库走 mammoth，它只认样式。直接格式化
            # 的标题回读后一律变成 <p><strong>，章节结构全丢——这正是上一批
            # 旧稿「没有标题」的来源。
            # Markdown 层级与 Word Heading 一一对应：# → H1、## → H2、### → H3。
            # 旧实现把 # 与 ## 都压成 Heading 1，编辑回传后二级结构全丢，
            # 正是「编辑器里有标题一标题二、浏览时看不出来」的根因。
            style = f"Heading {min(level, 4)}"
            try:
                p = doc.add_paragraph(style=style)
            except KeyError:
                p = doc.add_paragraph()
            pf = p.paragraph_format
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            pf.space_before = Pt(12 if level == 1 else (8 if level == 2 else 6))
            pf.space_after = Pt(6 if level == 1 else 4)
            pf.line_spacing = 1.3
            run = p.add_run(text)
            heading_size = 14 if level == 1 else (12 if level == 2 else BODY_PT)
            _set_font(run, name=HEAD_FONT, size=heading_size, bold=True)
            # 一级/二级标题用品牌墨绿，更深层保持黑色，避免整页飘绿影响阅读。
            run.font.color.rgb = BRAND_DARK if level <= 2 else RGBColor(0, 0, 0)
            i += 1
            continue

        # 图题 / 表题
        if re.match(r"^(图|附图)\s*\d", t):
            _caption(doc, t, above=False); i += 1; continue
        if re.match(r"^(表|附表)\s*\d", t):
            _caption(doc, t, above=True); i += 1; continue

        # 参考文献条目
        if re.match(r"^\[?\d{1,3}[\]\.、)]\s", t):
            p = _para(doc, align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent_chars=0, after=2, line=1.3)
            p.paragraph_format.left_indent = Pt(21)
            p.paragraph_format.first_line_indent = Pt(-21)
            _add_inline(p, t, size=CAPTION_PT)
            i += 1
            continue

        # 列表
        lm = re.match(r"^[-*•]\s+(.*)$", t)
        if lm:
            p = _para(doc, indent_chars=0, after=2, line=1.5)
            p.paragraph_format.left_indent = Pt(21)
            p.paragraph_format.first_line_indent = Pt(-10.5)
            _add_inline(p, "· " + lm.group(1))
            i += 1
            continue

        # 正文段（把软换行合回一段）
        para = [t]
        j = i + 1
        while j < len(lines) and lines[j].strip() and not re.match(
            r"^(#|\||[-*•]\s|\d+[\.、\)]\s|!\[|图\s*\d|表\s*\d)", lines[j].strip()
        ):
            para.append(lines[j].strip())
            j += 1
        p = _para(doc, indent_chars=2, after=0, line=1.5)
        _add_inline(p, "".join(para))
        i = j

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --- 从 Markdown 里抽出元数据 -------------------------------------------------


def parse_meta(md: str, fallback_title: str = "") -> Meta:
    meta = Meta(title=fallback_title)
    lines = md.splitlines()

    # 摘要：## 摘要 之后、关键词之前的连续段落
    for idx, ln in enumerate(lines):
        if re.match(r"^#{1,6}\s*(摘\s*要|abstract)", ln.strip(), re.I):
            got: list[str] = []
            for nxt in lines[idx + 1 :]:
                s = nxt.strip()
                if not s:
                    continue
                if s.startswith("#") or re.match(r"^\**\s*关键词", s):
                    break
                got.append(s)
            meta.abstract = "".join(got)
            break

    for ln in lines:
        m = re.match(r"^\**\s*关键词[：:]\**\s*(.+)$", ln.strip())
        if m:
            meta.keywords = [k.strip(" 　*~") for k in re.split(r"[；;]", m.group(1)) if k.strip(" 　*~")]
            break
    return meta


def build_file(src: Path, out: Path, *, title: str = "", authors: list[str] | None = None) -> Path:
    md = src.read_text(encoding="utf-8", errors="replace")
    meta = parse_meta(md, fallback_title=title or src.stem)
    if authors:
        meta.authors = authors
    blob = build(md, meta, base_dir=src.parent)
    out.write_bytes(blob)
    return out
