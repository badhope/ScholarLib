"""数字丢失体检：对比原稿 PDF 与线上 Markdown 里的数字个数。

PDF 里数字常被排成另一种字体（数学字体/小型大写），提取器一旦按字体分块，
"我们生成了 120 篇论文" 就会变成 "我们生成了篇论文"。这类丢失在阅读页上
看不出来——句子依然通顺，只是事实没了。

判据：Markdown 里的数字字符数 < PDF 里的 60%，即认定该篇发生过丢失。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pymupdf


def digits(text: str) -> int:
    return len(re.findall(r"\d", text))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paper-digits")
    ap.add_argument("mapping", help="TSV：resource_id<TAB>pdf路径<TAB>md路径")
    ap.add_argument("--out", default="/tmp/digits.json")
    ap.add_argument("--threshold", type=float, default=0.6)
    args = ap.parse_args(argv)

    rows = []
    for line in Path(args.mapping).read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        rid, pdf, md = parts[0], Path(parts[1]), Path(parts[2])
        if not pdf.exists() or not md.exists():
            continue
        try:
            doc = pymupdf.open(pdf)
            pdf_text = "".join(p.get_text() for p in doc)
        except Exception as exc:
            print(f"跳过 {rid}: {exc}", file=sys.stderr)
            continue
        md_text = md.read_text(encoding="utf-8", errors="replace")
        # base64 图片里全是字母数字，必须先剔掉再数
        md_text = re.sub(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+", "", md_text)
        a, b = digits(pdf_text), digits(md_text)
        if a < 10:
            continue
        ratio = b / a
        if ratio < args.threshold:
            rows.append({"id": int(rid), "pdf_digits": a, "md_digits": b, "ratio": round(ratio, 2)})

    rows.sort(key=lambda r: r["ratio"])
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"疑似丢数字 {len(rows)} 篇；最严重：")
    for r in rows[:12]:
        print(f"  #{r['id']}  PDF {r['pdf_digits']} → MD {r['md_digits']}（保留 {r['ratio']:.0%}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
