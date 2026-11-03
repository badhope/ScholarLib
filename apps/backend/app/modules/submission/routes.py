"""Submission API routes — 作者侧（创建 / 查询 / 编辑 / 版本 / 删除 / 重投）。

编辑与审稿侧见 routes_editor.py；文件上传下载见 routes_files.py。
本文件末尾通过底部 import 把三个路由文件注册到同一个 router 上
（FastAPI 拆分路由文件的惯例做法，避免循环导入）。
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ROLE_EDITOR,
    get_current_user,
    user_has_role,
)
from app.core.db import get_db
from app.models import Role, User, UserRole
from app.modules.notifications import services as notifications
from app.modules.submission._helpers import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    _get_or_404,
    _list_submissions,
    _snapshot_submission,
    _to_response,
    _try_delete_storage,
)
from app.modules.submission.models import Submission, SubmissionVersion
from app.modules.submission.schemas import (
    MessageResponse,
    ResubmitRequest,
    SubmissionCreate,
    SubmissionListResponse,
    SubmissionResponse,
    SubmissionUpdate,
    SubmissionVersionListResponse,
    SubmissionVersionResponse,
)

router = APIRouter(prefix="/submissions", tags=["submissions"])

# ---------------------------------------------------------------------------
# 注册编辑/审稿侧与文件侧路由（必须在 GET /{submission_id} 之前 import：
# FastAPI 按注册顺序匹配，静态路径（/pending、/me）必须先于路径参数注册）。
# 此处 router 与常量已就绪，子模块 `from .routes import router` 无循环导入。
# ---------------------------------------------------------------------------
from app.modules.submission import routes_editor, routes_files  # noqa: E402,F401


@router.post(
    "",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_submission(
    body: SubmissionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """Submit a record for editor review.

    1.8.0 起投稿零等级门槛：注册登录即可投（require_level(3) 移除）。
    唯一前置是确认当版《投稿规范》（rules_ack_version，见下）——这是
    合规动作而非等级门槛；确认动作在个人中心 / gamification/onboarding/author，
    同时授予作者引导积分。
    """
    from app.api.levels import CURRENT_RULES_VERSION

    if current_user.rules_ack_version != CURRENT_RULES_VERSION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "rules_ack_required",
                "version": CURRENT_RULES_VERSION,
                "message": "投稿前请先阅读并确认《Rubbish 投稿与编辑规范》。",
            },
        )
    submission = Submission(
        tenant_id=current_user.tenant_id,
        submitted_by=current_user.id,
        status="pending",
        title=body.title,
        type=body.type,
        track=body.track,
        authors=body.authors,
        year=body.year,
        venue=body.venue,
        discipline=body.discipline,
        subdiscipline=body.subdiscipline,
        keywords=body.keywords,
        jel_codes=body.jel_codes,
        tags=body.tags,
        abstract=body.abstract,
        preview=body.preview,
        download_url=str(body.download_url) if body.download_url else None,
        external_url=str(body.external_url) if body.external_url else None,
        doi=body.doi,
        corresponding_author_email=body.corresponding_author_email,
    )
    db.add(submission)
    await db.flush()  # 拿到 submission.id 供 v1 快照引用
    # v1 快照：保证「最初提交了什么」永远可查（版本历史从创建开始）
    await _snapshot_submission(db, submission, created_by=current_user.id)
    from app.modules.gamification import service as gamification

    await gamification.award(
        db, current_user, "submission.create", ref_type="submission", ref_id=str(submission.id)
    )
    await db.commit()
    await db.refresh(submission)
    return _to_response(submission)


@router.get("/me", response_model=SubmissionListResponse)
async def list_my_submissions(
    status_filter: str = Query(
        default=None,
        alias="status",
        pattern=r"^(pending|under_review|major_revision|minor_revision|resubmitted|rework_requested|accepted|approved|rejected)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionListResponse:
    """List the current user's own submissions."""
    query = select(Submission).where(
        Submission.submitted_by == current_user.id,
        Submission.tenant_id == current_user.tenant_id,
    )
    if status_filter is not None:
        query = query.where(Submission.status == status_filter)
    return await _list_submissions(db, query, page, page_size)


@router.get("/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """View a submission. Owner sees their own; admin or editor sees any."""
    entry = await _get_or_404(db, submission_id)
    if (
        entry.submitted_by != current_user.id
        and not current_user.is_admin
        and not await user_has_role(db, current_user, ROLE_EDITOR)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    response = _to_response(entry)
    if entry.resource_id is not None:
        # 刊出状态随详情下发：前端据此区分「已发表」与「刊前预览」。
        from app.modules.catalog.models import Resource

        response.resource_publication_status = (
            await db.execute(
                select(Resource.publication_status).where(
                    Resource.id == entry.resource_id,
                    Resource.tenant_id == entry.tenant_id,
                )
            )
        ).scalar_one_or_none()
    return response


@router.patch("/{submission_id}", response_model=SubmissionResponse)
async def update_submission(
    submission_id: int,
    body: SubmissionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """作者修改自己的稿件内容（补齐修回链路的缺口）。

    此前 major/minor revision 后作者只能翻状态「重投」，却改不了
    任何内容 —— 修回等于空转。此端点让作者在以下状态可编辑：

    - ``pending``：还没进入评审，随便改；
    - ``major_revision`` / ``minor_revision``：按审稿意见修改，
      改完再点重投（重投时快照为新版本）。

    under_review 不可编辑：审稿人正在看的稿子不能被作者悄悄换掉。
    终态（accepted/rejected/approved）不可编辑。
    """
    entry = await _get_or_404(db, submission_id)
    if entry.submitted_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the submitter can edit the submission",
        )
    if entry.status not in ("pending", "major_revision", "minor_revision", "rework_requested"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot edit submission in status '{entry.status}'",
        )
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return _to_response(entry)
    for field, value in updates.items():
        # AnyHttpUrl 落库前转 str，与 create 端点行为一致
        if field in ("download_url", "external_url") and value is not None:
            value = str(value)
        setattr(entry, field, value)
    await db.commit()
    await db.refresh(entry)
    return _to_response(entry)


@router.get(
    "/{submission_id}/versions",
    response_model=SubmissionVersionListResponse,
)
async def list_submission_versions(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionVersionListResponse:
    """稿件版本历史（v1 = 初次提交；之后每次重投一个版本）。

    可见方：作者本人、admin/editor。审稿人故意不给 —— 双盲模式下
    历史版本可能残留身份信息，且审稿人只需要看「当前版本」。
    """
    entry = await _get_or_404(db, submission_id)
    allowed = (
        entry.submitted_by == current_user.id
        or current_user.is_admin
        or await user_has_role(db, current_user, ROLE_EDITOR)
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    rows = (
        (
            await db.execute(
                select(SubmissionVersion)
                .where(SubmissionVersion.submission_id == entry.id)
                .order_by(SubmissionVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return SubmissionVersionListResponse(
        data=[SubmissionVersionResponse.model_validate(v) for v in rows]
    )


@router.delete(
    "/{submission_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_submission(
    submission_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Delete a submission. Submitter may delete their own pending only.

    Approved/rejected submissions are immutable historical records and
    cannot be deleted by the submitter (admin can via direct DB access
    if needed; not exposed via API to keep the audit trail intact).
    """
    entry = await _get_or_404(db, submission_id)
    if entry.submitted_by != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    if entry.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a reviewed submission",
        )
    file_path = entry.file_path
    await db.delete(entry)
    await db.commit()
    # 删除稿件时应同步清理其存储文件，否则 PDF 在磁盘 / S3 上成为孤儿对象，
    # 既泄露删除行为的"残留"，也会让存储无限增长。
    await _try_delete_storage(file_path)
    return MessageResponse(message="Submission deleted")


@router.post(
    "/{submission_id}/resubmit",
    response_model=SubmissionResponse,
)
async def author_resubmit(
    submission_id: int,
    body: ResubmitRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """作者收到 major_revision / minor_revision 后重新提交。

    将状态置为 under_review（编辑可再次分配/决断），并把当前（作者已
    通过 PATCH 修改过的）稿件内容快照为新版本。可选 ``note`` 记录
    「针对审稿意见做了哪些修改」，随版本一起存档并推送给编辑。

    仅作者本人可操作。body 可省略，兼容旧的无 body 调用。
    """
    entry = await _get_or_404(db, submission_id)
    if entry.submitted_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the submitter can resubmit",
        )
    if entry.status not in ("major_revision", "minor_revision"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resubmit in status '{entry.status}'",
        )
    note = body.note if body else None
    entry.status = "under_review"
    # 快照与状态变更同事务：避免「状态翻了但没留版本」的历史空洞
    snapshot = await _snapshot_submission(db, entry, created_by=current_user.id, note=note)
    # commit 后 ORM 对象过期，异步会话下惰性刷新会炸；版本号在 commit 前取出
    version_no = snapshot.version
    # 通知编辑：作者已重投（与状态变更同事务，遵循 S-3）。
    # admin 在权限模型里视同 editor（deps._user_has_role 对 admin 直接放行），
    # fan-out 必须与之对齐 —— 否则只有 admin 的小刊重投通知会石沉大海。
    editor_ids = (
        select(UserRole.user_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            UserRole.tenant_id == entry.tenant_id,
            Role.tenant_id == entry.tenant_id,
            Role.name == "editor",
        )
    )
    editors = (
        (
            await db.execute(
                select(User)
                .where(
                    User.tenant_id == entry.tenant_id,
                    User.is_active.is_(True),
                    (User.id.in_(editor_ids)) | (User.is_admin.is_(True)),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    notify_body = f"Submission #{entry.id}（v{version_no}）已进入 under_review，请处理。"
    if note:
        notify_body += f"\n作者修改说明：{note}"
    for editor in editors:
        await notifications.create(
            db,
            tenant_id=entry.tenant_id,
            user_id=editor.id,
            type_="submission.resubmitted",
            title=f"作者已重新提交：{entry.title}",
            body=notify_body,
            related_type="submission",
            related_id=str(entry.id),
        )
    try:
        await db.commit()
    except IntegrityError as exc:
        # (submission_id, version) 唯一约束冲突 = 并发重投撞号
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Concurrent resubmit detected, please retry",
        ) from exc
    await db.refresh(entry)
    return _to_response(entry)
