"""020 — resources.content_genre（娱乐轨文体细分）

``content_track`` 只回答论文/娱乐；娱乐区要按小说、评论、指南、整活分栏时，
不能在标题正则上做运行时判断（既慢，也不允许编辑部改口）。

本迁移只加列与索引，存量回填由 ``scripts/backfill_content_genre.py`` 按
标题强文体词 + 少量人工 id 兜底完成；判不出的统一落到 ``joke``。

Revision ID: c1d2e3f4a5b6
Revises: a6b7c8d9e0f1
Create Date: 2026-11-08
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resources",
        sa.Column("content_genre", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_resources_content_genre",
        "resources",
        ["content_genre"],
    )


def downgrade() -> None:
    op.drop_index("ix_resources_content_genre", table_name="resources")
    op.drop_column("resources", "content_genre")
