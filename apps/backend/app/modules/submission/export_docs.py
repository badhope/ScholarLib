"""规范化文档导出（1.10.0）：Markdown → PDF / docx。

背景：投稿管线已内置 PDF→MD（pymupdf4llm）与 docx→MD（mammoth +
markdownify），但读者只能下载**原始 PDF**（排版混乱的投稿版）。本模块把
线上规范化后的阅读版 Markdown 反向生成为干净排版的 PDF / Word，让
「原稿 PDF」与「规范化版本」并存：阅读版=网站排版，导出版=打印/存档排版。

- PDF：pymupdf Story（HTML+CSS → PDF），内置 CJK 字体，无新增系统依赖。
- docx：python-docx（新增依赖 python-docx>=1.1）。

转换都在 ``async def`` 路由的工作线程里执行（见 routes 的 to_thread 用法），
避免大文档阻塞事件循环。
"""

from __future__ import annotations

import base64
import io
import re

# --- Markdown → HTML --------------------------------------------------------


def md_to_html(md: str) -> str:
    """markdown-it（GFM 表格启用）渲染为 HTML 片段。"""
    from markdown_it import MarkdownIt

    parser = MarkdownIt("commonmark", {"typographer": False}).enable("table")
    return parser.render(md)


# --- HTML → PDF（pymupdf Story） ---------------------------------------------

_CSS = """
body { font-family: china-s; font-size: 11pt; line-height: 1.7; }
h1 { font-size: 20pt; text-align: center; margin: 6pt 0 14pt 0; }
h2 { font-size: 15pt; margin: 14pt 0 6pt 0; }
h3 { font-size: 12.5pt; margin: 10pt 0 5pt 0; }
p { margin: 5pt 0; text-align: justify; }
table { border-collapse: collapse; margin: 8pt auto; }
th, td { border: 0.6pt solid #444; padding: 3pt 6pt; font-size: 9.5pt; }
th { background-color: #eee; }
img { margin: 6pt auto; }
blockquote { color: #444; margin: 6pt 12pt; }
code { font-family: monospace; font-size: 9.5pt; }
"""

_FIRST_DATA_URI = re.compile(r"data:image/([a-z]+);base64,", re.I)


def _story_html(body_html: str, title: str) -> str:
    return (
        f"<h1>{title}</h1>"
        # 正文里通常已有一个 H1（清洗管线保留的题名），降级避免双题名
        + body_html
    )


def html_to_pdf(body_html: str, title: str) -> bytes:
    """pymupdf Story 渲染 A4 PDF。data URI 图片在分块时逐块绘制。"""
    import pymupdf

    html = _story_html(body_html, title)
    story = pymupdf.Story(html=html, user_css=_CSS, em=11)
    writer = pymupdf.DocumentWriter()
    buf = io.BytesIO()
    # DocumentWriter 需要文件路径或可写二进制——pymupdf 支持直接传 BytesIO
    writer = pymupdf.DocumentWriter(buf)
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (52, 56, -52, -56)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return buf.getvalue()


# --- Markdown → docx（python-docx） ------------------------------------------

_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\((data:image/[a-z]+;base64,|[^\s)]+)\)", re.I)


def _add_runs(paragraph, text: str) -> None:
    """把 **bold** / *italic* 内联标记转成 docx run。"""
    token_re = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)")
    for part in token_re.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            paragraph.add_run(part[2:-2]).bold = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            paragraph.add_run(part[1:-1]).italic = True
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
        else:
            paragraph.add_run(part)


def md_to_docx(md: str, title: str) -> bytes:
    """轻量 Markdown → docx：标题/段落/表格/列表/data-URI 图片。"""
    import docx
    from docx.shared import Pt, Inches

    document = docx.Document()
    style = document.styles["Normal"]
    style.font.size = Pt(11)
    # 中文字体设置（宋体正文 + 黑体标题由 Word 主题回退，这里不强制指定 east asian 字体名）
    document.add_heading(title, level=0)

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        t = ln.strip()
        if not t:
            i += 1
            continue
        # 图片（data URI 或普通 URL）
        m = _MD_IMAGE.match(t)
        if m:
            src = m.group(2)
            try:
                if src.startswith("data:"):
                    b64 = src.split("base64,", 1)[1]
                    stream = io.BytesIO(base64.b64decode(b64))
                    document.add_picture(stream, width=Inches(5.5))
                else:
                    document.add_paragraph(f"[图片] {m.group(1) or src}")
            except Exception:
                document.add_paragraph(f"[图片加载失败] {m.group(1)}")
            i += 1
            continue
        # 表格
        if t.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            rows = []
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                if not re.match(r"^\|[\s:|-]+\|$", lines[j].strip()):
                    rows.append(cells)
                j += 1
            if rows:
                ncols = max(len(r) for r in rows)
                table = document.add_table(rows=len(rows), cols=ncols)
                table.style = "Table Grid"
                for ri, row in enumerate(rows):
                    for ci in range(ncols):
                        cell = table.cell(ri, ci)
                        cell.text = ""
                        _add_runs(cell.paragraphs[0], row[ci] if ci < len(row) else "")
            i = j
            continue
        # 标题
        hm = re.match(r"^(#{1,6})\s+(.*)$", t)
        if hm:
            level = min(len(hm.group(1)), 4)
            document.add_heading(hm.group(2).strip(), level=level)
            i += 1
            continue
        # 列表
        lm = re.match(r"^[-*•]\s+(.*)$", t)
        if lm:
            p = document.add_paragraph(style="List Bullet")
            _add_runs(p, lm.group(1))
            i += 1
            continue
        nm = re.match(r"^(\d+)[\.、\)]\s+(.*)$", t)
        if nm:
            p = document.add_paragraph(style="List Number")
            _add_runs(p, nm.group(2))
            i += 1
            continue
        # 普通段落（合并软换行）
        para = [t]
        j = i + 1
        while j < len(lines) and lines[j].strip() and not re.match(r"^(#|\||[-*•]\s|\d+[\.、\)]\s|!\[)", lines[j].strip()):
            para.append(lines[j].strip())
            j += 1
        p = document.add_paragraph()
        _add_runs(p, " ".join(para))
        i = j

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()
