"""批量重建：PDF → 结构化 Markdown → 结构规范化 → 图片内嵌 → 门禁体检。

用一句话说清这一步在干什么
--------------------------
它**只做发布前提**：把 PDF 里被压坏的版式、页眉切片、空章节、中英混排的
节标题修回可发布的样子。它**不提高、也不评价文章质量**——一篇内容平庸的
文章修完格式仍然平庸，只是能发了。质量由人读内容来评（见
``docs/scoring-model.md``）。

替换策略
--------
不是「重建了就一定更好」。扫描版 PDF、异形版式、图表为主的稿子，重建出来
可能比原稿更差。所以每篇都算一遍门禁，**只有阻断项变少才替换**，否则保留
原稿并记进 ``skipped``，等人看。

用法::

    python -m scripts.paper batch --pdf-dir D:/work/allpdf_host --out D:/work/rebuilt
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from pathlib import Path

from .inline_images import inline
from .lint import lint
from .normalize_md import normalize
from .rebuild import rebuild

# 这些是「阻断发布」的项：缺摘要、篇名/章节缺失、图注吞正文、乱码、重复段、
# 文献不足。其余（空间紧、长段、无 DOI）只提示，不拦发布。
BLOCKING = {
    "E001", "E002", "E003", "E004", "E005", "E006", "E007",
    "E008", "E010", "E011", "E012", "E013",
}


def _render_blocks(data: dict) -> str:
    """把 rebuild 的块序列写成 Markdown。"""
    parts: list[str] = []
    for b in data["blocks"]:
        kind = b["kind"]
        text = (b.get("text") or "").strip()
        if kind == "title":
            parts.append(f"# {text}")
        elif kind == "heading":
            level = int(b.get("level") or 2)
            parts.append(f"{'#' * min(level, 4)} {text}")
        elif kind == "image":
            parts.append(f"![{b.get('alt', '')}]({b['path']})")
        elif kind == "table":
            parts.append(text)
        elif kind == "caption":
            parts.append(f"*{text}*")
        elif text:
            parts.append(text)
    return "\n\n".join(parts) + "\n"


def _blocking(codes: list[str]) -> int:
    return sum(1 for c in codes if c in BLOCKING)


def process_one(pdf: Path, out_dir: Path, keep_all: bool = False) -> dict:
    key = pdf.stem
    work = Path(tempfile.mkdtemp(prefix=f"rb-{key}-"))
    try:
        img_dir = work / "img"
        data = rebuild(pdf, img_dir)
        raw = _render_blocks(data)
        norm, stats = normalize(raw)
        md, n_img, n_bytes = inline(norm, img_dir)

        rep = lint(md, name=key)
        codes = [f.code for f in rep.findings]
        info = {
            "id": key,
            "chars": rep.chars,
            "blocking": _blocking(codes),
            "findings": codes,
            "images": n_img,
            "kb": round(len(md.encode("utf-8")) / 1024),
            "normalize": stats,
        }
        if keep_all or info["blocking"] == 0:
            (out_dir / f"{key}.md").write_text(md, encoding="utf-8")
            info["written"] = True
        else:
            info["written"] = False
            info["sample"] = md[:400]
        return info
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paper batch", description="批量重建 + 结构规范化")
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep-all", action="store_true", help="门禁未通过的也写出，便于人工看")
    ap.add_argument("--report", default=None)
    args = ap.parse_args(argv)

    pdf_dir = Path(args.pdf_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(pdf_dir.glob("*.pdf"), key=lambda p: (len(p.stem), p.stem))
    if args.limit:
        pdfs = pdfs[: args.limit]

    rows: list[dict] = []
    for i, pdf in enumerate(pdfs, 1):
        try:
            info = process_one(pdf, out_dir, keep_all=args.keep_all)
        except Exception as exc:  # 单篇失败不能带倒整批
            info = {"id": pdf.stem, "error": repr(exc)[:200]}
        rows.append(info)
        flag = "OK " if info.get("blocking") == 0 else f"BLK{info.get('blocking', '?')}"
        print(f"[{i}/{len(pdfs)}] {pdf.stem:>4} {flag}  {info.get('chars', 0):>6} 字  {info.get('kb', 0):>5}KB", flush=True)

    report = Path(args.report) if args.report else out_dir / "batch-report.json"
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for r in rows if r.get("blocking") == 0)
    print(f"\n完成 {len(rows)} 篇：门禁通过 {ok}，待人工 {len(rows) - ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
