"""023 — review_assignments external expert flags

主编可以指定外省/外单位的外审专家。这里只记录这次邀请的性质，
不改变账号体系；第三方裁决人继续复用 is_adjudicator。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = ("c2d3e4f5a6b7", "d0e1f2a3b4c5")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_assignments",
        sa.Column("is_external", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "review_assignments",
        sa.Column("external_affiliation", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("review_assignments", "external_affiliation")
    op.drop_column("review_assignments", "is_external")
