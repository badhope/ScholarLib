"""017 — submission_versions.cover_image

016 给 submissions 表加了 cover_image，但漏了给版本历史表
submission_versions 加同名列。SubmissionVersion 模型里声明了
cover_image（作者上传 / 编辑指定的封面，物化时带到 catalog.resources），
导致查询 submission_versions.cover_image 时炸 UndefinedColumnError。
本迁移补齐该列，类型与 submissions.cover_image 保持一致。

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submission_versions",
        sa.Column("cover_image", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submission_versions", "cover_image")
