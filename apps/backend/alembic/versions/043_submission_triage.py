"""043 — 两段式初筛（triage）

- ``submissions.triage_status``：pending（待初筛）/ passed（已送外审）/
  rework（退回修改）/ rejected（直接拒稿）。
- ``triage_note`` / ``triaged_at`` / ``triaged_by``：初筛决定与审计。
- 旧数据回填：已在外审及之后的稿件置 passed，已拒稿置 rejected，
  其余保持 pending，避免迁移后把历史稿件重新排进初筛队列。

Revision ID: 043_submission_triage
Revises: 042_reviewer_conflict_declarations
Create Date: 2026-11-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "043_submission_triage"
down_revision = "042_reviewer_conflict_declarations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column(
            "triage_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("submissions", sa.Column("triage_note", sa.Text(), nullable=True))
    op.add_column(
        "submissions",
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "submissions",
        sa.Column(
            "triaged_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_submissions_triage_status",
        "submissions",
        ["triage_status"],
    )
    op.execute(
        """
        UPDATE submissions
        SET triage_status = 'passed'
        WHERE status IN (
            'under_review', 'major_revision', 'minor_revision',
            'resubmitted', 'accepted', 'approved'
        )
        """
    )
    op.execute(
        """
        UPDATE submissions
        SET triage_status = 'rejected'
        WHERE status = 'rejected'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_submissions_triage_status", table_name="submissions")
    op.drop_column("submissions", "triaged_by")
    op.drop_column("submissions", "triaged_at")
    op.drop_column("submissions", "triage_note")
    op.drop_column("submissions", "triage_status")
