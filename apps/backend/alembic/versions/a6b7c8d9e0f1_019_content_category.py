"""019 — resources.content_category（内容类别，非等级）

背景：站点定位「内容不分等级，层级只与创作者经验挂钩；只有同类别的
内容才能互相比对」。但历史上存在两套隐形分级展示：RQS 等级徽章
（quality_grade，16 档）与荒诞指数四档（正经/轻诞/荒诞/离谱）。二者
都不是「类别」——类别应当是编辑部给内容定的一等公民属性（学术研究/
娱乐向/吐槽向），等级只能挂在创作者（XP 经验等级）身上。

本迁移：
1. 新增 ``resources.content_category``（academic/fun/rant，可空，索引）。
2. 回填存量：优先沿用已下线的 track 字段（serious→academic）；
   无 track 时按荒诞指数折算（<2.5 学术，<7.5 娱乐向，其余吐槽向）；
   两者皆缺按 ``paper`` 类型默认学术。回填后清空 track（列保留兼容）。

Revision ID: a6b7c8d9e0f1
Revises: a9b8c7d6e5f4
Create Date: 2026-11-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a6b7c8d9e0f1"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resources",
        sa.Column("content_category", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "ix_resources_content_category",
        "resources",
        ["content_category"],
    )
    # 回填 1：历史赛道 serious → 学术研究
    op.execute(
        "UPDATE resources SET content_category = 'academic' "
        "WHERE track = 'serious' AND content_category IS NULL"
    )
    # 回填 2：荒诞指数折算（编辑部口径：<2.5 学术；2.5–7.5 娱乐向；≥7.5 吐槽向）
    op.execute(
        "UPDATE resources SET content_category = 'academic' "
        "WHERE content_category IS NULL AND absurdity_index IS NOT NULL "
        "AND absurdity_index < 2.5"
    )
    op.execute(
        "UPDATE resources SET content_category = 'fun' "
        "WHERE content_category IS NULL AND absurdity_index IS NOT NULL "
        "AND absurdity_index >= 2.5 AND absurdity_index < 7.5"
    )
    op.execute(
        "UPDATE resources SET content_category = 'rant' "
        "WHERE content_category IS NULL AND absurdity_index IS NOT NULL "
        "AND absurdity_index >= 7.5"
    )
    # 回填 3：类型兜底——论文按学术，其余按娱乐向
    op.execute(
        "UPDATE resources SET content_category = 'academic' "
        "WHERE content_category IS NULL AND type = 'paper'"
    )
    op.execute(
        "UPDATE resources SET content_category = 'fun' "
        "WHERE content_category IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_resources_content_category", table_name="resources")
    op.drop_column("resources", "content_category")
