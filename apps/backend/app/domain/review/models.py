"""SQLAlchemy models for the peer-review module.

Tables:

- ``review_assignments`` — editor→reviewer task assignment. One submission
  can have multiple assignments (multiple reviewers). Each assignment has
  its own status lifecycle: ``pending`` (invited) → ``accepted`` / ``declined``
  → ``completed`` (reviewer submitted) → ``cancelled`` (editor withdrew).
- ``review_reports`` — the actual review report submitted by a reviewer:
  overall recommendation + per-criterion scores + comments to editor +
  comments to author. One report per assignment (1:1).

Tenant-scoped with RLS, mirroring the catalog/submission strategy.
Single-blind by default: reviewer identity visible to editors but not
to authors. (Double-blind is a future tenant setting; for now we keep
the data model identity-bearing to keep the MVP simple.)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models import Base, JSONBVariant, TenantScopedMixin


class ReviewAssignment(Base, TenantScopedMixin):
    """Editor→reviewer task assignment for a submission.

    Lifecycle: ``pending`` (invited) → ``accepted``|``declined`` →
    ``completed`` (reviewer submitted the report) → ``cancelled``.
    """

    __tablename__ = "review_assignments"
    __table_args__ = (
        # 同一稿件、同一审稿人、同一轮只能有一条邀请；重投后可邀请同一
        # 审稿人进入新一轮，不能被旧的 (submission, reviewer) 约束拦住。
        UniqueConstraint(
            "submission_id",
            "reviewer_id",
            "round",
            name="uq_review_assignment_submission_reviewer_round",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # pending=已邀请待回应, accepted=审稿人接受, declined=审稿人拒绝,
    # completed=审稿人已提交报告, cancelled=编辑撤销邀请
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 催办记录（0.8.0）：最近一次自动催办时间与累计次数。用于幂等
    # （同一窗口内不重复催）与编辑侧可见的"已催 N 次"。
    last_reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # P1：轮次（默认 1）、slot（1/2/3，审稿人槽位）、是否裁决人。
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    slot: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_adjudicator: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # 外审专家（主编指定，可标注外省/外单位）；不改变账号体系，
    # 只记录这次邀请的性质，供矩阵与审计识别。
    is_external: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    external_affiliation: Mapped[str | None] = mapped_column(String(120), nullable=True)

    submission = relationship("Submission", backref="review_assignments")
    reviewer = relationship("User", foreign_keys="ReviewAssignment.reviewer_id")
    assigner = relationship("User", foreign_keys="ReviewAssignment.assigned_by")
    report: Mapped[list[ReviewReport]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


class ReviewReport(Base, TenantScopedMixin):
    """Review report submitted by a reviewer (one per assignment).

    ``recommendation``: accept / minor_revision / major_revision / reject.
    ``scores``: structured JSON of per-criterion scores (e.g. originality,
    methodology, clarity, significance, each on 1-5 scale).
    ``comments_to_editor``: confidential comments visible to editor only.
    ``comments_to_author``: comments visible to author (single-blind:
    author sees these but not reviewer identity).
    """

    __tablename__ = "review_reports"
    __table_args__ = (UniqueConstraint("assignment_id", name="uq_review_report_assignment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("review_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONBVariant, nullable=False, default=dict)
    comments_to_editor: Mapped[str | None] = mapped_column(Text, nullable=True)
    comments_to_author: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 审稿报告附件（主要是带批注的 PDF/Word/图片）。存元数据数组而不是
    # 单列：一个审稿人可能同时交“批注版 PDF + 补充数据表”。
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBVariant, nullable=False, default=list
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    assignment = relationship("ReviewAssignment", back_populates="report")


__all__ = ["ReviewAssignment", "ReviewReport"]
