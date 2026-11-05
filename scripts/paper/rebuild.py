"""PDF → 干净稿件（重建版）。

为什么重写：老 `extract.py` 按 block 拼文字，遇到「数字被拆成独立绘制单元」
「页眉被切成几十张位图」这类期刊 PDF，会把正文打散、把页眉碎片当成插图，
最后产出「图 1：附图 3（原文插图）UBBISH」这种图注——这正是阅读页错乱的
源头。

这一版换读法：
1. **按栏裁剪取文**：先用行的 x 分布算出栏间距（gutter），再按「整宽行切带、
   带内先左栏后右栏」逐块 `get_text(clip=…, sort=True)`。让 pymupdf 自己拼
   行，数字和上下标不会再丢。
2. **页眉页脚按跨页重复剔除**：同一串短文本在 ≥2 页出现，就是页眉。
3. **图片只留真图**：高度 < 80pt 的位图是页眉切片/刊头 logo，一律丢弃；真
   图按纵向位置插回所在栏。

    python -m scripts.paper rebuild a.pdf -o out/a.md --images out/img
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

_CJK = r"\u4e00-\u9fff"
_CAP = re.compile(r"^\s*(图|表|附图|附表|Figure|Fig\.|Table)\s*([0-9]+)")
_SENT_END = "。！？!?….．：:；;」』””）)】"
_HEAD_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)[.、．]?\s*[\u4e00-\u9fffA-Za-z]")
_KNOWN_HEAD = re.compile(
    r"^\s*(abstract|摘\s*要|关键词|keywords?|引\s*言|introduction|methodology|method|"
    r"methods|materials?\s+and\s+methods|材料与方法|结\s*果|results?|讨论|discussion|"
    r"结\s*论|conclusions?|致\s*谢|acknowledg(e)?ments?|参考文献|references?|附录|appendix)"
    r"\s*[:：]?\s*$",
    re.I,
)
_BOILER = re.compile(
    r"^(rubbish|ubbish|bish|open access|research article|review article|"
    r"received\b.*|accepted\b.*|published\b.*|doi\b.*|mid\b.*|https?://\S+|www\.\S+|"
    r"issn\b.*|©.*|\d{1,4}|第\s*\d+\s*卷.*|vol\.?\s*\d+.*|[|:.\-·]+)$",
    re.I,
)


# --------------------------------------------------------------------------
# 版面
# --------------------------------------------------------------------------


def _physical_lines(page: pymupdf.Page) -> list[dict]:
    out: list[dict] = []
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") != 0:
            continue
        for line in b.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            out.append(
                {
                    "bbox": line["bbox"],
                    "text": "".join(s["text"] for s in spans).strip(),
                    "size": max(s.get("size", 0) for s in spans),
                    "y": (line["bbox"][1] + line["bbox"][3]) / 2,
                }
            )
    return out


def _layout(lines: list[dict], rect) -> dict:
    """判断单栏还是双栏，并给出栏间距位置。"""
    mid = rect.x0 + rect.width / 2
    left = [l for l in lines if (l["bbox"][0] + l["bbox"][2]) / 2 < mid]
    right = [l for l in lines if (l["bbox"][0] + l["bbox"][2]) / 2 >= mid]
    if len(left) < 4 or len(right) < 4:
        return {"two_col": False, "gutter": mid}
    left_x1 = max(l["bbox"][2] for l in left)
    right_x0 = min(l["bbox"][0] for l in right)
    gutter = (left_x1 + right_x0) / 2 if right_x0 > left_x1 else mid
    return {"two_col": True, "gutter": gutter}


def _regions(lines: list[dict], rect, layout: dict) -> list[dict]:
    """按阅读顺序给出矩形块：整宽行单独成带，带内先左栏后右栏。"""
    mid = rect.x0 + rect.width / 2
    gutter = layout["gutter"]
    x0 = min((l["bbox"][0] for l in lines), default=rect.x0 + 40)
    x1 = max((l["bbox"][2] for l in lines), default=rect.x1 - 40)

    full = sorted(
        [l for l in lines if l["bbox"][0] < mid - 14 and l["bbox"][2] > mid + 14],
        key=lambda l: l["bbox"][1],
    )

    out: list[dict] = []
    prev = min(l["bbox"][1] for l in lines)
    for f in full:
        top = f["bbox"][1]
        if top - prev > 8 and layout["two_col"]:
            out.append({"y0": prev, "y1": top, "rect": (x0, prev, gutter - 1, top)})
            out.append({"y0": prev, "y1": top, "rect": (gutter + 1, prev, x1, top)})
        out.append({"y0": top, "y1": f["bbox"][3], "rect": (x0, top - 2, x1, f["bbox"][3] + 1)})
        prev = max(prev, f["bbox"][3])

    bottom = max(l["bbox"][3] for l in lines)
    if bottom - prev > 8 and layout["two_col"]:
        out.append({"y0": prev, "y1": bottom, "rect": (x0, prev, gutter - 1, bottom)})
        out.append({"y0": prev, "y1": bottom, "rect": (gutter + 1, prev, x1, bottom)})
    elif bottom > prev:
        out.append({"y0": prev, "y1": bottom, "rect": (x0, prev, x1, bottom)})
    return out


# --------------------------------------------------------------------------
# 取文
# --------------------------------------------------------------------------


def _clean_text(raw: str, repeated: set[str]) -> list[str]:
    """逐行判定后切段：标题自成一节，正文按句末标点收口。"""
    paras: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf:
            paras.append(re.sub(r"[ \t]+", " ", buf).strip())
            buf = ""

    for ln in raw.splitlines():
        ln = ln.replace(" ", " ").strip()
        if not ln or _BOILER.match(ln) or (ln in repeated and len(ln) <= 40):
            continue
        if _heading_like(ln) or (_CAP.match(ln) and len(ln) < 130):
            flush()
            buf = ln
            flush()
            continue
        if not buf:
            buf = ln
            continue
        prev = buf[-1]
        if prev == "-" and re.match(r"[a-z]", ln):
            buf = buf[:-1] + ln
        elif re.search(rf"[{_CJK}，。；：！？、）】]$", buf) and re.match(rf"[{_CJK}（【]", ln):
            buf += ln
        elif re.search(r"[A-Za-z0-9,;:.)%]$", buf) and re.match(r"[A-Za-z0-9(]", ln):
            buf += " " + ln
        else:
            buf += ln
        if buf and buf[-1] in _SENT_END:
            flush()
    flush()
    return paras


_BULLET = re.compile(r"^([（(]?[0-9一二三四五六七八九十]{1,2}[)）.、]|[-•·])\s*")


def _heading_like(text: str) -> bool:
    t = text.strip().replace(" ", " ")
    if _KNOWN_HEAD.match(t):
        return True
    if _CAP.match(t) or len(t) > 40:
        return False
    # 标题里不会有句读；有逗号的「82 条消息中仅32 种…」是正文
    if re.search(r"[，。；！？、]", t):
        return False
    return bool(_HEAD_NUM.match(t) and len(t) <= 30)


def _is_continuation(prev: str, nxt: str) -> bool:
    """上一段没写完、下一段不是新开话头 → 应该接上。

    PDF 里每个文本块常常只有一行，不合回去手机上就是一行一段；但合过头会
    把「1 Introduction」并进正文，所以标题、图注、列表项、公式一律不合。
    """
    if not prev or len(prev) < 20:
        return False
    if prev[-1] in _SENT_END:
        return False
    if len(re.findall(rf"[{_CJK}]", prev)) < 8:
        return False
    if _CAP.match(nxt) or _CAP.match(prev):
        return False
    if _BULLET.match(nxt) or _BULLET.match(prev):
        return False
    if _heading_like(nxt) or _heading_like(prev):
        return False
    # 篇名/作者行：短、没有任何停顿标点，接上就变成「标题作者名」
    if len(prev) <= 45 and not re.search(r"[，。；！？、]", prev):
        return False
    if re.search(r"[*†@]", nxt) and len(nxt) < 160:
        return False
    return True


def _post_merge(blocks: list[dict]) -> list[dict]:
    out: list[dict] = []
    for b in blocks:
        if b["kind"] != "para":
            out.append(b)
            continue
        if out and out[-1]["kind"] == "para" and _is_continuation(out[-1]["text"], b["text"]):
            prev = out[-1]["text"]
            nxt = b["text"]
            if re.search(rf"[{_CJK}，、；：]$", prev) or re.match(rf"[{_CJK}（【]", nxt):
                out[-1]["text"] = prev + nxt
            elif re.search(r"[A-Za-z0-9,;:.]$", prev) and re.match(r"[A-Za-z0-9(]", nxt):
                out[-1]["text"] = prev + " " + nxt
            else:
                out[-1]["text"] = prev + nxt
            continue
        out.append(b)
    return out


def _split_title(blocks: list[dict], first_page_lines: list[dict], rect) -> list[dict]:
    """首页上半页字号最大的一行是篇名——它常常和作者行粘在一段里。"""
    cand = [
        l
        for l in first_page_lines
        if rect.height * 0.08 <= l["bbox"][1] <= rect.height * 0.55 and len(l["text"]) >= 6
    ]
    # 刊名「RUBBISH」是首页字号最大的那一行，但它不是篇名
    cand = [c for c in cand if not re.fullmatch(r"[ru]?bbish", c["text"].strip(), re.I)]
    if not cand:
        return blocks
    top = max(c["size"] for c in cand)
    # 篇名常被拆成两行（主标题 + 破折号副题），字号略有差别，一起收
    titles = sorted([c for c in cand if c["size"] >= top * 0.9], key=lambda c: c["bbox"][1])
    title = "".join(t["text"] for t in titles) if titles else ""
    if not title:
        return blocks
    out: list[dict] = []
    done = False
    for b in blocks:
        if not done and b["kind"] == "para" and b["text"].startswith(title) and len(b["text"]) > len(title) + 4:
            done = True
            out.append({"kind": "title", "text": title, "page": b["page"]})
            rest = b["text"][len(title):].lstrip(" ，,、")
            if rest:
                out.append({"kind": "para", "text": rest, "page": b["page"]})
            continue
        out.append(b)
    return out


def _repeated_strings(pages: list[list[str]]) -> set[str]:
    freq = Counter()
    for pl in pages:
        for s in set(pl):
            if len(s) <= 60:
                freq[s] += 1
    return {s for s, n in freq.items() if n >= 2 and re.fullmatch(r"[\x00-\x7f\s|:.\-]*", s)}


# --------------------------------------------------------------------------
# 图片
# --------------------------------------------------------------------------


def _figures(page: pymupdf.Page, pno: int) -> list[dict]:
    out = []
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            continue
        for r in rects:
            if r.height < 80 or r.width < 120:
                continue
            # 页面上沿 15% 内的位图是刊头/封面，不是插图
            if r.y1 < page.rect.height * 0.15:
                continue
            # 首页上方的小图是刊名 logo，不是插图
            if pno == 1 and r.y1 < page.rect.height * 0.35 and r.width < 420:
                continue
            out.append({"bbox": (r.x0, r.y0, r.x1, r.y1), "xref": xref, "page": pno, "y": r.y0})
    return out


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def rebuild(pdf: Path, image_dir: Path | None = None) -> dict:
    doc = pymupdf.open(pdf)
    image_dir = image_dir or (pdf.parent / "images")
    image_dir.mkdir(parents=True, exist_ok=True)

    page_lines = [_physical_lines(p) for p in doc]

    # 第一遍：只取文字，用于统计「跨页重复」的页眉页脚
    raw_pages: list[list[str]] = []
    for pno, page in enumerate(doc, 1):
        lay = _layout(page_lines[pno - 1], page.rect)
        texts: list[str] = []
        for reg in _regions(page_lines[pno - 1], page.rect, lay):
            raw = page.get_text("text", clip=pymupdf.Rect(*reg["rect"]), sort=True)
            texts += [ln.strip() for ln in raw.splitlines() if ln.strip()]
        raw_pages.append(texts)
    repeated = _repeated_strings(raw_pages)

    blocks: list[dict] = []
    for pno, page in enumerate(doc, 1):
        lay = _layout(page_lines[pno - 1], page.rect)
        figs = _figures(page, pno)
        used: set[int] = set()
        for reg in _regions(page_lines[pno - 1], page.rect, lay):
            for i, f in enumerate(figs):
                if i not in used and reg["y0"] - 4 <= f["y"] <= reg["y1"]:
                    blocks.append({"kind": "image", "xref": f["xref"], "page": pno})
                    used.add(i)
            raw = page.get_text("text", clip=pymupdf.Rect(*reg["rect"]), sort=True)
            for p in _clean_text(raw, repeated):
                if _CAP.match(p) and len(p) < 130:
                    blocks.append({"kind": "caption", "text": p, "page": pno})
                elif _KNOWN_HEAD.match(p):
                    blocks.append({"kind": "heading", "text": p, "level": 1, "page": pno})
                elif _HEAD_NUM.match(p) and len(p) <= 26 and not _CAP.match(p):
                    lvl = 2 if "." in p.split()[0] else 1
                    blocks.append({"kind": "heading", "text": p, "level": lvl, "page": pno})
                else:
                    blocks.append({"kind": "para", "text": p, "page": pno})
        for i, f in enumerate(figs):
            if i not in used:
                blocks.append({"kind": "image", "xref": f["xref"], "page": pno})

    blocks = _split_title(blocks, page_lines[0], doc[0].rect)
    blocks = _post_merge(blocks)

    # 图片落地：同一 xref 只存一次（刊头 logo 每页都会出现）
    fig_no, saved = 0, {}
    out: list[dict] = []
    for b in blocks:
        if b["kind"] != "image":
            out.append(b)
            continue
        xref = b["xref"]
        if xref in saved:
            continue
        fig_no += 1
        target = image_dir / f"fig-{fig_no:02d}.png"
        try:
            pix = pymupdf.Pixmap(doc, xref)
            if pix.n - pix.alpha >= 4:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            pix.save(target)
        except Exception as exc:  # pragma: no cover
            print(f"  图片 {xref} 导出失败：{exc}", file=sys.stderr)
            continue
        saved[xref] = target
        out.append({"kind": "image", "path": str(target), "page": b["page"]})

    return {"source": str(pdf), "pages": doc.page_count, "blocks": out}


def to_markdown(data: dict) -> str:
    lines: list[str] = []
    for b in data["blocks"]:
        k = b["kind"]
        if k == "heading":
            lines += ["", "#" * min(b.get("level", 2) + 1, 6) + " " + b["text"], ""]
        elif k == "image":
            lines += ["", f"![]({Path(b['path']).name})", ""]
        elif k == "caption":
            lines += [b["text"], ""]
        else:
            lines += [b["text"], ""]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return text.strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paper-rebuild", description="PDF → 干净 Markdown")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--images", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    src = Path(args.pdf)
    data = rebuild(src, Path(args.images) if args.images else None)
    md = to_markdown(data)
    Path(args.out).write_text(md, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    kinds = Counter(b["kind"] for b in data["blocks"])
    han = len(re.findall(rf"[{_CJK}]", md))
    print(f"{src.name}: {data['pages']} 页 {dict(kinds)} 汉字 {han}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
