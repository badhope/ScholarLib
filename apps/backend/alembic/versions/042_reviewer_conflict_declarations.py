"""042 — 审稿人年度利益冲突声明

- ``reviewer_conflict_declarations``：每位审稿人每年一条声明，冲突对象
  以 JSON 数组保存；分派审稿人时按作者姓名/通讯邮箱做可解释匹配。
- 没有声明不阻止分派，但编辑侧会提示“未声明”；有声明且命中则 409 拦截。
  机构字段暂不在投稿表中，不做猜测式拦截。

Revision ID: 042_reviewer_conflict_declarations
Revises: 041_content_reports_api_tokens
Create Date: 2026-11-15
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "042_reviewer_conflict_declarations"
down_revision = "041_content_reports_api_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reviewer_conflict_declarations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "conflicts",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "year",
            name="uq_reviewer_conflict_tenant_user_year",
        ),
    )
    op.create_index(
        "ix_reviewer_conflict_declarations_tenant_id",
        "reviewer_conflict_declarations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_reviewer_conflict_declarations_user_id",
        "reviewer_conflict_declarations",
        ["user_id"],
    )
    op.create_index(
        "ix_reviewer_conflict_declarations_year",
        "reviewer_conflict_declarations",
        ["year"],
    )
    op.execute("ALTER TABLE reviewer_conflict_declarations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reviewer_conflict_declarations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON reviewer_conflict_declarations
        USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON reviewer_conflict_declarations"
    )
    op.execute("ALTER TABLE reviewer_conflict_declarations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reviewer_conflict_declarations DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "ix_reviewer_conflict_declarations_year",
        table_name="reviewer_conflict_declarations",
    )
    op.drop_index(
        "ix_reviewer_conflict_declarations_user_id",
        table_name="reviewer_conflict_declarations",
    )
    op.drop_index(
        "ix_reviewer_conflict_declarations_tenant_id",
        table_name="reviewer_conflict_declarations",
    )
    op.drop_table("reviewer_conflict_declarations")
