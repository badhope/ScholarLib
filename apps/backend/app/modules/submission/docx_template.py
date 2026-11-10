"""按《RUBBISH 论文规范》生成 Word 稿件（官方模板）。

这份模板不是「把 Markdown 倒进 Word」，而是把规范本身写进样式里：

| 部位 | 字体 | 字号 | 其他 |
|---|---|---|---|
| 篇名 | 思源黑体（Noto Sans SC） | 小二（18pt） | 居中，段后 0.5 行 |
| 作者 | 霞鹜文楷（LXGW WenKai） | 小四（12pt） | 居中 |
| 单位 | 思源宋体（Noto Serif SC） | 小五（9pt） | 居中，含城市与邮编位 |
| 摘要 | 思源宋体 | 五号（10.5pt） | 「摘要：」思源黑体，两端对齐，首行不缩进 |
| 关键词 | 思源宋体 | 五号 | 「关键词：」思源黑体，分号分隔 |
| 一级标题 | 思源黑体 | 四号（14pt） | 段前 0.5 行，编号与题名间空一格 |
| 二级标题 | 思源黑体 | 小四（12pt）加粗 | 段前 0.3 行 |
| 三级标题 | 思源黑体 | 五号加粗（10.5pt） | 段前 0.25 行 |
| 正文 | 思源宋体 | 五号 | 首行缩进 2 字符，1.5 倍行距，两端对齐 |
| 图题 | 思源宋体 | 小五（9pt） | 图下居中，「图 N　题名」 |
| 表题 | 思源宋体 | 小五 | 表上居中，「表 N　题名」 |
| 表格 | 思源宋体 | 小五 | 三线表，无竖线 |
| 参考文献 | 思源宋体 | 小五 | 悬挂缩进，GB/T 7714-2015 |

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
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# 全站统一使用 OFL 免费字体，不引用任何商业字库：
# 正文与图表题注 Noto Serif SC（思源宋体）、标题 Noto Sans SC（思源黑体）、
# 作者与书名号 LXGW WenKai（霞鹜文楷）、西文 DejaVu Serif。
BODY_FONT = "Noto Serif SC"
HEAD_FONT = "Noto Sans SC"
AUTHOR_FONT = "LXGW WenKai"
LATIN_FONT = "DejaVu Serif"

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
    # 本站刊号（R-六位刊号-日期-流水），与 DOI 并列打印；不是官方 DOI。
    site_id: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    year: str = ""
    # paper / essay：娱乐轨不排“摘要/关键词/编号章节”，避免把吐槽稿
    # 印成论文。缺省当 paper，兼容旧调用。
    track: str = ""


def _set_font(
    run: Any,
    *,
    name: str,
    size: float,
    bold: bool = False,
    italic: bool = False,
    latin: str | None = None,
) -> None:
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
    # 中西文分开指定：只设 w:ascii 时 Word 会用主题字体接管中文，中文字体会丢
    fonts.set(qn("w:eastAsia"), name)
    fonts.set(qn("w:ascii"), latin_font)
    fonts.set(qn("w:hAnsi"), latin_font)


def _para(
    doc: Any,
    *,
    align: Any = WD_ALIGN_PARAGRAPH.JUSTIFY,
    indent_chars: float = 0.0,
    before: float = 0.0,
    after: float = 0.0,
    line: float = 1.5,
) -> Any:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    p.alignment = align
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    if indent_chars:
        pf.first_line_indent = Pt(indent_chars * BODY_PT)
    return p


def _page_number_footer(section: Any) -> None:
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


def _green_rule(paragraph: Any, *, size: str = "8") -> None:
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


def _brand_header(section: Any, title: str) -> None:
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
    # 页眉只做“认出是哪篇”的短标识：过长会顶到右边距，在 PDF 里被裁成
    # 半句话（实测 303 的长标题）。正文首屏已有完整篇名，无需重复。
    short_title = (title or "").strip()
    if len(short_title) > 22:
        short_title = short_title[:22] + "…"
    hr2 = p.add_run("　" + short_title)
    _set_font(hr2, name=BODY_FONT, size=8.5)
    hr2.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    _green_rule(p)


def _three_line_table(table: Any) -> None:
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


_MD_IMAGE = re.compile(
    r"!\[([^\]]*)\]\((data:image/[a-z+]+;base64,[^)]+|[^)\s]+)"
    r"(?:\s+[\"'][^\"']*[\"'])?\)"
)
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


def _add_inline(p: Any, text: str, *, size: float = BODY_PT, name: str = BODY_FONT) -> None:
    # 来源稿里大量跨段落的残破 `**` 无法与正文配对；宁可放弃少量粗体，
    # 也不能让 Word 下载件里印出 Markdown 符号。
    text = text.replace("```", "")
    for part in _INLINE.split(_clean_inline(text)):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            r = p.add_run(part[2:-2])
            _set_font(r, name=name, size=size, bold=True)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            r = p.add_run(part[1:-1])
            _set_font(r, name=name, size=size, italic=True)
        elif part.startswith("~~") and part.endswith("~~"):
            r = p.add_run(part[2:-2])
            _set_font(r, name=name, size=size)
            r.font.strike = True
        elif part.startswith("`") and part.endswith("`"):
            # 行内码：西文也要等宽，不能被 _set_font 的 DejaVu Serif 回退吃掉。
            r = p.add_run(part[1:-1])
            _set_font(r, name="DejaVu Sans Mono", size=size, latin="DejaVu Sans Mono")
        elif part.startswith(("《", "「", "“")):
            # 书名号/中文引号：按国内出版惯例走楷体，不用西文斜体硬套中文；
            # 书名额外用品牌墨绿点出，与页面上的「书名」语义一致。
            r = p.add_run(part)
            _set_font(r, name=AUTHOR_FONT, size=size)
            if part.startswith("《"):
                r.font.color.rgb = BRAND_DARK
        elif tag := _TAG_INNER.match(part):
            kind, inner = tag.group(1).lower(), tag.group(2)
            r = p.add_run(inner)
            _set_font(r, name=name, size=size)
            if kind == "u":
                r.font.underline = True
            elif kind == "mark":
                r.font.highlight_color = WD_COLOR_INDEX.YELLOW
            elif kind == "sup":
                r.font.superscript = True
            elif kind == "sub":
                r.font.subscript = True
        else:
            # 旧稿里常见跨段落的残破强调标记：`**主要拓展。`、`*图 2…**`。
            # 匹配成功的粗体在上面的分支处理；这里只清掉没配对的星号，
            # 避免 Word 里印出 `**`，同时不动 `2*3` 这类行内乘号。
            plain = part.replace("**", "")
            plain = re.sub(r"^\*{1,2}\s*", "", plain)
            plain = re.sub(r"\s*\*{1,2}$", "", plain)
            if not plain:
                continue
            r = p.add_run(plain)
            _set_font(r, name=name, size=size)


def _add_picture(doc: Any, src: str, base_dir: Path | None) -> bool:
    try:
        if src.startswith("data:"):
            raw = base64.b64decode(src.split("base64,", 1)[1])
            doc.add_picture(io.BytesIO(raw), width=Cm(14.0))
        elif (
            src.startswith("/api/catalog/")
            or src.startswith("https://rubbish.argjiemi.cn/api/catalog/")
            or src.startswith(("http://", "https://"))
        ):
            # 网页正文里的图片常写成 `/api/catalog/{rid}/img/{n}`。此前模板
            # 只认 data URI 和本地路径，这类引用会在 Word/PDF 里静默丢图，
            # 造成网页有图、下载件没图。这里按同站图片端点取回字节。
            from urllib.request import ProxyHandler, Request, build_opener

            url = (
                "http://localhost:8080" + src
                if src.startswith("/api/")
                else src.replace("https://rubbish.argjiemi.cn", "http://localhost:8080", 1)
                if src.startswith("https://rubbish.argjiemi.cn")
                else src
            )
            req = Request(url, headers={"User-Agent": "rubbish-docx/1.0"})
            opener = build_opener(ProxyHandler({}))
            with opener.open(req, timeout=8) as resp:
                raw = resp.read()
            if not raw:
                return False
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


def _caption(doc: Any, text: str, *, above: bool = False) -> None:
    p = _para(
        doc,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        before=0 if above else 3,
        after=6 if above else 10,
        line=1.0,
    )
    _add_inline(p, text, size=CAPTION_PT)


_MATH_SYMBOLS = ("⟩", "〈", "```")


def _plain_pipe_row(text: str) -> bool:
    """无分隔线的 `| a | b | c |` 行：只认纯文字表格，不碰狄拉克符号/矩阵/公式。"""
    t = text.strip()
    if not (t.startswith("|") and t.endswith("|") and t.count("|") >= 3):
        return False
    if any(sym in t for sym in _MATH_SYMBOLS):
        return False
    # 纯公式行不当表格：无中文且同时带 + / =，常见于矩阵、哈密顿量与态矢。
    if not re.search(r"[\u4e00-\u9fff]", t) and ("+" in t or "=" in t):
        return False
    # 至少有一个非空单元含数字、中文或拉丁字母，避免把空壳 | | | 当表格。
    cells = [c.strip() for c in t.strip("|").split("|")]
    if not any(re.search(r"[0-9A-Za-z\u4e00-\u9fff]", c) for c in cells):
        return False
    return True


_BACK_MATTER = (
    "参考文献",
    "致谢",
    "附录",
    "后记",
    "作者贡献",
    "利益冲突",
    "数据可用性",
    "数据与材料说明",
    "伦理声明",
    "伦理与数据声明",
    "作者回复",
    "审稿意见",
    "声明",
    "基金",
    "资助",
)
_TOP_NUM = re.compile(r"^(?:\d+[.、]?\s|一、|二、|三、|四、|五、|六、|七、|八、|九、|十、)")


def _normalize_heading_levels(md: str) -> str:
    """统一正文章节层级，并给缺失编号的一级章节补序号。

    34 号稿是 `## 摘要`→`## 关键词`→`## 引言`：剥离前置块后，正文所有
    章节都停在 Heading 2，比 24 号稿的 `# 引言` 低一级。这里按正文实际
    最小层级整体上移，保证每篇下载件的“引言/方法/结论”都在同一级。
    若一级章节全都没有编号，则按出现顺序补 `1 引言`、`2 …`；已有编号
    或“参考文献/致谢/附录”等后置部分不动。
    """
    lines = md.splitlines()
    levels = []
    for ln in lines:
        m = re.match(r"^(#{1,6})\s+", ln.strip())
        if m:
            levels.append(len(m.group(1)))
    if not levels:
        return md
    shift = min(levels) - 1
    if shift > 0:
        out = []
        for ln in lines:
            m = re.match(r"^(#{1,6})\s+(.*)$", ln.strip())
            if m:
                out.append("#" * max(1, len(m.group(1)) - shift) + " " + m.group(2))
            else:
                out.append(ln)
        lines = out
    # 一级章节统一重排编号：24 号稿第一篇是“引言”、后面却是“1 导师…”，
    # 混排会让读者以为缺了一节。后置部分（参考文献/致谢/附录）不编号。
    top = []
    for idx, ln in enumerate(lines):
        m = re.match(r"^#\s+(.*)$", ln.strip())
        if m:
            top.append((idx, m.group(1).strip()))
    if not top:
        return "\n".join(lines)
    seq = 0
    for idx, text in top:
        if text.startswith(_BACK_MATTER):
            continue
        seq += 1
        cleaned = re.sub(
            r"^(?:\d+[\.、]?\s*|一、|二、|三、|四、|五、|六、|七、|八、|九、|十、)", "", text
        ).strip()
        lines[idx] = f"# {seq} {cleaned}"
    # 旧稿把标题粘在段落末尾（“。##### 10.1.4.2 全文强制…”），只换行不
    # 拆开会让 `#####` 原样印进 PDF（295 实锤）。仅在句末标点后拆。
    md = "\n".join(lines)
    md = re.sub(r"(?<=[。；;.!?！？])[ \t]*#{2,6}[ \t]*", "\n## ", md)
    return md


_SECTION_WORD = re.compile(
    r"^[\d一二三四五六七八九十\.、]*\s*(摘\s*要|abstract|关键词|引[言论]|绪论|前言|导言|背景|问题|方法|材料|结果|讨论|结论|综述|文献|理论|模型|实验|分析|建议|展望|研究|数据|实证|案例|局限|贡献|创新|参考文献|致谢|附录)"
)


def _title_key(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", (text or "").lower())


def _is_title_line(text: str, meta: Meta) -> bool:
    """判断正文第一行是不是篇名（而不是“1 引言”这种章节）。"""
    t = re.sub(r"^#{1,6}\s*", "", text.strip()).strip()
    if not t or not meta.title:
        return False
    key, tkey = _title_key(t), _title_key(meta.title)
    if not key or not tkey:
        return False
    # 篇名与 meta.title 完全一致时优先判为篇名：否则「研究亮点…」
    # 「方法…」这类标题会被 _SECTION_WORD 误判成章节而留在正文里。
    if key == tkey:
        return True
    if _SECTION_WORD.match(t):
        return False
    if min(len(key), len(tkey)) >= 8 and (key.startswith(tkey) or tkey.startswith(key)):
        return True
    # 略改标题：只差几个字但仍保留主干（277/278 这类“语义坍缩”变体）
    from difflib import SequenceMatcher

    return SequenceMatcher(None, key, tkey).ratio() >= 0.82


_AUTHORISH = re.compile(r"(通讯作者|作者简介|收稿日期|基金项目|E-?mail|邮箱|@|†)")


def _clean_body_start(md: str, meta: Meta) -> str:
    """再清一次正文开头：旧稿常在“摘要/关键词”之后又放一遍中英标题、
    作者和单位；只靠前置块剥离会把这行当“1 xxx”印发。"""
    lines = md.splitlines()
    names = {n.strip() for n in (meta.authors or []) if n and n.strip()}
    # “**作者：** 安雅”这类行在摘要之前，先清掉
    while True:
        i = 0
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            break
        st = lines[i].strip()
        if re.match(r"^\**\s*作者[：:]", st) or st in names:
            del lines[i]
            continue
        break
    while True:
        i = 0
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            break
        first = lines[i].strip()
        hm = re.match(r"^#{1,6}\s+(.*)$", first)
        if not hm:
            # 旧稿开头是“英文标题 / 中文标题 → 作者行 → 空行 → 章节”，
            # 没有 Markdown 标题，前置块剥离抓不到（77 实锤：篇名以
            # “篇名M uzi”形式在导读上方重复一次）。只在 4 行内出现明显
            # 作者行且后面紧跟章节时才丢，避免吃掉真正的开篇段落。
            nxt = next((line.strip() for line in lines[i + 1 :] if line.strip()), "")
            head_idx = next(
                (
                    k
                    for k in range(i + 1, min(len(lines), i + 5))
                    if re.match(r"^#{1,6}\s+", lines[k].strip())
                ),
                None,
            )
            if (
                head_idx is not None
                and nxt
                and (
                    _AUTHORISH.search(nxt)
                    or re.match(r"^[\w\u4e00-\u9fff·\- ]{2,40}[¹²³⁴\*†,]+", nxt)
                )
                and len(nxt) <= 80
                and (len(first) >= 12 or re.search(r"[A-Za-z]", first))
            ):
                del lines[i:head_idx]
                continue
            break
        plain = hm.group(1).strip()
        nxt_head = next(
            (
                re.sub(r"^#{1,6}\s*", "", line.strip()).strip()
                for line in lines[i + 1 :]
                if re.match(r"^#{1,6}\s+", line.strip())
            ),
            "",
        )
        title_like = (not _SECTION_WORD.match(plain)) and (
            _is_title_line(first, meta)
            or (
                len(plain) >= 12
                and nxt_head
                and (_SECTION_WORD.match(nxt_head) or re.match(r"^\d+[\.、]?\s+", nxt_head))
            )
        )
        if not title_like:
            break
        del lines[i]
        # 紧随标题的作者/单位/关键词行一并删除，直到下一个标题
        while i < len(lines):
            st = lines[i].strip()
            if not st:
                del lines[i]
                continue
            if re.match(r"^#{1,6}\s+", st):
                break
            is_author = (
                st in names
                or _AUTHORISH.search(st)
                or re.match(r"^\**\s*作者[：:]", st)
                or re.match(r"^[¹²³⁴\d]?\s*[^。；]{2,60}(大学|学院|系|研究所|研究院|实验室)", st)
                or re.match(r"^[\w\u4e00-\u9fff·\- ]{2,40}[¹²³⁴\*†,，]+", st)
            )
            # 标题后、第一节前的纯关键词行（151 这类）
            is_kw = ("；" in st or ";" in st) and "。" not in st and len(st) <= 120
            if is_author or is_kw:
                del lines[i]
                continue
            break
    return "\n".join(lines)


def _strip_front_matter(md: str, meta: Meta) -> str:
    """去掉正文里与模板标题块重复的 H1 / 摘要 / 关键词区。

    投稿 Markdown 普遍是 `# 标题` → `## 摘要` → `## 关键词` → `## 引言`，
    而品牌模板已经用 meta 打印标题、作者、摘要和关键词。若不剥离，Word 与
    PDF 会出现“标题→摘要→关键词→标题→摘要→关键词”的重复前戏（303 实锤）。
    仅当模板确实有对应内容时才删，避免把唯一一份摘要删掉。
    """
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    # 第一个非空行可能是 H1 篇名，也可能是 `## 标题`（旧稿常见）。
    # 只按“像不像 meta.title”判断，绝不把 `# 引言` 当成篇名丢掉。
    if i < len(lines):
        first = lines[i].strip()
        if re.match(r"^#{1,6}\s+", first):
            # 明显篇名：meta.title 相似，或长标题且下一行就是摘要/关键词/
            # 作者行。这样 287/286 这类中英标题不一致的旧稿也不会把篇名
            # 当成“1 论文可以水到什么地步”的正文一级章节。
            _plain = re.sub(r"^#{1,6}\s*", "", first).strip()
            _nxt = next((line.strip() for line in lines[i + 1 :] if line.strip()), "")
            _heads = [
                re.sub(r"^#{1,6}\s*", "", line.strip()).strip()
                for line in lines[i + 1 :]
                if re.match(r"^#{1,6}\s+", line.strip())
            ]
            _next_head = _heads[0] if _heads else ""
            _long_title = (
                not _SECTION_WORD.match(_plain)
                and len(_plain) >= 14
                and (
                    re.match(r"^#{2,6}\s*(摘\s*要|abstract|关键词)", _nxt, re.I)
                    or re.match(r"^\**\s*作者", _nxt)
                    or bool(re.match(r"^[^。；]{2,40}（[^）]{1,40}）", _nxt))
                    or bool(re.match(r"^（[^）]{4,80}）$", _nxt))
                    or (
                        _next_head
                        and (
                            re.match(r"^(摘\s*要|abstract|关键词)", _next_head, re.I)
                            or _SECTION_WORD.match(_next_head)
                            or re.match(r"^\d+[\.、]?\s+", _next_head)
                        )
                    )
                )
            )
            if _is_title_line(first, meta) or _long_title:
                i += 1
    lines = lines[i:]
    # 投稿编辑器会把「作者信息」整块塞进 Markdown（298 实锤）：
    # ## 作者信息 + 第一作者/合作者/通讯作者 + 投稿须知。模板顶部已经有
    # 作者行，这块必须整段丢弃，否则邮箱会印到 PDF 首页标题上方。
    for k, raw in enumerate(lines):
        st = raw.strip()
        if re.match(r"^#{1,6}\s*(作者信息|作者简介|署名信息)\s*$", st):
            end = len(lines)
            for m in range(k + 1, len(lines)):
                if re.match(r"^#{1,6}\s+", lines[m].strip()):
                    end = m
                    break
            lines = lines[:k] + lines[end:]
            break
    # 作者/单位/通讯作者行：模板顶部已经用 meta 打印，正文里再出现一次
    # 会在摘要下方重复一段作者信息（线上 25 号稿实锤）。只删第一个二级
    # 标题之前、明显属于作者块的行，避免误伤正文。
    _names = {n.strip() for n in meta.authors if n and n.strip()}
    j = 0
    while j < len(lines):
        raw = lines[j]
        st = raw.strip()
        if not st:
            j += 1
            continue
        if re.match(r"^#{1,6}\s+", st):
            break
        if (
            st in _names
            or (meta.title and st == meta.title.strip())
            or (bool(_names) and all(x in _names for x in re.split(r"[、,，\s]+", st) if x))
            or (len(st) <= 80 and _AUTHORISH.search(st))
            or (len(st) <= 120 and re.match(r"^[^。；]{2,40}（[^）]{1,40}）", st))
        ):
            lines[j] = "\x00"
        j += 1
    lines = [ln for ln in lines if ln != "\x00"]
    i = 0
    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^#{2,6}\s+(.+)$", line.strip())
        if heading:
            name = re.sub(r"[*_`]", "", heading.group(1)).strip()
            if (meta.abstract and name.startswith("摘要")) or (
                meta.keywords and name.startswith("关键词")
            ):
                i += 1
                while i < len(lines) and not re.match(r"^#{1,6}\s+", lines[i].strip()):
                    i += 1
                continue
        out.append(line)
        i += 1
    return "\n".join(out).lstrip("\n")


_FUN_HEADING_RULES: list[tuple[re.Pattern[str], str | None]] = [
    (re.compile(r"^研究背景"), "为啥聊这个"),
    (re.compile(r"^(主要)?研究对象"), "先看谁"),
    (re.compile(r"^(研究设计|实验设计|观测实验设计)"), "怎么搭的"),
    (re.compile(r"^数据来源"), "数据哪来的"),
    (re.compile(r".*利益冲突.*"), None),
    (re.compile(r".*作者贡献.*"), None),
    (re.compile(r".*数据可用性.*"), None),
    (re.compile(r".*致谢.*"), None),
    (re.compile(r".*参考文献.*"), None),
    (re.compile(r".*关键词.*"), None),
    (re.compile(r"^(研究设计与材料范围|研究设计概述|研究设计与立场)$"), "怎么搭的"),
    (re.compile(r"^(研究对象与流程)$"), "先看谁"),
    (re.compile(r"^(研究背景与问题陈述)$"), "为啥聊这个"),
    (re.compile(r"^(数据来源与采集边界)$"), "数据哪来的"),
    (re.compile(r"^(引言|绪论|前言|导论)(?:[：:].*)?$"), "开场"),
    (re.compile(r"^(文献综述|相关工作|Related Work)$", re.I), "前情提要"),
    (
        re.compile(
            r"^(研究设计与方法|研究方法|方法|材料与方法|Methods?|Methodology|Materials and Methods)$",
            re.I,
        ),
        "怎么玩的",
    ),
    (re.compile(r"^(研究设计|实验设计|实验设置|Experimental Setup)$", re.I), "怎么搭的"),
    (re.compile(r"^(核心概念界定与理论基础|概念界定)$"), "先把词说清"),
    (re.compile(r"^(核心概念界定)$"), "语言通胀是个啥"),
    (re.compile(r"^(理论基础|分析框架|理论框架)$"), "拿什么看"),
    (re.compile(r"^(研究背景|研究意义|背景)$"), "为啥聊这个"),
    (re.compile(r"^(研究问题|问题提出|问题的提出)$"), "事儿是这么来的"),
    (re.compile(r"^(研究对象|样本来源)$"), "先看谁"),
    (re.compile(r"^(研究假设|假设)$"), "先猜一下"),
    (re.compile(r"^(数据来源|数据来源与空间范围)$"), "数据哪来的"),
    (re.compile(r"^(实验材料)$"), "拿什么做的"),
    (re.compile(r"^(模型构建)$"), "怎么搭的"),
    (re.compile(r"^(统计学分析)$"), "怎么算的"),
    (re.compile(r"^(数据分析|Data Analysis)$", re.I), "数据怎么说"),
    (re.compile(r"^(生成动因分析|动因分析)$"), "为啥会这样"),
    (re.compile(r"^(.*生成动因分析)$"), "为啥会这样"),
    (re.compile(r"^(语义贬值路径实证分析|实证分析)$"), "拿数据说话"),
    (re.compile(r"^(典型场景的质性拆解|质性拆解)$"), "一个个看"),
    (re.compile(r"^(网络社交的语义稀释效应|语义稀释效应)$"), "语义是怎么被稀释的"),
    (re.compile(r"^(情感脱敏时代的表达代偿|表达代偿)$"), "为什么我们都麻木了"),
    (re.compile(r"^(社交安全距离的缓冲构建|缓冲构建)$"), "亲密话当缓冲垫"),
    (re.compile(r"^(结果与讨论|结果|Results?)$", re.I), "所以呢"),
    (re.compile(r"^(讨论|Discussion)$", re.I), "聊两句"),
    (re.compile(r"^(结论|结语|总结|Conclusion|Conclusions?)$", re.I), "最后"),
    (re.compile(r"^(研究局限|局限|Limitations?)$", re.I), "别信太多"),
    (re.compile(r"^(创新点|研究贡献|贡献)$"), "花活在哪儿"),
    (re.compile(r"^(案例|案例分析)$"), "举个例子"),
    (re.compile(r"^(小结)$"), "先说到这"),
    (re.compile(r"^(附录|Appendix)$", re.I), "彩蛋"),
    (re.compile(r".*核心概念界定.*"), "先把词说清"),
    (re.compile(r"^(摘要|Abstract)$", re.I), None),
    (re.compile(r"^(关键词|关键字|Keywords?)$", re.I), None),
    (re.compile(r"^(参考文献|References?|Bibliography)$", re.I), None),
    (re.compile(r"^(致谢|Acknowledg(e)?ments?)$", re.I), None),
    (
        re.compile(
            r"^(声明|作者贡献|作者声明|贡献声明|利益冲突|基金项目?|资助|数据可用性|伦理声明|AI[ \t\u3000]*使用声明?)$",
            re.I,
        ),
        None,
    ),
]

_FUN_FALLBACK_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"研究|方法|模型|样本|变量|数据|实证|实验|检验|回归|统计|假设"), "怎么做的"),
    (re.compile(r"结果|发现|效应|显著性"), "所以呢"),
    (re.compile(r"讨论|局限|反思|不足"), "聊两句"),
    (re.compile(r"结论|总结|启示|建议"), "最后"),
    (re.compile(r"背景|问题|缘起|动机"), "为啥聊这个"),
    (re.compile(r"概念|定义|理论|框架|机制"), "先把词说清"),
    (re.compile(r"案例|场景|样本"), "举个例子"),
]


def _map_fun_heading(name: str, level: int = 2) -> str | None:
    """把论文式小标题换成副刊口吻；None 表示整节丢弃。

    三级及以下的小标题多是具体概念、理论或案例名，不做词表兜底改写，
    否则“社交成本最小化理论”会被误改成“先把词说清”。
    """
    for pattern, mapped in _FUN_HEADING_RULES:
        if pattern.match(name):
            return mapped
    if level >= 3:
        return name
    for pattern, mapped in _FUN_FALLBACK_RULES:
        if pattern.search(name):
            return mapped
    return name


def _dedupe_essay_against_abstract(md: str, abstract: str | None) -> str:
    """删掉正文中与“导读”完全重复的段落；只删长段，不动标题和短句。"""
    if not abstract:
        return md

    def norm(text: str) -> str:
        return re.sub(r"[“”\"'\s\u3000]", "", text).lower()

    abs_norm = norm(abstract)
    blocks = re.split(r"\n{2,}", md)
    kept: list[str] = []
    for block in blocks:
        text = block.strip()
        if not text or text.startswith("#"):
            kept.append(block)
            continue
        n = norm(text)
        if len(n) >= 40 and n in abs_norm:
            continue
        kept.append(block)
    return "\n\n".join(kept)


def _essayize(md: str, abstract: str | None = None) -> str:
    """副刊去论文范式：去作者上标块、去重复导读、改写小节标题、丢学术声明。"""
    md = re.sub(
        r"^\s*[^\n]{1,50}[¹²³⁴⁵⁶⁷⁸⁹]\s*\n+\s*[¹²³⁴⁵⁶⁷⁸⁹][^\n]*\n+",
        "",
        md,
    )
    md = _dedupe_essay_against_abstract(md, abstract)

    out: list[str] = []
    dropped_intro = False
    skip_section = False
    for line in md.splitlines():
        t = line.strip()
        m = re.match(r"^(#{1,6})\s+(.*)$", t)
        if not m:
            if not skip_section:
                out.append(line)
            continue
        level, raw_name = m.group(1), m.group(2)
        name = re.sub(
            r"^[0-9一二三四五六七八九十]+(?:[.．][0-9]+)*[、.．]?[\s　]*", "", raw_name
        ).strip()
        if not name:
            continue
        if len(level) == 1:
            # H1 是篇名，不是小节：不要套「研究→怎么做的」这类副刊章节词表。
            out.append(line)
            continue
        if name in ("摘要", "Abstract", "ABSTRACT"):
            if abstract:
                # 页首已经排了“导读”，正文里的摘要节整节丢弃。
                skip_section = True
                continue
            # 没有单独摘要时，把论文式“摘要”改写成副刊的“导读”，
            # 而不是整节丢掉——否则 Word 里会直接从正文开场。
            out.append(f"{level} 导读")
            skip_section = False
            continue
        mapped = _map_fun_heading(name, len(level))
        if mapped is None:
            skip_section = True
            continue
        skip_section = False
        if not dropped_intro and name in ("引言", "绪论", "前言", "导言"):
            dropped_intro = True
            continue
        out.append(f"{level} {mapped}")
    return "\n".join(out)


def build(md: str, meta: Meta, *, base_dir: Path | None = None) -> bytes:
    md = _normalize_heading_levels(_clean_body_start(_strip_front_matter(md, meta), meta))
    if (meta.track or "").lower() == "essay":
        md = _essayize(md, meta.abstract)
    doc = Document()
    # PDF/DOCX 元数据也必须是真作者，而不是 python-docx 的默认值：
    # 读者在属性面板里看到的 author=python-docx 会被当成“不是正式出版件”。
    try:
        doc.core_properties.title = meta.title or ""
        doc.core_properties.author = "、".join(meta.authors) or "Rubbish 编辑部"
        doc.core_properties.subject = "Rubbish 期刊论文"
        doc.core_properties.keywords = "; ".join(meta.keywords or [])
    except Exception:
        pass

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin = sec.bottom_margin = Cm(2.8)
    sec.left_margin = sec.right_margin = Cm(3.0)
    # 首页是标题页，不排 running head；从第二页起才出现刊名+短篇名。
    sec.different_first_page_header_footer = True
    _page_number_footer(sec)
    # 首页也要有页码：different_first_page_header_footer 只让页眉不出现，
    # 不代表首页可以没有页码。期刊 PDF 的首页同样需要可引用页码。
    try:
        _page_number_footer(sec.first_page_footer)
    except Exception:
        pass

    _brand_header(sec, meta.title)

    # 首页刊头：旧版首页完全没有品牌标识，读者拿到 PDF 只看到标题，
    # 分不清是哪本刊。这里放当前 R 标 + RUBBISH 字标，第二页起继续用
    # running head，保证首页与内页同一套品牌。
    p = _para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, before=0, after=2, line=1.0)
    if LOGO_PATH.exists():
        try:
            p.add_run().add_picture(str(LOGO_PATH), width=Cm(0.8))
        except Exception:
            pass
    r = p.add_run("　RUBBISH")
    _set_font(r, name=HEAD_FONT, size=9, bold=True)
    r.font.color.rgb = BRAND_GREEN

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
        # 中文摘要里的换行不能换成空格：会在“研 究”“局 限 性”处留下
        # 断字空隙；英文摘要才需要保留词间空格。
        _abs = meta.abstract.strip()
        _cjk = len(re.findall(r"[\u4e00-\u9fff]", _abs))
        _abs = re.sub(r"\s*\n\s*", "" if _cjk > 8 else " ", _abs)
        _abs = re.sub(r"[ \t]{2,}", " ", _abs)
        p = _para(doc, indent_chars=0, before=4, after=2, line=1.4)
        r = p.add_run("导读：" if (meta.track or "").lower() == "essay" else "摘要：")
        _set_font(r, name=HEAD_FONT, size=BODY_PT, bold=True)
        r.font.color.rgb = BRAND_DARK
        _add_inline(p, _abs, size=BODY_PT)

    if meta.keywords and (meta.track or "").lower() != "essay":
        # 关键词只放作者给定的关键词；内部学科/栏目标签不能混进来。
        _kws = [k.strip(" 　*~；;，,。.") for k in meta.keywords if k and k.strip(" 　*~；;，,。.")]
        if _kws:
            p = _para(doc, indent_chars=0, before=0, after=4, line=1.4)
            r = p.add_run("关键词：")
            _set_font(r, name=HEAD_FONT, size=BODY_PT, bold=True)
            r.font.color.rgb = BRAND_DARK
            _add_inline(p, "；".join(_kws), size=BODY_PT)

    # 刊名/卷期/年份/页码/DOI：期刊 PDF 的引用信息。此前 Meta 里有字段，
    # 但 build() 从未打印，导致每篇下载件都缺引用信息。
    _cite = []
    if meta.year:
        _cite.append(meta.year)
    if meta.volume or meta.issue:
        _cite.append(f"第 {meta.volume or '—'} 卷第 {meta.issue or '—'} 期")
    if meta.pages:
        _cite.append(f"页码 {meta.pages}")
    if meta.doi:
        _cite.append(f"DOI: {meta.doi}")
    if meta.site_id:
        _cite.append(f"本站刊号: {meta.site_id}")
    if _cite:
        p = _para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, before=0, after=10, line=1.3)
        _add_inline(p, " · ".join(_cite), size=CAPTION_PT)

    # --- 正文 ---
    lines = md.splitlines()
    i = 0
    # 摘要/关键词已经在刊头排过一遍，正文里遇到同名节直接跳过，
    # 否则 Word 里会印两遍摘要（这正是阅读页上看到的重复）。
    skip_abstract = False
    while i < len(lines):
        raw = lines[i]
        t = raw.strip()
        # 断图后的裸占位可能和正文粘在同一行，例如“指标如下：[图]”。
        # 全行匹配只能清掉独占一行的，行内残留会印进 Word，这里统一剔除。
        t = re.sub(r"\[(?:图|图片|image)\]", "", t, flags=re.I).strip()
        if not t or t in ("#", "##", "###", "####", "#####", "######"):
            i += 1
            continue
        # 原稿里图片链接断掉后只剩 `[图]` / `[图片]` 的裸占位：不要印进 Word。
        if re.fullmatch(r"\[(图|图片|image)\]", t, re.I):
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

        # 旧稿里偶发裸 HTML 图片：转成同一套图片路径，避免 Word 里印标签。
        m_html = re.fullmatch(r"<img\s+[^>]*src=[\"']([^\"']+)[\"'][^>]*>", t, re.I)
        if m_html:
            ok = _add_picture(doc, m_html.group(1), base_dir)
            if not ok:
                # 图源缺失时宁可不印，也不要把占位符印进正式 PDF
                pass
            i += 1
            continue

        # 引用块 / 分隔线 / 代码围栏标记：不当作正文符号印出来
        if t.startswith(">"):
            t = t.lstrip(">").strip()
            if not t:
                i += 1
                continue
        if re.fullmatch(r"[-*_]{3,}", t):
            i += 1
            continue
        if t.startswith("```"):
            i += 1
            continue

        # 图片（单独一行）
        m = _MD_IMAGE.fullmatch(t)
        if m:
            ok = _add_picture(doc, m.group(2), base_dir)
            if not ok:
                p = _para(doc)
                if (m.group(1) or "").strip():
                    _caption(doc, m.group(1))
            i += 1
            continue

        # 表格：标准 Markdown 分隔线，或旧稿里丢了分隔线的纯文字 | a | b | c | 行
        _std_table = (
            t.startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip())
        )
        _bare_table = _plain_pipe_row(t)
        if _std_table or _bare_table:
            rows: list[list[str]] = []
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                line = lines[j].strip()
                if not re.match(r"^\|[\s:|-]+\|$", line):
                    if _bare_table and not _plain_pipe_row(line):
                        break
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
            # 必须用 Word 内置的 Heading 样式，不能只是「把字设成无衬线加粗」：
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

        # 图题 / 表题（兼容旧稿行首残留的 * / **）
        # 只把「短、无句号」的图 N 行当图注；正文里「图 2 中…」「图 3 展示…」
        # 也以图号开头，若只按前缀判定会被误排成居中 9pt 图注。
        cap_t = re.sub(r"^\*{1,2}\s*", "", t)
        _caption_like = len(cap_t) <= 140 and "。" not in cap_t
        if _caption_like and re.match(r"^(图|附图)\s*\d", cap_t):
            _caption(doc, cap_t, above=False)
            i += 1
            continue
        if _caption_like and re.match(r"^(表|附表)\s*\d", cap_t):
            _caption(doc, cap_t, above=True)
            i += 1
            continue

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
        while (
            j < len(lines)
            and lines[j].strip()
            and not re.match(r"^(#|\||[-*•]\s|\d+[\.、\)]\s|!\[|图\s*\d|表\s*\d)", lines[j].strip())
        ):
            _cont = re.sub(r"\[(?:图|图片|image)\]", "", lines[j].strip(), flags=re.I).strip()
            if _cont:
                para.append(_cont)
            j += 1
        p = _para(doc, indent_chars=2, after=0, line=1.5)
        _add_inline(p, "".join(para))
        i = j

    buf = io.BytesIO()
    doc.save(buf)
    return _patch_theme(buf.getvalue())


def _patch_theme(blob: bytes) -> bytes:
    """把 python-docx 默认主题里的 Calibri/Cambria/宋体等换成 OFL 字体。

    正文 run 已显式设字体；主题只影响「用户打开后新敲的字」。
    一并换掉，避免模板在别人机器上又回退到商业字库。
    """
    import zipfile

    src = io.BytesIO(blob)
    out = io.BytesIO()
    mapping = {
        "Calibri": "Noto Sans SC",
        "Cambria": "Noto Serif SC",
        "Times New Roman": "DejaVu Serif",
        "宋体": "Noto Serif SC",
        "黑体": "Noto Sans SC",
        "楷体": "LXGW WenKai",
        "Consolas": "DejaVu Sans Mono",
    }
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/theme/theme1.xml":
                text = data.decode("utf-8")
                for a, b in mapping.items():
                    text = text.replace(f'typeface="{a}"', f'typeface="{b}"')
                data = text.encode("utf-8")
            zout.writestr(item, data)
    return out.getvalue()


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
            meta.keywords = [
                k.strip(" 　*~") for k in re.split(r"[；;]", m.group(1)) if k.strip(" 　*~")
            ]
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
