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
    r"(!\[[^\]]*\]\([^)]*\))"      # 图片
    r"|(\[[^\]]*\]\([^)]*\))"      # 链接
    r"|(`[^`\n]*`)"             # 行内代码
    r"|(</?[A-Za-z][^>\n]*>)"   # HTML 标签
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
_SPACE_AFTER_CJK_PUNCT = re.compile(rf"([，。；：！？、）》」』】])[ \t]+")

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
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.、]?[ \t]*(\S.*)$")
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
    body = _fix_headings(body)
    body = unify_heading_levels(body)
    body = _fix_captions(body)
    body = _merge_broken_table_rows(body)
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
        issues.append({
            "key": "mixed_language",
            "label": "中英文段落混杂",
            "detail": f"中文段落 {len(zh_lines)} 行 / 纯英文段落 {len(en_lines)} 行，需统一叙述语言",
        })

    # 半角标点夹在中文里：中文阅读体验差，属排印问题而非内容问题
    half_in_zh = [ln for ln in zh_lines if re.search(rf"[{_CJK}],|[{_CJK}];", ln)]
    if len(half_in_zh) >= 3:
        issues.append({
            "key": "halfwidth_punct",
            "label": "中文句子里用半角标点",
            "detail": f"{len(half_in_zh)} 行，建议统一为全角",
        })

    if re.search(r"^#{1,6}\s*(摘要|Abstract)", md, re.M) is None:
        issues.append({"key": "no_abstract", "label": "缺摘要标题", "detail": "阅读版应显式呈现摘要"})
    if re.search(r"^(#{1,6}\s*)?(参考文献|References)", md, re.M) is None:
        issues.append({"key": "no_references", "label": "缺参考文献", "detail": "文末需有文献表"})

    dup_headings = {}
    for h in re.findall(r"^#{2,4}\s+(.+)$", md, re.M):
        key = re.sub(r"\s", "", h)
        dup_headings[key] = dup_headings.get(key, 0) + 1
    dups = [k for k, v in dup_headings.items() if v > 1]
    if dups:
        issues.append({
            "key": "duplicate_headings",
            "label": "标题重复",
            "detail": "、".join(dups[:5]),
        })

    return {"ok": not issues, "issues": issues}
