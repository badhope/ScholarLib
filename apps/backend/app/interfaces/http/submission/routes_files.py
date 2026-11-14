"""Submission API routes — 文件上传与下载（作者/编辑/审稿人）。

从 routes.py（52KB 单文件）拆出。router 来自 routes.py，本模块在其上
追加端点；注册顺序见 routes.py 文件末尾的底部 import。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import mimetypes
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_current_user_optional,
    user_has_editor_access,
)
from app.core.db import get_db
from app.core.storage import get_storage
from app.domain.review.models import ReviewAssignment
from app.domain.submission._helpers import _try_delete_storage
from app.interfaces.http.submission.responses import _get_or_404, _to_response
from app.interfaces.http.submission.routes import router
from app.interfaces.http.submission.schemas import SubmissionResponse
from app.models import User

# 扩展名白名单：字母数字加点，最多 12 字符（``.markdown`` 9 个）。
# 严格到这种程度是刻意的——这个值会进入存储 key 和下载响应头，
# 任何引号、分号、CR/LF 都会在那里变成注入面。
_EXT_PATTERN = re.compile(r"^\.[A-Za-z0-9]{1,12}$")


def _safe_extension(filename: str) -> str:
    """从用户文件名提取可安全用于存储 key 与响应头的扩展名。

    不合规一律返回空串（丢弃扩展名），而不是截断或转义：截断可能留下
    半个控制字符序列，转义又会在下载文件名里出现奇怪的百分号。丢扩展名
    的代价只是 MIME 猜不准，而猜不准有 ``application/octet-stream`` 兜底。
    """
    ext = os.path.splitext(filename or "")[1]
    return ext if _EXT_PATTERN.match(ext) else ""


def _content_disposition(filename: str, *, inline: bool = False) -> str:
    """构造下载响应头，含 ASCII 回退与 RFC 5987 的 UTF-8 文件名。

    只用 ASCII 回退会让中文标题变成乱码，只用 RFC 5987 又会让老客户端
    拿不到文件名，所以两个都给（现代浏览器优先 ``filename*``）。
    """
    from urllib.parse import quote

    ascii_name = (
        "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in filename)
        or "download"
    )
    encoded = quote(filename, safe="")
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


_ALLOWED_UPLOAD_MIMES = frozenset(
    {
        # 稿件本体：PDF / Word / 纯文本 / Markdown / LaTeX 源文件 / PostScript
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/postscript",
        "text/plain",
        "text/markdown",
        "text/x-markdown",
        "application/x-tex",
        "application/x-latex",
        # 富文本与幻灯片：审稿人常收到 .rtf / .odt / .pptx
        "application/rtf",
        "text/rtf",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        # 表格与数据：附录与可复现材料
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "application/json",
        "application/x-bibtex",
        # 图表：单独提交的高分辨率图（期刊常要求 300dpi 独立图文件）
        "image/png",
        "image/jpeg",
        "image/svg+xml",
        "image/tiff",
        # 代码与材料：源码压缩包、补充材料、Jupyter notebook
        "application/zip",
        "application/x-zip-compressed",
        "application/gzip",
        "application/x-tar",
        "application/x-7z-compressed",
        "application/x-ipynb+json",
    }
)
# 单文件 50 MB 上限：足够容纳 300 dpi 图集与源码包，又不会让上传走满
# 整个请求超时窗口。前端从 /capabilities 读取同一数值，避免两边写死不一致。
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# 前端 accept 属性与错误文案共用这份扩展名清单（由 /capabilities 下发）。
_ALLOWED_UPLOAD_EXTENSIONS = (
    ".docx .doc .pdf .odt .rtf .txt .md .tex .ps "
    ".pptx .xls .xlsx .csv .json .bib "
    ".png .jpg .jpeg .svg .tif .tiff "
    ".zip .gz .tar .7z .ipynb"
).split()


async def _read_upload_for_conversion(file: UploadFile) -> tuple[bytes, str, str]:
    """校验上传并读取字节，返回 (contents, original_filename, actual_format)。

    只用于“提交前识别 / 原文件预览”两个无数据库端点，不落盘、不建稿件。
    与正式上传共用同一扩展名白名单和 50MB 上限。
    """
    upload_name = file.filename or "upload"
    upload_ext = os.path.splitext(upload_name)[1].lower()
    if upload_ext not in set(_ALLOWED_UPLOAD_EXTENSIONS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {upload_ext or 'no extension'}",
        )
    contents = b""
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        contents += chunk
        if len(contents) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
            )
    from app.domain.submission.fileformat import detect_format

    detected = detect_format(contents, upload_name)
    return contents, upload_name, detected.actual


@router.post("/convert-preview")
async def convert_submission_preview(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """提交前把 Word/PDF 识别成 Markdown，回填编辑器。

    以前作者选完文件后，转换要到“提交成功”才在后台发生，编辑器仍是空的；
    作者无法校对识别结果。这里在选文件当下就跑同一条 ``convert_manuscript``
    管线，把 Markdown 返回给表单；正式提交时仍由上传端点再转换一次并落库，
    两次使用同一实现，不引入第二套解析口径。
    """
    from app.domain.submission.manuscript import convert_manuscript_async

    contents, original_filename, actual_format = await _read_upload_for_conversion(file)
    result = await convert_manuscript_async(contents, original_filename)
    warnings: list[str] = []
    if result.extension_mismatch:
        warnings.append("扩展名与实际格式不一致（已按文件头识别）")
    if result.needs_docx:
        warnings.append(result.reason or "无法识别为可编辑正文，请另存为 .docx 后重试")
    return {
        "markdown": result.markdown or "",
        "warnings": warnings,
        "actual_format": actual_format,
        "extension_mismatch": result.extension_mismatch,
        "needs_docx": result.needs_docx,
        "reason": result.reason,
    }


def _source_preview_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "rubbish-source-preview"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _uploaded_file_to_pdf(file: UploadFile) -> bytes:
    """与 /source-preview 同一条转换口径：PDF 原样、DOCX 转 PDF。"""
    from app.domain.submission.export_docs import docx_to_pdf

    contents, _original_filename, actual_format = await _read_upload_for_conversion(file)
    if actual_format == "pdf":
        return contents
    if actual_format == "docx":
        try:
            return await asyncio.to_thread(docx_to_pdf, contents)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Word 原件转 PDF 失败：{exc}",
            ) from exc
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="原件预览只支持 PDF / DOCX；老式 .doc、RTF 请先另存为 .docx。",
    )


@router.post("/source-preview/pages")
async def preview_uploaded_source_pages(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """提交前原件预览：先落一份 PDF，返回分页 PNG 的 token 与页数。

    和发表版文章页的「PDF 版式预览」走同一条分页 PNG 渲染链路，不再让
    投稿页单独跑 pdf.js。页面图片由下面的 GET 端点按需渲染，避免一次
    返回几十张大图。
    """
    import pymupdf

    pdf_bytes = await _uploaded_file_to_pdf(file)
    token = hashlib.sha256(b"srcprev:" + pdf_bytes).hexdigest()[:32]
    cache_path = _source_preview_dir() / f"{token}.pdf"
    if not cache_path.exists():
        temp_path = cache_path.with_suffix(".tmp")
        temp_path.write_bytes(pdf_bytes)
        temp_path.replace(cache_path)
    with pymupdf.open(cache_path) as document:
        pages = document.page_count
    return {"token": token, "pages": pages}


@router.get("/source-preview/{token}.pdf")
async def preview_uploaded_source_pdf(token: str) -> Response:
    """token 对应的预览 PDF，供“直接下载原件”兜底。"""
    from fastapi.responses import FileResponse

    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview not found")
    cache_path = _source_preview_dir() / f"{token}.pdf"
    if not cache_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview not found")
    return FileResponse(
        cache_path,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="source-preview.pdf"'},
    )


@router.get("/source-preview/{token}/{page}.png")
async def preview_uploaded_source_page(token: str, page: int) -> Response:
    """按需把缓存的预览 PDF 渲染成分页 PNG。"""
    import pymupdf

    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview not found")
    cache_path = _source_preview_dir() / f"{token}.pdf"
    if not cache_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview not found")
    try:
        with pymupdf.open(cache_path) as document:
            if page < 1 or page > document.page_count:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")
            pixmap = document[page - 1].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
            png = pixmap.tobytes("png")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"原件分页渲染失败：{exc}",
        ) from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=600"},
    )


@router.post("/source-preview")
async def preview_uploaded_source(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> Response:
    """把作者上传的 Word/PDF 原样转成 PDF 流，用于提交前“原件预览”。

    这是识别结果的对照视图：用户能看到 Word 里真实排版/图片，再检查
    Markdown 是否漏段、错序或丢图。只接受 PDF / DOCX；老式 .doc 与 RTF
    返回明确错误，不静默换成别的格式。
    """
    from app.domain.submission.export_docs import docx_to_pdf

    contents, _original_filename, actual_format = await _read_upload_for_conversion(file)
    if actual_format == "pdf":
        pdf_bytes = contents
    elif actual_format == "docx":
        try:
            pdf_bytes = await asyncio.to_thread(docx_to_pdf, contents)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Word 原件转 PDF 失败：{exc}",
            ) from exc
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="原件预览只支持 PDF / DOCX；老式 .doc、RTF 请先另存为 .docx。",
        )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="source-preview.pdf"'},
    )


@router.post(
    "/{submission_id}/files",
    response_model=SubmissionResponse,
)
async def upload_submission_file(
    submission_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """作者上传稿件 PDF（替换式：重复上传会覆盖 file_path）。

    限制：
    - 仅作者本人
    - submission 必须处于 pending / under_review / major_revision / minor_revision
      （under_review 允许是为了让编辑要求作者替换稿件时仍能上传）
    - accepted / rejected 终态下不可上传
    - MIME 必须在白名单内
    - 大小 ≤ 50 MB
    - 文件名经过 path 安全检查（防 ../ 穿越）
    """
    entry = await _get_or_404(db, submission_id)
    if entry.submitted_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the submitter can upload files",
        )
    if entry.status not in (
        "pending",
        "under_review",
        "major_revision",
        "minor_revision",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot upload files in status '{entry.status}'",
        )
    # MIME 白名单 + 扩展名兜底：浏览器对 .md/.tex/.csv/.ipynb 报的
    # content-type 千奇百怪（从 application/octet-stream 到空串都有），
    # 只认 MIME 会把合法稿件拒之门外。扩展名命中即放行。
    upload_name = file.filename or "upload"
    upload_ext = os.path.splitext(upload_name)[1].lower()
    mime_ok = file.content_type in _ALLOWED_UPLOAD_MIMES
    ext_ok = upload_ext in set(_ALLOWED_UPLOAD_EXTENSIONS)
    if not (mime_ok or ext_ok):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type: {file.content_type or 'unknown'} "
                f"({upload_ext or 'no extension'}). "
                f"Accepted: {' '.join(_ALLOWED_UPLOAD_EXTENSIONS)}"
            ),
        )

    # 流式读 + 大小校验，避免一次性 OOM
    contents = b""
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        contents += chunk
        if len(contents) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit. "
                    "Put large datasets or repositories on a hosting service and paste "
                    "the link into the submission form instead."
                ),
            )

    # 存储 key：{tenant_id}/{submission_id}/{uuid}{ext}
    # 用 uuid 防文件名碰撞 + 路径穿越；本地/S3 后端共用同一 key 形状，
    # 切换后端无需迁移数据库。
    #
    # 扩展名必须严格白名单化，不能只截长度：
    # ``os.path.splitext('paper.pdf"\r\nX-Injected: 1')`` 得到
    # ``.pdf"\r\nX-Injected: 1``（20 字符，恰好躲过下面的截断），于是
    # CRLF 与控制字符会进入存储 key，并在下载时被原样拼进
    # ``Content-Disposition``——轻则响应头注入（响应拆分），重则 h11 抛
    # LocalProtocolError 让该文件永久 500。同一仓库的
    # ``catalog._download_name`` 早就做了字符白名单，这里对齐它。
    original_filename = file.filename or "upload"
    ext = _safe_extension(original_filename)
    safe_name = f"{uuid4().hex}{ext}"
    rel_path = f"{entry.tenant_id}/{entry.id}/{safe_name}"
    old_path = entry.file_path  # 可能为 None（首次上传）
    if old_path == rel_path:  # uuid 碰撞极不可能，但保险起见跳过自删
        old_path = None
    # 浏览器常常不带 content-type（.md/.tex），此时按扩展名回填一份，
    # 否则存储层会把它标成二进制，之后下载头也猜不出正确类型。
    stored_type = (
        file.content_type
        or mimetypes.guess_type(original_filename)[0]
        or "application/octet-stream"
    )
    await get_storage().save(rel_path, contents, content_type=stored_type)
    entry.file_path = rel_path

    # 在线阅读用 Markdown：按文件头识别格式，质量闸门不达标则标 needs_docx
    # （写侧car 原因），不再静默回退 PDF 视图。
    from app.domain.submission.clc import parse_clc
    from app.domain.submission.manuscript import (
        convert_manuscript_async,
        markdown_storage_key,
        needs_docx_storage_key,
    )

    old_md = entry.markdown_path
    old_sidecar = needs_docx_storage_key(rel_path)
    # 转换放到工作线程并带硬超时：pymupdf4llm 解析一份 50MB PDF 是数秒
    # 到数分钟的纯 CPU 工作，直接 await 会把整个事件循环（所有租户、
    # 所有请求，含 /health）一起卡死。
    result = await convert_manuscript_async(contents, original_filename)
    warnings: list[str] = []
    if result.extension_mismatch:
        warnings.append("扩展名与实际格式不一致（已按文件头识别）")
    if result.needs_docx or not result.markdown:
        entry.markdown_path = None
        reason = result.reason or "无法在线阅读，请下载原件"
        # 把具体原因落侧car，阅读端点据此明确告知"不可在线阅读 + 可下载原件"。
        await get_storage().save(
            old_sidecar,
            reason.encode("utf-8"),
            content_type="text/plain; charset=utf-8",
        )
        if result.reason:
            warnings.append(result.reason)
    else:
        md_key = markdown_storage_key(rel_path)
        await get_storage().save(
            md_key, result.markdown.encode("utf-8"), content_type="text/markdown"
        )
        entry.markdown_path = md_key
        # 清除可能存在的旧 needs_docx 侧car（重新上传成功）。
        await _try_delete_storage(old_sidecar)
        # 从正文 front-matter 解析中图分类号；非法值原样保留并标待校正。
        clc = parse_clc(result.markdown)
        if clc.code:
            entry.clc_code = clc.code
            entry.clc_label = clc.label
            if clc.status == "needs_correction":
                warnings.append(f"中图分类号 {clc.code} 格式待校正")

    await db.commit()
    await db.refresh(entry)
    # 替换式上传会覆盖 file_path，被替换的旧文件（及旧 md/侧car）若不清会变成孤儿对象。
    await _try_delete_storage(old_path)
    await _try_delete_storage(old_md)

    resp = _to_response(entry)
    # 结构报告：作者上传后立刻知道"离《投稿规范》还差什么"，而不是等
    # 编辑部初审退修。转换失败（无 md）就不报——没有内容可分析。
    if result.markdown:
        from app.domain.submission.markdown_clean import analyze_structure

        resp.format_report = analyze_structure(result.markdown)  # type: ignore[assignment]
    if warnings:
        resp.upload_warnings = warnings
    return resp


@router.post("/{submission_id}/cover", response_model=SubmissionResponse)
async def upload_submission_cover(
    submission_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """作者上传封面图（替换式）。

    为什么允许作者自选封面：本刊是双赛道期刊，荒诞稿的封面往往就是
    作品的一部分（一张梗图胜过一千字摘要）。不给作者这个入口，所有
    文章只能长成同一个样子。

    限制：仅作者本人；仅图片格式；≤5MB。未上传时前端按学科自动分配
    默认封面（covers.json 的精选图库），所以封面永远不为空。
    """
    entry = await _get_or_404(db, submission_id)
    if entry.submitted_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the submitter can upload a cover",
        )
    if entry.status in ("accepted", "approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot change cover in status '{entry.status}'",
        )

    mime = (file.content_type or "").lower()
    if mime not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="封面仅支持 PNG / JPEG / WebP",
        )
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="封面图不能超过 5MB",
        )
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime]
    key = f"{entry.tenant_id}/{entry.id}/cover-{uuid4().hex}{ext}"
    await get_storage().save(key, contents, content_type=mime)

    old = entry.cover_image
    entry.cover_image = key
    await db.commit()
    await db.refresh(entry)
    await _try_delete_storage(old)
    return _to_response(entry)


def _anonymized_markdown(md: str) -> str:
    """Remove author-identifying blocks from a submission Markdown.

    Two layouts exist in the corpus:
    * title/author block before the first ``##`` section (328-style);
    * a dedicated ``## 作者信息`` section after the title (329-style).

    Both must be removed.  The generated Word document writes its own title
    page from metadata, so retaining those raw lines would leak identity into
    the reviewer's download.
    """
    lines = md.splitlines()

    # Layout 2: remove author/affiliation/funding/acknowledgement sections
    # wherever they occur (normally immediately after the title).
    drop_section = re.compile(
        r"^#{1,6}\s*(作者信息|作者简介|作者贡献|通信作者|通讯作者|基金项目|致谢)\b",
        re.I,
    )
    cleaned: list[str] = []
    skipping = False
    for line in lines:
        if drop_section.match(line.strip()):
            skipping = True
            continue
        if skipping and re.match(r"^#{1,6}\s+", line.strip()):
            skipping = False
        if not skipping:
            cleaned.append(line)

    # Layout 1: drop textual lines before the first real body heading, but
    # keep figures that legitimately precede it.
    first_heading = next(
        (i for i, line in enumerate(cleaned) if re.match(r"^#{1,6}\s+", line.strip())),
        None,
    )
    if first_heading is not None:
        prefix = cleaned[:first_heading]
        kept = [line for line in prefix if line.strip().startswith("![")]
        cleaned = kept + cleaned[first_heading:]

    # Inline fallback for lines that survived a non-standard author block.
    author_line = re.compile(
        r"(第一作者|合作者|通讯作者|通信作者|作者简介|作者单位|邮箱|ORCID|"
        r"E-?mail|@)[：:]?",
        re.I,
    )
    body = "\n".join(line for line in cleaned if not author_line.search(line))
    body = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[邮箱已隐藏]", body)
    body = re.sub(r"\b1[3-9]\d{9}\b", "[手机号已隐藏]", body)
    return body


def _strip_leading_title(md: str, title: str) -> str:
    """Drop a Markdown ``# Title`` line that duplicates the metadata title."""
    if not title:
        return md
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        m = re.match(r"^#{1,2}\s+(.+)$", line.strip())
        if m and re.sub(r"[*_`]", "", m.group(1)).strip() == title.strip():
            del lines[i]
        break
    return "\n".join(lines)


def _redact_identity_text(
    text: str, entry: Any, *, names: list[Any] | None = None, affiliations: list[Any] | None = None
) -> str:
    """Remove author names/affiliations from metadata fields and prose.

    The body anonymizer only drops author blocks; on 322 the author's pen name
    appears in the abstract itself ("Zabwerk 在备课的时候…").  The generated
    Word writes ``meta.abstract`` separately, so it must be scrubbed too.
    """
    if not text:
        return text
    names = list(names if names is not None else (getattr(entry, "authors", None) or []))
    affiliations = list(
        affiliations if affiliations is not None else (getattr(entry, "affiliations", None) or [])
    )
    for name in names:
        name = str(name).strip()
        if not name:
            continue
        # Two-letter Latin names are too ambiguous to replace globally.
        if re.fullmatch(r"[A-Za-z .'-]{2,}", name) and len(name) < 3:
            continue
        text = re.sub(re.escape(name), "作者", text, flags=re.I)
    for aff in affiliations:
        aff = str(aff).strip()
        if len(aff) >= 4:
            text = re.sub(re.escape(aff), "作者单位", text, flags=re.I)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[邮箱已隐藏]", text)
    text = re.sub(r"\b1[3-9]\d{9}\b", "[手机号已隐藏]", text)
    return text


async def _generated_download(
    entry: Any,
    output_format: str,
    *,
    anonymized: bool,
    resource: Any = None,
    inline: bool = False,
) -> Response:
    """Build a submission download from its Markdown.

    Default format is Word.  This is also the double-blind path: instead of
    refusing the reviewer because no editor-uploaded anonymized PDF exists, we
    render an anonymized Word/PDF directly from the stored Markdown.
    """
    if not entry.markdown_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This submission has no online manuscript to generate a download from",
        )

    storage = get_storage()
    try:
        raw = await storage.load(entry.markdown_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored manuscript is missing",
        ) from exc

    # Published resources carry the calibrated title/abstract/keywords that the
    # web article and the public /export use.  A submission's own abstract can
    # still be the pre-normalization version (299 is the proof), so prefer the
    # resource metadata whenever the submission has been linked to one.
    canonical_title = getattr(resource, "title", None) or entry.title or ""
    canonical_abstract = (
        getattr(resource, "abstract", None) or getattr(entry, "abstract", None) or ""
    )
    canonical_authors = list(
        getattr(resource, "authors", None) or getattr(entry, "authors", None) or []
    )
    canonical_affiliations = list(
        getattr(resource, "affiliations", None) or getattr(entry, "affiliations", None) or []
    )
    canonical_keywords = list(
        getattr(resource, "keywords", None) or getattr(entry, "keywords", None) or []
    )
    if resource is not None:
        canonical_keywords += list(getattr(resource, "tags", None) or [])

    md = raw.decode("utf-8", errors="replace")
    md = _strip_leading_title(md, canonical_title)
    if anonymized:
        md = _anonymized_markdown(md)
        md = _redact_identity_text(
            md,
            entry,
            names=canonical_authors,
            affiliations=canonical_affiliations,
        )
    else:
        # Even in a non-blind download, contact details must not be exposed in
        # the generated file; the site already masks them in article previews.
        md = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[邮箱已隐藏]", md)
        md = re.sub(r"\b1[3-9]\d{9}\b", "[手机号已隐藏]", md)

    from app.domain.submission.docx_template import build, parse_meta

    meta = parse_meta(md, fallback_title=canonical_title or f"submission-{entry.id}")
    meta.title = canonical_title or meta.title
    if anonymized:
        meta.authors = ["[双盲评审：作者信息已隐藏]"]
        meta.affiliations = []
    else:
        meta.authors = canonical_authors
        meta.affiliations = canonical_affiliations
    if canonical_abstract:
        meta.abstract = (
            _redact_identity_text(
                canonical_abstract,
                entry,
                names=canonical_authors,
                affiliations=canonical_affiliations,
            )
            if anonymized
            else canonical_abstract
        )
    if canonical_keywords:
        meta.keywords = canonical_keywords

    docx_bytes = await asyncio.to_thread(build, md, meta)

    if output_format == "pdf":
        from app.domain.submission.export_docs import docx_to_pdf

        payload = await asyncio.to_thread(docx_to_pdf, docx_bytes)
        media = "application/pdf"
        ext = "pdf"
    else:
        payload = docx_bytes
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ext = "docx"

    # The title goes into RFC 5987 filename*; _content_disposition supplies an
    # ASCII fallback, so Chinese names survive the browser download.
    base = re.sub(r'[\r\n"\\/:*?<>|]+', "-", canonical_title.strip())[:60].strip(" -")
    filename = (
        f"{base or f'submission-{entry.id}'}-{'anonymized' if anonymized else 'manuscript'}.{ext}"
    )

    return Response(
        content=payload,
        media_type=media,
        headers={"Content-Disposition": _content_disposition(filename, inline=inline)},
    )


_DOWNLOAD_TICKET_TTL = 600


def _download_ticket_secret() -> bytes:
    from app.core.config import get_settings

    key = get_settings().secret_key
    return key.encode("utf-8") if isinstance(key, str) else key


def _make_download_ticket(submission_id: int, user_id: int, file_format: str) -> str:
    """短时下载票据：移动端浏览器/下载器带不上 Authorization 头时用。

    票据只绑定稿件、用户、格式和到期时间，不携带用户密码或长期 token；
    泄露后最多 10 分钟内可下载同一份稿件，且不能调用其他接口。
    """
    expires = int(time.time()) + _DOWNLOAD_TICKET_TTL
    payload = f"{submission_id}:{user_id}:{file_format}:{expires}"
    signature = hmac.new(
        _download_ticket_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode("ascii")


def _verify_download_ticket(ticket: str, submission_id: int, file_format: str) -> int | None:
    try:
        decoded = base64.urlsafe_b64decode(ticket.encode("ascii")).decode("utf-8")
        payload, signature = decoded.rsplit(":", 1)
        parts = payload.split(":")
        if len(parts) != 4:
            return None
        ticket_submission, ticket_user, ticket_format, expires_s = parts
        expected = hmac.new(
            _download_ticket_secret(), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(ticket_submission) != submission_id or ticket_format != file_format:
            return None
        if int(expires_s) < int(time.time()):
            return None
        return int(ticket_user)
    except (ValueError, UnicodeDecodeError):
        return None


async def _can_access_submission_file(
    db: AsyncSession, entry: Any, user_id: int, user: User | None
) -> bool:
    if entry.submitted_by == user_id:
        return True
    if user is not None and await user_has_editor_access(db, user):
        return True
    assignment = (
        (
            await db.execute(
                select(ReviewAssignment).where(
                    ReviewAssignment.submission_id == entry.id,
                    ReviewAssignment.reviewer_id == user_id,
                    ReviewAssignment.status.in_(("pending", "accepted", "completed")),
                )
            )
        )
        .scalars()
        .first()
    )
    return assignment is not None


@router.post("/{submission_id}/download-ticket")
async def create_submission_download_ticket(
    submission_id: int,
    file_format: str = Query(default="pdf", alias="format", pattern="^(docx|pdf)$"),
    inline: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """给移动端换一条短时直链，避免 blob 下载在 iOS/微信里被撤销。"""
    entry = await _get_or_404(db, submission_id)
    if not entry.file_path and not entry.markdown_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This submission has no uploaded file or online manuscript",
        )
    if not await _can_access_submission_file(db, entry, current_user.id, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this submission file",
        )
    ticket = _make_download_ticket(entry.id, current_user.id, file_format)
    # 路径必须以 .pdf/.docx 结尾：微信内置浏览器按扩展名判断能否
    # 交给文件查看器/下载器；只靠 ?format=pdf 它经常当成网页不处理。
    return {
        "url": (
            f"/api/submissions/{entry.id}/files/{entry.id}.{file_format}"
            f"?inline={str(inline).lower()}&ticket={ticket}"
        )
    }


@router.get("/{submission_id}/files/{filename}")
async def download_submission_file_named(
    submission_id: int,
    filename: str,
    request: Request,
    ticket: str | None = Query(default=None),
    inline: bool = Query(default=False),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """带扩展名的同一下载口，专供微信识别 .pdf/.docx 文件。"""
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in (".pdf", ".docx"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unsupported file suffix",
        )
    return await download_submission_file(
        submission_id=submission_id,
        request=request,
        file_format=suffix[1:],
        ticket=ticket,
        inline=inline,
        current_user=current_user,
        db=db,
    )


@router.get("/{submission_id}/files")
async def download_submission_file(
    submission_id: int,
    request: Request,
    file_format: str = Query(default="docx", alias="format", pattern="^(docx|pdf|md)$"),
    ticket: str | None = Query(default=None),
    inline: bool = Query(default=False),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """下载稿件文件。

    这里补上了此前缺失的链路终点：稿件此前只能上传、无法取回，
    编辑与被指派的审稿人拿不到作者的 PDF，评审无从谈起。

    可访问方：
    - 作者本人
    - admin / editor
    - 该稿件的被指派审稿人（assignment 处于 pending/accepted/completed）

    S3 后端会尽量返回 302 预签名直链（省一次服务端带宽）；本地后端
    与预签名失败时改为服务端流式返回，权限校验始终发生在这里。
    """
    entry = await _get_or_404(db, submission_id)
    if not entry.file_path and not entry.markdown_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This submission has no uploaded file or online manuscript",
        )

    if current_user is not None:
        actor_id = current_user.id
        if not await _can_access_submission_file(db, entry, actor_id, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this submission file",
            )
    elif ticket is not None:
        # 票据换发时已经完整校验过权限；这里只验证 HMAC/绑定/到期，
        # 不再要求浏览器带 Authorization 头。票据 10 分钟失效。
        actor_id = _verify_download_ticket(ticket, entry.id, file_format) or 0
        if not actor_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Download ticket is invalid or expired",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # 作者/编辑可直接取回 Markdown 源文件（审稿人仍走匿名通道）。
    if file_format == "md" and (entry.file_path or entry.markdown_path):
        is_privileged_md = current_user is not None and (
            entry.submitted_by == current_user.id or await user_has_editor_access(db, current_user)
        )
        if is_privileged_md:
            # 作者上传的 .md 原件优先（保留原始换行/字节）；没有原件时
            # 退回规范化后的在线阅读 Markdown。
            path = (
                entry.file_path
                if entry.file_path and str(entry.file_path).lower().endswith(".md")
                else entry.markdown_path
            )
            if not path:
                raise HTTPException(status_code=404, detail="No markdown source")
            data = await get_storage().load(path)
            return Response(
                content=data,
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="submission-{entry.id}.md"'},
            )

    # 双盲评审：原始上传文件不能交给审稿人。
    #
    # 旧实现要求编辑先上传一条 ``anonymized_file_url``，否则直接 403；线上
    # ``review_mode=double_blind``，但 328/329 都没有匿名稿，于是审稿人连
    # 稿件都下载不了，整个评审流程卡死。现在改为**从 Markdown 现场生成**
    # 匿名 Word/PDF：不依赖外部 URL，也不会把原始 PDF 的元数据带出去。
    is_privileged = current_user is not None and (
        entry.submitted_by == current_user.id or await user_has_editor_access(db, current_user)
    )
    needs_anonymized = False
    if not is_privileged:
        # 函数级导入：blinding 模块读取设置，保持与原实现一致的加载时机，
        # 规避潜在的模块环。
        from app.domain.review.blinding import get_review_mode

        mode = await get_review_mode(db, entry.tenant_id)
        needs_anonymized = mode == "double_blind"
        if needs_anonymized and not entry.markdown_path:
            anon_url = (entry.anonymized_file_url or "").strip()
            if anon_url.lower().startswith(("http://", "https://")):
                return RedirectResponse(anon_url, status_code=status.HTTP_302_FOUND)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Double-blind review is enabled and this submission has no online "
                    "manuscript to anonymize. Ask the author to provide Markdown or the "
                    "editor to upload an anonymized version."
                ),
            )

    # Canonical source of truth is the online Markdown: web article, Word and
    # PDF must render the same text and the same house layout.  Old uploads
    # (Word 2016/WPS PDFs) predate the normalization pass and are kept only as
    # an archival fallback when there is no Markdown at all.
    serve_stored = not needs_anonymized and not entry.markdown_path and bool(entry.file_path)
    storage = get_storage()
    if serve_stored and entry.file_path:
        # The DB row can outlive the object on disk (old submissions were
        # converted to Markdown and the source PDF was pruned).  A presigned
        # URL would still be issued for such a missing key, and the PDF button
        # would die at the object store.  Check existence first; when the
        # original is gone, fall back to generating the requested format from
        # Markdown instead of returning 404.
        try:
            stored_exists = await storage.exists(entry.file_path)
        except Exception:
            stored_exists = False
        if not stored_exists:
            if entry.markdown_path:
                return await _generated_download(
                    entry, file_format, anonymized=needs_anonymized, inline=inline
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Stored file is missing",
            )

    if not serve_stored:
        canonical_resource = None
        if getattr(entry, "resource_id", None):
            from app.domain.catalog.models import Resource

            canonical_resource = (
                await db.execute(select(Resource).where(Resource.id == entry.resource_id))
            ).scalar_one_or_none()
        return await _generated_download(
            entry,
            file_format,
            anonymized=needs_anonymized,
            resource=canonical_resource,
            inline=inline,
        )

    file_path = entry.file_path
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored file is missing",
        )
    url = storage.presigned_url(file_path)
    if url:
        # S3 预签名 URL 直接重定向到对象存储；对象存储自身会依据客户端的
        # Range 头返回 206，无需在此追加（追加未签名的 range 参数会让
        # SigV4 签名失效，导致 SignatureDoesNotMatch → 403）。
        return RedirectResponse(url, status_code=status.HTTP_302_FOUND)

    try:
        data = await storage.load(file_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored file is missing",
        ) from exc

    filename = file_path.rsplit("/", 1)[-1]
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    # F9: HTTP Range 支持（本地后端）。解析 Range: bytes=start-end，
    # 返回 206 Partial Content + Content-Range 头。若 Range 非法或缺失，
    # 退回 200 全量流式。
    range_header = request.headers.get("Range")
    if range_header and range_header.startswith("bytes="):
        spec = range_header[len("bytes=") :]
        try:
            if "-" in spec:
                start_s, end_s = spec.split("-", 1)
                if not start_s:
                    # ``bytes=-500`` 是 **suffix-range**：最后 500 字节，
                    # 不是"从 0 到 500"。旧实现按后者处理，返回了前 501 字节
                    # ——语义正好相反，PDF 阅读器拖到末尾时会拿到开头的
                    # 内容，表现为"翻到最后一页画面却跳回封面"。
                    suffix_len = int(end_s) if end_s else 0
                    if suffix_len <= 0:
                        raise ValueError("invalid suffix range")
                    start = max(0, len(data) - suffix_len)
                    end = len(data) - 1
                else:
                    start = int(start_s)
                    end = int(end_s) if end_s else len(data) - 1
            else:
                start = int(spec)
                end = len(data) - 1
            start = max(start, 0)
            end = min(end, len(data) - 1)
            if start > end or start >= len(data):
                raise ValueError("invalid range")
            chunk = data[start : end + 1]
            return Response(
                content=chunk,
                status_code=status.HTTP_206_PARTIAL_CONTENT,
                media_type=media_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{len(data)}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(chunk)),
                    "Content-Disposition": _content_disposition(filename, inline=inline),
                },
            )
        except (ValueError, IndexError):
            # 非法 Range → 退回全量 200（不报错）
            pass

    return StreamingResponse(
        iter((data,)),
        media_type=media_type,
        headers={
            "Content-Disposition": _content_disposition(filename, inline=inline),
            "Accept-Ranges": "bytes",
        },
    )
