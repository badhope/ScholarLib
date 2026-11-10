"""文件格式识别（按文件头魔数，不看扩展名）。

P0 重构的核心校正：此前 ``convert_to_markdown`` 按扩展名分流，
一份把内容改成 PDF 却叫 ``.docx`` 的文件会被当成 docx 喂给 mammoth 直接
失败，前端静默回退 PDF。现在一律先看文件头：

- ``%PDF-``                → PDF
- ``PK\\x03\\x04`` + 包内含 ``[Content_Types].xml`` → docx（OOXML）
- ``\\xd0\\xcf\\x11\\xe0`` → 老式 OLE2 复合文档（.doc / .xls）
- ``{\\rtf``               → RTF
- 其余按可打印文本比例判断 text / markdown

扩展名只用于**提示**不一致（``extension_mismatch``），绝不决定解析通道。
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass
from typing import Final

# 识别出的实际格式取值。文本类细分到 text/markdown，便于阅读端按 Markdown 直读。
FMT_PDF: Final = "pdf"
FMT_DOCX: Final = "docx"
FMT_DOC: Final = "doc"
FMT_RTF: Final = "rtf"
FMT_MARKDOWN: Final = "markdown"
FMT_TEXT: Final = "text"
FMT_UNKNOWN: Final = "unknown"

# 扩展名 → 期望格式表。仅用于比对"扩展名与实际是否一致"，不用于分流。
_EXT_EXPECT: Final[dict[str, str]] = {
    ".pdf": FMT_PDF,
    ".docx": FMT_DOCX,
    ".doc": FMT_DOC,
    ".rtf": FMT_RTF,
    ".markdown": FMT_MARKDOWN,
    ".md": FMT_MARKDOWN,
    ".txt": FMT_TEXT,
}

_OLE2_MAGIC: Final = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_RTF_MAGIC: Final = b"{\\rtf"


@dataclass(frozen=True)
class DetectedFormat:
    """文件头识别结果。

    ``actual`` 为按内容判定的真实格式；``extension_mismatch`` 为 True 时
    说明扩展名暗示的格式与真实格式不一致（上传结果需提示作者）。
    """

    actual: str
    extension_mismatch: bool
    expected_from_extension: str | None


def _looks_like_text(contents: bytes) -> bool:
    """粗判是否为可打印文本（避免把二进制当文本读成乱码）。"""
    if not contents:
        return False
    # 取前 4KB 采样即可：二进制文件在前几个字节就会出现高比例的 NUL/控制符。
    sample = contents[:4096]
    if b"\x00" in sample:
        return False
    control = sum(1 for b in sample if b < 9 or (13 < b < 32))
    return control / len(sample) < 0.05


def detect_format(contents: bytes, filename: str = "") -> DetectedFormat:
    """按文件头判定真实格式，并与扩展名做一致性比对。"""
    actual: str
    if contents.startswith(b"%PDF-"):
        actual = FMT_PDF
    elif contents.startswith(_OLE2_MAGIC):
        actual = FMT_DOC
    elif contents.startswith(_RTF_MAGIC):
        actual = FMT_RTF
    elif contents.startswith(b"PK\x03\x04"):
        # ZIP 容器：OOXML（docx/xlsx/pptx）都长这样。靠包内
        # ``[Content_Types].xml`` 这一 OOXML 签名区分 docx 与普通 zip。
        actual = FMT_UNKNOWN
        try:
            with zipfile.ZipFile(io.BytesIO(contents)) as zf:
                names = zf.namelist()
            if "[Content_Types].xml" in names:
                # 进一步区分：xlsx/pptx 也有该文件。稿件通道只关心 docx。
                has_docx = any(n.startswith("word/") for n in names) or any(
                    "wordprocessingml" in n.lower() for n in names
                )
                actual = FMT_DOCX if has_docx else FMT_UNKNOWN
        except (zipfile.BadZipFile, ValueError):
            actual = FMT_UNKNOWN
    elif _looks_like_text(contents):
        # Markdown 以 # 标题 / --- 分隔 / front-matter 为信号；其余按纯文本。
        head = contents[:4096].decode("utf-8", errors="replace")
        actual = FMT_MARKDOWN if re.search(r"(?m)^(#{1,6}\s|---\s*$|```)", head) else FMT_TEXT
    else:
        actual = FMT_UNKNOWN

    ext = os.path.splitext(filename or "")[1].lower()
    expected = _EXT_EXPECT.get(ext)
    mismatch = bool(expected) and expected != actual
    return DetectedFormat(
        actual=actual, extension_mismatch=mismatch, expected_from_extension=expected
    )


__all__ = [
    "FMT_DOC",
    "FMT_DOCX",
    "FMT_MARKDOWN",
    "FMT_PDF",
    "FMT_RTF",
    "FMT_TEXT",
    "FMT_UNKNOWN",
    "DetectedFormat",
    "detect_format",
]
