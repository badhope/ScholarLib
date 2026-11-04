"""018 — author_claims（作者认领存量文章）

背景：本刊早期文章由编辑部批量导入，作者署名是纯字符串数组，与
站内账号无关。作者需要在站内名下挂上自己的文章——本迁移新增
``author_claims`` 表承载认领申请：用户发起 → 编辑部批准 → 自动
创建关联投稿（submissions.submitted_by = 认领人），打通"我的文章"
等基于 Submission 链路的一切功能。

同风格：租户列 + RLS 策略（与 007/010 的 ``_RLS_TABLES`` 一致）。

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a9b8c7d6e5f4"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None

# 本迁移启用 RLS 的表（for-loop 列表形式，供 test_rls_coverage 识别）。
_RLS_TABLES = ("author_claims",)


def upgrade() -> None:
    op.create_table(
        "author_claims",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "resource_id",
            sa.Integer(),
            sa.ForeignKey("resources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "decided_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "resource_id", "user_id", name="uq_author_claims_once"),
    )
    op.create_index("ix_author_claims_resource_id", "author_claims", ["resource_id"])
    op.create_index("ix_author_claims_user_id", "author_claims", ["user_id"])
    op.create_index("ix_author_claims_tenant_id", "author_claims", ["tenant_id"])
    op.create_index("ix_author_claims_status_created", "author_claims", ["status", "created_at"])

    for table in _RLS_TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id::text = current_setting('app.current_tenant_id', true)) "
            "WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))"
        )


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_index("ix_author_claims_status_created", table_name="author_claims")
    op.drop_index("ix_author_claims_tenant_id", table_name="author_claims")
    op.drop_index("ix_author_claims_user_id", table_name="author_claims")
    op.drop_index("ix_author_claims_resource_id", table_name="author_claims")
    op.drop_table("author_claims")
