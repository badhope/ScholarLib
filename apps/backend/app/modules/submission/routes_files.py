"""Submission API routes — 文件上传与下载（作者/编辑/审稿人）。

从 routes.py（52KB 单文件）拆出。router 来自 routes.py，本模块在其上
追加端点；注册顺序见 routes.py 文件末尾的底部 import。
"""

from __future__ import annotations

import mimetypes
import os
import re
from uuid import uuid4

from fastapi import Depends, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ROLE_EDITOR, get_current_user, user_has_role
from app.core.db import get_db
from app.core.storage import get_storage
from app.models import User
from app.modules.review.models import ReviewAssignment
from app.modules.submission._helpers import (
    _get_or_404,
    _to_response,
    _try_delete_storage,
)
from app.modules.submission.routes import router
from app.modules.submission.schemas import SubmissionResponse

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


def _content_disposition(filename: str) -> str:
    """构造下载响应头，含 ASCII 回退与 RFC 5987 的 UTF-8 文件名。

    只用 ASCII 回退会让中文标题变成乱码，只用 RFC 5987 又会让老客户端
    拿不到文件名，所以两个都给（现代浏览器优先 ``filename*``）。
    """
    from urllib.parse import quote

    ascii_name = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in filename
    ) or "download"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"

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
    ".pdf .doc .docx .odt .rtf .txt .md .tex .ps "
    ".pptx .xls .xlsx .csv .json .bib "
    ".png .jpg .jpeg .svg .tif .tiff "
    ".zip .gz .tar .7z .ipynb"
).split()


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

    # 在线阅读用 Markdown：尽力转换，失败静默（阅读器回退 PDF 视图）。
    from app.modules.submission.manuscript import (
        convert_to_markdown_async,
        markdown_storage_key,
    )

    old_md = entry.markdown_path
    # 转换放到工作线程并带硬超时：pymupdf4llm 解析一份 50MB PDF 是数秒
    # 到数分钟的纯 CPU 工作，直接 await 会把整个事件循环（所有租户、
    # 所有请求，含 /health）一起卡死。转换是 best-effort 的增值能力，
    # 超时就放弃并回退 PDF 视图——"预览转不出来"绝不能升级成"全站不可用"。
    md_text = await convert_to_markdown_async(contents, original_filename)
    if md_text and old_path != rel_path:
        md_key = markdown_storage_key(rel_path)
        await get_storage().save(md_key, md_text.encode("utf-8"), content_type="text/markdown")
        entry.markdown_path = md_key
    else:
        entry.markdown_path = None

    await db.commit()
    await db.refresh(entry)
    # 替换式上传会覆盖 file_path，被替换的旧文件（及旧 md）若不清会变成孤儿对象。
    await _try_delete_storage(old_path)
    await _try_delete_storage(old_md)
    return _to_response(entry)


@router.get("/{submission_id}/files")
async def download_submission_file(
    submission_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
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
    if not entry.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This submission has no uploaded file",
        )

    allowed = entry.submitted_by == current_user.id or await user_has_role(
        db, current_user, ROLE_EDITOR
    )
    if not allowed:
        assignment = (
            (
                await db.execute(
                    select(ReviewAssignment).where(
                        ReviewAssignment.submission_id == entry.id,
                        ReviewAssignment.reviewer_id == current_user.id,
                        ReviewAssignment.status.in_(("pending", "accepted", "completed")),
                    )
                )
            )
            .scalars()
            .first()
        )
        allowed = assignment is not None
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this submission file",
        )

    # 双盲评审：原始上传文件不能交给审稿人。
    #
    # 修复前，双盲只在 JSON 字段上做抹除（authors/邮箱/submitted_by/venue/doi），
    # 文件下载端点却把**原始 PDF** 直接返回给被指派的审稿人——标题页和 PDF
    # 元数据里就是作者姓名与单位，双盲在核心流程上等于不存在。
    #
    # 第二层修复（双盲绕过 v2）：重定向目标曾用 ``download_url``，但该字段
    # **作者可控**（创建端点与作者编辑端点均可写）——作者填一条带身份的
    # URL 即可直穿双盲（重定向目标对审稿人可见，页面内容更可直接暴露身份）。
    # 现在只放行编辑端点写入的 ``anonymized_file_url``；没有匿名稿则明确报错，
    # 由编辑补上传。服务端不具备剥离 PDF 元数据的能力，不假装能做到。
    is_privileged = entry.submitted_by == current_user.id or await user_has_role(
        db, current_user, ROLE_EDITOR
    )
    if not is_privileged:
        # 函数级导入：blinding 模块读取设置，保持与原实现一致的加载时机，
        # 规避潜在的模块环。
        from app.modules.review.blinding import get_review_mode

        mode = await get_review_mode(db, entry.tenant_id)
        if mode == "double_blind":
            anon_url = (entry.anonymized_file_url or "").strip()
            if anon_url.lower().startswith(("http://", "https://")):
                return RedirectResponse(anon_url, status_code=status.HTTP_302_FOUND)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Double-blind review is enabled: the original manuscript may reveal "
                    "author identity. Ask the editor to provide an anonymized version "
                    "(editor: PUT /api/submissions/{id}/anonymized-file) before reviewing."
                ),
            )

    storage = get_storage()
    url = storage.presigned_url(entry.file_path)
    if url:
        # S3 预签名 URL 直接重定向到对象存储；对象存储自身会依据客户端的
        # Range 头返回 206，无需在此追加（追加未签名的 range 参数会让
        # SigV4 签名失效，导致 SignatureDoesNotMatch → 403）。
        return RedirectResponse(url, status_code=status.HTTP_302_FOUND)

    try:
        data = await storage.load(entry.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored file is missing",
        ) from exc

    filename = entry.file_path.rsplit("/", 1)[-1]
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
                    "Content-Disposition": _content_disposition(filename),
                },
            )
        except (ValueError, IndexError):
            # 非法 Range → 退回全量 200（不报错）
            pass

    return StreamingResponse(
        iter((data,)),
        media_type=media_type,
        headers={
            "Content-Disposition": _content_disposition(filename),
            "Accept-Ranges": "bytes",
        },
    )
