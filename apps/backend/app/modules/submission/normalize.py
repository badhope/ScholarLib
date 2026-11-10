"""Publication-grade normalisation for converted manuscripts.

背景
----
读者看到的是 Markdown 阅读版，不是作者上传的 PDF。转换器（pymupdf4llm /
mammoth）只保证「文字不漏」，不保证「像一篇论文」：

- 标题常写成 ``##2.1方法``（编号与标题间没有空格；中文标题还缺西文空格）
- 图注 ``图1 系统架构``、表注 ``表2参数`` 编号粘连
- 中文与西文混排忽紧忽松（``使用Python3.8实现`` / ``使用 Python 3.8 实现``）
- 双栏 PDF 的表格被拆成「每行一段」，在阅读版里变成一列散字
- 连续空行、行尾空格、零宽字符

``markdown_clean.clean`` 处理的是「结构归位」（刊头、伪粗体、标题误判），
本模块处理的是「排印统一」——它必须在 clean 之后运行，且必须**幂等**：
同一份稿子跑两遍结果一致，否则重新上传会把已修好的稿子改出二次偏差。

设计边界
--------
只改「怎么排」，不改「写什么」：不删句子、不改语序、不替换术语。
语言不统一、逻辑混乱这类问题属于编辑加工，机器只做标注（见
``audit_style``），不擅自改写——那需要逐篇由学科编辑判断。

保护策略：链接、图片、行内代码、HTML 标签先换成占位符，排印规则只在
纯文本片段上生效，最后原样还原。否则 ``![](data:image/png;base64,…)``
里的 base64 会被「中英文加空格」规则插进空格，图片直接损坏。
"""

from __future__ import annotations

import re

_CJK = r"\u3400-\u4dbf\u4e00-\u9fff"

# 需要在排印处理时保护起来的片段：图片、链接、行内代码、自动链接、HTML 标签。
# 顺序有讲究——图片必须排在链接前面，否则 ``![alt](url)`` 会先被链接规则
# 吃掉 ``[alt](url)``，留下一个孤立的 ``!``。
_PROTECT = re.compile(
    r"(!\[[^\]]*\]\([^)]*\))"  # 图片
    r"|(\[[^\]]*\]\([^)]*\))"  # 链接
    r"|(`[^`\n]*`)"  # 行内代码
    r"|(</?[A-Za-z][^>\n]*>)"  # HTML 标签
)

_PLACEHOLDER = "\x00P{}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00P(\d+)\x00")

# 标题里编号与标题之间的空格：``##2.1方法`` → ``## 2.1 方法``。
# 只处理「数字编号 + 中文/字母」紧贴的情况，避免把 ``## 2024`` 拆开。
# 标题里编号与标题之间的空格：``##2.1方法`` → ``## 2.1 方法``。
# 只处理「数字编号 + 中文/字母」紧贴的情况；``## 2024年度报告`` 这类以年份
# 开头的标题不能被拆成「编号 2024 + 标题 年度报告」，故排除时间量词。
_HEADING_NO_SPACE = re.compile(
    rf"^(#{{1,6}})([ \t]*)(\d+(?:\.\d+)*)(?![年月日])(?=[{_CJK}A-Za-z])", re.M
)

# 图/表编号与题注文字：``图1系统架构`` → ``图 1 系统架构``。
# 限定在行首（可带 ``**`` 或 ``表`` 前的引用符号），避免改到正文里的「图 1 所示」。
_CAPTION_NUM = re.compile(
    rf"^(\*\*)?[ \t]*(图|表|Figure|Fig\.?|Table)[ \t]*(\d+)(?=[{_CJK}A-Za-z])", re.M
)

# 中文句读后的多余空格：``。 下一句`` → ``。下一句``。
# 只吃空格与制表符，绝不能吃换行——``\s+`` 会把「句号 + 空行」一起吞掉，
# 两段正文会被粘成一段（实测事故，务必保留 [ \t]）。
# 表格单元格边界 ``） |`` 前的空格是列分隔的视觉留白，不能清掉，
# 否则整行贴成 ``）| −1.2``，表格会读成一列散字。
_SPACE_AFTER_CJK_PUNCT = re.compile(r"([，。；：！？、）》」』】])[ \t]+(?![|])")

# 破折号被 PDF 拆成两个单横线：``— —`` → ``——``
_BROKEN_EMDASH = re.compile(r"—[ \t]+—")

# `**关键词：**观鸟`：收尾的 ** 后面紧跟汉字时，CommonMark 判定它不是右闭合
# 适配符，整行原样输出——读者看到的是字面的两个星号。补一个空格即可闭合，
# 这个空格出现在行首标签之后，视觉上看不出来。
_TIGHT_BOLD = re.compile(r"\*\*([^*\n]{1,14}[：:])\*\*(?=[^\s*])")

# --- 硬换行碎段复原 ---------------------------------------------------------

# 句末标点。行尾是否有它，决定这处换行是「段落结束」还是「版心宽度到了」。
# 分号与冒号**不算**：它们表示话没说完，后面必然还有同一段的下文。
_SENT_END = "。！？…!?."
# 收尾符号：先剥掉它们再看前一个字符（``。”（`` 这类）。
_CLOSERS = "”’」』）】》\"'"

# 块级行：标题、列表、引用、表格、围栏、图片占位、HTML、图/表题注。
# 这些行自成一块，不与相邻文本合并——题注被并进正文是阅读版最刺眼的错位之一。
_BLOCKISH = re.compile(
    r"^(#{1,6}[ \t]|[-*+][ \t]|\d+[.)][ \t]|>|\||```|~~~|<|!\[|\x00P\d+\x00"
    r"|(图|表|Figure|Fig\.?|Table)[ \t]*\d)"
)


# --- 页眉 / 裸标题 ---------------------------------------------------------

# 刊物刊头与页码。PDF 每页都会重复一次，页眉行尾没有标点，若不先剔掉，
# 段落合并会把它接进句子中间。
_HEAD_EXACT = {
    "Rubbish-于荒诞处见同路人",
    "Rubbish—于荒诞处见同路人",
    "于荒诞处见同路人",
    "于荒诞处，见同路人",
    "RUBBISH",
    "Rubbish",
}
_PAGE_NO = re.compile(r"^\d{1,3}$")

# 「有编号、没 #」的标题行：``1 引言`` / ``2.1 方法``
_BARE_HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})[ \t]+(\S.*)$")
_HEADING_PUNCT = re.compile(r"[，。；：！？,;!?]")
# 公式特征。``2.1.3 limt→+oP(t)=Ao`` 这类是行间公式，不能被提成标题；
# 只在含 ``=`` / ``→`` / 不等号时才否决，英文标题里的括号不算。
_FORMULA = re.compile(r"[=＝→←≤≥<>]")


# 全角数字 → 半角
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")

# 标题粘连处：汉字/全角括号之后紧跟下一级编号
_NESTED_TITLE = re.compile(rf"(?<=[{_CJK}）)])[ \t]*(?=\d{{1,2}}\.\d)")

# 半角括号（不含嵌套，够用）
_HALF_BRACKET = re.compile(r"\(([^()\n]{1,60})\)")

# 粗体编号标题：``**1.3　本文的效力声明**``。标题文字限 40 字符、不含句读，
# 以免把正文里的行内强调误当标题。
_BOLD_NUM_HEADING = re.compile(r"\*\*(\d{1,2}(?:\.\d{1,2}){0,2})[ \u3000]+([^*\n]{1,40}?)\*\*")

# 句末切分（保留标点）
_SENT_SPLIT = re.compile(r"(?<=[。！？])")


def _is_formula_text(text: str) -> bool:
    return bool(_FORMULA.search(text))


def _ends_sentence(line: str) -> bool:
    s = line.rstrip().rstrip("*_~`")
    while s and s[-1] in _CLOSERS:
        s = s[:-1].rstrip()
    return bool(s) and s[-1] in _SENT_END


def _join_cjk(a: str, b: str) -> str:
    """拼接两行：两侧都是中文时不加空格（中文没有词间空格），否则补一个。"""
    if not a:
        return b
    if not b:
        return a
    if re.match(rf"[{_CJK}]", a[-1]) or re.match(rf"[{_CJK}]", b[0]):
        return a + b
    return a + " " + b


def _strip_running_heads(md: str) -> str:
    """剔掉每页重复的刊头与页码。

    必须在段落合并**之前**做：页眉是独立一行、行尾没有标点，reflow 会把它
    当成被截断的句子接进正文，得到
    ``…交运 Rubbish - 于荒诞处见同路人2大学一支重点课题组…`` 这种句子。
    这里只删整行、保留空行，不碰正文——``markdown_clean.strip_boilerplate``
    会连空行一并丢弃，段落会被全部粘死，故不能直接复用。
    """
    lines = md.split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        text = line.strip().strip("*_ ")
        compact = re.sub(r"[\s#*_>]", "", text)
        if compact in _HEAD_EXACT:
            continue
        if _PAGE_NO.match(text):
            # 纯数字行：表格数据与有序列表里合法，只在真正孤立的页码位置删
            prev = lines[i - 1].strip() if i else ""
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if prev.startswith("|") or nxt.startswith("|"):
                out.append(line)
            elif re.match(r"^\d+[.)][ \t]", prev) or re.match(r"^\d+[.)][ \t]", nxt):
                out.append(line)
            continue
        out.append(line)
    return "\n".join(out)


def _promote_bare_headings(md: str) -> str:
    """把 ``1 引言`` / ``2.1 方法`` 这类「有编号、没 #」的行提成标题。

    PDF 转换经常把章节标题输出成纯文本行，读者看到的是正文里孤零零一句
    「2 研究方法」，而目录/锚点里根本没有这一节。

    判定刻意收紧：编号 1–2 位、标题不超过 24 个字符、不含任何句读标点。
    「1. 体外实验：肿瘤细胞株…」这类列表项因为有冒号或超长而不会被误提。
    """
    out: list[str] = []
    for line in md.split("\n"):
        s = line.strip()
        m = _BARE_HEADING.match(s)
        if (
            m
            and len(m.group(2)) <= 24
            and not _HEADING_PUNCT.search(m.group(2))
            and not _is_formula_text(m.group(2))
        ):
            depth = m.group(1).count(".") + 1
            out.append(f"{'#' * min(6, depth + 1)} {m.group(1)} {m.group(2)}")
        else:
            out.append(line)
    return "\n".join(out)


def _demote_formula_headings(md: str) -> str:
    """把被误提成标题的公式行放回正文。

    历史转换 + 早期版本的裸标题提升，会把 ``limt→+oP(t)=Ao`` 变成二级标题，
    阅读页目录里就多出一条公式。判据：整行没有汉字、且含关系符。
    """
    out: list[str] = []
    for line in md.split("\n"):
        m = re.match(r"^(#{1,6})[ \t]+(\S.*)$", line)
        if m and _is_formula_text(m.group(2)) and not re.search(rf"[{_CJK}]", m.group(2)):
            out.append(m.group(2))
        else:
            out.append(line)
    return "\n".join(out)


def _normalise_digits(md: str) -> str:
    """全角数字转半角：``４ 结论`` → ``4 结论``。

    转换器把某些章节号输出成全角数字，导致标题顺序、目录页码都对不上。
    只动数字，不动全角标点（中文标点必须保持全角）。
    """
    return md.translate(_FULLWIDTH_DIGITS)


def _split_stuck_headings(md: str) -> str:
    """拆分粘连的标题：``## 2.1 模型2.1.1 核心定义`` → 两个标题。

    双栏 PDF 把相邻两级的标题读到同一行，阅读页会出现一个又长又怪的
    大标题，而 2.1.1 这一级在结构里彻底消失。
    """
    out: list[str] = []
    for line in md.split("\n"):
        m = re.match(r"^(#{1,6})[ \t]+(.+)$", line)
        if m:
            parts = [p.strip() for p in _NESTED_TITLE.split(m.group(2)) if p.strip()]
            if len(parts) > 1:
                out.extend(f"{m.group(1)} {p}" for p in parts)
                continue
        out.append(line)
    return "\n".join(out)


def _fix_cjk_brackets(md: str) -> str:
    """中文语境里的半角括号改全角：``(被爱解存在条件)`` → ``（被爱解存在条件）``。

    只在括号内含汉字时改：``f(x)``、``(OOD)`` 这类公式与英文缩写保持原样。
    链接与图片已被占位符保护，不会被误伤。
    """
    return _HALF_BRACKET.sub(
        lambda m: f"（{m.group(1)}）" if re.search(rf"[{_CJK}]", m.group(1)) else m.group(0),
        md,
    )


def _promote_bold_headings(md: str) -> str:
    """把 ``**1.3　本文的效力声明**`` 这类粗体编号标题转成真标题。

    PDF 转换常把章节标题输出成整段加粗的正文行，且与上下文粘在同一行
    （实测 300 号稿 6.9 万字、0 个 Markdown 标题，149 处标题全是这种形态，
    读者在目录里看不到任何章节）。

    只在「编号 + 空格 + 短标题」时触发：正文里的行内强调（``**注意**``）
    没有编号，不会被误提。
    """

    def _sub(m: re.Match[str]) -> str:
        num, title = m.group(1), m.group(2).strip().rstrip("：:")
        # 「0 级事实」是正文里的证据层级术语，「1.10.4 的地位…」是句子开头引用，
        # 都不是章节标题：标题不可能以「级/的/是/在」起头。
        if not title or title[0] in "级的在是":
            return m.group(0)
        depth = num.count(".") + 1
        return f"\n\n{'#' * min(6, depth + 1)} {num} {title}\n\n"

    return _BOLD_NUM_HEADING.sub(_sub, md)


def _demote_term_headings(md: str) -> str:
    """把误提成标题的术语行放回正文。

    ``## 0 级事实``、``#### 1.10.4 的地位需要单独钉死`` —— 这些是证据层级
    术语和句子开头的交叉引用，被粗体标题规则误判过。判据与提升时一致：
    标题不可能以「级/的/在/是」起头。
    """
    out: list[str] = []
    for line in md.split("\n"):
        m = re.match(r"^(#{1,6})[ \t]+(\d{1,2}(?:\.\d{1,2}){0,2})[ \t]+(.+)$", line)
        if m and m.group(3)[:1] in "级的在是":
            out.append(f"{m.group(2)} {m.group(3)}")
        else:
            out.append(line)
    return "\n".join(out)


def _split_overlong_blocks(md: str, limit: int = 450) -> str:
    """把超长段落按句子切开。

    碎段复原之后会出现相反的问题：原稿整节挤在一行、句读完整，reflow 把
    它收成一段，手机上就是密不透风的一坨（实测有 1226 个汉字一段）。
    只在超过 600 汉字时才切，切点落在句号处，每段不超过 ``limit``；
    正常长度的段落一律不动。
    """
    out: list[str] = []
    for block in md.split("\n\n"):
        s = block.strip()
        if len(re.findall(rf"[{_CJK}]", s)) <= 600 or s[:1] in "#|!-*>`<" or _BLOCKISH.match(s):
            out.append(block)
            continue

        pieces: list[str] = []
        cur: list[str] = []
        cur_len = 0
        for sentence in _SENT_SPLIT.split(s):
            if not sentence:
                continue
            n = len(re.findall(rf"[{_CJK}]", sentence))
            if cur and cur_len + n > limit:
                pieces.append("".join(cur))
                cur, cur_len = [], 0
            cur.append(sentence)
            cur_len += n
        if cur:
            pieces.append("".join(cur))
        out.extend(pieces)
    return "\n\n".join(out)


def _reflow_shredded(md: str) -> str:
    """把「版心宽度造成的硬换行」接回自然段落。

    判定只依赖一个事实：**行尾有没有句末标点**。PDF 每行 30–40 字就断，
    行尾若是逗号、顿号或干脆没有标点，说明这句话被切断了，必须接回去；
    行尾若是句号，说明作者本来就要在这里结束句子，保持分段。

    这与 ``markdown_clean.reflow_paragraphs`` 不同：后者以空行为界，会把
    一整节并成一大段（PDF 稿常常整节没有空行）；这里按标点恢复原有段落
    边界，因此更接近作者的写作意图。

    块级行（标题、列表、表格、图片、围栏）自成一块，不参与合并。
    """
    out: list[str] = []
    buf: list[str] = []
    in_fence = False

    def flush() -> None:
        if buf:
            joined = buf[0]
            for nxt in buf[1:]:
                joined = _join_cjk(joined, nxt)
            out.append(joined)
            buf.clear()

    for raw in md.split("\n"):
        line = raw.strip()
        if line.startswith(("```", "~~~")):
            flush()
            in_fence = not in_fence
            out.append(raw)
            continue
        if in_fence:
            out.append(raw)
            continue
        if not line:
            # 空行未必是段落边界：PDF 的分栏间隙、文本框换行都会留下空行。
            # 若上一句还没写完（行尾无句末标点），这个空行是误插的，忽略它。
            if buf and not _ends_sentence(buf[-1]):
                continue
            flush()
            out.append("")
            continue
        if _BLOCKISH.match(line) or (_is_formula_text(line) and not re.search(rf"[{_CJK}]", line)):
            # 纯公式行也是块级：``a = b`` 不能和上下文拼成一句
            flush()
            out.append(line)
            continue
        buf.append(line)
        if _ends_sentence(line):
            flush()
    flush()
    return "\n".join(out)


# 中英文之间补空格。
# 只处理拉丁**字母**，不处理数字：中文排版里「2024年度」「3个样本」是
# 正常连写，硬插空格反而读起来别扭；数字与单位/量词的间距交给作者。
_CJK_LATIN = re.compile(rf"([{_CJK}])([A-Za-z@#$%&])")
_LATIN_CJK = re.compile(rf"([A-Za-z%])([{_CJK}])")

# 表格行内被换行拆断：``| a | b`` 后面紧跟 ``| c |`` 且本行不以 ``|`` 收尾
_TABLE_ROW_OPEN = re.compile(r"^\|.*$")

# 常见零宽/软连字符垃圾
_INVISIBLE = re.compile("[\u200b\u200c\u200d\ufeff\u00ad]")


def _protect(md: str) -> tuple[str, list[str]]:
    kept: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        kept.append(m.group(0))
        return _PLACEHOLDER.format(len(kept) - 1)

    return _PROTECT.sub(_sub, md), kept


def _restore(md: str, kept: list[str]) -> str:
    def _sub(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        return kept[idx] if 0 <= idx < len(kept) else m.group(0)

    return _PLACEHOLDER_RE.sub(_sub, md)


def _fix_headings(md: str) -> str:
    # 标题标记与文字之间至少一个空格
    md = re.sub(r"^(#{1,6})(?=[^\s#])", r"\1 ", md, flags=re.M)
    # 编号与标题之间补空格（``## 2.1方法`` → ``## 2.1 方法``）
    md = _HEADING_NO_SPACE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)} ", md)
    # 标题末尾的句号/冒号是转换残留（``## 3 结果：``）
    md = re.sub(r"^(#{1,6}\s+.*?)[：:。]\s*$", r"\1", md, flags=re.M)
    return md


def _fix_captions(md: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        bold = m.group(1) or ""
        label = m.group(2)
        num = m.group(3)
        return f"{bold}{label} {num} "

    return _CAPTION_NUM.sub(_sub, md)


def _merge_broken_table_rows(md: str) -> str:
    """修复「表格行被硬换行切断」。

    两种形态分开处理，不能一律拼接：

    1. 当前行缺尾部竖线、下一行是一条完整表格行 → 只补一个 ``|``，
       两行仍是两行（``| a | b`` + ``| c | d |`` → ``| a | b |`` + ``| c | d |``）；
    2. 连续两行都不完整 → 说明单元格文字被切断，拼接后再补竖线。

    正常表格每行都以 ``|`` 收尾，因此不会误伤。
    """
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()
        if _TABLE_ROW_OPEN.match(line) and not stripped.endswith("|"):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            nxt_stripped = nxt.rstrip()
            if _TABLE_ROW_OPEN.match(nxt) and nxt_stripped.endswith("|"):
                out.append(stripped + " |")
                i += 1
                continue
            if _TABLE_ROW_OPEN.match(nxt):
                merged = stripped
                j = i + 1
                while j < len(lines) and _TABLE_ROW_OPEN.match(lines[j]):
                    merged += " " + lines[j].strip()
                    j += 1
                    if merged.endswith("|"):
                        break
                out.append(merged)
                i = j
                continue
        out.append(line)
        i += 1
    return "\n".join(out)


def _space_cjk_latin(md: str) -> str:
    md = _CJK_LATIN.sub(r"\1 \2", md)
    md = _LATIN_CJK.sub(r"\1 \2", md)
    # 补空格可能造成连续两个空格；折叠成一个（不影响行首缩进，行首已被
    # \s 匹配限制在非行首场景，这里再做一次全局幂等折叠）。
    md = re.sub(r"[ \t]{2,}", " ", md)
    return md


def _tidy_whitespace(md: str) -> str:
    md = _INVISIBLE.sub("", md)
    md = "\n".join(line.rstrip() for line in md.split("\n"))
    md = re.sub(r"\n{3,}", "\n\n", md)
    # 标题前保证一个空行（除文首）；标题后不留空行
    md = re.sub(r"([^\n])\n(#{1,6}\s)", r"\1\n\n\2", md)
    md = re.sub(r"^(#{1,6}\s[^\n]*)\n+", r"\1\n\n", md, flags=re.M)
    return md.strip() + "\n"


# --- 章节骨架 ---------------------------------------------------------------

_HEADING_LINE = re.compile(r"^(#{1,6})[ \t]*(\S.*)$")
# 全角空格（U+3000）必须算作「编号后的分隔」。否则 ``2.1　演化博弈`` 会让
# ``(\S.*)`` 在 U+3000 处失败并回溯到 ``[.、]?`` 分支，把编号拆成
# 「2 + . + 1」——深度算成 1，H3 被降级成 H2（实测事故，影响全库多级标题）。
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.、]?[ \t\u3000]*(\S.*)$")
# 无编号但属于固定章节的标题，应与一级章节同级
_FIXED_SECTIONS = re.compile(
    r"^(摘要|Abstract|关键词|Keywords|引言|绪论|前言|方法|材料与方法|研究方法|"
    r"结果|结果与分析|讨论|结论|参考文献|References|致谢|附录|利益冲突声明|作者贡献)"
    r"(?=[\s:：（(]|$)",
    re.I,
)


def unify_heading_levels(md: str) -> str:
    """把编号深度映射成固定的标题级别：1 → H2，1.1 → H3，1.1.1 → H4。

    PDF 转换出来的层级是「视觉字号」而不是「语义层级」：摘要可能因为字号
    大被判成 H2，正文章节反而成了 H3（实测 38 号稿 ``## Abstract`` 与
    ``### 2 Methodology`` 并存）。同一篇里两级标题混用，读者看不出谁统谁。

    H1 只留给文章标题（文首第一处），不参与重排。
    """
    lines = md.split("\n")
    numbered: list[tuple[int, int, str]] = []  # (行号, 深度, 原文)
    h1_seen = False

    for i, line in enumerate(lines):
        m = _HEADING_LINE.match(line)
        if not m:
            continue
        hashes, text = m.group(1), m.group(2).strip()
        if len(hashes) == 1:
            if not h1_seen:
                h1_seen = True  # 文章标题，保持 H1
            continue
        num = _NUMBERED.match(text)
        if num:
            depth = len(num.group(1).split("."))
            numbered.append((i, depth, text))
        elif _FIXED_SECTIONS.match(text):
            numbered.append((i, 1, text))

    if not numbered:
        return md

    for i, depth, text in numbered:
        level = min(6, depth + 1)  # 深度 1 → H2
        lines[i] = f"{'#' * level} {text}"
    return "\n".join(lines)


# --- 主入口 -----------------------------------------------------------------


def normalize_markdown(md: str) -> str:
    """排印＋骨架规范化（幂等）。输入为空时原样返回。"""
    if not md or not md.strip():
        return md
    body, kept = _protect(md)
    body = _normalise_digits(body)
    body = _strip_running_heads(body)
    body = _promote_bold_headings(body)
    body = _promote_bare_headings(body)
    body = _demote_formula_headings(body)
    body = _split_stuck_headings(body)
    body = _fix_headings(body)
    body = unify_heading_levels(body)
    body = _demote_term_headings(body)
    body = _fix_captions(body)  # 先规整题注编号，reflow 才能认出题注行
    body = _reflow_shredded(body)
    body = _fix_cjk_brackets(body)
    body = _split_overlong_blocks(body)
    body = _merge_broken_table_rows(body)
    body = _BROKEN_EMDASH.sub("——", body)
    body = _TIGHT_BOLD.sub(r"**\1** ", body)
    body = _SPACE_AFTER_CJK_PUNCT.sub(r"\1", body)
    body = _space_cjk_latin(body)
    body = _tidy_whitespace(body)
    return _restore(body, kept)


# --- 编辑加工标注（不改写，只提示） -----------------------------------------

_ZH_PUNCT = re.compile(r"[，。；：！？、]")
_EN_WORD = re.compile(r"\b[A-Za-z]{2,}\b")


def audit_style(md: str | None) -> dict[str, object]:
    """给编辑部一份「这篇还需人工加工哪些地方」的清单。

    机器不改语言风格；它只把可疑处标出来，由学科编辑逐篇判断。判断口径
    故意宽松（阈值高），宁可漏报也不要把正常稿子标成满屏问题。
    """
    if not md or not md.strip():
        return {"ok": False, "issues": []}
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    lines = [ln for ln in text.split("\n") if ln.strip() and not ln.startswith("#")]
    zh_lines = [ln for ln in lines if _ZH_PUNCT.search(ln)]
    en_lines = [ln for ln in lines if len(_EN_WORD.findall(ln)) >= 3 and not _ZH_PUNCT.search(ln)]

    issues: list[dict[str, object]] = []
    if zh_lines and en_lines and len(en_lines) >= max(3, len(zh_lines) // 4):
        issues.append(
            {
                "key": "mixed_language",
                "label": "中英文段落混杂",
                "detail": f"中文段落 {len(zh_lines)} 行 / 纯英文段落 {len(en_lines)} 行，需统一叙述语言",
            }
        )

    # 半角标点夹在中文里：中文阅读体验差，属排印问题而非内容问题
    half_in_zh = [ln for ln in zh_lines if re.search(rf"[{_CJK}],|[{_CJK}];", ln)]
    if len(half_in_zh) >= 3:
        issues.append(
            {
                "key": "halfwidth_punct",
                "label": "中文句子里用半角标点",
                "detail": f"{len(half_in_zh)} 行，建议统一为全角",
            }
        )

    if re.search(r"^#{1,6}\s*(摘要|Abstract)", md, re.M) is None:
        issues.append(
            {"key": "no_abstract", "label": "缺摘要标题", "detail": "阅读版应显式呈现摘要"}
        )
    if re.search(r"^(#{1,6}\s*)?(参考文献|References)", md, re.M) is None:
        issues.append({"key": "no_references", "label": "缺参考文献", "detail": "文末需有文献表"})

    dup_headings = {}
    for h in re.findall(r"^#{2,4}\s+(.+)$", md, re.M):
        key = re.sub(r"\s", "", h)
        dup_headings[key] = dup_headings.get(key, 0) + 1
    dups = [k for k, v in dup_headings.items() if v > 1]
    if dups:
        issues.append(
            {
                "key": "duplicate_headings",
                "label": "标题重复",
                "detail": "、".join(dups[:5]),
            }
        )

    return {"ok": not issues, "issues": issues}
