"""命令行入口：python -m scripts.paper {lint,fix,audit} ...

把三个子命令收到一个入口，避免在容器里写一长串带引号的 -c。
"""

from __future__ import annotations

import sys

USAGE = """用法：
  python -m scripts.paper lint  <文件|--dir 目录> [--json] [--out 报告.json]
  python -m scripts.paper fix   <文件...> [--write]
  python -m scripts.paper audit <上传根目录> [--apply] [--limit N] [--out 报告.json]
"""


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(USAGE)
        return 0
    cmd = sys.argv.pop(1)
    if cmd == "lint":
        from .lint import main as m
    elif cmd == "fix":
        from .fix import main as m
    elif cmd == "audit":
        from .audit import main as m
    elif cmd == "restore":
        from .restore import main as m
    elif cmd == "extract":
        from .extract import main as m
    elif cmd == "rebuild":
        from .rebuild import main as m
    elif cmd == "batch":
        from .batch import main as m
    elif cmd == "normalize":
        from .normalize_md import main as m
    elif cmd == "inline":
        from .inline_images import main as m
    elif cmd == "docx":
        from .docx_template import build_file  # noqa: F401
        from .docx_cli import main as m
    else:
        print(USAGE)
        return 2
    return m(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
