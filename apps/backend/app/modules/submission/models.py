"""SQLAlchemy model for the submission module.

Single table, tenant-scoped with RLS:

- ``submissions`` — author-submitted bibliographic record awaiting
  editor review. Mirrors the catalog ``Resource`` field shape so an
  approval can materialize a Resource with no field reshuffling. The
  ``resource_id`` column is set when (and only when) the submission is
  approved and the corresponding catalog Resource has been created.

The reviewer + submitter FKs point at ``users.id`` in the core schema;
the resource FK points at ``catalog.resources.id``. All cross-module FKs
resolve naturally because the submission model inherits from the core
``Base`` (ARCHITECTURE.md "All modules share the tenant's PostgreSQL
database").
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models import Base, JSONBVariant, TenantScopedMixin, User

if TYPE_CHECKING:
    # Resource lives in the catalog module; import lazily under
    # TYPE_CHECKING to avoid a circular import at module load time
    # (submission depends on catalog; importing catalog here would
    # re-trigger its own __init__ registration).
    from app.modules.catalog.models import Resource


class Submission(Base, TenantScopedMixin):
    """An author-submitted record awaiting editor review.

    Status lifecycle: ``pending`` → ``approved`` | ``rejected``
    (terminal). Once approved, ``resource_id`` points at the
    catalog Resource materialized from this submission; until then it
    is NULL.
    """

    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Author / submitter. CASCADE so deleting a user removes their
    # submissions (consistent with how catalog handles ownership).
    submitted_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Reviewer. SET NULL so historical approvals survive a reviewer
    # account being deleted (the approved resource must outlive the
    # reviewer's account).
    reviewed_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Catalog Resource created on approval. SET NULL so deleting a
    # catalog Resource does not silently rewrite submission history
    # (the submission record itself is the source of truth for "this
    # author submitted this on this date").
    resource_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("resources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Bibliographic payload — mirrors catalog ResourceBase so approval
    # can materialize a Resource with no field reshuffling.
    title: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    authors: Mapped[list[str]] = mapped_column(JSONBVariant, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    venue: Mapped[str | None] = mapped_column(Text, nullable=True)
    discipline: Mapped[str] = mapped_column(String(100), nullable=False)
    subdiscipline: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Nature 式栏目 / 期次分部：投稿时即确定，录用物化时原样带入
    # Resource，避免“表单能选、目录永远是空栏目”的断链。
    article_section: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    issue_part: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    # 关键词：补 submission → catalog 物化时丢失的字段，与 catalog.Resource
    # 对齐。jel_codes 暂不同步——catalog.Resource 没有该列（功能未落地），
    # 仅 keywords 参与物化，避免声称不存在的字段对齐。
    keywords: Mapped[list[str]] = mapped_column(JSONBVariant, nullable=False, default=list)
    jel_codes: Mapped[list[str]] = mapped_column(JSONBVariant, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONBVariant, nullable=False)
    abstract: Mapped[str] = mapped_column(Text, nullable=False)
    preview: Mapped[str] = mapped_column(Text, nullable=False)
    download_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 编辑在双盲评审下提供的匿名稿外链（http/https）。与 download_url 的
    # 关键区别：download_url/external_url 都是**作者可控**的（创建与作者
    # 编辑端点均可写），双盲下直接放行等于把身份信息端点交给作者；本列
    # 只由编辑端点 PUT /submissions/{id}/anonymized-file 写入。
    anonymized_file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    corresponding_author_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Workflow fields。
    # status 兼容旧值 pending/approved/rejected，同时支持
    # under_review/major_revision/minor_revision/resubmitted/accepted。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    # 赛道（serious / absurd）：历史字段，已下线（见 core/tracks.py），
    # 投稿侧由 schema 归一为 serious；录用物化时原样带到
    # catalog.resources.track。为兼容历史数据保留本列。
    track: Mapped[str] = mapped_column(
        String(16), nullable=False, default="serious", server_default="serious"
    )
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 免评审录用（desk accept）的显式豁免记录。
    # 正常情况下录用必须有至少一份已完成的审稿意见（见 routes_editor
    # decide_submission）。真实期刊确实存在"编辑直接录用"的场景（约稿、
    # 编委特稿、纪念专辑），但那必须是一个被明确声明、可审计的例外，
    # 而不是沉默的默认路径。置位后才允许零审稿录用，且理由进审计日志。
    review_waived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_waived_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    review_waive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 编辑 4 元决定（accept/minor_revision/major_revision/reject）的备注，
    # 区别于 admin_note（兼容旧 review 端点的备注字段）
    editor_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 封面图（作者上传 / 编辑指定）。存储 key 与 file_path 同族，
    # 物化到 catalog.resources.cover_image 时原样带过去。
    # 空 = 未上传，前端回退到按学科自动分配的默认封面。
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 在线阅读用 Markdown 稿件（上传 PDF/Word 后服务端转换，见
    # manuscript.py）；可空 = 未转换或转换失败（needs_docx，见
    # ``{file_path}.needs_docx`` 侧car 存具体原因）。
    markdown_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 中图分类号（P0）：从正文 front-matter ``clc`` / ``clc_label`` 解析，
    # 入库两列；非法值原样保留并由 clc_status_of 标记待校正。
    clc_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    clc_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # 内容赛道派生值（P0）：paper|essay。与历史 track(serious|absurd)
    # 无关——由 content_category 派生（academic→paper，fun/rant→essay）。
    content_track: Mapped[str | None] = mapped_column(String(8), nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    submitter: Mapped[User] = relationship("User", foreign_keys="Submission.submitted_by")
    reviewer: Mapped[User | None] = relationship("User", foreign_keys="Submission.reviewed_by")
    # Resource lives in the catalog module; import lazily (string ref)
    # to avoid a circular import at module load time.
    resource: Mapped[Resource | None] = relationship("Resource")


class SubmissionVersion(Base, TenantScopedMixin):
    """Immutable snapshot of a submission's bibliographic payload.

    版本产生时机（追加式，绝不回写）：

    - **v1**：作者创建投稿时立即快照，保证「最初提交了什么」永远可查。
    - **v2..n**：作者在大修/小修后点「重投」时，把当前（可能已被作者
      编辑过的）payload 再快照一份，并可附「给编辑的修改说明」。

    快照存 JSONB 整体 payload 而不是逐列复制：submission 的字段形状
    还会继续演化（keywords/jel_codes 就是后加的），逐列复制会让每次
    加字段都牵动版本表迁移；JSONB 快照只增不改，天然向前兼容。

    ``file_path`` 单独抽出来存：文件是版本间最常见的差异（改了稿子重
    传 PDF），且下载链路需要按 key 直达存储层，不适合埋在 JSON 里。
    """

    __tablename__ = "submission_versions"
    # 版本号从 1 开始、按 submission 单调递增；唯一约束防并发重投产生
    # 重号。此前只由迁移创建、metadata 未声明，导致 `alembic check`
    # 误报漂移 — 现补齐命名声明与迁移一致。
    __table_args__ = (
        UniqueConstraint("submission_id", "version", name="uq_submission_version_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # 完整书目 payload 快照（title/authors/abstract/... 与 Submission 列同形）
    payload: Mapped[dict[str, Any]] = mapped_column(JSONBVariant, nullable=False)
    # 该版本对应的稿件文件 key（可能为 None：作者还没传文件）
    # 封面图（作者上传 / 编辑指定）。存储 key 与 file_path 同族，
    # 物化到 catalog.resources.cover_image 时原样带过去。
    # 空 = 未上传，前端回退到按学科自动分配的默认封面。
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 作者附言：v1 恒空；重投版本可填「针对审稿意见做了哪些修改」
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


__all__ = ["Submission", "SubmissionVersion"]
