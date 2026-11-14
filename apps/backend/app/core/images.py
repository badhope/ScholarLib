"""Shared image upload rules for user-generated content.

论坛、投稿正文、后续的评论/消息都只接受浏览器能直接显示的四种位图。
SVG 不能收——SVG 可带脚本和外部引用，不能和正文 Markdown 共享同源执行权限。
"""

from __future__ import annotations

import re

IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGE_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
IMAGE_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp)$")
IMAGE_EXT_MIME = {ext.lstrip("."): mime for mime, ext in IMAGE_MIME_EXT.items()}
IMAGE_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def image_magic_ok(contents: bytes, mime: str) -> bool:
    """Check the file signature, not just the client-declared MIME."""
    if mime == "image/png":
        return contents.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return contents.startswith(b"\xff\xd8\xff")
    if mime == "image/gif":
        return contents.startswith((b"GIF87a", b"GIF89a"))
    if mime == "image/webp":
        return contents.startswith(b"RIFF") and contents[8:12] == b"WEBP"
    return False


def image_mime_for_name(filename: str) -> str:
    """Resolve MIME only for the four allowed extensions (or raise KeyError)."""
    return IMAGE_EXT_MIME[filename.rsplit(".", 1)[1]]
