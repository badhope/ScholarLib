"""039 — 投稿站内相似度

- ``submissions.similarity_score``：0–100，提交时与本站已发表条目/投稿比对。
- ``submissions.similarity_matches``：Top 3 命中 JSON（kind/id/title/score）。

不接 CNKI/CrossCheck，字段名与文案都必须明确是“站内相似度”，避免把
内部提示冒称学术查重结论。

Revision ID: 039_submission_similarity
Revises: 038_forum_boards
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "039_submission_similarity"
down_revision = "038_forum_boards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("submissions", sa.Column("similarity_score", sa.Float(), nullable=True))
    op.add_column("submissions", sa.Column("similarity_matches", sa.JSON(), nullable=True))
    op.create_index(
        "ix_submissions_similarity_score", "submissions", ["tenant_id", "similarity_score"]
    )


def downgrade() -> None:
    op.drop_index("ix_submissions_similarity_score", table_name="submissions")
    op.drop_column("submissions", "similarity_matches")
    op.drop_column("submissions", "similarity_score")
