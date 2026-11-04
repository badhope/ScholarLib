"""PDF → 结构化稿件（文字 + 图片 + 阅读顺序）。

这是「先落成 Word 再入库」流水线的第一步。为什么不能直接用 pymupdf4llm 出
Markdown：它对双栏期刊 PDF 的阅读顺序判断经常失败，结果是「4 结论」排在
「3 结果」前面、图注把下一栏的正文整段吞进来、正文里同一段印两遍。这些在
阅读页上不是小瑕疵，是读者一眼就看得出的错乱。

这里显式做三件事：
1. **分栏判定**：整页宽度的块充当分隔带，带内先左栏后右栏，带与带之间按 y 走；
2. **角色判定**：按字号/加粗判标题层级，按「图 N / 表 N」判图注，其余为正文；
3. **图片落地**：把内嵌位图导出成文件（不再塞 base64），单篇体积从几百 KB
   降到几十 KB，手机加载和再导出都轻。

    python -m scripts.paper extract a.pdf -o out/a.json --images out/images
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pymupdf

_CJK = r"\u4e00-\u9fff"
_CAPTION = re.compile(r"^\s*(图|表|附图|附表|Figure|Table)\s*([0-9]+)")
_HEAD_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)[.、．]?\s*(\S.*)$")

# 页眉页脚与刊头信息：这些不是正文，留在稿子里会在阅读页顶部堆一屏无关文字
_BOILERPLATE = re.compile(
    r"^(open access|research article|review article|received\b.*|accepted\b.*|"
    r"published\b.*|doi\b.*|https?://\S+|www\.\S+|issn\b.*|©.*|"
    r"第\s*\d+\s*卷.*|vol\.?\s*\d+.*|\d{1,4})$",
    re.I,
)


def _is_boilerplate(text: str, page_rect, bbox) -> bool:
    s = text.strip()
    if _BOILERPLATE.match(s):
        return True
    # 位于页面上沿 8% 或下沿 8% 的短行基本都是页眉页脚
    y0, y1 = bbox[1], bbox[3]
    top, bottom = page_rect.y0 + page_rect.height * 0.07, page_rect.y1 - page_rect.height * 0.07
    return len(s) < 40 and (y1 < top or y0 > bottom)


def _join_lines(lines: list[str]) -> str:
    """把同一块里的多行拼成一段：中文之间不补空格，英文之间补一个。"""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if out and re.search(rf"[{_CJK}，。；：！？、）】]$", out) and re.match(rf"[{_CJK}（【]", ln):
            out += ln
        elif out and re.search(r"[A-Za-z0-9,;:.)]$", out) and re.match(r"[A-Za-z0-9(]", ln):
            out += " " + ln
        elif out.endswith("-") and re.match(r"[a-zA-Z]", ln):
            out = out[:-1] + ln
        else:
            out += ln
    return out


def _page_blocks(page: pymupdf.Page, page_no: int) -> list[dict]:
    raw = page.get_text("dict")
    width = page.rect.width
    mid = page.rect.x0 + width / 2
    blocks: list[dict] = []

    for b in raw.get("blocks", []):
        x0, y0, x1, y1 = b["bbox"]
        if b.get("type") == 1:  # 位图
            blocks.append(
                {"kind": "image", "bbox": (x0, y0, x1, y1), "xref": b.get("number"), "page": page_no}
            )
            continue
        lines = []
        sizes: list[float] = []
        for line in b.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if text.strip():
                lines.append(text)
                sizes.extend(span.get("size", 0) for span in line.get("spans", []))
        if not lines:
            continue
        text = _join_lines(lines)
        if _is_boilerplate(text, page.rect, b["bbox"]):
            continue
        blocks.append(
            {
                "kind": "text",
                "bbox": (x0, y0, x1, y1),
                "text": text,
                "size": max(sizes) if sizes else 0,
                "page": page_no,
            }
        )
    return blocks


def _column_of(block: dict, mid: float) -> int:
    """-1 = 跨栏（整宽），0 = 左栏，1 = 右栏。"""
    x0, _, x1, _ = block["bbox"]
    if x0 < mid - 12 and x1 > mid + 12:
        return -1
    return 0 if (x0 + x1) / 2 < mid else 1


def _is_two_column(blocks: list[dict], rect) -> bool:
    mid = rect.x0 + rect.width / 2
    cols = [_column_of(b, mid) for b in blocks]
    left, right = cols.count(0), cols.count(1)
    total = len(blocks)
    # 两栏都至少占到三成，才认定是双栏；否则单栏页会被硬切成左右两半，
    # 读起来变成"左半句、右半句"。
    return total >= 6 and left >= total * 0.3 and right >= total * 0.3


def _order(blocks: list[dict], rect) -> list[dict]:
    """按阅读顺序排列：整宽块作分隔带，带内先读完左栏再读右栏。"""
    if not blocks:
        return []
    if not _is_two_column(blocks, rect):
        return sorted(blocks, key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0]))

    mid = rect.x0 + rect.width / 2
    full = sorted((b for b in blocks if _column_of(b, mid) == -1), key=lambda b: b["bbox"][1])
    remaining = [b for b in blocks if _column_of(b, mid) != -1]
    ordered: list[dict] = []
    prev_y = -1e9
    for sep in full:
        band = [b for b in remaining if prev_y <= b["bbox"][1] and b["bbox"][3] <= sep["bbox"][1] + 2]
        band.sort(key=lambda b: (_column_of(b, mid), b["bbox"][1], b["bbox"][0]))
        ordered += band
        ordered.append(sep)
        prev_y = sep["bbox"][3]
        remaining = [b for b in remaining if b not in band]
    remaining.sort(key=lambda b: (_column_of(b, mid), b["bbox"][1], b["bbox"][0]))
    return ordered + remaining


def extract(path: Path, image_dir: Path | None = None) -> dict:
    doc = pymupdf.open(path)
    image_dir = image_dir or (path.parent / "images")
    image_dir.mkdir(parents=True, exist_ok=True)

    all_blocks: list[dict] = []
    for pno, page in enumerate(doc, 1):
        # 必须逐页排序：跨页混在一起排，第 2 页的左栏会排到第 1 页右栏之前
        all_blocks += _order(_page_blocks(page, pno), page.rect)

    # 正文字号 = 出现最多的字号
    from collections import Counter

    size_counter = Counter(round(b["size"], 1) for b in all_blocks if b["kind"] == "text")
    body_size = size_counter.most_common(1)[0][0] if size_counter else 10.0

    out_blocks: list[dict] = []
    fig_no = 0
    seen: set[str] = set()
    for idx, b in enumerate(all_blocks):
        if b["kind"] == "image":
            fig_no += 1
            xref = b.get("xref")
            target = image_dir / f"fig-{fig_no:02d}.png"
            try:
                if xref:
                    pix = pymupdf.Pixmap(doc, xref)
                    if pix.n - pix.alpha >= 4:
                        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                    pix.save(target)
                else:
                    page = doc[b["page"] - 1]
                    page.get_pixmap(clip=pymupdf.Rect(b["bbox"]), dpi=200).save(target)
                out_blocks.append({"kind": "image", "path": str(target), "page": b["page"]})
            except Exception:
                continue
            continue

        text = b["text"].strip()
        if not text or text in seen:
            continue
        seen.add(text)

        if _CAPTION.match(text) and len(text) < 120:
            out_blocks.append(
                {"kind": "caption", "text": text, "page": b["page"], "bbox": b["bbox"], "size": b["size"]}
            )
        elif b["size"] >= body_size * 1.15 and len(text) < 80:
            hm = _HEAD_NUM.match(text)
            level = 1 if b["size"] >= body_size * 1.5 else (2 if hm else 2)
            out_blocks.append(
                {
                    "kind": "heading",
                    "text": text,
                    "level": level,
                    "page": b["page"],
                    "bbox": b["bbox"],
                    "size": b["size"],
                }
            )
        else:
            out_blocks.append(
                {"kind": "para", "text": text, "page": b["page"], "bbox": b["bbox"], "size": b["size"]}
            )

    title = _guess_title(doc, out_blocks, body_size)
    out_blocks = _merge_paragraphs(out_blocks)
    return {
        "source": str(path),
        "pages": doc.page_count,
        "title": title,
        "blocks": out_blocks,
    }


_SENT_END = "。！？!?…：:」』”）)"


def _merge_paragraphs(blocks: list[dict]) -> list[dict]:
    """把被 PDF 拆成一行的段落合回去。

    PDF 里每个文本块往往只是一行，直接输出会让正文变成"一行一段"，在手机
    上就是每隔十几个字换一段。合并条件是：上一块没有句末标点、下一块不是
    标题/图注/图片。跨页也合，只要句子没结束。
    """
    out: list[dict] = []
    for b in blocks:
        if b["kind"] != "para":
            out.append(b)
            continue
        if out and out[-1]["kind"] == "para":
            prev = out[-1]["text"]
            gap = b["bbox"][1] - out[-1]["bbox"][3]
            # 行距内的续行才合并；明显空开的一行是新段落（作者行、单位行都
            # 不以句号结尾，光看标点会把它们并进摘要里）
            if prev and prev[-1] not in _SENT_END and gap < (b.get("size") or 10) * 0.8:
                nxt = b["text"]
                if prev.endswith("-"):
                    out[-1]["text"] = prev[:-1] + nxt
                elif re.match(rf"[{_CJK}（【]", nxt) or re.search(rf"[{_CJK}]$", prev):
                    out[-1]["text"] = prev + nxt
                else:
                    out[-1]["text"] = prev + " " + nxt
                out[-1]["bbox"] = (
                    out[-1]["bbox"][0],
                    out[-1]["bbox"][1],
                    b["bbox"][2],
                    b["bbox"][3],
                )
                continue
        out.append(b)
    return out


def _guess_title(doc: pymupdf.Page, blocks: list[dict], body_size: float) -> str:
    """标题 = 首页上半页字号最大的那段文字（排除刊名与页眉）。"""
    page = doc[0]
    h = page.rect.height
    best, best_size = "", 0.0
    for b in page.get_text("dict").get("blocks", []):
        for line in b.get("lines", []):
            text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
            size = max((s.get("size", 0) for s in line.get("spans", [])), default=0)
            y = line.get("bbox", (0, 0, 0, 0))[1]
            if not (h * 0.04 <= y <= h * 0.5):
                continue
            if re.fullmatch(r"(RUBBISH|rubbish|ISSN.*|DOI.*|Vol.*)", text):
                continue
            if size > best_size and 8 <= len(text) <= 90:
                best, best_size = text, size
    return best or "未命名稿件"


# --- 结构化 → Markdown（供现有入库管线复用） ---------------------------------


def to_markdown(data: dict) -> str:
    lines: list[str] = []
    for b in data["blocks"]:
        if b["kind"] == "heading":
            lines += ["", "#" * min(b.get("level", 2) + 1, 6) + " " + b["text"], ""]
        elif b["kind"] == "image":
            lines += ["", f"![]({b['path']})", ""]
        elif b["kind"] == "caption":
            lines += [b["text"], ""]
        else:
            lines += [b["text"], ""]
    return "\n".join(lines).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paper-extract", description="PDF → 结构化 JSON")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", help="输出 JSON 路径")
    ap.add_argument("--images", help="图片输出目录")
    ap.add_argument("--md", help="同时输出 Markdown")
    args = ap.parse_args(argv)

    src = Path(args.pdf)
    data = extract(src, Path(args.images) if args.images else None)
    out = Path(args.out) if args.out else src.with_suffix(".json")
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.md:
        Path(args.md).write_text(to_markdown(data), encoding="utf-8")
    kinds: dict[str, int] = {}
    for b in data["blocks"]:
        kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
    print(f"{src.name}: {data['pages']} 页  {kinds}  标题「{data['title']}」")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
