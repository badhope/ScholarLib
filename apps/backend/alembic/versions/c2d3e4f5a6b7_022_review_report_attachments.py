"""022 — review_reports.attachments

审稿报告此前只能提交文字意见，审稿人批注完 PDF 没有地方交批注件。
新增 JSONB 附件列表，存文件名 / 存储 key / MIME / 大小；文件本身沿用
现有 storage 的 `{tenant}/review/{report}/{uuid}{ext}` key。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c2d3e4f5a6b7"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_reports",
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("review_reports", "attachments")
