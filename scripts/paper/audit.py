"""全库体检索引：遍历上传目录里的 Markdown 稿件，逐篇体检，可选就地修复。

    python -m scripts.paper.audit /data/uploads --out /tmp/audit.json
    python -m scripts.paper.audit /data/uploads --apply --out /tmp/audit.json

`--apply` 会先写 `.bak-fix` 再改文件；同一份文件只备份一次（已存在则跳过），
避免反复跑把最初的原始版本覆盖掉。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .fix import fix
from .lint import lint


def find_manuscripts(root: Path) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for p in sorted(root.rglob("rub-*.md")):
        # 路径形如 <tenant>/<resource_id>/rub-xxxx.md
        parent = p.parent.name
        out.append((int(parent) if parent.isdigit() else 0, p))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paper-audit")
    ap.add_argument("root")
    ap.add_argument("--out", default="/tmp/paper-audit.json")
    ap.add_argument("--apply", action="store_true", help="就地修复（带 .bak-fix 备份）")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    files = find_manuscripts(Path(args.root))
    if args.limit:
        files = files[: args.limit]
    print(f"共 {len(files)} 篇", file=sys.stderr)

    rows = []
    fixed_total = 0
    for i, (rid, path) in enumerate(files, 1):
        try:
            md = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"跳过 {path}: {exc}", file=sys.stderr)
            continue
        before = lint(md, str(path))
        row = {
            "id": rid,
            "file": str(path),
            "chars": before.chars,
            "score_before": before.score,
            "errors_before": [f.code for f in before.errors],
            "findings": [f.code for f in before.findings],
        }
        if args.apply:
            new, stats = fix(md)
            if stats:
                bak = path.with_suffix(path.suffix + ".bak-fix")
                if not bak.exists():
                    shutil.copy2(path, bak)
                path.write_text(new, encoding="utf-8")
                fixed_total += 1
            after = lint(new, str(path))
            row.update(
                {
                    "score_after": after.score,
                    "errors_after": [f.code for f in after.errors],
                    "fixes": stats,
                }
            )
        rows.append(row)
        if i % 25 == 0:
            print(f"  {i}/{len(files)}", file=sys.stderr)
            Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- 汇总 ---
    from collections import Counter

    codes = Counter(c for r in rows for c in r["findings"])
    hard = Counter(c for r in rows for c in r["errors_before"])
    avg_before = sum(r["score_before"] for r in rows) / max(1, len(rows))
    print(f"\n篇数 {len(rows)}　平均分 {avg_before:.1f}")
    if args.apply:
        avg_after = sum(r.get("score_after", r["score_before"]) for r in rows) / max(1, len(rows))
        print(f"修复后平均分 {avg_after:.1f}　实际改动 {fixed_total} 篇")
    print("\n问题分布：")
    for code, n in hard.most_common():
        print(f"  硬伤 {code}: {n} 篇")
    for code, n in codes.most_common():
        if code.startswith(("W", "E")) and code not in hard:
            print(f"  提示 {code}: {n} 篇")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
