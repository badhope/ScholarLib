"""命令行：Markdown / 结构化 JSON → 官方模板 Word。

    python -m scripts.paper docx a.md -o a.docx --title "篇名" --authors "张三、李四"
    python -m scripts.paper docx a.json -o a.docx      # 用 extract 的产物
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .docx_template import Meta, build, build_file


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paper-docx")
    ap.add_argument("src", help=".md 或 extract 产出的 .json")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--authors", default="", help="顿号或逗号分隔")
    ap.add_argument("--affiliations", default="", help="分号分隔")
    args = ap.parse_args(argv)

    src = Path(args.src)
    out = Path(args.out)
    authors = [a.strip() for a in args.authors.replace("，", "、").split("、") if a.strip()]
    affs = [a.strip() for a in args.affiliations.split(";") if a.strip()]

    if src.suffix.lower() == ".json":
        data = json.loads(src.read_text(encoding="utf-8"))
        from .extract import to_markdown

        md = to_markdown(data)
        meta = Meta(
            title=args.title or data.get("title", ""),
            authors=authors,
            affiliations=affs,
        )
        # 从 markdown 里补摘要与关键词
        from .docx_template import parse_meta

        parsed = parse_meta(md)
        meta.abstract = parsed.abstract
        meta.keywords = parsed.keywords
        out.write_bytes(build(md, meta, base_dir=src.parent))
    else:
        build_file(src, out, title=args.title, authors=authors)

    print(f"已生成 {out}（{out.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
