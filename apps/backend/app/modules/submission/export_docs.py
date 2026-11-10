"""规范化文档导出（1.10.0）：Markdown → PDF / docx。

背景：投稿管线已内置 PDF→MD（pymupdf4llm）与 docx→MD（mammoth +
markdownify），但读者只能下载**原始 PDF**（排版混乱的投稿版）。本模块把
线上规范化后的阅读版 Markdown 反向生成为干净排版的 PDF / Word，让
「原稿 PDF」与「规范化版本」并存：阅读版=网站排版，导出版=打印/存档排版。

- PDF：pymupdf Story（HTML+CSS → PDF），内置 CJK 字体，无新增系统依赖。
- docx：python-docx（新增依赖 python-docx>=1.1）。

转换都在 ``async def`` 路由的工作线程里执行（见 routes 的 to_thread 用法），
避免大文档阻塞事件循环。

1.10.1 排版修正：
- 预处理修复转换遗留：标题编号缺空格（"2Methodology"→"2 Methodology"）、
  图注与正文粘连（"图 5 ……。大多数打工人……"拆为图注段+正文段）。
- 图片按高宽比分级缩放（竖图 52% / 方图 66% / 横图 88%），大幅减少
  "图片放不下整块推下页"造成的大片空白。
- h4/h5/h6 显式样式（此前五级子标题渲染得像正文）。
- 图注段落居中灰字（class="caption"）。
"""

from __future__ import annotations

import base64
import io
import re

# --- Markdown 预处理（修复转换遗留，阅读版同样受益） -------------------------

# 标题编号后紧跟字母/汉字/左括号：缺空格（"## 2Methodology"）
_HEAD_NO_SPACE = re.compile(r"^(#{1,6}\s+)(\d+)(?=[A-Za-z\u4e00-\u9fff(（])", re.M)
# 标题内成对下划线斜体残留（"### _4_ 结论"）
_HEAD_ITALIC = re.compile(r"^(#{1,6}\s+)_{1,2}([^_\n]{1,30})_{1,2}", re.M)
# 整行只有一张图片
_LINE_IMAGE = re.compile(r"^!\[[^\]]*\]\([^)]+\)\s*$")


def preprocess_md(md: str) -> str:
    """修复 PDF/Word→MD 转换的常见遗留（幂等，可重复调用）。"""
    md = _HEAD_NO_SPACE.sub(lambda m: f"{m.group(1)}{m.group(2)} ", md)
    md = _HEAD_ITALIC.sub(lambda m: f"{m.group(1)}{m.group(2)}", md)

    # 图注与正文粘连：行以"图 N"开头、第一个句号前 ≤28 字且句号后还有 ≥20 字
    out_lines = []
    for line in md.splitlines():
        m = re.match(r"^(图\s*\d+[^。\n]{0,28}。)(\S.{20,})$", line.strip())
        if m:
            out_lines.append(m.group(1))
            out_lines.append("")
            out_lines.append(m.group(2))
        else:
            out_lines.append(line)
    md = "\n".join(out_lines)

    # 图片行前后补空行：markdown-it 会把"图片行+紧随的图注行"合成一个段落，
    # 导致图注无法独立成段（阅读版与导出 PDF 都受影响）
    lines = md.splitlines()
    spaced = []
    for i, ln in enumerate(lines):
        if _LINE_IMAGE.match(ln.strip()):
            if spaced and spaced[-1].strip():
                spaced.append("")
            spaced.append(ln)
            if i + 1 < len(lines) and lines[i + 1].strip():
                spaced.append("")
        else:
            spaced.append(ln)
    return "\n".join(spaced)


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
h4 { font-size: 11.5pt; margin: 9pt 0 4pt 0; }
h5 { font-size: 11pt; margin: 8pt 0 3pt 0; }
h6 { font-size: 10.5pt; color: #555; margin: 8pt 0 3pt 0; }
p { margin: 5pt 0; text-align: justify; }
table { border-collapse: collapse; margin: 8pt auto; }
th, td { border: 0.6pt solid #444; padding: 3pt 6pt; font-size: 9.5pt; }
th { background-color: #eee; }
img { display: block; margin: 8pt auto; }
blockquote { color: #444; margin: 6pt 12pt; }
code { font-family: monospace; font-size: 9.5pt; }
/* 图注：居中灰字 */
p.caption { text-align: center; color: #555; font-size: 9.5pt; margin: 2pt 0 10pt 0; }
/* 署名行：标题下居中灰字（作者 · 发表日期） */
p.byline { text-align: center; color: #555; font-size: 10.5pt; margin: -8pt 0 14pt 0; }
/* 图片按高宽比分级缩放，减少整块分页造成的空白 */
img.img-land { width: 88%; }
img.img-sq { width: 66%; }
img.img-tall { width: 52%; }
"""

_PNG_DIMS = re.compile(rb"^\x89PNG\r\n\x1a\n.{4}IHDR(.{8})", re.S)
_JPEG_SOI = b"\xff\xd8"


def _image_dims(data: bytes) -> tuple[int, int] | None:
    """轻量读取 PNG / JPEG 像素尺寸（不依赖 PIL）。"""
    m = _PNG_DIMS.match(data)
    if m:
        w, h = m.group(1)[:4], m.group(1)[4:]
        return int.from_bytes(w, "big"), int.from_bytes(h, "big")
    if data[:2] == _JPEG_SOI:
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                h = int.from_bytes(data[i + 5 : i + 7], "big")
                w = int.from_bytes(data[i + 7 : i + 9], "big")
                return w, h
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
            i += 2 + seg_len
    return None


_IMG_TAG = re.compile(r'<img([^>]*src="(data:image/[a-z+]+;base64,)([^"]+)"[^>]*)>')


def _classify_images(html: str) -> str:
    """给 data-URI 图片按高宽比加分级宽度 class。"""

    def _repl(m: re.Match) -> str:
        attrs, _, b64 = m.group(1), m.group(2), m.group(3)
        try:
            dims = _image_dims(base64.b64decode(b64[:65536] + b"==", validate=False))
        except Exception:
            dims = None
        cls = "img-land"
        if dims and dims[1] > 0:
            ratio = dims[1] / dims[0]
            if ratio >= 1.15:
                cls = "img-tall"
            elif ratio >= 0.8:
                cls = "img-sq"
        if "class=" in attrs:
            return m.group(0)
        return f'<img class="{cls}"{attrs}>'

    return _IMG_TAG.sub(_repl, html)


# 「图 N …」或「附图 N …」（编辑部为无图注的历史插图补的编号）都算图注
_CAPTION_P = re.compile(r"<p>((?:附)?图\s*\d+[^<]{0,40})</p>")


def _style_captions(html: str) -> str:
    return _CAPTION_P.sub(lambda m: f'<p class="caption">{m.group(1)}</p>', html)


def _story_html(body_html: str, title: str, byline: str | None = None) -> str:
    """正文包上刊头：标题 + 署名行（作者 · 发表日期）。

    署名行来自 Resource 元数据（authors / publish_at），让导出的
    PDF/Word 不再是"无名氏文档"——作者与刊出日期随文档走。
    """
    head = f"<h1>{title}</h1>"
    if byline:
        head += f'<p class="byline">{byline}</p>'
    return head + body_html


_DATA_URI_IMG = re.compile(r"data:image/(png|jpeg|jpg);base64,([A-Za-z0-9+/=\s]+)", re.I)


def _shrink_data_uri_images(html: str, max_width: int = 900) -> str:
    """把正文里内嵌的超大位图降采样后重新编码。

    线上实测：单篇导出 PDF 13 MB，其中 8.7 MB 是两张图——pymupdf 排版时
    会把图片按原始像素写进 PDF，A4 版心根本用不到这么多像素。
    这里按 2 倍降采样（像素降到 1/4），仍用 PNG（图表带透明通道）。
    """
    import base64

    import pymupdf

    def _repl(m: re.Match[str]) -> str:
        raw = base64.b64decode(m.group(2), validate=False)
        try:
            pix = pymupdf.Pixmap(raw)
            if pix.width <= max_width:
                return m.group(0)
            # PyMuPDF 1.24+ 的 shrink() 原地修改、返回 None；
            # 写成 pix = pix.shrink(f) 会拿到 None，压缩会静默失效。
            pix.shrink(2)
            out = pix.tobytes("png")
        except Exception:
            # 解不开就原样保留——导出宁可大一点，也不能因为一张图挂掉
            return m.group(0)
        return "data:image/png;base64," + base64.b64encode(out).decode("ascii")

    return _DATA_URI_IMG.sub(_repl, html)


def html_to_pdf(body_html: str, title: str, byline: str | None = None) -> bytes:
    """pymupdf Story 渲染 A4 PDF。data URI 图片在分块时逐块绘制。"""
    import pymupdf

    html = _story_html(_style_captions(_classify_images(body_html)), title, byline)
    html = _shrink_data_uri_images(html)
    story = pymupdf.Story(html=html, user_css=_CSS, em=11)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    mediabox = pymupdf.paper_rect("a4")
    where = pymupdf.Rect(mediabox.x0 + 52, mediabox.y0 + 56, mediabox.x1 - 52, mediabox.y1 - 56)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    # DocumentWriter 写出的流默认不压缩：8 页中文稿 4.7 MB，大半是未压缩的
    # 字体与内容流。重压缩后 2.1 MB（整篇 13.2 MB → 2.1 MB），耗时 +0.2s。
    doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    # 字体子集化：Story 默认把整个中文字体嵌进 PDF（Droid Sans Fallback 全文
    # 约 1.7 MB），而一篇文章只用到几百个字形。子集化后 2.0 MB → 220 KB，
    # 耗时 +0.12s；在 380 KB/s 的出口带宽下等于把下载时间从 8s 压到 1s。
    try:
        doc.subset_fonts()
    except Exception:
        pass
    packed = io.BytesIO()
    doc.save(packed, deflate=True, garbage=4, deflate_images=True, deflate_fonts=True)
    return packed.getvalue()


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
            run.font.name = "DejaVu Sans Mono"
        else:
            paragraph.add_run(part)


def _docx_img_width(data: bytes):
    """按高宽比选图片显示宽度（python-docx 只给宽度保持纵横比）。"""
    from docx.shared import Inches

    dims = _image_dims(data)
    if dims and dims[0] > 0:
        ratio = dims[1] / dims[0]
        if ratio >= 1.15:
            return Inches(3.2)
        if ratio >= 0.8:
            return Inches(4.2)
    return Inches(5.5)


def md_to_docx(md: str, title: str, byline: str | None = None) -> bytes:
    """Markdown → 官方模板 docx。

    1.11.0 起不再用「能塞进去就行」的轻量转换：那版没有刊头（题名/作者/单位/
    摘要/关键词）、图题表题不居中、表格还是带竖线的网格。读者下载到的 Word
    和站内规范不一致，编辑部也就没法拿它当工作稿。现在统一走
    ``docx_template.build``，模板参数写在 docs/paper-specification.md §7.2。

    ``byline`` 仍保留：导出接口从 Resource 元数据带过来的「作者 · 日期」，
    拆回作者列表交给模板排版。
    """
    from app.modules.submission.docx_template import build, parse_meta

    meta = parse_meta(md, fallback_title=title)
    if byline:
        authors = byline.split("·")[0].strip()
        if authors:
            meta.authors = [a.strip() for a in re.split(r"[、,，]", authors) if a.strip()]
    return build(md, meta)


# --- 整期版面（封面 + 编后记 + 目录 + 版权页） -----------------------------

_ISSUE_CSS = """
body { font-family: china-s; font-size: 10.5pt; line-height: 1.65; color: #1f2a24; }
.kicker { font-size: 8pt; letter-spacing: 2pt; color: #6b7a70; text-transform: uppercase; }
.masthead img { width: 300pt; margin: 2pt 0 6pt 0; }
.issue-no { font-size: 72pt; line-height: 0.95; margin: 18pt 0 4pt 0; }
.issue-theme { font-size: 15pt; font-weight: bold; margin: 6pt 0 2pt 0; color: #2f5d46; }
.meta { font-size: 9pt; color: #5f6b63; }
.rule { border-top: 1.2pt solid #2f5d46; margin: 10pt 0; }
h2 { font-size: 14pt; margin: 14pt 0 6pt 0; }
h3 { font-size: 11pt; margin: 10pt 0 3pt 0; }
p { margin: 4pt 0; text-align: justify; }
.toc-row { margin: 3pt 0; }
.toc-no { color: #7a857d; }
.toc-title { font-weight: bold; }
.toc-meta { font-size: 8.5pt; color: #6b7a70; }
.note { background: #f4efe4; padding: 9pt 11pt; margin: 8pt 0 12pt 0; }
.pagebreak { page-break-after: always; }
.footer { font-size: 8.5pt; color: #6b7a70; margin-top: 12pt; border-top: 0.6pt solid #c9d1c8; padding-top: 6pt; }
"""


def issue_front_matter_pdf(
    *,
    volume: str,
    issue: str,
    theme: str,
    note: str,
    range_label: str,
    entries: list[dict],
    editor: str = "Rubbish 编辑部",
) -> bytes:
    """把一期做成可下载的“版面”：封面、编后记、完整目录、版权页。"""
    import base64
    import html as _html
    from pathlib import Path

    import pymupdf

    papers = [e for e in entries if e.get("track") == "paper"]
    essays = [e for e in entries if e.get("track") != "paper"]

    def esc(x: object) -> str:
        return _html.escape(str(x or ""))

    def toc(group: list[dict], label: str) -> str:
        if not group:
            return ""
        rows = "".join(
            f'<div class="toc-row"><span class="toc-no">{i + 1:02d}.</span> '
            f'<span class="toc-title">{esc(e["title"])}</span>'
            f"{" <span class='toc-meta'>[特别篇]</span>" if e.get('special') else ''}"
            f'<div class="toc-meta">{esc("、".join(e.get("authors") or []))} · '
            f"{esc(e.get('discipline'))}{(' · CLC ' + esc(e.get('clc'))) if e.get('clc') else ''}</div></div>"
            for i, e in enumerate(group)
        )
        return f"<h3>{esc(label)} · {len(group)} 篇</h3>{rows}"

    logo_path = Path(__file__).resolve().parent / "assets" / "brand-lockup.png"
    logo_b64 = base64.b64encode(logo_path.read_bytes()).decode() if logo_path.is_file() else ""

    html = f"""<html><body>
<div class="pagebreak">
  <div class="kicker">Rubbish · Vol. {esc(volume)} · {esc(issue)}</div>
  <div class="masthead"><img src="data:image/png;base64,{logo_b64}" alt="Rubbish" /></div>
  <div class="kicker">A Journal of Serious Format &amp; Free Subjects</div>
  <div class="rule"></div>
  <div class="issue-no">{int(issue):02d}</div>
  <div class="issue-theme">{esc(theme)}</div>
  <div class="meta">第 {esc(volume)} 卷 第 {int(issue)} 期 · {esc(range_label)}</div>
  <div class="meta">共 {len(entries)} 篇 · {len(papers)} 篇论文 · {len(essays)} 篇副刊</div>
  <div style="margin-top:120pt" class="meta">{esc(editor)} · rubbish.argjiemi.cn</div>
</div>
<h2>本期编后记</h2>
<div class="note"><p>{esc(note)}</p><p style="text-align:right">— {esc(editor)}</p></div>
<h2>本期目录</h2>
{toc(papers, "论文")}
{toc(essays, "副刊与随笔")}
<h2>版权页</h2>
<p>出版：Rubbish 编辑部 · 纯数字出版 · 滚动刊出</p>
<p>主编：陆止于海　副主编：沈知非、顾荒唐</p>
<p>编委：白鹿原上、林一苇、R. 编辑部</p>
<p>本版：第 {esc(volume)} 卷 第 {int(issue)} 期 · {esc(range_label)}</p>
<div class="footer">Rubbish · rubbish.argjiemi.cn · 本版面由站内排版器自动生成</div>
</body></html>"""

    story = pymupdf.Story(html=html, user_css=_ISSUE_CSS, em=11)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    mediabox = pymupdf.paper_rect("a4")
    where = pymupdf.Rect(mediabox.x0 + 56, mediabox.y0 + 60, mediabox.x1 - 56, mediabox.y1 - 60)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    try:
        doc.subset_fonts()
    except Exception:
        pass
    out = io.BytesIO()
    doc.save(out, deflate=True, garbage=4, deflate_images=True, deflate_fonts=True)
    return out.getvalue()


def docx_to_pdf(docx_bytes: bytes, *, timeout: int = 90) -> bytes:
    """用镜像内置的 LibreOffice headless 把品牌 Word 转成 PDF。

    这是「PDF 由 Word 转出」的唯一实现：先由 docx_template 生成与下载件
    完全相同的 .docx，再转换，保证 Word 与 PDF 的标题、表格、图注、页眉
    是同一份版式，而不是两条各自排版的流水线。

    LibreOffice 首次启动要初始化用户配置，因此每次转换给独立的
    UserInstallation 目录，避免并发请求互相锁住；失败抛异常，由路由回退。
    """
    import os
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="rubbish-docx2pdf-") as td:
        root = Path(td)
        src = root / "manuscript.docx"
        src.write_bytes(docx_bytes)
        profile = root / "lo-profile"
        env = {
            **os.environ,
            "HOME": str(root),
            "TMPDIR": str(root),
        }
        cmd = [
            "soffice",
            "--headless",
            "--norestore",
            "--nologo",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(root),
            str(src),
        ]
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        out = root / "manuscript.pdf"
        if proc.returncode != 0 or not out.is_file() or out.stat().st_size < 1024:
            detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "ignore")[-300:]
            raise RuntimeError(f"LibreOffice docx→pdf failed: {detail}")
        return out.read_bytes()
