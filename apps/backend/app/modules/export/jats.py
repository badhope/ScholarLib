"""Markdown → NISO JATS 1.3 全文转换器（纯函数，无 I/O）。

用途：``GET /api/catalog/resources/{id}/manuscript.jats`` 与书目级
``GET /api/export?format=jats``。JATS 是 PubMed Central / Crossref /
DOI 元数据注册的标准交换格式，产出必须是 well-formed XML。

转换口径（与 Word 下载件一致）：

- ``#``/``##``/``###`` → 嵌套 ``<sec>``（title 一级、H2 二级、H3 三级）；
- 段落 → ``<p>``；``**bold**`` → ``<bold>``、``*italic*`` → ``<italic>``、
  ``~~del~~`` → ``<strike>``、`` `code` `` → ``<monospace>``、
  ``<u>`` → ``<underline>``、``<mark>`` → ``<styled-content style="highlight">``、
  ``<sup>/<sub>`` → 原生 ``<sup>/<sub>``；
- 无序/有序列表 → ``<list>``，引用块 → ``<disp-quote>``，表格 →
  ``<table-wrap>``，图片 → ``<fig>``，围栏代码块 → ``<code>``；
- PDF 转换残留的裸 HTML 标签按 Word 下载件同一规则清理。

书名号《》与中文引号是纯文本，JATS 原样保留（Word 侧的楷体是排版
语义，XML 交换层不需要）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from xml.sax.saxutils import escape as _xml_escape

_JATS_DTD = "https://jats.nlm.nih.gov/publishing/1.3/JATS-journalpublishing1.dtd"
_JATS_XSD = "https://jats.nlm.nih.gov/publishing/1.3/xsd/JATS-journalpublishing1.xsd"

# 与 docx_template 同源的清理规则：PDF/Word 转换会在正文留下裸 HTML。
_HTML_TAG = re.compile(r"</?(?:mark|u|em|i|b|strong|span|div|p|font)[^>]*>", re.I)
_BR = re.compile(r"<br\s*/?>", re.I)
_MATH_DOLLAR = re.compile(r"(?<!\\)\$([^$]{1,200})\$")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\((data:image/[a-z+]+;base64,[^)]+|[^)\s]+)\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_INLINE = re.compile(
    r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|~~[^~]+~~|<u>[^<]*</u>|<mark>[^<]*</mark>|"
    r"<sup>[^<]*</sup>|<sub>[^<]*</sub>)",
    re.I,
)


@dataclass
class JatsMeta:
    """书目元数据（front matter）。全部字段允许为空，转换器按需输出。"""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    journal: str = "Rubbish"
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    year: int = 2026
    language: str = "zh"
    article_id: str = ""
    publisher_name: str = "Rubbish Editorial Office"


def _esc(text: str) -> str:
    return _xml_escape(text or "", {'"': "&quot;"})


def _clean_inline(text: str) -> str:
    text = _BR.sub(" ", text)
    text = _HTML_TAG.sub("", text)
    return _MATH_DOLLAR.sub(r"\1", text)


def _render_inline(text: str) -> str:
    """Markdown 行内标记 → JATS 行内元素，纯文本转义。

    注意顺序：先按语义标签切分（u/mark/sup/sub 是要保留的排版语义），
    未匹配的纯文本再经 ``_clean_inline`` 剥掉残留裸标签并转义——
    如果反过来先 clean，语义标签会在切分前就被剥掉。
    """
    out: list[str] = []
    pos = 0
    for m in _INLINE.finditer(text):
        out.append(_esc(_clean_inline(text[pos : m.start()])))
        part = m.group(0)
        low = part.lower()
        if low.startswith("**"):
            out.append(f"<bold>{_render_inline(part[2:-2])}</bold>")
        elif low.startswith("~~"):
            out.append(f"<strike>{_render_inline(part[2:-2])}</strike>")
        elif low.startswith("`"):
            out.append(f"<monospace>{_esc(part[1:-1])}</monospace>")
        elif low.startswith("<u>"):
            out.append(f"<underline>{_render_inline(part[3:-4])}</underline>")
        elif low.startswith("<mark>"):
            out.append(
                f'<styled-content style="highlight">{_render_inline(part[6:-7])}</styled-content>'
            )
        elif low.startswith("<sup>"):
            out.append(f"<sup>{_render_inline(part[5:-6])}</sup>")
        elif low.startswith("<sub>"):
            out.append(f"<sub>{_render_inline(part[5:-6])}</sub>")
        else:  # *italic*
            out.append(f"<italic>{_render_inline(part[1:-1])}</italic>")
        pos = m.end()
    out.append(_esc(_clean_inline(text[pos:])))
    return "".join(out)


def _strip_image_and_links(text: str) -> str:
    """JATS 正文里链接转纯文本（引用走 <xref>，普通 URL 文本保留）；图片由块级处理。"""
    text = _MD_IMAGE.sub(r"\1", text)
    return _MD_LINK.sub(r"\1（\2）", text)


# --- 块级解析 -------------------------------------------------------------


class _Block:
    __slots__ = ("kind", "lang", "level", "lines")

    def __init__(self, kind: str, level: int = 0, lang: str = "") -> None:
        self.kind = kind
        self.level = level
        self.lang = lang
        self.lines: list[str] = []


def _parse_blocks(md: str) -> list[_Block]:
    """把 Markdown 切成块：h1/h2/h3/p/li/quote/table/code/fig。"""
    blocks: list[_Block] = []
    current = _Block("p")
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            if current.kind == "code":
                blocks.append(current)
                current = _Block("p")
            else:
                if current.lines:
                    blocks.append(current)
                current = _Block("code", lang=stripped[3:].strip())
            i += 1
            continue
        if current.kind == "code":
            current.lines.append(line)
            i += 1
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if m:
            if current.lines:
                blocks.append(current)
            current = _Block("h", level=len(m.group(1)))
            current.lines.append(m.group(2))
            blocks.append(current)
            current = _Block("p")
            i += 1
            continue
        if re.match(r"^[-*]\s+", stripped):
            if current.kind != "li":
                if current.lines:
                    blocks.append(current)
                current = _Block("li")
            current.lines.append(re.sub(r"^[-*]\s+", "", stripped))
            i += 1
            continue
        if re.match(r"^\d+[.)]\s+", stripped):
            if current.kind != "li":
                if current.lines:
                    blocks.append(current)
                current = _Block("li")
            current.lines.append(re.sub(r"^\d+[.)]\s+", "", stripped))
            i += 1
            continue
        if stripped.startswith(">"):
            if current.kind != "quote":
                if current.lines:
                    blocks.append(current)
                current = _Block("quote")
            current.lines.append(stripped.lstrip("> "))
            i += 1
            continue
        if (
            stripped.startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\|?[\s:|-]+\|?", lines[i + 1].strip())
            and set(
                lines[i + 1].replace("|", "").replace("-", "").replace(":", "").replace(" ", "")
            )
            == set()
        ):
            if current.lines:
                blocks.append(current)
            current = _Block("table")
            current.lines.append(stripped)
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                current.lines.append(lines[i].strip())
                i += 1
            blocks.append(current)
            current = _Block("p")
            continue
        m_img = _MD_IMAGE.match(stripped)
        if m_img and stripped == m_img.group(0):
            if current.lines:
                blocks.append(current)
            current = _Block("fig")
            current.lines.append(m_img.group(1))
            current.lang = m_img.group(2)  # reuse lang for image src
            blocks.append(current)
            current = _Block("p")
            i += 1
            continue
        if not stripped:
            if current.lines:
                blocks.append(current)
                current = _Block("p")
            i += 1
            continue
        if current.kind != "p":
            blocks.append(current)
            current = _Block("p")
        current.lines.append(stripped)
        i += 1
    if current.lines:
        blocks.append(current)
    return blocks


def _sec_tree(blocks: list[_Block]) -> str:
    """h1/h2/h3 + 后续内容 → 嵌套 <sec>。无标题的正文直接进 <body>。"""

    class _Sec:
        __slots__ = ("children", "level", "title")

        def __init__(self, title: str, level: int) -> None:
            self.title = title
            self.level = level
            self.children: list[object] = []

    root: list[object] = []
    stack: list[_Sec] = []

    def _target() -> list[object]:
        return stack[-1].children if stack else root

    for b in blocks:
        if b.kind == "h":
            level = b.level
            while stack and stack[-1].level >= level:
                stack.pop()
            sec = _Sec(_render_inline(b.lines[0]), level)
            _target().append(sec)
            stack.append(sec)
            continue
        xml = _render_block(b)
        if xml:
            _target().append(xml)

    out: list[str] = []

    def _render(node: object) -> None:
        if isinstance(node, _Sec):
            out.append(f"<sec><title>{node.title}</title>")
            for child in node.children:
                _render(child)
            out.append("</sec>")
        else:
            out.append(str(node))

    for node in root:
        _render(node)
    return "".join(out)


def _render_block(b: _Block) -> str:
    if b.kind == "p":
        text = _strip_image_and_links(" ".join(b.lines))
        return f"<p>{_render_inline(text)}</p>" if text.strip() else ""
    if b.kind == "li":
        items = "".join(
            f"<list-item><p>{_render_inline(_strip_image_and_links(t))}</p></list-item>"
            for t in b.lines
        )
        return f'<list list-type="bullet">{items}</list>'
    if b.kind == "quote":
        paras = "".join(f"<p>{_render_inline(_strip_image_and_links(t))}</p>" for t in b.lines)
        return f"<disp-quote>{paras}</disp-quote>"
    if b.kind == "code":
        code = _esc("\n".join(b.lines))
        lang = f' language="{_esc(b.lang)}"' if b.lang else ""
        return f"<code{lang}><preformat>{code}</preformat></code>"
    if b.kind == "fig":
        alt = _esc(b.lines[0] if b.lines else "")
        src = _esc(b.lang)
        return f'<fig><caption><p>{alt}</p></caption><graphic xlink:href="{src}"/></fig>'
    if b.kind == "table":
        return _render_table(b.lines)
    return ""


def _render_table(lines: list[str]) -> str:
    rows = [
        [c.strip() for c in r.strip().strip("|").split("|")]
        for r in lines
        if not set(r.replace("|", "").replace("-", "").replace(":", "").replace(" ", "")) == set()
    ]
    if not rows:
        return ""
    header, *body = rows
    width = len(header)
    thead = "".join(f"<th>{_render_inline(c)}</th>" for c in header)
    trs = []
    for row in body:
        tds = "".join(f"<td>{_render_inline(c)}</td>" for c in (list(row) + [""] * width)[:width])
        trs.append(f"<tr>{tds}</tr>")
    return (
        "<table-wrap><table><thead>"
        f"<tr>{thead}</tr></thead><tbody>{''.join(trs)}</tbody>"
        "</table></table-wrap>"
    )


def _front(meta: JatsMeta) -> str:
    parts: list[str] = [f"<journal-meta><journal-title>{_esc(meta.journal)}</journal-title>"]
    parts.append(
        "<publisher><publisher-name>"
        f"{_esc(meta.publisher_name)}</publisher-name></publisher></journal-meta>"
    )
    article_meta = (
        [f'<article-id pub-id-type="doi">{_esc(meta.doi)}</article-id>'] if meta.doi else []
    )
    if meta.article_id:
        article_meta.append(
            f'<article-id pub-id-type="publisher-id">{_esc(meta.article_id)}</article-id>'
        )
    article_meta.append(
        f"<title-group><article-title>{_render_inline(meta.title)}</article-title></title-group>"
    )
    contribs = []
    for i, name in enumerate(meta.authors):
        contribs.append(
            f'<contrib corresp="no"><name><string-name>{_esc(name)}</string-name></name>'
            f'<xref ref-type="aff" rid="aff{i + 1}">{i + 1}</xref></contrib>'
        )
    affs = [
        f'<aff id="aff{i + 1}"><institution>{_esc(a)}</institution></aff>'
        for i, a in enumerate(meta.affiliations)
    ]
    if contribs or affs:
        article_meta.append("<contrib-group>" + "".join(contribs) + "</contrib-group>")
        article_meta.extend(affs)
    pub_date = f'<pub-date pub-type="epub"><year>{meta.year}</year></pub-date>'
    volume = f"<volume>{_esc(meta.volume)}</volume>" if meta.volume else ""
    issue = f"<issue>{_esc(meta.issue)}</issue>" if meta.issue else ""
    pages = f"<fpage>{_esc(meta.pages)}</fpage>" if meta.pages else ""
    article_meta.append(f"<pub-date-group>{pub_date}</pub-date-group>")
    article_meta.append(volume + issue + pages)
    kws = "".join(f"<kwd>{_esc(k)}</kwd>" for k in meta.keywords)
    if kws:
        article_meta.append(f"<kwd-group>{kws}</kwd-group>")
    if meta.abstract:
        article_meta.append(
            f"<abstract><p>{_render_inline(_strip_image_and_links(meta.abstract))}</p></abstract>"
        )
    parts.append(f"<article-meta>{''.join(article_meta)}</article-meta>")
    return "".join(parts)


def markdown_to_jats(md: str, meta: JatsMeta | None = None) -> str:
    """Markdown 稿件 → JATS 1.3 journalpublishing 全文 XML。"""
    meta = meta or JatsMeta()
    blocks = _parse_blocks(md or "")
    body = _sec_tree(blocks)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!DOCTYPE article PUBLIC "-//NISO//JATS journalpublishing DTD v1.3 20220210//EN" "{_JATS_DTD}">\n'
        f'<article xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article" '
        f'dtd-version="1.3" xml:lang="{_esc(meta.language or "zh")}">\n'
        "<front>" + _front(meta) + "</front>\n"
        f"<body>{body}</body>\n"
        "<back><notes><sec><title>发表说明</title><p>"
        "本文由 Rubbish 编辑部按开放获取条款发布；正文随线上版本更新。</p></sec></notes></back>\n"
        f"<!-- schema: {_JATS_XSD} -->\n"
        "</article>\n"
    )


__all__ = ["JatsMeta", "markdown_to_jats"]
