"""016 — submissions.cover_image + 默认封面库元数据

给投稿加封面图字段，让作者能在投稿时上传自己的封面。

背景：本刊是双赛道期刊，荒诞稿的封面往往就是作品的一部分（一张梗图
胜过一千字摘要）。此前只有 catalog 的 Resource 有 cover_image，且只有
管理员能改——作者投稿时无法附图，所有文章只能长成同一个样子。

默认封面库（apps/frontend/public/covers/）已经存在 15 张按学科分类的
精选图（covers.json 记录了来源与授权）。本迁移不改前端资源；它只保证
数据库有地方存"作者上传的封面"。没有上传时前端按学科从默认库挑选，
所以封面永远不为空。

Revision ID: e7f8a9b0c1d2
Revises: c3d4e5f6a7b8
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("submissions", sa.Column("cover_image", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("submissions", "cover_image")
