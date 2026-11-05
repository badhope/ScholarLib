"""给 GB/T 7714 缺类型标识的参考文献条目补 [J]/[M]/[C]/[D]/[EB/OL] 等。

规则按优先级（一条命中即停）：
- 学位论文特征（University thesis / dissertation / 学位论文）→ [D]
- 会议特征（Proceedings / Conference / Proc. / 会议论文集）→ [C]
- 网络特征（http(s)://、www.、[Online]、Available、Accessed、Hotfix）→ [EB/OL]
- 期刊特征（vol. / no. / pp. / Art. no. / 卷(期)）→ [J]
- 出版特征（Press / Publishing / 出版社 / Press, Inc）→ [M]
- 兜底 → [EB/OL]（网络时代来源不明的条目按电子资源处理）

插入位置：条目末尾句号之前。
"""

from __future__ import annotations

import re

_MARKED = re.compile(r"\[(?:J|M|C|D|R|N|P|S|A|CD|EB/OL|J/OL|M/OL)\](/OL)?\s*$")
_REF_LINE = re.compile(r"^\s*(?:[-*]\s*)?\[\d+\]", re.M)


def _infer(line: str) -> str:
    low = line.lower()
    if re.search(r"(thesis|dissertation|学位论文|doctoral|ph\.?d)", low):
        return "[D]"
    if re.search(r"(proceedings|conference|proc\.|symposium|论文集)", low):
        return "[C]"
    if re.search(r"(https?://|www\.|\[online\]|available|accessed|retrieved)", low):
        return "[EB/OL]"
    if re.search(r"(vol\.|no\.|pp\.|art\.? no\.|\d+\s*\(\d+\)|et al)", low):
        return "[J]"
    if re.search(r"(press|publishing|publisher|出版社|house)", low):
        return "[M]"
    return "[EB/OL]"


def add_type_markers(md: str) -> tuple[str, int]:
    if "参考文献" not in md and "References" not in md:
        return md, 0
    lines = md.splitlines()
    in_refs = False
    n = 0
    for i, ln in enumerate(lines):
        if re.match(r"^#{1,3}\s*(参考文献|References)", ln.strip()):
            in_refs = True
            continue
        if in_refs and re.match(r"^#{1,3}\s", ln.strip()):
            in_refs = False
            continue
        if not in_refs or not re.match(r"\s*(?:[-*]\s*)?\[\d+\]", ln):
            continue
        if _MARKED.search(ln):
            continue
        mark = _infer(ln)
        stripped = ln.rstrip()
        if stripped.endswith("."):
            lines[i] = stripped[:-1] + f" {mark}."
        else:
            lines[i] = stripped + f" {mark}"
        n += 1
    return "\n".join(lines), n
