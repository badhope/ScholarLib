"""论文修复（fix）：把体检里能机械判定的问题就地改掉。

只做「确定性」修复——改完不需要人再判断对错的那一类：
- 中文标点前的空格（"不堪入目 、"→"不堪入目、"）
- 相邻重复段落（PDF 双栏提取最典型的产物）
- 重复子句（"以 X 为对象，以 X 为对象"）
- 一级节按编号重排（4 结论跑到 3 结果前面）
- 图注吞正文（图注里塞进了一整段话）

**不碰**需要判断的东西：摘要要不要扩写、关键词补哪几个、文献补哪几条、
公式丢了哪个符号。这些交给编辑，不交给脚本。

    python -m scripts.paper.fix a.md              # 预览（不写盘）
    python -m scripts.paper.fix a.md --write      # 就地写，备份 a.md.bak-fix
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

_CJK = r"\u4e00-\u9fff"
_SPACE_BEFORE_PUNCT = re.compile(rf"([{_CJK}）】」』”’])\s+([，。；：！？、）》】」』])")
_REPEAT_CLAUSE = re.compile(rf"([{_CJK}A-Za-z0-9]{{6,40}})[，,]\s*\1")
_TOP_NUM = re.compile(r"^##\s+(\d+)[.、．]?\s+(\S.*)$")
_CAPTION_LINE = re.compile(r"^(\s*)(图|表|附图|附表)\s*(\d+)\s*[：:.、]?\s*(.*)$")
_NESTED_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _fix_punct_space(md: str) -> tuple[str, int]:
    out, n = _SPACE_BEFORE_PUNCT.subn(r"\1\2", md)
    return out, n


def _fix_repeat_clause(md: str) -> tuple[str, int]:
    out, n = _REPEAT_CLAUSE.subn(r"\1", md)
    return out, n


def _fix_dup_paragraphs(md: str) -> tuple[str, int]:
    """删掉与上一段完全相同的段落（保留一份）。"""
    blocks = md.split("\n\n")
    kept: list[str] = []
    removed = 0
    for b in blocks:
        core = b.strip()
        if core and kept and kept[-1].strip() == core and len(core) > 12:
            removed += 1
            continue
        kept.append(b)
    return "\n\n".join(kept), removed


def _fix_caption_swallow(md: str) -> tuple[str, int]:
    """图注里塞了正文：在结构标记处断开，后半段还原成正文。

    PDF 双栏提取最典型的伤：图注把下一栏的开头整段吞进来，于是在手机上
    "图 3：…" 这一行里塞着两段正文。断开点不是随便找句号，而是找**结构
    标记**——标题（###）、下一张图的编号（附图 6）、内嵌图片、或第一个句号。
    按顺序取最早出现的那个，保证切下来的前半段仍是完整的图注。
    """
    lines = md.splitlines()
    out: list[str] = []
    fixed = 0
    for ln in lines:
        prev = next((x for x in reversed(out) if x.strip()), "")
        is_after_figure = bool(re.match(r"^\s*!\[", prev) or prev.strip().startswith("|"))
        m = _CAPTION_LINE.match(ln) if is_after_figure else None
        if not m:
            out.append(ln)
            continue

        indent, label, num, body = m.groups()
        body = _NESTED_IMG.sub("", body).strip()
        if not body:
            out.append(f"{indent}{label} {num}")
            continue

        cuts: list[int] = []
        # 1) 吞进了下一级标题
        for mm in re.finditer(r"#{1,6}\s", body):
            cuts.append(mm.start())
        # 2) 吞进了下一张图的编号
        for mm in re.finditer(r"(?:附)?[图表]\s*\d", body):
            if mm.start() > 0:
                cuts.append(mm.start())
        # 3) 图注本该一句话；第一个句号之后还有实义内容，就从那里断
        dot = body.find("。")
        if dot >= 6 and body[dot + 1 :].strip():
            cuts.append(dot + 1)
        cut = min(cuts) if cuts else -1

        if cut <= 0 or len(body) <= 16:
            out.append(f"{indent}{label} {num}：{body}")
            continue

        head = body[:cut].strip().rstrip("，,、")
        rest = body[cut:].strip()
        out.append(f"{indent}{label} {num}：{head}")
        if rest:
            out.append("")
            out.append(rest)
        fixed += 1
    return "\n".join(out), fixed


def _fix_section_order(md: str) -> tuple[str, int]:
    """一级节编号是 1..n 的排列但顺序乱了 → 按编号重排。

    只在这个前提下动手：编号必须恰好是 1..n（不缺不重），否则宁可不排——
    缺号意味着提取时丢了整节，重排会把问题藏起来。
    """
    lines = md.splitlines()
    starts = [(i, int(m.group(1)), m.group(2)) for i, ln in enumerate(lines) if (m := _TOP_NUM.match(ln))]
    if len(starts) < 3:
        return md, 0
    nums = [n for _, n, _ in starts]
    if sorted(nums) != list(range(1, len(nums) + 1)) or nums == sorted(nums):
        return md, 0

    preamble = lines[: starts[0][0]]
    chunks: dict[int, list[str]] = {}
    for k, (idx, num, title) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        chunks[num] = lines[idx:end]
    # 末尾若还有编号 1..n 之外的收尾内容（如「## 参考文献」），挂在最后一节后面
    body = []
    for num in range(1, len(nums) + 1):
        body.extend(chunks[num])
    return "\n".join(preamble + body), 1


def fix(md: str) -> tuple[str, dict[str, int]]:
    stats: dict[str, int] = {}
    md, stats["标点前空格"] = _fix_punct_space(md)
    md, stats["重复段落"] = _fix_dup_paragraphs(md)
    md, stats["重复子句"] = _fix_repeat_clause(md)
    md, stats["图注吞正文"] = _fix_caption_swallow(md)
    md, stats["章节重排"] = _fix_section_order(md)
    return md, {k: v for k, v in stats.items() if v}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paper-fix", description="按确定性规则修复 Markdown 稿件")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--write", action="store_true", help="就地写回（自动备份 .bak-fix）")
    args = ap.parse_args(argv)

    for p in args.paths:
        path = Path(p)
        md = path.read_text(encoding="utf-8", errors="replace")
        new, stats = fix(md)
        if not stats:
            print(f"{path.name}: 无需修改")
            continue
        print(f"{path.name}: " + "，".join(f"{k} {v} 处" for k, v in stats.items()))
        if args.write:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak-fix"))
            path.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
