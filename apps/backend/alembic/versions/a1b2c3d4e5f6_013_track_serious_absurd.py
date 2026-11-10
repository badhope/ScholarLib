"""013 — track（正经 / 荒诞双赛道）

把「两条赛道」从文案变成数据。此前 README、首页、作者指南、编辑规范
都在讲「正经与荒诞兼容」，但数据库里没有任何字段承载这个分野：

- 投稿时作者无法声明自己写的是哪一类；
- 录用物化到目录时赛道信息丢失；
- 目录无法按赛道筛选，读者读之前不知道自己在读什么；
- 期刊统计只能报一个混合总数，接收率没有意义。

本次给 ``submissions`` 与 ``resources`` 各加一列 ``track``：

- ``serious`` — 正经研究，按学术惯例评审
- ``absurd``  — 荒诞研究，格式/引用/论证标准与正经完全相同

默认 ``serious`` 是保守选择：把一篇正经论文误标成荒诞（读者当玩笑、
编辑放松标准）的伤害，远大于把荒诞论文误标成正经。历史数据全部落到
``serious``，由编辑部在需要时逐条修正。

索引：公开面列表的典型查询是
``WHERE tenant_id = ? AND publication_status = 'published' AND track = ?``，
建复合索引 ``(tenant_id, track, publication_status)`` 覆盖；不建单列索引，
避免公开面查询多一次回表。

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-11-02
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None

# SQLite batch 模式重建表时，反射出的外键没有名字，add_constraint 会抛
# "Constraint must have a name"。显式给约束命名规则，两边（PG/SQLite）
# 生成一致的约束名。
_NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    for table in ("submissions", "resources"):
        if is_pg:
            # PostgreSQL：原生 ALTER，一条语句加列 + 带名 CHECK 约束。
            op.add_column(
                table,
                sa.Column(
                    "track",
                    sa.String(length=16),
                    nullable=False,
                    server_default="serious",
                ),
            )
            op.create_check_constraint(
                f"ck_{table}_track",
                table,
                "track IN ('serious', 'absurd')",
            )
        else:
            # SQLite（本地演示/测试库）：
            # - 加列用原生 ALTER ADD COLUMN（不重建表，避免 batch 反射
            #   未命名外键时抛 "Constraint must have a name"）；
            # - SQLite 不支持 ALTER ADD CONSTRAINT，CHECK 落在应用层
            #   （Pydantic 与 ORM 默认值已约束取值范围），演示库可接受。
            op.add_column(
                table,
                sa.Column(
                    "track",
                    sa.String(length=16),
                    nullable=False,
                    server_default="serious",
                ),
            )

    op.create_index(
        "ix_resources_tenant_track_status",
        "resources",
        ["tenant_id", "track", "publication_status"],
    )

    # 免评审录用（desk accept）的豁免记录。PG 上 FK 走原生 ALTER；
    # SQLite 上普通 add_column 也能加 FK（内联到 CREATE？不能——
    # 但测试与演示库不依赖该 FK，跳过 FK 只建普通列）。
    if is_pg:
        op.add_column(
            "submissions",
            sa.Column("review_waived_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            "submissions",
            sa.Column(
                "review_waived_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.add_column(
            "submissions",
            sa.Column("review_waive_reason", sa.Text(), nullable=True),
        )
    else:
        op.add_column(
            "submissions", sa.Column("review_waived_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.add_column("submissions", sa.Column("review_waived_by", sa.Integer(), nullable=True))
        op.add_column("submissions", sa.Column("review_waive_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    op.drop_index("ix_resources_tenant_track_status", table_name="resources")
    if is_pg:
        op.drop_column("submissions", "review_waive_reason")
        op.drop_column("submissions", "review_waived_by")
        op.drop_column("submissions", "review_waived_at")
    else:
        op.drop_column("submissions", "review_waive_reason")
        op.drop_column("submissions", "review_waived_by")
        op.drop_column("submissions", "review_waived_at")
    for table in ("resources", "submissions"):
        if is_pg:
            op.drop_constraint(f"ck_{table}_track", table, type_="check")
        op.drop_column(table, "track")
