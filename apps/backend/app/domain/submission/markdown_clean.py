"""Structural cleanup for pymupdf4llm output (reader-facing Markdown).

Why a structural pass and not more regex patches
------------------------------------------------
The submitted PDFs typeset CJK with a serif face and Latin with a serif face.
pymupdf4llm turns every font switch into a bold run, so one paper produced
930 ``**`` markers; it also merges a heading with the paragraph that follows
on the same visual line ("## 2 研究方法 ### 2.1 动物实验 **实验采用…"), and
sometimes puts an image inside a heading line.

Reader symptoms (verified on /reader/44 and /reader/64):
- 刊头 `Open Access Research Article Received … Accepted …` 留在正文顶部
- 标题 + 作者 + 机构 + 邮箱挤成一条 H1
- `## 摘要 (Abstract) **目的：…` —— 小节标题和摘要正文同一行
- 正文出现成百上千个 ``**``，读起来像被随机加粗
- `### 类为皮质醇）持续升高。 ![](data:image…)` —— 图片被当成标题

So this module does five things in order:

1. normalise line endings and strip inline boilerplate fragments;
2. split lines that contain several heading markers into separate lines;
3. demote "headings" that are really body text / table captions / images;
4. strip font-switch bold noise (dense ``**`` runs on one line);
5. drop the duplicated title block (the page header already renders it).

Every rule is covered by ``tests/test_markdown_clean.py``.
"""

from __future__ import annotations

import re

# --- 1. boilerplate ------------------------------------------------------

BOILER_FRAGMENTS = re.compile(
    r"(?:"
    r"Open\s*Access(?:\s*Research\s*Article)?"
    r"|Research\s*Article"
    r"|Received\s+\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+(?:\d{4}|20xx)[,，]?"
    r"|Accepted\s+\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+(?:\d{4}|20xx)[,，]?"
    r"|MID:\s*(?:None|xxxx?/[\w./-]+|\S*)"
    r"|https?://\S+"
    r")\s*",
    re.I,
)

RUNNING_HEAD = re.compile(
    r"^\s*(?:[>*_#]{0,3}\s*)*(?:#{1,6}\s*)?\**\s*(?:"
    r"Rubbish\s*[-—]\s*于荒诞处见同路人"
    r"|于荒诞处[，,]?\s*见同路人"
    r"|Where the absurd dwells.*"
    r"|(?:Rubbish|RUBBISH|RUBBIS\s*H)\s*(?:\|\s*Volume.*)?"
    r"|\d{1,3}"
    r")\s*\**\s*$",
    re.I,
)

# RUNNING_HEAD 的线性替代：先剥掉行首的引用/粗体/标题标记，再对剩余
# 文本做无嵌套量词的等值或前缀判断。
#
# 为什么必须换掉上面那条正则：`(?:[>*_#]{0,3}\s*)*` 是嵌套量词，外层 `*`
# 与内层 `{0,3}` + `\s*` 可以对同一串 `>` 产生组合级数的切分路径。
# 实测 28 个 `>` 加一个字符（`">"*28 + "X"`）单行匹配超过 30 秒，26 个约
# 2.7 秒。而输入完全由作者控制——PDF 正文里写一行 28 个 `>` 就能触发，
# 且调用链是同步跑在事件循环上的（见 manuscript.py），一份特制稿件即可
# 让整个 worker 卡死，所有租户的请求一起挂。
#
# 保留正则对象只为向后兼容外部引用；内部判定走 _is_running_head。
_HEAD_MARKER_CHARS = ">*_#"
_HEAD_PREFIXES = ("Where the absurd dwells",)
_HEAD_EXACT = {
    "Rubbish-于荒诞处见同路人",
    "Rubbish—于荒诞处见同路人",
    "于荒诞处见同路人",
    "于荒诞处，见同路人",
    "RUBBISH",
    "Rubbish",
}

# 单行处理上限：超过这个长度的行不参与页眉判定（正常页眉不可能这么长），
# 避免任何正则在大输入上退化成二次复杂度。
MAX_HEAD_LINE_CHARS = 4096

# 行首页脚：可带 blockquote 标记与粗体页码前缀（"**1** "）。
VOLUME_FOOTER = re.compile(
    r"^[ \t]*(?:>[ \t]*)?(?:\*\*\d+\*\*[ \t]+)?[_*]*[ \t]*Rubbish[ \t]*[_*]*"
    r"[ \t]*\|[ \t]*Volume.*$",
    re.I | re.M,
)
# 与正文粘在同一行的页脚（分页把页脚拼进了段落末尾）。
VOLUME_FOOTER_INLINE = re.compile(
    r"[ \t]+[_*]*[ \t]*Rubbish[ \t]*[_*]*[ \t]*\|[ \t]*Volume[^\n]*",
    re.I,
)

ABSTRACT_ONLY = re.compile(r"^\s*(?:#{1,6}\s*)?(摘\s*要|Abstract|ABSTRACT|抽\s*象)\b", re.I)

# --- 2/3. headings -------------------------------------------------------

HEADING_MARK = re.compile(r"(?<![\w#])(#{1,6})[ \t]+")
SECTION_WORDS = re.compile(
    r"^(?:\d+(?:\.\d+)*[.、]?\s+|摘\s*要|Abstract|ABSTRACT|关键词|关键字|Keywords?"
    r"|参\s*考\s*文\s*献|References|致\s*谢|Acknowledg|声\s*明|结\s*论|讨论|结果|方法|引言|绪论)",
    re.I,
)
SENTENCE_END = re.compile(r"[。！？；]$")
IMAGE_REF = re.compile(r"!\[[^\]]*\]\([^)]*\)")
BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
CJK_GAP = re.compile(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])")
TAG = re.compile(r"</?(?:sup|sub|i|b|em|strong|span|font|div|p|br)\b[^>]*>", re.I)

MAX_HEADING_CHARS = 60


def strip_tags(md: str) -> str:
    """Drop inline HTML: the reader renders Markdown only (no rehype-raw)."""
    md = TAG.sub("", md)
    return md.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")


def normalise(md: str) -> str:
    md = md.replace("\r\n", "\n").replace("\r", "\n")
    md = VOLUME_FOOTER.sub("", md)
    md = VOLUME_FOOTER_INLINE.sub("", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def _looks_like_running_head(line: str) -> bool:
    compact = re.sub(r"[\s#*_>]", "", line)
    return compact in {
        "Rubbish-于荒诞处见同路人",
        "Rubbish—于荒诞处见同路人",
        "于荒诞处见同路人",
        "于荒诞处，见同路人",
        "RUBBISH",
        "Rubbish",
    }


def _is_running_head(line: str) -> bool:
    """Linear-time replacement for ``RUNNING_HEAD.match``.

    复杂度 O(len(line))，无嵌套量词，因此对任意恶意输入都不会回溯爆炸。
    与旧正则的语义等价性由 ``tests/test_markdown_clean.py`` 的
    ``test_running_head_matches_legacy_behaviour`` 与
    ``test_pathological_input_is_linear`` 两条用例锁定。
    """
    if len(line) > MAX_HEAD_LINE_CHARS:
        return False
    # 1. 剥掉行首的引用/粗体/标题标记（对应旧正则的 [>*_#]{0,3} 与 #{1,6}）
    text = line.lstrip()
    while text and text[0] in _HEAD_MARKER_CHARS:
        text = text[1:].lstrip()
    # 2. 剥掉包裹的 ** 与尾部空白
    text = text.strip()
    if text.startswith("**"):
        text = text[2:]
    if text.endswith("**"):
        text = text[:-2]
    text = text.strip()
    if not text:
        return False
    # 3. 等值 / 前缀 / 纯数字页码
    if text in _HEAD_EXACT:
        return True
    if text.isdigit() and 1 <= len(text) <= 3:
        return True
    if any(text.startswith(prefix) for prefix in _HEAD_PREFIXES):
        return True
    # 4. "Rubbish" 或 "Rubbish | Volume ..." 形态
    upper = text.upper().replace(" ", "")
    if upper.startswith("RUBBISH"):
        rest = text[len("Rubbish") :].lstrip() if text[:7].upper() == "RUBBISH" else ""
        return rest == "" or rest.startswith("|") or rest.startswith("| Volume")
    return False


def strip_boilerplate(md: str) -> str:
    """Remove masthead fragments wherever they appear.

    Article 44's first line is
    ``**Open Access Research Article** Received 8th March 2026 Accepted … ``:
    several fragments on one line, so a line-anchored rule misses it.
    """
    out = []
    for line in md.split("\n"):
        stripped = BOILER_FRAGMENTS.sub("", line).strip(" *_")
        if not stripped:
            continue
        if _looks_like_running_head(stripped) or _is_running_head(stripped):
            continue
        out.append(stripped)
    return "\n".join(out)


def split_merged_headings(md: str) -> str:
    """One line can carry several headings: ``## X ### Y #### Z body``."""
    out = []
    for line in md.split("\n"):
        marks = list(HEADING_MARK.finditer(line))
        if len(marks) <= 1:
            out.append(line)
            continue
        cursor = 0
        for m in marks:
            chunk = line[cursor : m.start()].strip()
            if chunk:
                out.append(chunk)
            cursor = m.start()
        out.append(line[cursor:].strip())
    return "\n".join(out)


def _heading_text(line: str) -> tuple[str, str]:
    m = re.match(r"^(#{1,6})\s+(.*)$", line)
    if not m:
        return "", line
    return m.group(1), m.group(2).strip()


def demote_bad_headings(md: str) -> str:
    """A heading must be short, section-like and text-only.

    Everything else is body text: table captions (``#### 表 1. …``), wrapped
    prose (``### 也侵蚀着…``), and headings that swallowed an image.
    """
    out = []
    for line in md.split("\n"):
        hashes, text = _heading_text(line)
        if not hashes:
            out.append(line)
            continue
        body = IMAGE_REF.sub("", text).strip()
        images = IMAGE_REF.findall(text)
        too_long = len(body) > MAX_HEADING_CHARS
        sentence = bool(SENTENCE_END.search(body))
        caption = re.match(r"^(表|图|Table|Figure|Fig\.?)\s*\d", body)
        sectionish = bool(SECTION_WORDS.match(body))
        numbered = bool(re.match(r"^\d+(?:\.\d+)*[.、]?\s+", body))
        if caption:
            out.append(f"**{body}**")
        # 小节名很短（"声明""致谢"）且命中词表；带编号的才算结构化标题。
        # 其余短句（"也侵蚀着医患之间的信任基础，成为影响医疗"）是正文续行。
        elif too_long or sentence or (not sectionish and not numbered and len(body) > 14):
            # 标题吞了正文：能拆就拆出前导的小节名，其余还原成段落。
            head, rest = _split_label(body)
            if head:
                out.append(f"{hashes} {head}")
                if rest:
                    out.append(rest)
            else:
                out.append(body)
        else:
            head_text, extras = split_heading_tail(body)
            out.append(f"{hashes} {head_text}")
            for extra in extras:
                if extra:
                    out.append(extra)
        for img in images:
            out.append(img)
    return "\n".join(out)


EMBEDDED_HEADING = re.compile(r"^(?P<head>.{2,40}?)\s+(?P<next>\d+(?:\.\d+)+[.、]?\s+\S.{4,})$")
MID_SENTENCE = re.compile(r"^(?P<head>[^。！？]{2,45})[。！？]\s*(?P<tail>.+)$", re.S)


def split_heading_tail(text: str) -> tuple[str, list[str]]:
    """Split a heading that swallowed the next heading or the body.

    Real cases from the submitted PDFs (article 44):

    - ``3.1 动物实验 3.1.1 便秘模型建立与分组情况`` — two headings merged;
    - ``4.4 临床意义：从 "一肚子火" 到 "通便防冲突" 临床部分的结果为…`` —
      heading + paragraph on one line.
    """
    extras: list[str] = []
    m = EMBEDDED_HEADING.match(text)
    if m:
        extras.append(m.group("next").strip())
        text = m.group("head").strip()
    m2 = MID_SENTENCE.match(text)
    if m2 and not SECTION_WORDS.match(text[m2.end("head") :].strip()):
        extras.insert(0, m2.group("tail").strip())
        text = m2.group("head").strip()
    # 无句末标点的长标题（PDF 断行导致正文被截在标题行里）：
    # 在最后一个右引号/冒号后切开，超长时按 34 字截断。
    if len(text) > 34 and re.match(r"^\d+(?:\.\d+)*[.、]?\s+", text):
        cut = max(text.rfind("”"), text.rfind("："), text.rfind(":"))
        if cut > 6 and cut < len(text) - 6:
            extras.insert(0, text[cut + 1 :].strip())
            text = text[: cut + 1].strip()
        else:
            extras.insert(0, text[34:].strip())
            text = text[:34].strip()
    return text, extras


def _split_label(text: str) -> tuple[str, str]:
    """``摘要 (Abstract) 目的：…`` → (``摘要 (Abstract)``, ``目的：…``)."""
    m = re.match(
        r"^((?:\d+(?:\.\d+)*[.、]?\s+)?(?:摘\s*要|Abstract|关键词|关键字|Keywords?|"
        r"参\s*考\s*文\s*献|References|致\s*谢|声\s*明|结\s*论|讨论|结果|方法|引言|绪论)"
        r"(?:\s*[（(][^）)]{0,20}[）)])?)[，,:：\s]*(.*)$",
        text,
        re.I,
    )
    if not m:
        return "", text
    return m.group(1).strip(), m.group(2).strip()


def drop_title_block(md: str) -> str:
    """Drop everything before 摘要/Abstract — the page header shows the title.

    When a paper has no abstract marker, still drop the leading title/author/
    affiliation block: a run of short lines with digits, daggers and emails
    before the first real paragraph.
    """
    lines = md.split("\n")
    for i, line in enumerate(lines[:80]):
        if ABSTRACT_ONLY.match(line):
            return "\n".join(lines[i:]).lstrip("\n")
    for i, line in enumerate(lines[:40]):
        text = line.strip()
        if len(text) >= 120 and not text.startswith(("#", "!", "|", "**")):
            keep: list[str] = []
            for prev in reversed(lines[max(0, i - 3) : i]):
                if prev.strip().startswith("#"):
                    keep.insert(0, prev.strip())
                    break
            return "\n".join(keep + lines[i:]).lstrip("\n")
    return md


def strip_bold_noise(md: str) -> str:
    """Remove font-switch bold from body text.

    The PDFs alternate CJK/Latin fonts, so pymupdf4llm wraps spans in ``**``;
    the markers are frequently *unbalanced*, so counting matched pairs is not
    enough — a line that opens ``**`` and never closes renders as literal
    asterisks (article 44 had 930 of them).

    Body text therefore loses all bold: the sources use font switches, not
    real emphasis, and stray ``**`` in a journal reader is worse than no
    emphasis. ``tidy_inline`` re-adds the one intentional label
    (``**关键词**：``) afterwards.
    """
    out = []
    for line in md.split("\n"):
        if "**" not in line:
            out.append(line)
            continue
        # 唯一保留的粗体：关键词标签（**关键词**：…）
        if re.match(r"^\s*\*\*(关键词|关键字|Keywords?)\*\*\s*[:：]", line, re.I):
            out.append(line)
            continue
        # 其余一律清掉：包括带 # 的标题行与表格行 —— 标题里的 ** 只是
        # 字体切换的残留，表格里的 ** 会让 GFM 表格断列。
        out.append(line.replace("**", ""))
    return "\n".join(out)


KEYWORD_INLINE = re.compile(r"(?<=[。；;）)])\s*(关键词|关键字|Keywords?)\s*[:：]", re.I)


def split_keywords_paragraph(md: str) -> str:
    """关键词常与摘要粘成一个段落（PDF 里没有空行）。

    摘要是长块、关键词是字段行，挤在一起会让读者以为关键词属于摘要正文。
    """
    out = []
    for line in md.split("\n"):
        if line.lstrip().startswith(("#", "!", "|")):
            out.append(line)
            continue
        pieces = KEYWORD_INLINE.split(line)
        if len(pieces) >= 3:
            first = pieces[0].rstrip()
            if first:
                out.append(first)
                # 关键词是独立字段行：必须与摘要段落隔一个空行，
                # 否则 CommonMark 会把两行并成同一段（读者看到「…。关键词：…」）。
                out.append("")
            for i in range(1, len(pieces), 2):
                label = pieces[i]
                body = pieces[i + 1] if i + 1 < len(pieces) else ""
                out.append(f"**{label}**：{body.strip()}")
        else:
            out.append(line)
    return "\n".join(out)


KEYWORD_LINE = re.compile(r"^\*\*(关键词|关键字|Keywords?)\*\*\s*[:：]", re.I)


def ensure_block_spacing(md: str) -> str:
    """关键词行、图注行与标题之间必须空一行，否则 CommonMark 会并段。"""
    out: list[str] = []
    for line in md.splitlines():
        is_block = bool(
            KEYWORD_LINE.match(line)
            or line.startswith("#")
            or line.startswith("![](")
            or line.startswith("**图")
            or line.startswith("**表")
            or line.startswith("|")
        )
        if is_block and out and out[-1].strip() and not out[-1].startswith(("#", "!", "|")):
            out.append("")
        out.append(line)
    return chr(10).join(out)


def tidy_inline(md: str) -> str:
    # 关键词 **:** x → 关键词：x
    md = re.sub(
        r"^(关键词|关键字|Keywords?)\s*\*{0,2}\s*[:：]\s*\*{0,2}\s*",
        lambda m: f"**{m.group(1)}**：",
        md,
        flags=re.M | re.I,
    )
    md = re.sub(r"\*\*\s*([:：])\s*\*\*", lambda m: m.group(1), md)
    md = CJK_GAP.sub("", md)
    # 标题内不再保留粗体（无意义，且会被目录取词）
    md = re.sub(
        r"^(#{1,6})\s*\*\*([^*]+)\*\*\s*",
        lambda m: f"{m.group(1)} {m.group(2).strip()} ",
        md,
        flags=re.M,
    )
    md = re.sub(r"^(#{1,6})([^\s#])", lambda m: f"{m.group(1)} {m.group(2)}", md, flags=re.M)
    # 摘要统一 H2
    md = re.sub(r"^#{3,6}\s*(摘\s*要|Abstract|ABSTRACT)\s*$", r"## \1", md, flags=re.M)
    return md


def demote_long_headings(md: str) -> str:
    """Final safety net: a heading longer than a title is body text.

    Runs after bold removal so length is measured on real text — font-switch
    ``**`` used to inflate it and 60–200 char "headings" slipped through.
    """
    out = []
    for line in md.split("\n"):
        hashes, text = _heading_text(line)
        if hashes and len(text) > MAX_HEADING_CHARS:
            head, rest = _split_label(text)
            if head and len(head) <= MAX_HEADING_CHARS:
                out.append(f"{hashes} {head}")
                if rest:
                    out.append(rest)
                continue
            out.append(text)
            continue
        out.append(line)
    return "\n".join(out)


def clean(md: str) -> str:
    md = normalise(strip_tags(md))
    md = strip_boilerplate(md)
    md = split_merged_headings(md)
    md = drop_title_block(md)
    # 先去掉字体切换伪粗体：标题长度要按真实文字量测。
    md = strip_bold_noise(md)
    md = demote_bad_headings(md)
    md = demote_long_headings(md)
    md = split_keywords_paragraph(md)
    md = tidy_inline(md)
    # 块级元素（关键词/图注/标题/表格）之间补空行：CommonMark 会把相邻
    # 两行并成同一段，读者会看到「…。关键词：…」连在一起。
    md = ensure_block_spacing(md)
    # 段落重组（1.6.0）：把被 PDF 视觉行切碎的段落拼回流式段落——
    # 中文行间不加空格（修复「数字工 具」这类断词），并保证块间空行。
    md = reflow_paragraphs(md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md


# ---------------------------------------------------------------------------
# 段落重组（1.6.0）——论文阅读习惯的核心
#
# PDF/DOCX 提取的 Markdown 把每个视觉行存成一行：段落被切碎、CommonMark
# 渲染时还会在中文断行处插空格（「数字工 具」）。这里做块级感知的重组：
# - 连续的普通文本行合并为一个流式段落；
# - 拼接时若任一侧是 CJK 则不加空格，两侧均为拉丁/数字才补一个空格；
# - 标题/列表/引用/表格/代码块/图片行保持原样，绝不并入段落；
# - 块与块之间保证恰好一个空行。
# ---------------------------------------------------------------------------

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\uff00-\uffef]")
# 代码围栏 / 标题 / 引用 / 无序与有序列表 / 表格行 / 独立图片 / HTML 块
_BLOCK_MARK = re.compile(
    r"^(?:\s{0,3}(?:```|~~~|#{1,6}\s|>|[-*+]\s|\d{1,3}[.)]\s|\|)"
    r"|\s{0,3}!\[[^\]]*\]\([^)]*\)\s*$"
    r"|\s{0,3}<(?:p|div|table|figure|br)[\s>/])",
    re.I,
)


def _join_lines(a: str, b: str) -> str:
    """拼接两行为一个流式段落：CJK 相邻不加空格，否则补一个空格。"""
    if not a:
        return b
    if not b:
        return a
    if _CJK.match(a[-1:]) or _CJK.match(b[:1]):
        return a + b
    return a + " " + b


def reflow_paragraphs(md: str) -> str:
    out: list[str] = []
    buf: list[str] = []
    in_fence = False

    def flush() -> None:
        if buf:
            joined = buf[0]
            for nxt in buf[1:]:
                joined = _join_lines(joined, nxt)
            out.append(joined)
            buf.clear()

    for line in md.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            flush()
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if not stripped:
            flush()
            out.append("")
            continue
        if _BLOCK_MARK.match(line):
            flush()
            out.append(stripped)
            continue
        # 普通文本行：去掉 PDF 提取残留的前导空格后并入当前段落
        buf.append(stripped)
    flush()
    # 块间空行归一：连续空行压成一个；块标记后紧跟文本行的补一个空行
    collapsed: list[str] = []
    for line in out:
        if line == "" and (not collapsed or collapsed[-1] == ""):
            continue
        collapsed.append(line)
    return "\n".join(collapsed)


__all__ = ["clean", "reflow_paragraphs"]


# ---------------------------------------------------------------------------
# 稿件结构检测（格式自动识别）—— 给作者"离规范还差什么"的即时反馈
# ---------------------------------------------------------------------------

# 结构锚点：与 docs/editorial-standards.md「必须有的节」对应。
_STRUCTURAL_HEADINGS = {
    "引言": "introduction",
    "绪论": "introduction",
    "相关工作": "related_work",
    "文献综述": "related_work",
    "方法": "method",
    "材料与方法": "method",
    "论证框架": "method",
    "结果": "results",
    "讨论": "discussion",
    "结论": "conclusion",
    "参考文献": "references",
    "references": "references",
}

_ABSTRACT_MARK = re.compile(r"^\s*#{1,6}\s*(摘\s*要|Abstract)\b", re.I | re.M)
_KEYWORDS_MARK = re.compile(r"关键词|Keywords?\s*[:：]", re.I)

# 篇幅分档下限（正文字符，粗估； editorial-standards 的字数档按汉字计，
# 这里用字符数近似，宁松勿严——报告是提醒不是拒绝）。
MIN_BODY_CHARS = 1500


def analyze_structure(md: str | None) -> dict[str, object]:
    """检测稿件是否满足《投稿规范》的结构要求，返回逐项报告。

    这不是拒稿器：报告随上传响应返回给作者，让作者在编辑部初审之前
    就知道"缺摘要/没有参考文献/篇幅不够"，而不是等一周等来一封退修信。
    结构锚点与 editorial-standards.md 一一对应；标题匹配忽略编号
    （"3 方法" 与 "### 方法" 都算命中）。
    """
    if not md or not md.strip():
        return {"ok": False, "items": [], "word_count": 0}

    headings = re.findall(r"^#{1,6}\s+(.+)$", md, re.M)
    heading_norm = [re.sub(r"^[\d.、\s]+", "", h).strip().lower() for h in headings]
    found: dict[str, bool] = {}
    for label, slug in _STRUCTURAL_HEADINGS.items():
        # 同一 slug 有多个锚点（引言/绪论、方法/材料与方法…），必须累积
        # （|=）而不是覆盖：后一个锚点不命中不能抹掉前一个命中的结果。
        hit = any(h == label.lower() or h.startswith(label.lower()) for h in heading_norm)
        found[slug] = found.get(slug, False) or hit

    has_abstract = bool(_ABSTRACT_MARK.search(md))
    has_keywords = bool(_KEYWORDS_MARK.search(md))
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)  # 图片不占字数
    body = re.sub(r"[#>*\-\|\s`]", "", body)
    word_count = len(body)

    # 必查节：引言/方法/结果/讨论/结论 + 摘要 + 参考文献

    items: list[dict[str, object]] = [
        {
            "key": "abstract",
            "label": "摘要",
            "ok": has_abstract,
            "hint": "正文开头加一段「## 摘要」",
        },
        {
            "key": "keywords",
            "label": "关键词",
            "ok": has_keywords,
            "hint": "摘要后加一行「关键词：a；b；c」",
        },
        {
            "key": "references",
            "label": "参考文献",
            "ok": found.get("references", False),
            "hint": "文末加「## 参考文献」小节（≥4 条，GB/T 7714）",
        },
        {
            "key": "word_count",
            "label": "篇幅（字符）",
            "ok": word_count >= MIN_BODY_CHARS,
            "hint": f"短篇 ≥2500 字（当前约 {word_count} 字符）",
        },
    ]
    for slug, zh in [
        ("introduction", "引言"),
        ("method", "方法"),
        ("results", "结果"),
        ("discussion", "讨论"),
        ("conclusion", "结论"),
    ]:
        items.append(
            {
                "key": slug,
                "label": zh,
                "ok": bool(found.get(slug)),
                "hint": f"缺「{zh}」一级节——对应规范 §3.1",
            }
        )

    return {"ok": all(i["ok"] for i in items), "items": items, "word_count": word_count}
