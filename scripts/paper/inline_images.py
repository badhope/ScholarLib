"""把稿件里引用的本地图片压成 data URI 内嵌回 Markdown。

站内阅读页只认 `data:image/...;base64,`，相对路径的 `fig-01.png` 在浏览器
里会 404。这里统一做三件事：等比缩到宽 ≤ 1000 px、转成 JPEG（保留透明时
用 PNG）、写回 data URI，单图从几百 KB 降到几十 KB。

    python -m scripts.paper inline a.md --img-dir out/img116
"""

from __future__ import annotations

import argparse
import base64
import io
import re
from pathlib import Path

from PIL import Image

MAX_W, MAX_H = 1000, 1400
_IMG = re.compile(r"!\[([^\]]*)\]\((?!data:)([^)]+)\)")


def _encode(path: Path) -> str:
    im = Image.open(path)
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        alpha = im.convert("RGBA")
        bg = Image.new("RGB", alpha.size, (255, 255, 255))
        bg.paste(alpha, mask=alpha.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if im.width > MAX_W or im.height > MAX_H:
        im.thumbnail((MAX_W, MAX_H), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def inline(md: str, base: Path) -> tuple[str, int, int]:
    count, before, after = 0, len(md), 0

    def repl(m: re.Match) -> str:
        nonlocal count
        alt, src = m.group(1), m.group(2).strip()
        p = (base / src) if not Path(src).is_absolute() else Path(src)
        if not p.exists():
            return m.group(0)
        uri = _encode(p)
        count += 1
        return f"![{alt}]({uri})"

    out = _IMG.sub(repl, md)
    after = len(out)
    return out, count, after - before


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paper-inline")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--img-dir", default=None)
    args = ap.parse_args(argv)

    for f in args.files:
        path = Path(f)
        base = Path(args.img_dir) if args.img_dir else path.parent
        text = path.read_text(encoding="utf-8")
        new, n, delta = inline(text, base)
        path.write_text(new, encoding="utf-8")
        print(f"{path.name}: 内嵌 {n} 张图，体积 {delta/1024:+.0f} KB → {len(new)/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
