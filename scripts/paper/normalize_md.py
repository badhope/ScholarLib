"""把重建稿整理成「可发布」的结构：这一步只管格式，不改内容。

为什么单独一层
--------------
`rebuild.py` 负责从 PDF 里把字和图取对；取出来的稿子仍然带着一批**结构性
缺陷**——英文节标题（`## 2 Methodology`）、空章节（标题下面什么都没有）、
页眉残留（`RUBBISH 1`）、重复编号、Reference 排在 Conclusion 前面。这些都
属于「发布前提」：不修好不能发，但修好**不代表**文章变好。

所以这里只做确定性改写，不动任何观点、数据、玩笑。改完的稿子仍要过
`lint.py` 的门禁；门禁通过 ≠ 质量高，质量由人读内容来评。

规则表（按风险从低到高）
------------------------
1. 节标题英译中：Introduction→引言、Methodology→方法、Results→结果……
2. 页眉页脚残留：整行等于 `RUBBISH 1` / `RUBBISH | Volume …` / 纯页码 → 删
3. 空章节：标题与下一个标题之间没有正文（图片/表格算正文）→ 删标题
4. 重复标题：`## 2 方法` 紧跟 `## 2 Methodology` → 留一个
5. 尾章归位：参考文献 / 致谢 / 声明必须排在所有编号节之后
6. 标点：连续顿号逗号句号压成一个；中文标点前空格
7. 假图注：`图 3：附图 2（原文插图）xxxx` → `图 3`（真正的图题留给人写）
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

# --- 1. 节标题英译中 -------------------------------------------------------

_HEAD_MAP: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(abstract|summary)$", re.I), "摘要"),
    (re.compile(r"^(keywords?|key\s*words?)$", re.I), "关键词"),
    (re.compile(r"^(introduction|background)$", re.I), "引言"),
    (re.compile(r"^(materials? and methods?|methods?|methodology|approach)$", re.I), "方法"),
    (re.compile(r"^(results?|results? and discussion|findings?)$", re.I), "结果"),
    (re.compile(r"^(discussion)$", re.I), "讨论"),
    (re.compile(r"^(results? and discussion)$", re.I), "结果与讨论"),
    (re.compile(r"^(conclusions?|concluding remarks?)$", re.I), "结论"),
    (re.compile(r"^(related works?|literature review)$", re.I), "相关工作"),
    (re.compile(r"^(limitations?)$", re.I), "局限"),
    (re.compile(r"^(future works?)$", re.I), "展望"),
    (re.compile(r"^(acknowledge?ments?|acknowledgements?)$", re.I), "致谢"),
    (re.compile(r"^(references?|bibliography|citations?)$", re.I), "参考文献"),
    (re.compile(r"^(appendix|appendices)$", re.I), "附录"),
    (re.compile(r"^(data availability( statement)?)$", re.I), "数据可用性声明"),
    (re.compile(r"^(author contributions?|credit)$", re.I), "作者贡献声明"),
    (re.compile(r"^(conflicts? of interests?|competing interests?|declaration of interest)$", re.I), "利益冲突声明"),
    (re.compile(r"^(funding)$", re.I), "基金项目"),
    (re.compile(r"^(ethics( statement| approval)?)$", re.I), "伦理声明"),
)

_HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
_NUM_PREFIX = re.compile(r"^(\d+(?:\.\d+)*)[.、．]?\s*(.*)$")


def _translate_heading(text: str) -> str:
    """`2 Methodology` → `2 方法`；纯中文保持原样。"""
    m = _NUM_PREFIX.match(text.strip())
    num, rest = (m.group(1), m.group(2).strip()) if m else ("", text.strip())
    rest = rest.strip(" 　:：.")
    for pat, zh in _HEAD_MAP:
        if pat.fullmatch(rest):
            return f"{num} {zh}".strip()
    # `3 Results and Discussion` 这种带 and 的复合标题，逐段翻译
    if re.search(r"[A-Za-z]", rest) and " " in rest:
        parts = re.split(r"\s+(?:and|&|&amp;)\s+", rest)
        if len(parts) >= 2:
            zh_parts = []
            for part in parts:
                hit = next((z for p, z in _HEAD_MAP if p.fullmatch(part.strip())), None)
                if hit is None:
                    return text
                zh_parts.append(hit)
            return f"{num} {'与'.join(zh_parts)}".strip()
    return text


# --- 2. 页眉页脚残留 -------------------------------------------------------

_FURNITURE = re.compile(
    r"^\s*(?:"
    r"rubbish(?:[\s|·\-]*\d+)?(?:\s*\|.*)?"
    r"|第?\s*\d+\s*[页卷期]"
    r"|\d{1,3}"
    r"|—\s*\d{1,3}\s*—"
    r")\s*$",
    re.I,
)


def _drop_furniture(lines: list[str]) -> tuple[list[str], int]:
    out: list[str] = []
    n = 0
    for ln in lines:
        if _FURNITURE.match(ln.strip()):
            n += 1
            continue
        out.append(ln)
    return out, n


# --- 3/4. 空章节与重复标题 -------------------------------------------------

def _drop_empty_sections(lines: list[str]) -> tuple[list[str], int]:
    """标题下面什么都没有（下一个标题之前无正文）→ 删标题。

    图片、表格、图注都算正文；只有空白才算空。删空标题而不是补一句
    「本节略」，是因为空标题在阅读页上就是两行大字挤在一起（截图实锤）。
    """
    out: list[str] = []
    n = 0
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = _HEAD.match(ln)
        if not m:
            out.append(ln)
            i += 1
            continue
        level = len(m.group(1))
        # 向后找到第一个同级或更高级标题，看中间有没有实质内容
        j = i + 1
        has_body = False
        while j < len(lines):
            m2 = _HEAD.match(lines[j])
            if m2 and len(m2.group(1)) <= level:
                break
            if lines[j].strip() and not _HEAD.match(lines[j]):
                has_body = True
                break
            j += 1
        if has_body:
            out.append(ln)
        else:
            n += 1
        i += 1
    return out, n


def _merge_duplicate_headings(lines: list[str]) -> tuple[list[str], int]:
    """`## 2 方法` 紧跟 `## 2 Methodology`（翻译前）→ 只留一个。"""
    out: list[str] = []
    n = 0
    for ln in lines:
        m = _HEAD.match(ln)
        if m and out:
            prev = _HEAD.match(out[-1])
            if prev and len(prev.group(1)) == len(m.group(1)):
                a = re.sub(r"\s+", "", prev.group(2))
                b = re.sub(r"\s+", "", m.group(2))
                if a == b:
                    n += 1
                    continue
        out.append(ln)
    return out, n


# --- 5. 尾章归位 -----------------------------------------------------------

_TAIL_HEAD = re.compile(r"^(参考文献|致谢|附录|数据可用性声明|作者贡献声明|利益冲突声明|基金项目|伦理声明)\s*$")
_NUMBERED_HEAD = re.compile(r"^\d+(?:\.\d+)*\s")


def _move_tail_sections(lines: list[str]) -> tuple[list[str], int]:
    """参考文献被排到结论前面时，把尾章整体挪到最后。"""
    idx = [i for i, ln in enumerate(lines) if (m := _HEAD.match(ln)) and _TAIL_HEAD.fullmatch(m.group(2).strip())]
    if not idx:
        return lines, 0
    first = idx[0]
    # 后面还有编号节 → 说明尾章插在中间了
    later_numbered = any(
        (m := _HEAD.match(ln)) and _NUMBERED_HEAD.match(m.group(2).strip()) for ln in lines[first:]
    )
    if not later_numbered:
        return lines, 0
    head: list[str] = []
    tails: list[list[str]] = []
    cur: list[str] | None = None
    for i, ln in enumerate(lines):
        m = _HEAD.match(ln)
        if m and _TAIL_HEAD.fullmatch(m.group(2).strip()):
            cur = [ln]
            tails.append(cur)
            continue
        if cur is not None and m:
            cur = None
        if cur is None:
            head.append(ln)
        else:
            cur.append(ln)
    merged: list[str] = []
    for t in tails:
        merged.extend(t)
        merged.append("")
    return head + [""] + merged, 1


# --- 6. 标点 ---------------------------------------------------------------

_PUNCT_RUN = re.compile(r"([、，。；：！？])\1+")
_SPACE_BEFORE_PUNCT = re.compile(r"([\u4e00-\u9fff）】」』”’])\s+([，。；：！？、）》】」』])")
_SOFT_SPACE = re.compile(r"[\u00a0\u3000]{1,}")


def _fix_punct(md: str) -> tuple[str, int]:
    total = 0
    md, n = _PUNCT_RUN.subn(r"\1", md)
    total += n
    md, n = _SPACE_BEFORE_PUNCT.subn(r"\1\2", md)
    total += n
    md, n = _SOFT_SPACE.subn(" ", md)
    total += n
    return md, total


# --- 7. 假图注 -------------------------------------------------------------

_NOISE_IN_CAPTION = re.compile(r"(?:附图|附表)\s*\d+\s*(?:（原文插图）|\(原文插图\))?")


def _clean_fake_captions(lines: list[str]) -> tuple[list[str], int]:
    """图注里塞了整段正文 → 只留「图 N」，正文还原成段落。

    判定不是看长度，而是看**图注不该有的东西**：以句号收尾的完整句子、
    `附图 3（原文插图）` 这类管线残留。真正的图题是名词短语，不会以
    「。」结束（见 docs/paper-specification.md §4）。
    """
    out: list[str] = []
    n = 0
    for ln in lines:
        m = re.match(r"^(\s*)(图|表)\s*(\d+)\s*[：:.、]?\s*(.*)$", ln)
        if not m:
            out.append(ln)
            continue
        indent, label, num, rest = m.groups()
        rest = _NOISE_IN_CAPTION.sub("", rest).strip()
        if not rest:
            out.append(f"{indent}{label} {num}")
            n += 1
            continue
        swallowed = ("。" in rest or "，" in rest) and len(rest) > 24
        out.append(f"{indent}{label} {num}")
        if rest and not swallowed:
            out[-1] = f"{indent}{label} {num}　{rest}"
        elif swallowed:
            out.append("")
            out.append(rest)
            n += 1
    return out, n


def _renumber(lines: list[str]) -> tuple[list[str], int]:
    """删掉空章节后编号会缺号（1 引言 消失 → 直接从 2 方法开始），重编成连续。"""
    top = 0
    sub = 0
    out: list[str] = []
    changed = 0
    for ln in lines:
        m = _HEAD.match(ln)
        if not m:
            out.append(ln)
            continue
        level = len(m.group(1))
        body = m.group(2).strip()
        if level != 2:
            out.append(ln)
            continue
        nm = re.match(r"^(\d+)(?:\.(\d+))?\s*(.*)$", body)
        if not nm:
            # 无编号的尾章（参考文献/致谢）不参与编号
            out.append(ln)
            continue
        title = nm.group(3).strip()
        if nm.group(2) is None:
            top += 1
            sub = 0
            new = f"{top} {title}"
        else:
            sub += 1
            new = f"{top}.{sub} {title}"
        if new != body:
            changed += 1
            out.append(f"{m.group(1)} {new}")
        else:
            out.append(ln)
    return out, changed


def _drop_near_duplicate_paragraphs(md: str) -> tuple[str, int]:
    """图注吞进去的那段正文，拆出来后往往与上一段几乎相同——删掉重复的那份。

    判据是「开头 24 字相同」，不是全文相等：PDF 一次提取常把同一句的
    后半截丢掉，两段看着像两句其实是同一句被切了两次。
    """
    blocks = md.split("\n\n")
    kept: list[str] = []
    n = 0
    for b in blocks:
        core = b.strip()
        if core and kept and not core.startswith(("图 ", "表 ", "#", "![", "|")):
            # 往上找最近一段真正的正文：中间可能隔着图注、图片、空行
            prev = ""
            for cand in reversed(kept):
                c = cand.strip()
                if c and not c.startswith(("图 ", "表 ", "#", "![", "|")):
                    prev = c
                    break
            head = core[:24]
            if len(head) >= 20 and prev.startswith(head) and len(core) < len(prev):
                n += 1
                continue
        kept.append(b)
    return "\n\n".join(kept), n


def normalize(md: str) -> tuple[str, dict[str, int]]:
    from .fix import fix as _fix

    stats: dict[str, int] = {}
    lines = md.splitlines()

    lines, stats["页眉残留"] = _drop_furniture(lines)
    lines, stats["重复标题"] = _merge_duplicate_headings(lines)

    # 标题英译中（在空章节判定之前，翻译后标题更短，不影响判定）
    trans = 0
    for i, ln in enumerate(lines):
        m = _HEAD.match(ln)
        if not m:
            continue
        new = _translate_heading(m.group(2))
        if new != m.group(2):
            lines[i] = f"{m.group(1)} {new}"
            trans += 1
    stats["标题英译中"] = trans

    # 先清页眉再判空章节：`RUBBISH 1` 这种残留会让空章节看着像有正文
    lines, n = _drop_furniture(lines)
    stats["页眉残留"] = stats.get("页眉残留", 0) + n
    lines, stats["空章节"] = _drop_empty_sections(lines)
    lines, stats["编号重排"] = _renumber(lines)
    lines, stats["尾章归位"] = _move_tail_sections(lines)
    lines, stats["假图注"] = _clean_fake_captions(lines)

    md = "\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    # 复用 fix.py 的确定性修复：图注吞正文、重复段落、重复子句、章节重排
    md, extra = _fix(md)
    stats.update(extra)
    md, stats["近似重复段"] = _drop_near_duplicate_paragraphs(md)
    md, stats["标点"] = _fix_punct(md)
    return md, {k: v for k, v in stats.items() if v}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paper normalize", description="结构规范化（只改格式，不动内容）")
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--in-place", action="store_true", help="就地改写（默认写 .norm.md）")
    args = ap.parse_args(argv)

    for path in args.inputs:
        md = path.read_text(encoding="utf-8")
        out, stats = normalize(md)
        if args.in_place:
            path.write_text(out, encoding="utf-8")
            target = path
        else:
            target = path.with_suffix(".norm.md")
            target.write_text(out, encoding="utf-8")
        detail = " ".join(f"{k}{v}" for k, v in stats.items()) or "无需改动"
        print(f"{path.name} → {target.name}  {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
