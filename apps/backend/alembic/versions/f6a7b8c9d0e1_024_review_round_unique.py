"""024 — review assignment uniqueness includes round

作者大修/小修后重投会开启新一轮评审；同一审稿人需要能被再次邀请。
原来的 (submission_id, reviewer_id) 唯一约束会拦住这次邀请，故改为
(submission_id, reviewer_id, round)。
"""
from __future__ import annotations

from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_review_assignment_submission_reviewer",
        "review_assignments",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_review_assignment_submission_reviewer_round",
        "review_assignments",
        ["submission_id", "reviewer_id", "round"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_review_assignment_submission_reviewer_round",
        "review_assignments",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_review_assignment_submission_reviewer",
        "review_assignments",
        ["submission_id", "reviewer_id"],
    )
