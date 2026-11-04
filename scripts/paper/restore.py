"""回滚：把 `--apply` 改过的文件从 `.bak-fix` 恢复。

    python -m scripts.paper restore /data/uploads

每条 `.bak-fix` 都是「改动前」的完整副本；恢复后旧备份会被删掉，这样下次
`--apply` 会重新生成一份，不会把最早的原稿覆盖成中间态。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paper-restore")
    ap.add_argument("root")
    args = ap.parse_args(argv)

    baks = sorted(Path(args.root).rglob("*.bak-fix"))
    for bak in baks:
        target = Path(str(bak)[: -len(".bak-fix")])
        shutil.copy2(bak, target)
        bak.unlink()
    print(f"已恢复 {len(baks)} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
