"""Reader API routes — reading history + cross-device progress + file assets.

History endpoints (read + write) require authentication; every user sees
only their own history (tenant + user scope enforced by RLS in production
and by the ``tenant_id`` / ``user_id`` filters in tests). FileAsset
endpoints are admin-only: recording stored-file metadata is an
administrative action; the byte upload pipeline itself is a separate
storage-layer concern.

Upsert / retry pattern for ``PUT /progress``:

  1. SELECT the (user, resource) row.
  2. If found, update; if not, INSERT.
  3. On IntegrityError (race: another concurrent INSERT won), rollback
     and re-SELECT, then apply the update to the winner's row.

The semantic where ``duration_sec`` accumulates
across devices — a lost INSERT never loses reading time.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, require_tenant_id
from app.core.db import get_db, paginate
from app.core.time import utcnow
from app.domain.catalog.models import Resource
from app.domain.catalog.visibility import public_conditions
from app.domain.reader.models import FileAsset, ReadingHistory
from app.interfaces.http.reader.schemas import (
    FileAssetCreate,
    FileAssetResponse,
    MessageResponse,
    ReadingHistoryEntryResponse,
    ReadingHistoryListResponse,
    ReadingProgressResponse,
    ReadingProgressUpdate,
)
from app.models import AuditLog, User

router = APIRouter(prefix="/reader", tags=["reader"])

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _apply_progress(entry: ReadingHistory, body: ReadingProgressUpdate, now: datetime) -> None:
    """Apply a progress update to an existing entry in place.

    ``duration_sec`` accumulates; the rest overwrite. ``viewed_at`` and
    ``last_read_at`` are bumped so a progress update also counts as a view
    for ordering purposes.
    """
    if body.page is not None:
        entry.page = body.page
    if body.progress_percent is not None:
        entry.progress_percent = body.progress_percent
    if body.duration_sec is not None:
        # Accumulate, never overwrite — multiple devices may report
        # partial durations concurrently.
        entry.duration_sec = (entry.duration_sec or 0) + body.duration_sec
    if body.completed is not None:
        entry.completed = body.completed
    entry.last_read_at = now
    entry.viewed_at = now


# ---------------------------------------------------------------------------
# Reading history
# ---------------------------------------------------------------------------


@router.get("/history", response_model=ReadingHistoryListResponse)
async def list_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReadingHistoryListResponse:
    """List the current user's reading history, newest view first.

    只返回当前公开可见的资源（public_conditions）：被撤回/转入排期的条目
    不再出现在历史里，避免「历史里点进去 404」。资源元信息按 id 批量
    二次查询，前端「继续阅读」卡片一次请求即可渲染。
    """
    visible_ids = (
        select(Resource.id)
        .where(
            Resource.tenant_id == current_user.tenant_id,
            *public_conditions(),
        )
        .scalar_subquery()
    )
    base = select(ReadingHistory).where(
        ReadingHistory.user_id == current_user.id,
        ReadingHistory.tenant_id == current_user.tenant_id,
        ReadingHistory.resource_id.in_(visible_ids),
    )
    rows, meta = await paginate(
        db,
        base,
        page=page,
        page_size=page_size,
        order_by=(desc(ReadingHistory.viewed_at), ReadingHistory.id.asc()),
    )
    # 批量取本页涉及的资源元信息（避免 N+1；条目数 ≤ page_size）
    ids = [h.resource_id for h in rows]
    resources: dict[int, Resource] = {}
    if ids:
        res_rows = await db.execute(select(Resource).where(Resource.id.in_(ids)))
        resources = {r.id: r for r in res_rows.scalars().all()}
    data = []
    for h in rows:
        r = resources.get(h.resource_id)
        data.append(
            ReadingHistoryEntryResponse(
                resource_id=h.resource_id,
                viewed_at=h.viewed_at,
                last_read_at=h.last_read_at,
                visit_count=h.visit_count,
                page=h.page,
                progress_percent=h.progress_percent,
                duration_sec=h.duration_sec,
                completed=h.completed,
                title=r.title if r else None,
                authors=list(r.authors or []) if r else [],
                discipline=r.discipline if r else None,
                year=r.year if r else None,
                resource_type=str(r.type) if r else None,
            )
        )
    return ReadingHistoryListResponse(data=data, meta=meta)


@router.post(
    "/history/{resource_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_view(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Record that the current user opened a resource.

    Upserts the (user, resource) row: if it exists, bumps ``visit_count``
    and refreshes ``viewed_at`` / ``last_read_at``; if not, creates it
    with ``visit_count=1``.
    """
    # Reject views for non-existent resources so history cannot point at
    # missing rows. Scope by tenant too — a resource id from another tenant
    # must not be viewable.
    user_id = current_user.id
    tenant_id = current_user.tenant_id
    # 存在性校验：只投影 Resource.id，避免全行物料化（F5 列剪枝）。
    resource_exists = (
        await db.execute(
            select(Resource.id).where(
                Resource.id == resource_id,
                Resource.tenant_id == tenant_id,
                # 排期中的期号对读者不存在：否则 201/404 的差异会泄露存在性。
                *public_conditions(),
            )
        )
    ).scalar_one_or_none()
    if resource_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    now = utcnow()
    # 用 flush 而不是 commit 触发 IntegrityError：
    # SQLAlchemy 2 async + aiosqlite 在 commit 阶段抛 IntegrityError 时，
    # 会被包成 greenlet_spawn error，导致 except IntegrityError 不触发。
    # flush 在事务内执行 INSERT，IntegrityError 能被正常捕获。
    #
    # 同时：try 块前把 user_id / tenant_id 缓存为局部变量。db.rollback() 后
    # SQLAlchemy 会 expire 所有 ORM 对象的属性，再次访问 current_user.id 会
    # 触发 lazy-load（同步 IO），在 async 上下文里抛 greenlet_spawn error。
    # 用局部变量绕开对 current_user 的属性访问。
    try:
        entry = (
            await db.execute(
                select(ReadingHistory).where(
                    ReadingHistory.user_id == user_id,
                    ReadingHistory.resource_id == resource_id,
                    ReadingHistory.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if entry is not None:
            entry.viewed_at = now
            entry.last_read_at = now
            entry.visit_count = (entry.visit_count or 1) + 1
        else:
            entry = ReadingHistory(
                tenant_id=tenant_id,
                user_id=user_id,
                resource_id=resource_id,
                visit_count=1,
                viewed_at=now,
            )
            db.add(entry)
        await db.flush()
    except IntegrityError:
        # Race: another concurrent request inserted the same row. Roll
        # back, re-fetch the winner, and apply the visit bump to it so
        # the upsert still happens.
        await db.rollback()
        entry = (
            await db.execute(
                select(ReadingHistory).where(
                    ReadingHistory.user_id == user_id,
                    ReadingHistory.resource_id == resource_id,
                    ReadingHistory.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if entry is not None:
            entry.viewed_at = now
            entry.last_read_at = now
            entry.visit_count = (entry.visit_count or 1) + 1
            await db.flush()
    await db.commit()
    # 阅读积分：同一篇只记一次（ledger 唯一约束保证幂等）。
    # 放在 commit 之后按 id 重新取 user：上面的 rollback 分支会 expire
    # current_user 的属性，直接访问会触发 async lazy-load。
    from app.domain.gamification import service as gamification
    from app.models import User as UserModel

    fresh_user = await db.get(UserModel, user_id)
    if fresh_user is not None:
        await gamification.award(
            db, fresh_user, "read.article", ref_type="resource", ref_id=str(resource_id)
        )
        await db.commit()
    return MessageResponse(message="Added to history")


@router.delete(
    "/history/{resource_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def remove_from_history(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Remove a resource from the current user's history."""
    entry = (
        await db.execute(
            select(ReadingHistory).where(
                ReadingHistory.user_id == current_user.id,
                ReadingHistory.resource_id == resource_id,
                ReadingHistory.tenant_id == current_user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="History entry not found")
    await db.delete(entry)
    await db.commit()
    return MessageResponse(message="Removed from history")


# ---------------------------------------------------------------------------
# Reading progress
# ---------------------------------------------------------------------------


@router.get(
    "/history/{resource_id}/progress",
    response_model=ReadingProgressResponse,
)
async def get_progress(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReadingProgressResponse:
    """Get the current user's reading progress for a resource."""
    entry = (
        await db.execute(
            select(ReadingHistory).where(
                ReadingHistory.user_id == current_user.id,
                ReadingHistory.resource_id == resource_id,
                ReadingHistory.tenant_id == current_user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Progress not found")
    return ReadingProgressResponse.model_validate(entry)


@router.put(
    "/history/{resource_id}/progress",
    response_model=ReadingProgressResponse,
)
async def update_progress(
    resource_id: int,
    body: ReadingProgressUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReadingProgressResponse:
    """Upsert reading progress for a resource.

    ``duration_sec`` accumulates across calls; the other fields overwrite.
    On a concurrent INSERT race, the loser rolls back, re-fetches the
    winner's row, and re-applies the update so no reading time is lost.
    """
    # Reject progress for non-existent resources so the upsert cannot
    # create an orphaned history row pointing at a missing resource.
    user_id = current_user.id
    tenant_id = current_user.tenant_id
    # 存在性校验：只投影 Resource.id，避免全行物料化（F5 列剪枝）。
    # 与 record_view 同口径带上 public_conditions：进度写入同样不能给
    # 排期稿开绿灯，否则 201/404 的差异又是一条存在性探针。
    resource_exists = (
        await db.execute(
            select(Resource.id).where(
                Resource.id == resource_id,
                Resource.tenant_id == tenant_id,
                *public_conditions(),
            )
        )
    ).scalar_one_or_none()
    if resource_exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    now = utcnow()
    # 用 flush 而不是 commit 触发 IntegrityError（详见 record_view 的注释）。
    # user_id / tenant_id 缓存为局部变量，原因同 record_view。
    try:
        entry = (
            await db.execute(
                select(ReadingHistory).where(
                    ReadingHistory.user_id == user_id,
                    ReadingHistory.resource_id == resource_id,
                    ReadingHistory.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if entry is None:
            entry = ReadingHistory(
                tenant_id=tenant_id,
                user_id=user_id,
                resource_id=resource_id,
                visit_count=1,
                duration_sec=0,
                viewed_at=now,
                last_read_at=now,
            )
            db.add(entry)
        _apply_progress(entry, body, now)
        await db.flush()
    except IntegrityError:
        # Race: another concurrent INSERT won the (user, resource) slot.
        # Re-fetch and re-apply so the update is not lost.
        await db.rollback()
        entry = (
            await db.execute(
                select(ReadingHistory).where(
                    ReadingHistory.user_id == user_id,
                    ReadingHistory.resource_id == resource_id,
                    ReadingHistory.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if entry is None:
            # Extremely unlikely: the winner row vanished between the
            # commit and this re-fetch. Surface as 409 so the client retries.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="History entry disappeared after race; please retry",
            ) from None
        _apply_progress(entry, body, now)
        await db.flush()
    await db.commit()
    await db.refresh(entry)
    return ReadingProgressResponse.model_validate(entry)


# ---------------------------------------------------------------------------
# File assets (admin only)
# ---------------------------------------------------------------------------


@router.get(
    "/file-assets",
    response_model=list[FileAssetResponse],
)
async def list_file_assets(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[FileAssetResponse]:
    """List all file assets in the current tenant (admin only)."""
    tenant_id = require_tenant_id()
    rows = (
        (
            await db.execute(
                select(FileAsset)
                .where(FileAsset.tenant_id == tenant_id)
                .order_by(desc(FileAsset.created_at), FileAsset.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return [FileAssetResponse.model_validate(r) for r in rows]


@router.get(
    "/file-assets/{file_asset_id}",
    response_model=FileAssetResponse,
)
async def get_file_asset(
    file_asset_id: int,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FileAssetResponse:
    """Get a single file asset by id (admin only)."""
    tenant_id = require_tenant_id()
    entry = (
        await db.execute(
            select(FileAsset).where(
                FileAsset.id == file_asset_id,
                FileAsset.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File asset not found")
    return FileAssetResponse.model_validate(entry)


@router.post(
    "/file-assets",
    response_model=FileAssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_file_asset(
    payload: FileAssetCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FileAssetResponse:
    """Record metadata for a stored file (admin only).

    The caller must have already written the bytes to the storage
    backend; this endpoint only records what was stored.
    """
    tenant_id = require_tenant_id()
    asset = FileAsset(
        tenant_id=tenant_id,
        filename=payload.filename,
        original_filename=payload.original_filename,
        mime_type=payload.mime_type,
        file_size=payload.file_size,
        storage_path=payload.storage_path,
        storage_backend=payload.storage_backend,
        sha256=payload.sha256,
        uploaded_by=current_user.id,
    )
    db.add(asset)
    try:
        # 先 flush 拿到 asset.id（审计行要引用它），再和审计行一起提交。
        # 分成两次 commit 的话，第二次失败就会留下一条没有审计记录的资产
        # —— sha256 是事后追责的证据，丢了就没法回溯。
        await db.flush()
        # Audit: file-asset metadata is durable evidence (sha256 etc.); log
        # who recorded it so a later dispute can be traced.
        db.add(
            AuditLog(
                tenant_id=current_user.tenant_id,
                actor_user_id=current_user.id,
                action="reader.file_asset.create",
                target_type="file_asset",
                target_id=str(asset.id),
                payload={
                    "filename": asset.filename,
                    "storage_path": asset.storage_path,
                    "sha256": asset.sha256,
                },
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="File asset with this sha256 already exists in this tenant",
        ) from exc
    await db.refresh(asset)
    return FileAssetResponse.model_validate(asset)


@router.delete(
    "/file-assets/{file_asset_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_file_asset(
    file_asset_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Delete a file asset record (admin only).

    Does NOT delete the bytes from the storage backend — that is the
    storage layer's responsibility. This endpoint only removes the
    metadata row.
    """
    entry = (
        await db.execute(
            select(FileAsset).where(
                FileAsset.id == file_asset_id,
                FileAsset.tenant_id == require_tenant_id(),
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File asset not found")
    # Capture identifying info before delete so the audit row can describe
    # what was removed (storage_path stays valuable for cleanup audits).
    deleted_filename = entry.filename
    deleted_storage_path = entry.storage_path
    await db.delete(entry)
    db.add(
        AuditLog(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            action="reader.file_asset.delete",
            target_type="file_asset",
            target_id=str(file_asset_id),
            payload={
                "filename": deleted_filename,
                "storage_path": deleted_storage_path,
            },
        )
    )
    await db.commit()
    return MessageResponse(message="File asset deleted")
