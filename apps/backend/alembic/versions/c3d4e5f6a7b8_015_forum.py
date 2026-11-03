"""015 — forum（社区讨论区）

两张表 + RLS：

- ``forum_topics``  — 帖子（标题/正文/分类/置顶/锁定/回复计数）
- ``forum_replies`` — 回帖

为什么需要独立的论坛而不是复用 comments：comments 依附于已发表资源，
是"读者对这篇文章的评论"；论坛是**独立于文章的公共讨论**——提建议、
报 bug、聊选题、求合作。这些内容没有对应的 resource，塞进 comments
会让文章页出现与文章无关的帖子。

软删除（deleted_at）而非硬删除：论坛的价值在讨论上下文，硬删会让被
回复的楼层变成"回复不存在的内容"。

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

_RLS_TABLES = ("forum_topics", "forum_replies")


def upgrade() -> None:
    op.create_table(
        "forum_topics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False, server_default="discussion"),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reply_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_forum_topics_author_id", "forum_topics", ["author_id"])
    op.create_index("ix_forum_topics_tenant_id", "forum_topics", ["tenant_id"])
    op.create_index(
        "ix_forum_topics_tenant_pinned_last",
        "forum_topics",
        ["tenant_id", "is_pinned", sa.text("last_reply_at DESC"), "created_at"],
    )

    op.create_table(
        "forum_replies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "topic_id",
            sa.Integer(),
            sa.ForeignKey("forum_topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_forum_replies_topic_id", "forum_replies", ["topic_id"])
    op.create_index("ix_forum_replies_author_id", "forum_replies", ["author_id"])
    op.create_index("ix_forum_replies_tenant_id", "forum_replies", ["tenant_id"])
    op.create_index(
        "ix_forum_replies_tenant_topic_created",
        "forum_replies",
        ["tenant_id", "topic_id", "created_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id::text = current_setting('app.current_tenant_id', true))
                WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in _RLS_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_forum_replies_tenant_topic_created", table_name="forum_replies")
    op.drop_index("ix_forum_replies_tenant_id", table_name="forum_replies")
    op.drop_index("ix_forum_replies_author_id", table_name="forum_replies")
    op.drop_index("ix_forum_replies_topic_id", table_name="forum_replies")
    op.drop_table("forum_replies")
    op.drop_index("ix_forum_topics_tenant_pinned_last", table_name="forum_topics")
    op.drop_index("ix_forum_topics_tenant_id", table_name="forum_topics")
    op.drop_index("ix_forum_topics_author_id", table_name="forum_topics")
    op.drop_table("forum_topics")
