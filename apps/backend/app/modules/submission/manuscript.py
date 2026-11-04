"""Manuscript → Markdown conversion for online reading.

设计取舍（0.6.2）：

- 在线阅读渲染 Markdown（富排版、图片、公式、移动端友好），PDF 原件
  只作为下载通道；浏览器端 PDF 渲染（pdf.js）降级为无 md 稿件的兜底。
- 转换是**尽力而为**：任何失败返回 None（保留 PDF 即可），绝不让上传
  失败。日志记录原因，不向作者报错。
- PDF 用 pymupdf4llm（版面感知的文本流 + 图片抽取，图片以 data URI
  内嵌，Markdown 自包含）再经 ``markdown_clean`` 做结构清洗（双栏拼接
  产生的「标题+正文同行」、字体切换伪粗体、刊头与重跑页眉都在这一步处理）；
  docx 用 mammoth（语义 HTML）+ markdownify。
  老式 .doc / PS / ZIP 不转换（None），阅读器回退 PDF。
- 转换结果纯 Markdown 文本，不含原始 HTML —— 前端 react-markdown
  默认转义 HTML，XSS 面为零。

PDF 解析/渲染在不可控输入上崩溃的隔离：整段转换包在 try/except 里，
pymupdf 自身对损坏文件抛异常而不是 segfault（mupdf 以外挂沙盒态运行
解析器），历史版本的安全公告走依赖审计管道（pip-audit）。
"""

from __future__ import annotations

import base64
import logging
import math
import os
import re
import tempfile
from io import BytesIO
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)

_MD_SUFFIX = ".md"


def _original_simple_pdf_image(doc: pymupdf.Document) -> bytes | None:

    try:
        if len(doc) != 1:
            return None
        page = doc[0]
        if page.rotation or list(page.annots() or ()) or list(page.widgets() or ()):
            return None
        images = page.get_image_info(xrefs=True)
        if len(images) != 1 or page.get_bboxlog()[0][0] != "fill-image":
            return None
        if len(page.get_bboxlog()) != 1 or images[0]["has-mask"]:
            return None
        image = images[0]
        a, b, c, d, _, _ = image["transform"]
        if a <= 0 or d <= 0 or b != 0 or c != 0:
            return None
        if not math.isclose(a * image["height"], d * image["width"], rel_tol=1e-5):
            return None
        if doc.xref_get_key(image["xref"], "Decode")[0] != "null":
            return None
        if not page.rect.contains(pymupdf.Rect(image["bbox"])):
            return None
        streams = page.get_contents()
        if len(streams) != 1:
            return None
        number = rb"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
        matrix = rb"\s+".join([number] * 6)
        pattern = rb"\s*q\s+" + matrix + rb"\s+cm\s+/[^\s/]+\s+Do\s+Q\s*"
        if not re.fullmatch(pattern, doc.xref_stream(streams[0])):
            return None
        xref = image["xref"]
        if doc.xref_get_key(xref, "Mask")[0] != "null":
            return None
        node = page.xref
        seen = set()
        while node:
            if node in seen:
                return None
            seen.add(node)
            if doc.xref_get_key(node, "Resources/ColorSpace")[0] != "null":
                return None
            parent_type, parent = doc.xref_get_key(node, "Parent")
            if parent_type == "null":
                break
            if parent_type != "xref":
                return None
            node = int(parent.split()[0])
        color_space = doc.xref_get_key(xref, "ColorSpace")
        if color_space not in (("name", "/DeviceRGB"), ("name", "/DeviceGray")):
            return None
        if doc.xref_get_key(xref, "Filter") != ("name", "/DCTDecode"):
            return None
        if doc.xref_get_key(xref, "DecodeParms")[0] != "null":
            return None
        original = doc.xref_stream_raw(xref)
        pixmap = pymupdf.Pixmap(original)
        expected = 3 if color_space[1] == "/DeviceRGB" else 1
        if pixmap.alpha or pixmap.colorspace is None or pixmap.colorspace.n != expected:
            return None
        extracted = doc.extract_image(xref)
        if not extracted or extracted["ext"] != "jpeg" or extracted["smask"]:
            return None
        if extracted["image"] != original:
            return None
        return bytes(original)

    except Exception:
        return None


def _pdf_to_markdown(contents: bytes) -> str | None:
    """PDF → Markdown（pymupdf4llm），图片内嵌为 data URI。"""
    import pymupdf
    import pymupdf4llm

    doc = pymupdf.open(stream=contents, filetype="pdf")
    try:
        if doc.is_encrypted:
            logger.info("manuscript_convert_skipped reason=encrypted_pdf")
            return None
        with tempfile.TemporaryDirectory(prefix="rubbish-md-") as tmp:
            try:
                # 1.6.0：dpi 110 → 220（像素量 4×，论文插图不再模糊）；
                # 图片输出 PNG → JPEG（照片类体积砍 5-10×，q 默认值即可，
                # 截图类线条在 220dpi 下依然锐利）。jpeg 不被接受时回退 png。
                md = pymupdf4llm.to_markdown(
                    doc,
                    write_images=True,
                    image_path=tmp,
                    image_format="jpeg",
                    image_size_limit=0.0,
                    dpi=220,
                )
            except Exception:
                logger.info("manuscript_jpeg_fallback_to_png")
                md = pymupdf4llm.to_markdown(
                    doc,
                    write_images=True,
                    image_path=tmp,
                    image_format="png",
                    image_size_limit=0.0,
                    dpi=220,
                )
            names = sorted(os.listdir(tmp))
            original = _original_simple_pdf_image(doc) if len(names) == 1 else None
            if original and len(re.findall(r"!\[[^\]]*\]\([^)]+\)", md)) != 1:
                original = None
            for name in names:
                path = Path(tmp, name)
                if not path.is_file():
                    continue
                mime = "image/jpeg" if name.lower().endswith((".jpg", ".jpeg")) else "image/png"
                b64 = base64.b64encode(original or path.read_bytes()).decode("ascii")
                mime = "image/jpeg" if original else mime
                data_uri = f"data:{mime};base64,{b64}"
                paths = (name, path.as_posix(), str(path))
                for image_ref in set(paths):
                    pattern = r"!\[([^\]]*)\]\(" + re.escape(image_ref) + r"\)"
                    md = re.sub(pattern, f"![\\g<1>]({data_uri})", md)
        md = md.strip()
        return md or None
    finally:
        doc.close()


def _docx_to_markdown(contents: bytes) -> str | None:
    """docx → Markdown（mammoth 语义 HTML + markdownify + 段落重组）。"""
    import mammoth
    from markdownify import markdownify

    from app.modules.submission.markdown_clean import reflow_paragraphs

    result = mammoth.convert_to_html(BytesIO(contents))
    html = result.value
    md = markdownify(html, heading_style="ATX").strip()
    # docx 的段落通常带空行，但混排文档仍会产生碎行——统一重组一次。
    return reflow_paragraphs(md) or None


def convert_to_markdown(contents: bytes, filename: str) -> str | None:
    """尽力把上传稿件转成 Markdown；不支持或失败一律返回 None。"""
    ext = os.path.splitext(filename or "")[1].lower()
    try:
        result = _convert_to_markdown_inner(contents, ext)
        if result is None:
            return None
        # 排印统一放在最后一步：标题编号补空格、图表题注独立、中英混排间距、
        # 断行表格补管、连续空行折叠。规则幂等，重复上传不会二次漂移。
        from app.modules.submission.normalize import normalize_markdown

        result = normalize_markdown(result)
        # PDF 内嵌的数学斜体等字符偶尔以孤立代理对形式出现（\ud835…），
        # 存储层 UTF-8 编码会直接抛异常。这些残缺字形无法还原，直接剔除。
        return re.sub(r"[\ud800-\udfff]", "", result)
    except Exception:
        # 转换是增值能力：损坏/加密/超纲的输入一律静默降级。
        logger.warning("manuscript_convert_failed ext=%s", ext, exc_info=True)
        return None


# 转换的硬超时（秒）。超过即放弃 Markdown、回退 PDF 视图。
# 取值依据：正常稿件（<10MB）在 4 核上转换耗时 2–15 秒；60 秒足以覆盖
# 大稿，又能把"恶意构造的慢输入"压到用户可感知的等待上限内。
CONVERT_TIMEOUT_SECONDS = 60.0


async def convert_to_markdown_async(
    contents: bytes, filename: str, *, timeout: float = CONVERT_TIMEOUT_SECONDS
) -> str | None:
    """``convert_to_markdown`` 的异步安全版本（线程池 + 硬超时）。

    **为什么必须有这个包装**：``convert_to_markdown`` 是同步 CPU 密集函数
    （pymupdf4llm / mammoth 全量解析）。在 ``async def`` 路由里直接调用它，
    会把整个事件循环占住——期间所有租户的所有请求（包括 ``/api/health``）
    都无法被处理，一个用户上传一份特制 PDF 就能让整个进程假死。

    两层保护：
    1. ``anyio.to_thread.run_sync`` 把它挪到工作线程，事件循环继续服务；
    2. ``asyncio.wait_for`` 硬超时，防止线程被单份稿件长期占用（线程池
       满了一样会拖垮后续请求）。

    超时/异常一律返回 None：调用方已经把 None 当作"回退 PDF 视图"。
    """
    import asyncio

    import anyio

    def _run() -> str | None:
        return convert_to_markdown(contents, filename)

    try:
        return await asyncio.wait_for(anyio.to_thread.run_sync(_run), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        logger.warning(
            "manuscript_convert_timeout ext=%s bytes=%s timeout=%ss",
            os.path.splitext(filename or "")[1].lower(),
            len(contents),
            timeout,
        )
        return None
    except Exception:
        logger.warning("manuscript_convert_async_failed", exc_info=True)
        return None


def _convert_to_markdown_inner(contents: bytes, ext: str) -> str | None:
    try:
        if ext == ".pdf":
            md = _pdf_to_markdown(contents)
            # 统一清洗：去 HTML 标签/刊头重跑行/页码，摘要升为 H2。
            # 与历史 267 篇导入稿使用同一函数，保证新旧稿件阅读体验一致。
            from app.modules.submission.markdown_clean import clean

            return clean(md) if md else md
        if ext in (".docx",):
            return _docx_to_markdown(contents)
        if ext in (".txt", ".md", ".markdown"):
            text = contents.decode("utf-8", errors="replace").strip()
            if not text:
                return None
            # 1.6.0：TXT 直通时 Markdown 会把单换行当空格——整篇粘成一段。
            # 按论文阅读习惯重组：空行分段、段内续行、行尾空格清理。
            from app.modules.submission.markdown_clean import reflow_paragraphs

            return reflow_paragraphs(text) or None
        # .doc / .ps / .zip：不转换（阅读器回退 PDF 视图）。
        logger.info("manuscript_convert_skipped reason=unsupported ext=%s", ext)
        return None
    except Exception:
        # 转换是增值能力：损坏/加密/超纲的输入一律静默降级。
        logger.warning("manuscript_convert_failed ext=%s", ext, exc_info=True)
        return None


def markdown_storage_key(file_path: str) -> str:
    path = Path(file_path)
    if path.suffix.lower() == _MD_SUFFIX:
        return f"{file_path}.derived.md".replace("\\", "/")
    return str(path.with_suffix(_MD_SUFFIX)).replace("\\", "/")


__all__ = ["convert_to_markdown", "markdown_storage_key"]
