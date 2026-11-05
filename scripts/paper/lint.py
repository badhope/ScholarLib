"""论文体检（lint）：按《RUBBISH 论文规范》逐条检查 Markdown 稿件。

为什么要有这个文件：`docs/editorial-standards.md` 里的要求写在纸上，但从
PDF 提取出来的稿件并没有被逐条核对过。结果是读者看到"4 结论"排在"3 结果"
前面、"图 3"的图注里塞着两段正文、同一段话印了两遍。这些都不是渲染器的
问题——渲染器只有一套，问题在源文件。

用法：
    python -m scripts.paper.lint manuscript.md            # 文本报告
    python -m scripts.paper.lint manuscript.md --json     # 机读
    python -m scripts.paper.lint --dir /data/uploads --out report.json

只依赖标准库，可以在容器里直接跑。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# --- 规范常量（与 docs/editorial-standards.md 对齐，改这里等于改口径） ---------

ABSTRACT_MIN = 200
ABSTRACT_MAX = 350
KEYWORD_MIN = 3
KEYWORD_MAX = 8
REFERENCE_MIN = 8
PARA_MAX_CHARS = 600

# 必备一级节：键是识别用的同义词，值是给人看的名字
REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "引言": ("引言", "前言", "introduction"),
    "方法": ("方法", "方法论", "method", "材料与方法", "研究设计"),
    "结果": ("结果", "实验", "result", "发现"),
    "讨论": ("讨论", "discussion"),
    "结论": ("结论", "结语", "conclusion"),
    "参考文献": ("参考文献", "references", "文献"),
}

_NUM_HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(?:(\d+(?:\.\d+)*)[.、．]?\s*)?(.+?)\s*$")
_CAPTION = re.compile(r"^\s*(图|表|附图|附表|Figure|Table)\s*([0-9]+)\s*[：:.、]?\s*(.*)$")
_IMG_ONLY = re.compile(r"^\s*!\[[^\]]*\]\(([^)]+)\)\s*$")
_DATA_URI = re.compile(r"data:image/[a-z+]+;base64,([A-Za-z0-9+/=]+)")
_CJK = r"\u4e00-\u9fff"

# 中文标点前不应有空格："不堪入目 、" → "不堪入目、"
_SPACE_BEFORE_PUNCT = re.compile(rf"([{_CJK}）】」』”’])\s+([，。；：！？、）》】」』])")
# 重复子句：同一段 6–40 字的串被逗号隔开重复一次
_REPEAT_CLAUSE = re.compile(rf"([{_CJK}A-Za-z0-9]{{6,40}})[，,]\s*\1")


@dataclass
class Finding:
    code: str
    severity: str  # error | warn | info
    message: str
    detail: str = ""


@dataclass
class Report:
    file: str = ""
    chars: int = 0
    headings: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def add(self, code: str, severity: str, message: str, detail: str = "") -> None:
        self.findings.append(Finding(code, severity, message, detail))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def score(self) -> int:
        """100 分制：每个 error 扣 8，warn 扣 3，info 扣 1，下限 0。"""
        penalty = sum({"error": 8, "warn": 3, "info": 1}[f.severity] for f in self.findings)
        return max(0, 100 - penalty)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["errors"] = len(self.errors)
        d["score"] = self.score
        return d


def _strip_images(text: str) -> str:
    return _DATA_URI.sub("", _IMG_ONLY.sub("", text))


def _cjk_count(text: str) -> int:
    return len(re.findall(rf"[{_CJK}]", text))


def _blocks(md: str) -> list[tuple[str, str]]:
    """切成 (kind, text) 序列：heading / para / image / table / caption。"""
    out: list[tuple[str, str]] = []
    lines = md.splitlines()
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append(("para", " ".join(x.strip() for x in buf if x.strip()).strip()))
            buf.clear()

    i = 0
    while i < len(lines):
        ln = lines[i]
        t = ln.strip()
        if not t:
            flush()
            i += 1
            continue
        if _NUM_HEAD.match(t) or t.startswith("#"):
            flush()
            out.append(("heading", t))
            i += 1
            continue
        if _IMG_ONLY.match(t):
            flush()
            out.append(("image", t))
            i += 1
            continue
        if t.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            out.append(("table", "\n".join(rows)))
            continue
        # 列表项各自成块：参考文献常写成 `- [1] …` 一行一条，若与上一行
        # 合段，三条文献会被数成一条。
        if re.match(r"^[-*•]\s+", t):
            flush()
            out.append(("para", t))
            i += 1
            continue
        # 「图注」只有在紧跟图片/表格时才成立。正文里也有大量以「图 3」
        # 「表 2」开头的句子（"图 3 显示……"），把它们当图注会制造一堆假警报。
        if _CAPTION.match(t) and len(t) <= 90 and out and out[-1][0] in ("image", "table"):
            flush()
            out.append(("caption", t))
            i += 1
            continue
        buf.append(t)
        i += 1
    flush()
    return out


def lint(md: str, name: str = "") -> Report:
    rep = Report(file=name, chars=_cjk_count(_strip_images(md)))
    blocks = _blocks(md)

    heads: list[tuple[int, str, str]] = []  # (level, number, text)
    paras: list[str] = []
    captions: list[tuple[str, int, str]] = []
    images = 0
    base64_bytes = 0

    for kind, text in blocks:
        if kind == "heading":
            m = _NUM_HEAD.match(text)
            if m:
                level = len(m.group(1))
                num = m.group(2) or ""
                heads.append((level, num, m.group(3)))
        elif kind == "para":
            paras.append(text)
        elif kind == "caption":
            m = _CAPTION.match(text)
            if m:
                captions.append((m.group(1), int(m.group(2)), text))
        elif kind == "image":
            images += 1

    base64_bytes = sum(len(x) for x in _DATA_URI.findall(md)) * 3 // 4
    rep.headings = [h[2] for h in heads]

    # --- 摘要 -------------------------------------------------------------
    # 摘要是「连续几段」而不是「一段」：中文期刊常见做法是分 2–3 段
    # （背景 / 方法结果 / 结论）。只取第一段会把 300 字的摘要判成 50 字。
    abstract = ""
    for i, (kind, text) in enumerate(blocks):
        if kind == "heading" and re.search(r"摘\s*要|abstract", text, re.I):
            got: list[str] = []
            for k2, t2 in blocks[i + 1 :]:
                if k2 == "heading" or re.match(r"^\s*\**\s*(关键词|关键字|keywords?|key\s*words?)", t2, re.I):
                    break
                if k2 == "para" and t2:
                    got.append(t2)
            abstract = " ".join(got)
            break
    if not abstract:
        rep.add("E001", "error", "缺摘要：没有找到「摘要」或 Abstract 段")
    else:
        n = _cjk_count(abstract)
        if n and n < ABSTRACT_MIN:
            rep.add("E002", "error", f"摘要过短：{n} 字（规范 {ABSTRACT_MIN}–{ABSTRACT_MAX}）")
        elif n > ABSTRACT_MAX:
            rep.add("E002", "error", f"摘要过长：{n} 字（规范 {ABSTRACT_MIN}–{ABSTRACT_MAX}）")

    # --- 关键词 -----------------------------------------------------------
    kw_line = next((p for p in paras if re.match(r"^\s*\**\s*(关键词|关键字|keywords?|key\s*words?)", p, re.I)), "")
    if not kw_line:
        rep.add("E003", "error", "缺关键词段")
    else:
        kw_body = re.sub(r"^\**\s*(关键词|关键字|keywords?|key\s*words?)\s*[：:]*\**", "", kw_line, flags=re.I)
        kw_body = re.split(r"[；;]", kw_body)
        kws = [k.strip(" 　*~") for k in kw_body if k.strip(" 　*~")]
        if not (KEYWORD_MIN <= len(kws) <= KEYWORD_MAX):
            rep.add(
                "E003",
                "error",
                f"关键词 {len(kws)} 个（规范 {KEYWORD_MIN}–{KEYWORD_MAX}）",
                kw_line[:60],
            )

    # --- 必备节 -----------------------------------------------------------
    # 篇幅决定门槛：随笔/简报（<2500 字）不强求「方法/结果/讨论」三段，
    # 否则每篇短稿都会被判缺节，编辑会习惯性忽略这份报告。
    low = [h[2].lower() for h in heads]
    mandatory = {"引言": "error", "结论": "error", "参考文献": "error"}
    if rep.chars >= 2500:
        mandatory.update({"方法": "error", "结果": "error", "讨论": "error"})
    else:
        mandatory.update({"方法": "info", "结果": "info", "讨论": "info"})
    for label, severity in mandatory.items():
        aliases = REQUIRED_SECTIONS[label]
        if not any(any(a in h for a in aliases) for h in low):
            rep.add("E004", severity, f"缺必备节：{label}")

    # --- 一级节编号 -------------------------------------------------------
    top = [(int(n), t) for lv, n, t in heads if lv <= 2 and n and n.isdigit()]
    nums = [n for n, _ in top]
    if nums:
        for a, b in zip(nums, nums[1:]):
            if b < a:
                rep.add(
                    "E005",
                    "error",
                    f"章节顺序错乱：第 {b} 节排在第 {a} 节之后",
                    " / ".join(f"{n} {t}" for n, t in top),
                )
                break
        gaps = [n for n in range(1, max(nums) + 1) if n not in nums]
        if gaps:
            rep.add("E005", "warn", f"章节编号缺号：{gaps}", " / ".join(map(str, nums)))

    # --- 标题层级跳跃 -----------------------------------------------------
    prev = 0
    for lv, _, t in heads:
        if prev and lv > prev + 1:
            rep.add("W006", "warn", f"标题层级跳跃：H{prev} → H{lv}", t[:40])
        prev = lv

    # --- 图注 -------------------------------------------------------------
    if captions:
        by_kind: dict[str, list[int]] = {}
        for label, num, text in captions:
            by_kind.setdefault(label[0], []).append(num)
            body = _CAPTION.match(text).group(3) if _CAPTION.match(text) else ""
            # 图注本该是一句话（"图 3 不同温度下的收敛曲线"）。超过 40 字、
            # 或里面又冒出一个「图 N」编号，基本可以断定是提取时把下一段
            # 正文并进了图注——阅读页上就成了一行字吃掉两段内容。
            if len(body) > 40 or body.count("。") >= 2 or re.search(r"(附)?[图表]\s*\d", body):
                rep.add("E006", "error", f"{label}{num} 图注吞了正文（{len(body)} 字）", body[:70])
        for kind_key, ns in by_kind.items():
            expect = list(range(1, len(ns) + 1))
            if sorted(ns) != expect:
                rep.add("E007", "error", f"{kind_key}号不连续：{ns}")

    # 图表是否被正文引用
    for label, num, _ in captions:
        key = f"{label[0]}{num}"
        # 「图 1」中间那个空格是规范写法，不能因为它判成没引用
        if not re.search(rf"{label[0]}\s*{num}(?![0-9])", _strip_images("\n".join(paras))):
            rep.add("W004", "info", f"{key} 未在正文中被引用")

    # --- 重复 -------------------------------------------------------------
    seen_prev = ""
    for p in paras:
        core = _strip_images(p).strip()
        if len(core) > 12 and core == seen_prev:
            rep.add("E008", "error", "相邻段落完全重复", core[:50])
        seen_prev = core
    for p in paras:
        for m in _REPEAT_CLAUSE.finditer(_strip_images(p)):
            rep.add("E009", "warn", "重复子句", m.group(1)[:40])
            break

    # 摘要是否在正文里又抄了一遍
    if abstract:
        tail = _strip_images(abstract)[:60]
        for p in paras:
            if tail and tail in _strip_images(p) and _strip_images(p) != _strip_images(abstract):
                rep.add("W005", "warn", "摘要正文重复：正文里又出现摘要开头", p[:50])
                break

    # --- 编码 / 公式 ------------------------------------------------------
    if "\ufffd" in md:
        rep.add("E010", "error", f"乱码 {md.count(chr(0xFFFD))} 处（U+FFFD）")
    raw_tex = re.findall(r"\\begin\{|\\frac|\\sum_|\\alpha|\$\$", md)
    if raw_tex:
        rep.add("E011", "error", f"裸露 LaTeX {len(raw_tex)} 处，阅读页会原样显示")
    raw_html = re.findall(r"</?(?:div|span|p|br|img|table|td|tr)\b", md)
    if raw_html:
        rep.add("W007", "warn", f"正文存在裸 HTML {len(raw_html)} 处")

    # --- 参考文献 ---------------------------------------------------------
    ref_head = next(
        (i for i, (k, t) in enumerate(blocks)
         if k == "heading" and re.search(r"参考文献|references", t, re.I)),
        None,
    )
    if ref_head is not None:
        # 文献段常写成列表（`- [1] 作者…`）也常写成裸段落，两种都要数。
        ref_paras = []
        for k, t in blocks[ref_head + 1 :]:
            if k != "para":
                continue
            body = re.sub(r"^[-*•]\s*", "", t).strip()
            if re.match(r"^\[?\d{1,3}[\]\.、)]", body):
                ref_paras.append(body)
        if len(ref_paras) < REFERENCE_MIN:
            rep.add("E012", "error", f"参考文献 {len(ref_paras)} 条（规范 ≥ {REFERENCE_MIN}）")
        # [EB/OL]/[J/OL] 等复合标识也是 GB/T 7714 的合法类型标识
        missing_type = [p for p in ref_paras if not re.search(r"\[(?:EB|[JMDCSRNP])(/OL)?\]", p)]
        if missing_type:
            rep.add(
                "E013",
                "error",
                f"{len(missing_type)} 条文献缺类型标识（[J]/[M]/[C]/[D]）",
                missing_type[0][:50],
            )
        bare_doi = [p for p in ref_paras if "doi" not in p.lower() and "10." not in p]
        if len(bare_doi) == len(ref_paras) and ref_paras:
            rep.add("E014", "warn", "全部文献都没有 DOI，初审无法抽查真实性")

    # --- 标点 / 空格 ------------------------------------------------------
    bad_space = _SPACE_BEFORE_PUNCT.findall(md)
    if bad_space:
        rep.add("W002", "warn", f"中文标点前有空格 {len(bad_space)} 处")

    # --- 段落长度 ---------------------------------------------------------
    long_paras = [p for p in paras if _cjk_count(p) > PARA_MAX_CHARS]
    if long_paras:
        rep.add("W001", "warn", f"{len(long_paras)} 段超过 {PARA_MAX_CHARS} 字（手机上是一堵墙）")

    # --- 图片体积 ---------------------------------------------------------
    if base64_bytes > 300 * 1024:
        rep.add(
            "W003",
            "warn",
            f"内嵌 base64 图片 {base64_bytes / 1024:.0f} KB，单篇超过 300 KB 会让手机加载变慢",
        )
    if images and not captions:
        rep.add("W008", "warn", f"{images} 张图没有任何图注")
    return rep


def report_text(rep: Report) -> str:
    icon = {"error": "✗", "warn": "!", "info": "·"}
    lines = [
        f"{rep.file}  正文 {rep.chars} 汉字  得分 {rep.score}  "
        f"(error {len([f for f in rep.findings if f.severity=='error'])})"
    ]
    for f in rep.findings:
        lines.append(f"  {icon[f.severity]} [{f.code}] {f.message}" + (f"  — {f.detail}" if f.detail else ""))
    if not rep.findings:
        lines.append("  ✓ 未发现问题")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paper-lint", description="按论文规范体检 Markdown 稿件")
    ap.add_argument("path", nargs="?", help="单个 .md 文件")
    ap.add_argument("--dir", help="批量：目录下所有 .md")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--out", help="批量结果写入 JSON")
    args = ap.parse_args(argv)

    files: list[Path] = []
    if args.path:
        files = [Path(args.path)]
    elif args.dir:
        files = sorted(Path(args.dir).rglob("*.md"))
    else:
        ap.print_help()
        return 2

    reports = []
    for f in files:
        try:
            md = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"跳过 {f}: {exc}", file=sys.stderr)
            continue
        rep = lint(md, str(f))
        reports.append(rep)
        print(report_text(rep) if not args.json else json.dumps(rep.to_dict(), ensure_ascii=False))
        print()

    if args.out:
        Path(args.out).write_text(
            json.dumps([r.to_dict() for r in reports], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    if len(reports) > 1:
        bad = [r for r in reports if r.errors]
        print(f"合计 {len(reports)} 篇，其中 {len(bad)} 篇有硬伤；平均得分 "
              f"{sum(r.score for r in reports) / len(reports):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
