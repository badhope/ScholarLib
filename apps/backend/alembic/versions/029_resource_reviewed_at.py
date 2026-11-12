"""029: resources.reviewed_at，回填录用时间

Revision ID: 029_resource_reviewed_at
Revises: e1f2a3b4c5d6
Create Date: 2026-11-12

数据债：submissions.reviewed_at 有值，但 resources 没有对应字段，导致
“这篇什么时候过审”只能反查投稿表。这里补一个可空时间列，并从
submissions.reviewed_at 回填；不伪造没有记录的日期。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "029_resource_reviewed_at"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resources",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_resources_reviewed_at", "resources", ["reviewed_at"])
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        """
        UPDATE resources AS r
        SET reviewed_at = s.reviewed_at
        FROM (
            SELECT resource_id, MAX(reviewed_at) AS reviewed_at
            FROM submissions
            WHERE resource_id IS NOT NULL AND reviewed_at IS NOT NULL
            GROUP BY resource_id
        ) AS s
        WHERE r.id = s.resource_id AND r.reviewed_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_resources_reviewed_at", table_name="resources")
    op.drop_column("resources", "reviewed_at")
