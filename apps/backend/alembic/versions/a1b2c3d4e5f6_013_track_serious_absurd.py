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


def upgrade() -> None:
    # 用 batch_alter_table：SQLite 不支持 ALTER TABLE ADD CONSTRAINT，
    # 会抛 NotImplementedError。batch 模式在 SQLite 上走"建新表→搬数据→
    # 换名"，PostgreSQL 上退化为普通 ALTER，两边都能跑通同一条迁移。
    # （部署脚本 deploy_server.py 用 SQLite 起 demo，所以 SQLite 路径不能坏。）
    for table in ("submissions", "resources"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "track",
                    sa.String(length=16),
                    nullable=False,
                    server_default="serious",
                )
            )
            # 只允许两个值。用 CHECK 而不是原生 enum：SQLite 没有 enum，
            # CHECK 两边语义一致，加值只需改约束。
            batch.create_check_constraint(
                f"ck_{table}_track",
                "track IN ('serious', 'absurd')",
            )
    op.create_index(
        "ix_resources_tenant_track_status",
        "resources",
        ["tenant_id", "track", "publication_status"],
    )
    # 免评审录用（desk accept）的豁免记录：三列一起写，缺一不可审计。
    # 放在同一条迁移而不是新开一条，是因为它们都属于"投稿流程完整性"
    # 这同一件事，分开部署会出现"允许免评审但没地方记理由"的中间态。
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(
            sa.Column("review_waived_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "review_waived_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("review_waive_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_resources_tenant_track_status", table_name="resources")
    with op.batch_alter_table("submissions") as batch:
        batch.drop_column("review_waive_reason")
        batch.drop_column("review_waived_by")
        batch.drop_column("review_waived_at")
    for table in ("resources", "submissions"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_track", type_="check")
            batch.drop_column("track")
