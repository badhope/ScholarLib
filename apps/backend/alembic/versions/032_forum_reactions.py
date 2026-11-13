"""032 — forum 多维反馈与楼中楼

- ``forum_replies.parent_id``：两级楼中楼，回复子楼时归到根楼。
- ``forum_reactions``：帖子/回复的「赞同 / 有帮助 / 收藏」，不做“反对”。

唯一约束用 (tenant_id,user_id,target_type,target_id,kind)，不用两个可空
FK——可空列在 PostgreSQL 的 UNIQUE 里会放过多条 NULL，幂等会失效。

Revision ID: 032_forum_reactions
Revises: 031_release_approval
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "032_forum_reactions"
down_revision = "031_release_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("forum_replies", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_forum_replies_parent_id",
        "forum_replies",
        "forum_replies",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_forum_replies_parent_id", "forum_replies", ["parent_id"])

    op.create_table(
        "forum_reactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("target_type", sa.String(length=8), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "target_type",
            "target_id",
            "kind",
            name="uq_forum_reaction_once",
        ),
    )
    op.create_index("ix_forum_reactions_user_id", "forum_reactions", ["user_id"])
    op.create_index("ix_forum_reactions_tenant_id", "forum_reactions", ["tenant_id"])
    op.create_index(
        "ix_forum_reactions_tenant_target",
        "forum_reactions",
        ["tenant_id", "target_type", "target_id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE forum_reactions ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE forum_reactions FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY tenant_isolation ON forum_reactions
                USING (tenant_id::text = current_setting('app.current_tenant_id', true))
                WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON forum_reactions")
        op.execute("ALTER TABLE forum_reactions NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE forum_reactions DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_forum_reactions_tenant_target", table_name="forum_reactions")
    op.drop_index("ix_forum_reactions_tenant_id", table_name="forum_reactions")
    op.drop_index("ix_forum_reactions_user_id", table_name="forum_reactions")
    op.drop_table("forum_reactions")
    op.drop_index("ix_forum_replies_parent_id", table_name="forum_replies")
    op.drop_constraint("fk_forum_replies_parent_id", "forum_replies", type_="foreignkey")
    op.drop_column("forum_replies", "parent_id")
