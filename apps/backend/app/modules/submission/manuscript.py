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
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pymupdf

from app.modules.submission.fileformat import (
    FMT_DOC,
    FMT_DOCX,
    FMT_MARKDOWN,
    FMT_PDF,
    FMT_RTF,
    FMT_TEXT,
    detect_format,
)

logger = logging.getLogger(__name__)

_MD_SUFFIX = ".md"

# PDF 质量闸门阈值（P0）。任一不达标即标 needs_docx，绝不产出半截 Markdown。
_PDF_MIN_TEXT_CHARS = 300
_PDF_MIN_CJK_RATIO = 0.30  # 中文稿 CJK 占比下限
_PDF_MAX_BAD_CHAR_RATIO = 0.02  # 替换符/控制符占比上限
_PDF_MAX_REPEATED_LINE_RATIO = 0.30  # 连续重复页眉行占比上限
_PDF_MIN_AVG_PARAGRAPH_LEN = 10  # 段落平均长度下限（过碎=版面抽取异常）


@dataclass(frozen=True)
class ManuscriptResult:
    """稿件转换的结构化结果（P0）。

    - ``markdown`` 非空 = 可在线阅读；
    - ``needs_docx`` 为真 = 不可在线阅读，``reason`` 给出具体原因，
      前端应引导作者另存为 .docx，**不得**回退 pdf.js 渲染；
    - ``actual_format`` 为文件头判定的真实格式；
    - ``extension_mismatch`` 为真时上传结果需提示"扩展名与实际格式不一致"。
    """

    markdown: str | None
    actual_format: str
    extension_mismatch: bool
    needs_docx: bool = False
    reason: str | None = None


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


def _pdf_raw_text(contents: bytes) -> str:
    """抽取 PDF 纯文本（用于质量闸门）。不做版面重排，逐页拼接即可。"""
    doc = pymupdf.open(stream=contents, filetype="pdf")
    try:
        if doc.is_encrypted:
            return ""
        parts = [page.get_text("text") for page in doc]
        return "\n".join(parts)
    finally:
        doc.close()


def _pdf_quality_gate(text: str) -> tuple[bool, str | None]:
    """PDF 质量闸门：任一不达标返回 (False, 具体原因)。

    - 抽取文本 < 300 字符        → 无文本层（扫描件/图片 PDF）
    - 中文稿 CJK 占比 < 30%      → 乱码/外文稿
    - 替换符/控制符 ≥ 2%         → 乱码超标
    - 重复页眉行 ≥ 30%           → 页眉噪声污染
    - 段落平均长度 < 10         → 版面抽取过碎
    """
    stripped = (text or "").strip()
    if len(stripped) < _PDF_MIN_TEXT_CHARS:
        return False, "无文本层或文本过少（疑似扫描件/图片 PDF），请另存为 .docx 后重新上传"

    cjk = sum(1 for ch in stripped if "\u4e00" <= ch <= "\u9fff")
    if cjk > 0:
        ratio = cjk / max(len(stripped), 1)
        if ratio < _PDF_MIN_CJK_RATIO:
            return False, f"中文占比过低（{ratio:.0%}），疑似乱码，请另存为 .docx 后重新上传"

    bad = sum(
        1 for ch in stripped if ch == "\ufffd" or (ord(ch) < 32 and ch not in "\n\r\t")
    )
    if bad / max(len(stripped), 1) >= _PDF_MAX_BAD_CHAR_RATIO:
        return False, "乱码/控制符占比过高，请另存为 .docx 后重新上传"

    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    if lines:
        repeated = sum(c for c in Counter(lines).values() if c > 1)
        if repeated / len(lines) > _PDF_MAX_REPEATED_LINE_RATIO:
            return False, "重复页眉行占比过高，请另存为 .docx 后重新上传"

    paras = [p for p in re.split(r"\n\s*\n", stripped) if p.strip()]
    if paras:
        avg = sum(len(p) for p in paras) / len(paras)
        if avg < _PDF_MIN_AVG_PARAGRAPH_LEN:
            return False, "段落过碎，疑似版面抽取异常，请另存为 .docx 后重新上传"

    return True, None


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


def _normalize_markdown(md: str) -> str:
    """排印统一：标题编号补空格、图表题注独立、中英混排间距、断行表格补管、
    连续空行折叠；剔除孤立代理对。规则幂等，重复上传不会二次漂移。"""
    from app.modules.submission.normalize import normalize_markdown

    result = normalize_markdown(md)
    return re.sub(r"[\ud800-\udfff]", "", result)


def convert_manuscript(contents: bytes, filename: str) -> ManuscriptResult:
    """结构化转换（P0）：按文件头分流，失败给具体原因而不是 None。

    返回 ``ManuscriptResult``：``markdown`` 可在线阅读；``needs_docx`` 为真
    时 ``reason`` 说明为什么不能在线阅读（加密/扫描件/老 .doc/乱码…）。
    """
    try:
        result = _convert_manuscript_inner(contents, filename)
    except Exception:
        logger.warning("manuscript_convert_failed filename=%s", filename, exc_info=True)
        return ManuscriptResult(
            markdown=None,
            actual_format="unknown",
            extension_mismatch=False,
            needs_docx=True,
            reason="文件损坏或无法解析，请另存为 .docx 后重新上传",
        )
    if result.markdown:
        try:
            md = _normalize_markdown(result.markdown)
        except Exception:
            logger.warning("manuscript_normalize_failed", exc_info=True)
            return result
        return ManuscriptResult(
            markdown=md,
            actual_format=result.actual_format,
            extension_mismatch=result.extension_mismatch,
            needs_docx=False,
            reason=None,
        )
    return result


def convert_to_markdown(contents: bytes, filename: str) -> str | None:
    """尽力把上传稿件转成 Markdown；不支持或失败一律返回 None。

    保留此签名以兼容历史调用方与既有测试；新代码请用
    :func:`convert_manuscript` 拿到 needs_docx 原因。
    """
    return convert_manuscript(contents, filename).markdown


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


def _needs_docx(actual: str, mismatch: bool, reason: str) -> ManuscriptResult:
    return ManuscriptResult(
        markdown=None,
        actual_format=actual,
        extension_mismatch=mismatch,
        needs_docx=True,
        reason=reason,
    )


def _convert_manuscript_inner(contents: bytes, filename: str) -> ManuscriptResult:
    """按文件头分流的核心转换（P0）。"""
    detected = detect_format(contents, filename)
    actual = detected.actual
    mismatch = detected.extension_mismatch

    if actual == FMT_PDF:
        # 1) 先跑质量闸门：加密/扫描件/乱码一律 needs_docx，不进版面重排。
        try:
            probe = pymupdf.open(stream=contents, filetype="pdf")
        except Exception:
            return _needs_docx(actual, mismatch, "文件损坏或不是有效 PDF，请另存为 .docx 后重新上传")
        try:
            if probe.is_encrypted:
                return _needs_docx(actual, mismatch, "加密 PDF，无法抽取文本，请另存为 .docx 后重新上传")
            raw_text = "\n".join(page.get_text("text") for page in probe)
        finally:
            probe.close()
        ok, reason = _pdf_quality_gate(raw_text)
        if not ok:
            return _needs_docx(actual, mismatch, reason)
        # 2) 闸门通过才做版面重排（pymupdf4llm）。
        md = _pdf_to_markdown(contents)
        if not md:
            return _needs_docx(actual, mismatch, "PDF 版面抽取失败，请另存为 .docx 后重新上传")
        from app.modules.submission.markdown_clean import clean

        md = clean(md)
        if not md:
            return _needs_docx(actual, mismatch, "PDF 抽取结果为空，请另存为 .docx 后重新上传")
        return ManuscriptResult(
            markdown=md, actual_format=actual, extension_mismatch=mismatch
        )

    if actual == FMT_DOCX:
        md = _docx_to_markdown(contents)
        if not md:
            return _needs_docx(actual, mismatch, "Word 文档解析失败，文件可能损坏，请另存为 .docx 后重新上传")
        return ManuscriptResult(markdown=md, actual_format=actual, extension_mismatch=mismatch)

    if actual == FMT_DOC:
        # 老式 OLE2 二进制 Word：明确拒绝，不静默回退。
        return _needs_docx(actual, mismatch, "检测到老式 .doc 二进制格式，请在 Word 中另存为 .docx 后重新上传")

    if actual == FMT_RTF:
        return _needs_docx(actual, mismatch, "检测到 RTF 格式，请另存为 .docx 后重新上传")

    if actual in (FMT_MARKDOWN, FMT_TEXT):
        text = contents.decode("utf-8", errors="replace").strip()
        if not text:
            return _needs_docx(actual, mismatch, "文件为空，请上传含正文的稿件")
        from app.modules.submission.markdown_clean import reflow_paragraphs

        md = reflow_paragraphs(text)
        if not md:
            return _needs_docx(actual, mismatch, "未能从文本中解析出正文")
        return ManuscriptResult(markdown=md, actual_format=actual, extension_mismatch=mismatch)

    return _needs_docx(actual, mismatch, "无法识别文件格式，请另存为 .docx 后重新上传")


async def convert_manuscript_async(
    contents: bytes, filename: str, *, timeout: float = CONVERT_TIMEOUT_SECONDS
) -> ManuscriptResult:
    """``convert_manuscript`` 的异步安全版本（线程池 + 硬超时）。

    超时/异常返回 needs_docx 结果，而不是让调用方拿到 None 后悄悄回退。
    """
    import asyncio

    import anyio

    def _run() -> ManuscriptResult:
        return convert_manuscript(contents, filename)

    try:
        return await asyncio.wait_for(anyio.to_thread.run_sync(_run), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        logger.warning(
            "manuscript_convert_timeout filename=%s bytes=%s timeout=%ss",
            filename,
            len(contents),
            timeout,
        )
        return ManuscriptResult(
            markdown=None,
            actual_format="pdf",
            extension_mismatch=False,
            needs_docx=True,
            reason="转换超时，请另存为 .docx 后重新上传",
        )
    except Exception:
        logger.warning("manuscript_convert_async_failed", exc_info=True)
        return ManuscriptResult(
            markdown=None,
            actual_format="unknown",
            extension_mismatch=False,
            needs_docx=True,
            reason="转换失败，请另存为 .docx 后重新上传",
        )


def markdown_storage_key(file_path: str) -> str:
    path = Path(file_path)
    if path.suffix.lower() == _MD_SUFFIX:
        return f"{file_path}.derived.md".replace("\\", "/")
    return str(path.with_suffix(_MD_SUFFIX)).replace("\\", "/")


def needs_docx_storage_key(file_path: str) -> str:
    """needs_docx 原因侧car key：``{file_path}.needs_docx``。"""
    return f"{file_path}.needs_docx".replace("\\", "/")


__all__ = [
    "ManuscriptResult",
    "convert_manuscript",
    "convert_manuscript_async",
    "convert_to_markdown",
    "markdown_storage_key",
    "needs_docx_storage_key",
]
